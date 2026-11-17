#!/usr/bin/env python3
"""mc-pi: Mission Control's service on the Pi.

The phone app talks to this; this talks to pc-waker (unchanged) and pushes notifications through ntfy.

    python3 mcpi.py serve                run the API (systemd does this)
    python3 mcpi.py setup                create mc-pi.env (PC token, defaults); keeps existing values
    python3 mcpi.py token-add NAME       make an app token without the password (for tests), print it
    python3 mcpi.py token-list           list app tokens
    python3 mcpi.py token-revoke NAME    delete app tokens with this name
    python3 mcpi.py pc-token             print the token the PC helper needs

Login: the phone sends pc-waker's password once. It is checked against pc-waker's own scrypt hash
(read from pc-waker.env), so there is one password and changing it in pc-waker applies here too.
mc-pi calls pc-waker with a session cookie it signs the same way pc-waker does.
"""
import base64
import hashlib
import hmac
import json
import ntpath
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from claude_hub import ClaudeHub
from sessions_hub import SessionsHub
from docs_hub import DocsHub
from todo_hub import TodoHub
from system_hub import SystemHub

HERE = Path(__file__).resolve().parent
ENV_FILE = Path(os.environ.get("MC_PI_ENV", HERE / "mc-pi.env"))
# systemd sets STATE_DIRECTORY; the CLI (run as the same user) finds the same folder.
STATE = Path(os.environ.get("STATE_DIRECTORY") or (
    "/var/lib/mission-control" if os.access("/var/lib/mission-control", os.W_OK) else HERE / "state"))

DEFAULTS = {
    "BIND": "0.0.0.0",
    "PORT": "8780",
    "PCW_URL": "http://127.0.0.1:8765",
    "PCW_ENV": "/home/filip/pc-waker/pc-waker.env",
    "NTFY_URL": "http://127.0.0.1:2586",   # mc-pi posts here (local, not through the tunnel)
    "NTFY_TOKEN": "",
    "PC_TOKEN": "",
    # stage 6 (System tab). All optional; see mc-pi.env.example.
    "ROBLOX_UNIVERSE": "", "ROBLOX_KEY": "",
    "HA_URL": "", "HA_TOKEN": "", "HA_TEMP": "", "HA_DISK": "", "HA_UPTIME": "",
}
SERVICES = ["pc-waker", "mission-control", "cloudflared", "bp-gateway"]   # ntfy retired in stage 3
LOGIN_WINDOW, LOGIN_MAX_FAILS = 15 * 60, 5
HELPER_STALE = 30          # PC helper polls every 5 s; older than this = not connected
SLEEP_CMD_TTL = 60         # a queued sleep that the helper did not pick up in time is dropped
ACTION_PATHS = {"/api/stay-awake", "/api/autosleep"}   # buttons in notifications may call these
SETTINGS_DEFAULTS = {
    "muted": False,
    "quiet_on": True, "quiet_from": "22:00", "quiet_to": "07:00",
    "kinds": {"claude": True, "sleep": True, "room": True, "system": True},
    "wake_on_approve": False,   # wake the PC when Filip answers an approval
    "ideas_audio": False,       # ideas: send audio instead of speech-to-text
}
KIND_CAT = {"waiting": "claude", "error": "claude", "done": "claude", "stuck": "claude",
            "sleep": "sleep", "room": "room"}


# ---------------------------------------------------------------- config and files

def read_env(path: Path) -> dict:
    env = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except OSError:
        pass
    return env


def write_env(path: Path, updates: dict) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    todo = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in todo:
            lines[i] = f"{key}={todo.pop(key)}"
    lines += [f"{k}={v}" for k, v in todo.items()]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(read_env(ENV_FILE))
    return cfg


def load_json(name: str, default):
    try:
        return json.loads((STATE / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(name: str, obj) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = STATE / (name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    tmp.replace(STATE / name)


# ---------------------------------------------------------------- pc-waker

def pcw_secrets(cfg: dict) -> dict:
    """pc-waker's password hash and signing key. Read each time, so a password change applies at once."""
    env = read_env(Path(cfg["PCW_ENV"]))
    if not env.get("PASSWORD_HASH") or not env.get("SECRET_KEY"):
        raise RuntimeError(f"cannot read pc-waker secrets from {cfg['PCW_ENV']}")
    return env


def check_password(pw: str, stored: str) -> bool:
    """Same scrypt format as pc-waker's server.py."""
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r),
                             p=int(p), dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def pcw_cookie(cfg: dict) -> str:
    """A pc-waker session cookie, signed exactly like pc-waker's make_session(), valid 1 hour."""
    env = pcw_secrets(cfg)
    exp = str(int(time.time()) + 3600)
    sig = hmac.new((env["SECRET_KEY"] + env["PASSWORD_HASH"]).encode(), exp.encode(),
                   hashlib.sha256).hexdigest()
    return f"pcw_session={exp}.{sig}"


class PcWakerError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def pcw(cfg: dict, method: str, path: str, body=None, timeout: float = 8):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(cfg["PCW_URL"] + path, data=data, method=method)
    req.add_header("Cookie", pcw_cookie(cfg))
    req.add_header("X-Requested-With", "pc-waker")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error") or e.reason
        except ValueError:
            msg = e.reason
        raise PcWakerError(e.code, str(msg))
    except (urllib.error.URLError, OSError) as e:
        raise PcWakerError(502, f"pc-waker unreachable: {e}")


# ---------------------------------------------------------------- Pi health

def _read(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def pi_health() -> dict:
    temp = _read("/sys/class/thermal/thermal_zone0/temp")
    up = _read("/proc/uptime").split()
    mem = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0]) if v.split() else 0
    du = shutil.disk_usage("/")
    services = {}
    for s in SERVICES:
        try:
            out = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True,
                                 timeout=3).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            out = "unknown"
        services[s] = out or "unknown"
    down = [s for s, v in services.items() if v not in ("active",)]
    load1 = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
    t = round(int(temp) / 1000, 1) if temp.isdigit() else None
    return {
        "temp_c": t,
        "uptime_s": int(float(up[0])) if up else None,
        "load1": round(load1, 2) if load1 is not None else None,
        "mem_used_pct": round(100 * (1 - mem.get("MemAvailable", 0) / mem["MemTotal"])) if mem.get("MemTotal") else None,
        "disk_free_gb": round(du.free / 1e9, 1),
        "services": services,
        "down": down,
        "healthy": not down and (t is None or t < 75),
    }


# ---------------------------------------------------------------- notifications

def _hhmm(s: str) -> int:
    h, m = s.split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(s)
    return h * 60 + m


def in_quiet(settings: dict, now: datetime) -> bool:
    if not settings.get("quiet_on"):
        return False
    a, b, cur = _hhmm(settings["quiet_from"]), _hhmm(settings["quiet_to"]), now.hour * 60 + now.minute
    return a <= cur < b if a <= b else cur >= a or cur < b


def clean_settings(new: dict, old: dict) -> dict:
    out = json.loads(json.dumps(old))
    for k in ("muted", "quiet_on", "wake_on_approve", "ideas_audio"):
        if k in new:
            out[k] = bool(new[k])
    for k in ("quiet_from", "quiet_to"):
        if k in new:
            v = _hhmm(str(new[k]))
            out[k] = f"{v // 60:02d}:{v % 60:02d}"
    if "kinds" in new:
        if not isinstance(new["kinds"], dict):
            raise ValueError("kinds")
        for k in SETTINGS_DEFAULTS["kinds"]:
            if k in new["kinds"]:
                out["kinds"][k] = bool(new["kinds"][k])
    return out


class Pusher:
    """Sends messages to the phone's UnifiedPush endpoint (a ntfy topic) and remembers the last ones."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.endpoints = load_json("push-endpoints.json", {})   # device -> {"topic", "at"}
        self.log = load_json("push-log.json", [])[-50:]

    def register(self, device: str, endpoint: str) -> str:
        m = re.match(r"^https?://[^/]+/(up[A-Za-z0-9_-]{6,64})(\?.*)?$", endpoint or "")
        if not m:
            raise ValueError("endpoint must be a ntfy UnifiedPush topic URL")
        with self.lock:
            self.endpoints[device[:40] or "phone"] = {"topic": m.group(1), "endpoint": endpoint[:300],
                                                     "at": time.time()}
            save_json("push-endpoints.json", self.endpoints)
        return m.group(1)

    def unregister(self, device: str) -> None:
        with self.lock:
            self.endpoints.pop(device, None)
            save_json("push-endpoints.json", self.endpoints)

    def send(self, msg: dict) -> int:
        """Send to every registered device. Returns how many accepted it."""
        body = json.dumps(msg, ensure_ascii=False).encode()[:3900]
        ok = 0
        with self.lock:
            targets = list(self.endpoints.values())
        for t in targets:
            req = urllib.request.Request(f"{self.cfg['NTFY_URL']}/{t['topic']}?up=1", data=body, method="POST")
            if self.cfg.get("NTFY_TOKEN"):
                req.add_header("Authorization", f"Bearer {self.cfg['NTFY_TOKEN']}")
            try:
                with urllib.request.urlopen(req, timeout=8):
                    ok += 1
            except (urllib.error.URLError, OSError) as e:
                print(f"push to {t['topic'][:6]}… failed: {e}", flush=True)
        with self.lock:
            self.log.append({"at": time.time(), "kind": msg.get("kind"), "title": msg.get("title", ""),
                             "sent": ok, "of": len(targets)})
            self.log = self.log[-50:]
            save_json("push-log.json", self.log)
        return ok


class EventStore:
    """Messages for the phone app, which long-polls GET /api/events (at home directly, outside through
    the tunnel). Ids are millisecond timestamps that never go backwards."""
    KEEP = 200
    MAX_AGE = 6 * 3600     # after a long disconnect, don't replay older messages
    MAX_COUNT = 10

    def __init__(self):
        self.cond = threading.Condition()
        self.events = load_json("app-events.json", [])[-self.KEEP:]

    def add(self, msg: dict) -> None:
        with self.cond:
            last = self.events[-1]["id"] if self.events else 0
            msg = dict(msg, id=max(last + 1, int(time.time() * 1000)), at=msg.get("at") or time.time())
            self.events.append(msg)
            self.events = self.events[-self.KEEP:]
            save_json("app-events.json", self.events)
            self.cond.notify_all()

    def wait(self, since, timeout: float) -> dict:
        with self.cond:
            last = self.events[-1]["id"] if self.events else 0
            if since is None or since > last:
                return {"last": last, "events": []}   # first connect: start from now
            deadline = time.monotonic() + timeout
            while True:
                fresh = [e for e in self.events if e["id"] > since and time.time() - e["at"] < self.MAX_AGE]
                left = deadline - time.monotonic()
                if fresh or left <= 0:
                    break
                self.cond.wait(left)
            last = self.events[-1]["id"] if self.events else 0
            return {"last": last, "events": fresh[-self.MAX_COUNT:]}


class EventForwarder(threading.Thread):
    """Long-polls pc-waker's /api/events (like the PC Waker app does) and pushes each event to the phone."""

    def __init__(self, app_state):
        super().__init__(daemon=True)
        self.s = app_state
        self.last = load_json("events-cursor.json", {}).get("last")
        self.ok_at = None
        self.error = None

    def run(self):
        while True:
            try:
                q = f"?since={self.last}&wait=50" if self.last is not None else "?wait=0"
                r = pcw(self.s.cfg, "GET", "/api/events" + q, timeout=70)
                for ev in r.get("events", []):
                    self.forward(ev)
                self.last = r.get("last", self.last)
                save_json("events-cursor.json", {"last": self.last})
                self.ok_at, self.error = time.time(), None
            except Exception as e:   # noqa: BLE001 - keep the loop alive whatever happens
                self.error = str(e)[:200]
                print(f"events: {self.error}", flush=True)
                time.sleep(10)

    def forward(self, ev: dict) -> None:
        settings = self.s.settings
        kind = ev.get("kind", "")
        cat = KIND_CAT.get(kind, "system")
        if kind in ("done", "waiting", "error", "stuck", "sleep"):
            first = (ev.get("body") or "").splitlines()[0] if ev.get("body") else ""
            self.s.system.log(kind, f"{first + ': ' if first else ''}{ev.get('title', '')}")
        if kind == "cancel":
            self.s.deliver({"kind": "cancel", "group": ev.get("group", "")})
            return
        if kind != "test":
            if settings["muted"]:
                return
            if not settings["kinds"].get(cat, True):
                return
        actions = [{"label": str(a.get("label", ""))[:40], "post": a.get("post"), "body": a.get("body") or {}}
                   for a in (ev.get("actions") or []) if a.get("post") in ACTION_PATHS][:3]
        self.s.deliver({
            "id": ev.get("id"), "at": ev.get("at"), "kind": kind, "cat": cat,
            "title": ev.get("title", ""), "body": ev.get("body", ""), "group": ev.get("group", ""),
            "quiet": bool(ev.get("quiet")) or in_quiet(settings, datetime.now()),
            "actions": actions,
        })


# ---------------------------------------------------------------- app state

def _hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


class AppState:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.tokens = load_json("tokens.json", {})               # sha256 -> {"name", "created", "used"}
        self.settings = json.loads(json.dumps(SETTINGS_DEFAULTS))
        saved = load_json("settings.json", {})
        if saved:
            self.settings = clean_settings(saved, self.settings)
        self.pusher = Pusher(cfg)
        self.store = EventStore()
        self.fails = {}
        self.status = None
        self.status_at = 0.0
        self.pc_state = load_json("pc-state.json", {"online": None, "since": None})
        self.helper_at = 0.0
        self.sleep_cmd_at = 0.0
        self.events = None
        self.claude = ClaudeHub(STATE, load_json, save_json)
        self.sessions = SessionsHub(self.claude, load_json, save_json, self.deliver)
        self.docs = DocsHub(STATE)
        self.todos = TodoHub(STATE)
        self.system = SystemHub(STATE, cfg, load_json, save_json, pi_health)

    def deliver(self, msg: dict) -> None:
        """To the app's own event stream (GET /api/events)."""
        self.store.add(msg)

    # tokens
    def add_token(self, name: str) -> str:
        tok = secrets.token_urlsafe(32)
        with self.lock:
            self.tokens = load_json("tokens.json", {})
            self.tokens[_hash_token(tok)] = {"name": name[:40], "created": time.time(), "used": None}
            save_json("tokens.json", self.tokens)
        return tok

    def token_ok(self, tok: str) -> bool:
        if not tok:
            return False
        h = _hash_token(tok)
        with self.lock:
            rec = self.tokens.get(h)
            if not rec:
                self.tokens = load_json("tokens.json", {})   # a CLI token-add since start
                rec = self.tokens.get(h)
            if rec and (rec.get("used") or 0) < time.time() - 3600:
                rec["used"] = time.time()
                save_json("tokens.json", self.tokens)
        return rec is not None

    def locked_out(self, ip: str) -> bool:
        now = time.monotonic()
        self.fails[ip] = [t for t in self.fails.get(ip, []) if now - t < LOGIN_WINDOW]
        return len(self.fails[ip]) >= LOGIN_MAX_FAILS

    # pc-waker status, cached a few seconds and used to track since when the PC is on/off
    def pcw_status(self, fresh: bool = False) -> dict:
        with self.lock:
            if self.status and not fresh and time.monotonic() - self.status_at < 3:
                return self.status
        st = pcw(self.cfg, "GET", "/api/status?room_s=10")
        with self.lock:
            self.status, self.status_at = st, time.monotonic()
            online = bool(st.get("pc", {}).get("online"))
            if self.pc_state.get("online") != online:
                if self.pc_state.get("online") is not None:
                    self.system.log("pc", "PC woke up" if online else "PC went to sleep")
                self.pc_state = {"online": online, "since": time.time()}
                save_json("pc-state.json", self.pc_state)
        return st

    def update_settings(self, new: dict) -> dict:
        with self.lock:
            self.settings = clean_settings(new, self.settings)
            save_json("settings.json", self.settings)
            return json.loads(json.dumps(self.settings))


def status_watcher(state: AppState):
    """Keeps the PC on/off 'since' time right even when no phone is looking."""
    while True:
        try:
            state.pcw_status(fresh=True)
        except Exception as e:   # noqa: BLE001
            print(f"status: {e}", flush=True)
        time.sleep(15)


def build_home(state: AppState) -> dict:
    st = state.pcw_status()
    agent = st.get("agent") or {}
    a = st.get("autosleep") or {}
    a_now = a.get("now") or {}
    room = st.get("room") or {}
    sessions = agent.get("sessions") or []
    waiting = [s for s in sessions if s.get("status") == "waiting"]
    # Requests the phone can answer (questions, permissions, new-session cards, approvals) count as waiting too.
    lv = state.sessions.list_view()
    ask_titles = [g.get("session", "Claude") for g in lv["gates"]] + [p.get("session", "Claude") for p in lv["proposals"]] \
        + [a.get("title", "Approval") for a in state.claude.view()["approvals"]]
    seen_t, titles = set(), []
    for t in [(s.get("title") or s.get("name") or "Claude")[:80] for s in waiting] + ask_titles:
        if t not in seen_t:
            seen_t.add(t); titles.append(t)
    return {
        "pc": {"online": bool(st.get("pc", {}).get("online")), "since": state.pc_state.get("since"),
               "ping_ms": st.get("pc", {}).get("ping_ms"), "last_wake": st.get("last_wake"),
               "agent": bool(agent.get("fresh")),
               "helper": time.time() - state.helper_at < HELPER_STALE,
               "sleep_pending": time.time() - state.sleep_cmd_at < SLEEP_CMD_TTL},
        "autosleep": {"enabled": (a.get("settings") or {}).get("enabled"),
                      "idle_min": (a.get("settings") or {}).get("idle_min"),
                      "keep_awake_until": (a.get("settings") or {}).get("keep_awake_until") or 0,
                      "blockers": a_now.get("blockers") or [], "sleep_at": a_now.get("sleep_at"),
                      "input_idle_s": a_now.get("input_idle_s"), "warning": bool(a_now.get("warning"))},
        "room": {"present": room.get("present"), "fresh": room.get("fresh"),
                 "last_motion": room.get("last_motion"),
                 "wake_on_enter": (room.get("settings") or {}).get("wake_on_enter"),
                 "block_sleep": (room.get("settings") or {}).get("block_sleep")},
        "lights": st.get("pc_lights") or {},
        "claude": {"sessions": len(lv["sessions"]) or len(sessions), "waiting": len(titles), "waiting_titles": titles[:5]},
        "pi": pi_health(),
        "todos": {"open": state.todos.open_count()},
        "recent": (st.get("notify") or {}).get("recent", [])[:10],
        "push": {"devices": len(state.pusher.endpoints),
                 "events_ok_at": state.events.ok_at if state.events else None,
                 "events_error": state.events.error if state.events else None},
        "now": time.time(),
    }


# ---------------------------------------------------------------- HTTP API

def make_app(state: AppState):
    from fastapi import Body, FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse

    @asynccontextmanager
    async def lifespan(_app):
        state.events = EventForwarder(state)
        state.events.start()
        threading.Thread(target=status_watcher, args=(state,), daemon=True).start()
        threading.Thread(target=state.system.run, daemon=True).start()
        yield

    app = FastAPI(title="mc-pi", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def bearer(req: Request) -> str:
        h = req.headers.get("authorization", "")
        return h[7:] if h.lower().startswith("bearer ") else ""

    def need_app(req: Request):
        if not state.token_ok(bearer(req)):
            raise HTTPException(401, "login required")

    def need_pc(req: Request):
        tok = state.cfg.get("PC_TOKEN", "")
        if not tok or not hmac.compare_digest(bearer(req).encode(), tok.encode()):
            raise HTTPException(401, "bad token")

    def call(method, path, b=None):
        try:
            return pcw(state.cfg, method, path, b)
        except PcWakerError as e:
            raise HTTPException(e.code if e.code in (400, 409, 429) else 502, e.msg)

    @app.exception_handler(HTTPException)
    async def http_err(_req, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "mc-pi"}

    @app.post("/api/login")
    def login(req: Request, d: dict = Body(default={})):
        ip = req.client.host if req.client else "?"
        if state.locked_out(ip):
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        try:
            stored = pcw_secrets(state.cfg)["PASSWORD_HASH"]
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        if not check_password(str(d.get("password", "")), stored):
            state.fails.setdefault(ip, []).append(time.monotonic())
            print(f"{ip} login FAILED", flush=True)
            time.sleep(1)
            raise HTTPException(401, "Wrong password.")
        print(f"{ip} login ok", flush=True)
        return {"token": state.add_token(str(d.get("device") or "phone"))}

    @app.post("/api/logout")
    def logout(req: Request):
        need_app(req)
        with state.lock:
            state.tokens.pop(_hash_token(bearer(req)), None)
            save_json("tokens.json", state.tokens)
        return {"ok": True}

    @app.get("/api/home")
    def home(req: Request):
        need_app(req)
        try:
            return build_home(state)
        except PcWakerError as e:
            raise HTTPException(502, e.msg)

    @app.post("/api/pc/wake")
    def wake(req: Request):
        need_app(req)
        return call("POST", "/api/wake", {})

    @app.post("/api/pc/sleep")
    def sleep(req: Request):
        need_app(req)
        if time.time() - state.helper_at > HELPER_STALE:
            raise HTTPException(409, "PC helper not connected (is the PC on?)")
        state.sleep_cmd_at = time.time()
        print("sleep requested from the app", flush=True)
        return {"ok": True}

    @app.post("/api/lights")
    def lights(req: Request, d: dict = Body(default={})):
        need_app(req)
        return call("POST", "/api/pc-lights", {"on": bool(d.get("on"))})

    @app.post("/api/autosleep")
    def autosleep(req: Request, d: dict = Body(default={})):
        need_app(req)
        return call("POST", "/api/autosleep", {k: d[k] for k in ("enabled", "idle_min") if k in d})

    @app.post("/api/stay-awake")
    def stay_awake(req: Request, d: dict = Body(default={})):
        need_app(req)
        return call("POST", "/api/stay-awake", {"minutes": int(d.get("minutes", 60))})

    @app.post("/api/room-settings")
    def room_settings(req: Request, d: dict = Body(default={})):
        need_app(req)
        return call("POST", "/api/room-settings",
                    {k: bool(d[k]) for k in ("wake_on_enter", "block_sleep") if k in d})

    @app.post("/api/action")
    def action(req: Request, d: dict = Body(default={})):
        """A button in a notification (e.g. 'Stay awake 60 min')."""
        need_app(req)
        if d.get("post") not in ACTION_PATHS:
            raise HTTPException(400, "unknown action")
        return call("POST", d["post"], d.get("body") if isinstance(d.get("body"), dict) else {})

    @app.get("/api/settings")
    def get_settings(req: Request):
        need_app(req)
        return {"settings": state.settings, "push": {"devices": list(state.pusher.endpoints),
                                                     "log": state.pusher.log[-10:][::-1]}}

    @app.post("/api/settings")
    def set_settings(req: Request, d: dict = Body(default={})):
        need_app(req)
        try:
            return {"ok": True, "settings": state.update_settings(d)}
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, "bad settings")

    @app.post("/api/push/register")
    def push_register(req: Request, d: dict = Body(default={})):
        need_app(req)
        try:
            topic = state.pusher.register(str(d.get("device") or "phone"), str(d.get("endpoint") or ""))
        except ValueError as e:
            raise HTTPException(400, str(e))
        print(f"push endpoint registered: {topic[:6]}…", flush=True)
        return {"ok": True}

    @app.post("/api/push/unregister")
    def push_unregister(req: Request, d: dict = Body(default={})):
        need_app(req)
        state.pusher.unregister(str(d.get("device") or "phone"))
        return {"ok": True}

    @app.get("/api/push/setup")
    def push_setup(req: Request):
        """What the phone's ntfy app needs: the server address and the phone user's token."""
        need_app(req)
        def secret(name):
            try:
                return (HERE / "secrets" / name).read_text().strip()
            except OSError:
                return ""
        return {"server": state.cfg.get("NTFY_PUBLIC", ""), "server_lan": state.cfg.get("NTFY_LAN", ""),
                "username": "phone", "password": secret("ntfy-phone-password.txt"),
                "token": secret("ntfy-phone-token.txt")}

    @app.post("/api/push/test")
    def push_test(req: Request):
        need_app(req)
        state.deliver({"at": time.time(), "kind": "test", "cat": "system",
                       "title": "Mission Control test", "body": f"Push works ({time.strftime('%H:%M:%S')}).",
                       "group": f"test:{time.time()}", "quiet": False, "actions": []})
        return {"ok": True}

    @app.get("/api/events")
    def events(req: Request, since: str = "", wait: int = 0):
        """The app's long-poll (also reachable through the tunnel; nothing else is)."""
        need_app(req)
        try:
            s = int(since) if since else None
        except ValueError:
            raise HTTPException(400, "bad since")
        return state.store.wait(s, min(max(wait, 0), 55))

    @app.get("/api/pc/command")
    def pc_command(req: Request):
        need_pc(req)
        state.helper_at = time.time()
        out = {"inbox": state.claude.pc_inbox(), "watch": state.sessions.pc_watch()}
        if state.system.take_shot_request():
            out["screenshot"] = True
        if state.sleep_cmd_at and time.time() - state.sleep_cmd_at < SLEEP_CMD_TTL:
            print("sleep command handed to the PC helper", flush=True)
            out["cmd"] = "sleep"
        state.sleep_cmd_at = 0.0
        return out

    @app.post("/api/pc/ack")
    def pc_ack(req: Request, d: dict = Body(default={})):
        need_pc(req)
        state.claude.ack([str(k) for k in (d.get("keys") or [])][:50])
        return {"ok": True}

    @app.post("/api/pc/report")
    def pc_report(req: Request, d: dict = Body(default={})):
        need_pc(req)
        state.helper_at = time.time()
        state.system.on_pc_report(d.get("stats"))
        for a in state.claude.on_report(d):
            state.deliver({"at": time.time(), "kind": "approval", "cat": "claude",
                           "title": "Claude needs your approval", "body": a["title"],
                           "group": f"approval:{a['id']}", "quiet": False, "actions": []})
        return {"ok": True}

    @app.post("/api/pc/picture")
    async def pc_picture(req: Request, approval: str = "", n: int = 0):
        need_pc(req)
        try:
            state.claude.save_picture(approval, n, await req.body())
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.get("/api/pc/audio/{audio_id}")
    def pc_audio(req: Request, audio_id: str):
        need_pc(req)
        p = state.claude.audio_path(audio_id)
        if not p:
            raise HTTPException(404, "not found")
        return FileResponse(p, media_type="audio/mp4")

    @app.get("/api/claude")
    def claude_view(req: Request):
        need_app(req)
        v = state.claude.view()
        try:
            st = state.pcw_status()
            agent = st.get("agent") or {}
            v["sessions"] = [{"id": s.get("id"), "title": (s.get("title") or s.get("name") or "Claude")[:80],
                              "status": "idle" if s.get("status") == "shell" else s.get("status"),
                              "waiting_for": s.get("waiting_for"), "activity": (s.get("activity") or "")[:160],
                              "kind": s.get("kind"), "updated": s.get("updated")}
                             for s in agent.get("sessions") or []]
            v["pc_online"] = bool(st.get("pc", {}).get("online"))
        except PcWakerError:
            v["sessions"], v["pc_online"] = [], None
        v["helper"] = time.time() - state.helper_at < HELPER_STALE
        v["has_key"] = state.claude.has_key(_hash_token(bearer(req)))
        v["ideas_audio"] = state.settings.get("ideas_audio", False)
        return v

    # ------------------------------------------------------------ live sessions (Claude tab v2)
    def sess_call(fn):
        try:
            return fn()
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except LookupError as e:
            raise HTTPException(409, str(e))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))

    @app.post("/api/pc/sessions")
    def pc_sessions(req: Request, d: dict = Body(default={})):
        need_pc(req)
        state.helper_at = time.time()
        state.sessions.on_snapshot(d)
        return {"ok": True}

    @app.post("/api/pc/result")
    def pc_result(req: Request, d: dict = Body(default={})):
        need_pc(req)
        state.sessions.on_result(d)
        return {"ok": True}

    def with_plan_info(gates):
        """A plan request carries how many open comments its Doc has (the card asks before approving over them)."""
        for g in gates:
            if g.get("kind") == "plan" and g.get("doc"):
                g["doc_open_comments"] = state.docs.open_comment_count(g["doc"])
        return gates

    @app.get("/api/sessions")
    def sessions_list(req: Request):
        need_app(req)
        v = state.sessions.list_view()
        with_plan_info(v["gates"])
        v["has_key"] = state.claude.has_key(_hash_token(bearer(req)))
        return v

    @app.get("/api/sessions/{sid}")
    def session_one(req: Request, sid: str):
        need_app(req)
        v = sess_call(lambda: state.sessions.session_view(sid))
        with_plan_info(v["gates"])
        return v

    @app.post("/api/sessions/{sid}/message")
    def session_message(req: Request, sid: str, d: dict = Body(default={})):
        need_app(req)
        r = sess_call(lambda: state.sessions.send_message(_hash_token(bearer(req)), sid, d))
        state.system.log("claude", "Message sent to a Claude session from the phone")
        return r

    @app.post("/api/gate/{gid}/answer")
    def gate_answer(req: Request, gid: str, d: dict = Body(default={})):
        need_app(req)
        r = sess_call(lambda: state.sessions.answer_gate(_hash_token(bearer(req)), gid, d))
        state.system.log("approval", f"Claude request answered from the phone: {d.get('decision')}")
        return r

    @app.post("/api/proposals/{key}/start")
    def proposal_start(req: Request, key: str, d: dict = Body(default={})):
        need_app(req)
        return sess_call(lambda: state.sessions.start_proposal(_hash_token(bearer(req)), key, d))

    @app.post("/api/proposals/{key}/hide")
    def proposal_hide(req: Request, key: str):
        need_app(req)
        state.sessions.hide_proposal(key[:40])
        return {"ok": True}

    @app.post("/api/gate/config")
    def gate_config(req: Request, d: dict = Body(default={})):
        need_app(req)
        return {"ok": True, "config": sess_call(lambda: state.sessions.set_config(_hash_token(bearer(req)), d))}

    @app.get("/api/pictures/{aid}/{n}")
    def picture(req: Request, aid: str, n: int):
        need_app(req)
        p = state.claude.picture_path(aid, n)
        if not p:
            raise HTTPException(404, "not found")
        return FileResponse(p, media_type="image/jpeg")

    @app.post("/api/keys")
    def register_key(req: Request, d: dict = Body(default={})):
        need_app(req)
        try:
            state.claude.register_key(_hash_token(bearer(req)), str(d.get("public_key", "")))
        except ValueError as e:
            raise HTTPException(400, f"bad key: {e}")
        print("fingerprint key registered", flush=True)
        return {"ok": True}

    @app.post("/api/approvals/{aid}/answer")
    def answer(req: Request, aid: str, d: dict = Body(default={})):
        need_app(req)
        try:
            a = state.claude.answer(_hash_token(bearer(req)), aid, d)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except LookupError as e:
            raise HTTPException(409, str(e))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        print(f"approval {aid} answered: {a['decision']}", flush=True)
        state.system.log("approval", f"Approval answered: {a['decision']} ({str(a.get('title', ''))[:60]})")
        woke = False
        if state.settings.get("wake_on_approve"):
            try:
                if not state.pcw_status(fresh=True).get("pc", {}).get("online"):
                    pcw(state.cfg, "POST", "/api/wake", {})
                    woke = True
            except PcWakerError:
                pass
        return {"ok": True, "woke_pc": woke}

    @app.post("/api/ideas")
    async def idea(req: Request):
        need_app(req)
        ctype = req.headers.get("content-type", "")
        try:
            if ctype.startswith("audio/"):
                state.claude.add_idea(req.query_params.get("text", ""), await req.body())
            else:
                d = await req.json()
                text = str((d or {}).get("text", "")).strip()
                if not text:
                    raise ValueError("empty idea")
                state.claude.add_idea(text)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}


    # ------------------------------------------------------------ Docs & Checklists (stage 5)
    def docs_call(fn):
        try:
            return fn()
        except LookupError:
            raise HTTPException(404, "not found")
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))

    def inside(session_cwd: str, folder: str) -> bool:
        a, b = session_cwd.lower().rstrip("/" + chr(92)), folder.lower().rstrip("/" + chr(92))
        return bool(a) and (b == a or b.startswith(a + chr(92)) or b.startswith(a + "/"))

    def owner_view(meta: dict) -> dict:
        """Who owns a doc and whether that session is running: from the session that published it, else the
        newest live session whose folder contains the file (the deepest folder first), else nobody."""
        o = meta.get("owner") or {}
        sessions, fresh = state.sessions.sessions_snapshot()
        sid = o.get("sid") or ""
        if sid:
            s = next((x for x in sessions if x["id"] == sid), None)
            if s:
                return {"sid": sid, "title": s["title"], "cwd": s["cwd"], "state": "running", "busy": s["state"], "kind": s["kind"]}
            return {"sid": sid, "title": o.get("title") or "A Claude session", "cwd": o.get("cwd", ""),
                    "state": "ended" if fresh else "unknown", "busy": "", "kind": ""}
        folder = ntpath.dirname(meta.get("source") or "") or o.get("cwd") or ""
        if folder and fresh:
            c = [x for x in sessions if inside(x["cwd"], folder)]
            if c:
                s = max(c, key=lambda x: (len(x["cwd"]), x["updated"]))
                return {"sid": s["id"], "title": s["title"], "cwd": s["cwd"], "state": "running", "busy": s["state"], "kind": s["kind"],
                        "by_folder": True}
        return {"sid": "", "title": "", "cwd": folder, "state": "none", "busy": "", "kind": ""}

    @app.get("/api/docs")
    def docs_list(req: Request):
        need_app(req)
        return state.docs.summary(owner_view, state.sessions.gate_docs())

    @app.get("/api/docs/{slug}")
    def docs_get(req: Request, slug: str):
        need_app(req)
        return docs_call(lambda: state.docs.get(slug, owner_view, state.sessions.gate_for_doc(slug)))

    @app.get("/api/docs/{slug}/pdf")
    def docs_pdf(req: Request, slug: str):
        need_app(req)
        p = state.docs.pdf_path(slug)
        if not p:
            raise HTTPException(404, "no PDF")
        return FileResponse(p, media_type="application/pdf")

    @app.post("/api/docs/{slug}/sent")
    def docs_sent(req: Request, slug: str, d: dict = Body(default={})):
        """Comments that went to Claude another way (a rejected plan carries them as feedback)."""
        need_app(req)
        n = docs_call(lambda: state.docs.mark_sent(slug, {str(i) for i in (d.get("ids") or [])[:200]}))
        return {"ok": True, "marked": n}

    @app.post("/api/docs/{slug}/start-session")
    def docs_start_session(req: Request, slug: str, d: dict = Body(default={})):
        """No session owns this doc: type a request into the boss session, which starts one. Signed (fingerprint)."""
        need_app(req)
        m = docs_call(lambda: state.docs.get(slug, owner_view))
        batch, ids = state.docs.batch(slug)
        if not batch:
            raise HTTPException(400, "There are no new comments to hand over.")
        o = m.get("owner") or {}
        folder = str(d.get("folder") or "")[:200] or o.get("cwd") or ntpath.dirname(m.get("source") or "") or "D:" + chr(92) + "projekty"
        src = m.get("source") or ""
        text = (f'Mission Control: Filip commented on "{m["title"]}" on his phone and no Claude session owns it. Please start a session for it with '
                f"start_session (folder: {folder}) and this brief: apply or answer his comments"
                + (f" on {src}" if src else "") + f", then tell him it started. (Sent from Mission Control on my phone.)\n\nComments:\n{batch}\n"
                + f"(Also in D:{chr(92)}ai-hub{chr(92)}files{chr(92)}docs{chr(92)}{slug}{chr(92)}comments.md)")[:3900]
        r = sess_call(lambda: state.sessions.start_from_doc(_hash_token(bearer(req)), slug, text, d))
        state.docs.mark_sent(slug, set(ids))
        state.system.log("doc", f"Doc handed to the boss session: {slug}")
        return {"ok": True, "boss": r.get("boss", ""), "folder": folder}

    @app.post("/api/docs/{slug}/item/{item_id}")
    def docs_item(req: Request, slug: str, item_id: int, d: dict = Body(default={})):
        need_app(req)
        return docs_call(lambda: state.docs.set_item(slug, item_id, d.get("status"), d.get("note")))

    @app.post("/api/docs/{slug}/comment")
    def docs_comment(req: Request, slug: str, d: dict = Body(default={})):
        need_app(req)
        return docs_call(lambda: state.docs.comment(slug, d.get("text", ""), d.get("item"), d.get("line")))

    @app.post("/api/docs/{slug}/comment/{cid}/resolve")
    def docs_resolve(req: Request, slug: str, cid: str):
        need_app(req)
        docs_call(lambda: state.docs.resolve(slug, cid))
        return {"ok": True}

    @app.post("/api/docs/{slug}/item/{item_id}/shot")
    async def docs_shot(req: Request, slug: str, item_id: int):
        need_app(req)
        data = await req.body()
        return {"file": docs_call(lambda: state.docs.add_shot(slug, item_id, data))}

    @app.get("/api/docs/{slug}/shot/{file}")
    def docs_shot_get(req: Request, slug: str, file: str):
        need_app(req)
        p = state.docs.shot_path(slug, file)
        if not p:
            raise HTTPException(404, "not found")
        return FileResponse(p, media_type="image/jpeg")

    @app.post("/api/docs/{slug}/text")
    def docs_text(req: Request, slug: str, d: dict = Body(default={})):
        need_app(req)
        docs_call(lambda: state.docs.set_text(slug, str(d.get("text", ""))))
        return {"ok": True}

    @app.post("/api/docs/{slug}/{event}")
    def docs_event(req: Request, slug: str, event: str):
        need_app(req)
        if event not in ("finish", "send"):
            raise HTTPException(404, "not found")
        owner = None
        if event == "send":
            owner = owner_view(docs_call(lambda: state.docs.meta(slug)))
            if owner["state"] == "none":
                raise HTTPException(409, "No Claude session owns this doc. Use Start a session instead.")
        docs_call(lambda: state.docs.event(slug, event, owner))
        state.system.log("doc", f"{'Checklist finished' if event == 'finish' else 'Comments sent to a session'}: {slug}")
        if event == "finish":                      # a checklist attached to a to-do item closes the item
            tid = state.docs.todo_of(slug)
            if tid:
                _, changed = state.todos.close_from_checklist(tid, state.docs.result_phrase(slug))
                if changed:
                    state.system.log("todo", f"To-do closed by its checklist: {tid}")
        return {"ok": True}

    @app.post("/api/pc/docs/upload")
    def pc_docs_upload(req: Request, d: dict = Body(default={})):
        need_pc(req)
        m = docs_call(lambda: state.docs.upload(str(d.get("kind")), str(d.get("name", "")), str(d.get("text", "")), owner=d.get("owner"),
                                                 source=str(d.get("source") or ""), subject=str(d.get("subject") or ""), title=str(d.get("title") or ""),
                                                 pdf_failed=str(d.get("pdf_failed") or ""), file=str(d.get("file") or "")))
        if m.get("updated", 0) > time.time() - 5 and m["kind"] != "plan":      # a plan announces itself when Claude asks to approve it
            st = state.settings
            if not st["muted"] and st["kinds"].get("claude", True):
                title = {"checklist": "New checklist", "skola": "New school output"}.get(m["kind"], "New doc from Claude")
                body = (m.get("subject", "") + ": " if m["kind"] == "skola" and m.get("subject") else "") + m["title"]
                state.deliver({"at": time.time(), "kind": "doc", "cat": "claude", "title": title, "body": body,
                               "group": f"doc:{m['slug']}", "quiet": in_quiet(st, datetime.now()), "actions": [], "tab": 2})
        return {"ok": True, "slug": m["slug"]}

    @app.post("/api/pc/docs/{slug}/pdf")
    async def pc_docs_pdf(req: Request, slug: str):
        need_pc(req)
        data = await req.body()
        docs_call(lambda: state.docs.save_pdf(slug, data))
        return {"ok": True}

    @app.post("/api/pc/docs/{slug}/delete")
    def pc_docs_delete(req: Request, slug: str):
        need_pc(req)
        docs_call(lambda: state.docs.delete(slug))
        return {"ok": True}

    @app.get("/api/pc/docs/changes")
    def pc_docs_changes(req: Request):
        need_pc(req)
        return {"changes": state.docs.changes(), "events": state.docs.take_events()}

    @app.post("/api/pc/docs/ack")
    def pc_docs_ack(req: Request, d: dict = Body(default={})):
        need_pc(req)
        state.docs.ack(d.get("changes") or [])
        state.docs.ack_events([str(k) for k in (d.get("events") or [])])
        return {"ok": True}

    @app.get("/api/pc/docs/shot/{slug}/{file}")
    def pc_docs_shot(req: Request, slug: str, file: str):
        need_pc(req)
        p = state.docs.shot_path(slug, file)
        if not p:
            raise HTTPException(404, "not found")
        return FileResponse(p, media_type="image/jpeg")

    # ------------------------------------------------------------ Filip's to-do list (stage 11d)
    def todo_call(fn):
        try:
            return fn()
        except LookupError:
            raise HTTPException(404, "not found")
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))

    @app.get("/api/todos")
    def todos_list(req: Request):
        need_app(req)
        return state.todos.view()

    @app.get("/api/todos/{tid}")
    def todos_get(req: Request, tid: str):
        need_app(req)
        return todo_call(lambda: state.todos.get(tid))

    @app.post("/api/todos/{tid}/note")
    def todos_note(req: Request, tid: str, d: dict = Body(default={})):
        need_app(req)
        todo_call(lambda: state.todos.set_note(tid, str(d.get("note", ""))))
        return {"ok": True}

    @app.post("/api/todos/{tid}/photo")
    async def todos_photo(req: Request, tid: str):
        need_app(req)
        data = await req.body()
        return {"file": todo_call(lambda: state.todos.add_photo(tid, data))}

    @app.get("/api/todos/{tid}/photo/{file}")
    def todos_photo_get(req: Request, tid: str, file: str):
        need_app(req)
        p = state.todos.photo_path(tid, file)
        if not p:
            raise HTTPException(404, "not found")
        return FileResponse(p, media_type="image/jpeg")

    @app.post("/api/todos/{tid}/result")
    def todos_result(req: Request, tid: str, d: dict = Body(default={})):
        need_app(req)
        item, changed = todo_call(lambda: state.todos.result(tid, str(d.get("status", "")), d.get("note")))
        if changed:
            state.system.log("todo", f"To-do {item['status']}: {item['title'][:60]}")
        return {"ok": True, "status": item["status"], "changed": changed}

    @app.post("/api/todos/{tid}/reopen")
    def todos_reopen(req: Request, tid: str):
        need_app(req)
        todo_call(lambda: state.todos.reopen(tid))
        return {"ok": True}

    @app.post("/api/pc/todos/upload")
    def pc_todos_upload(req: Request, d: dict = Body(default={})):
        need_pc(req)
        cl = d.get("checklist") if isinstance(d.get("checklist"), dict) else None
        if cl:
            m = docs_call(lambda: state.docs.upload("checklist", str(cl.get("name", "")), str(cl.get("text", "")), todo=str(d.get("id", ""))))
            d = dict(d, checklist=m["slug"])
        else:
            d = dict(d, checklist=None)
        item, new = todo_call(lambda: state.todos.upload(d))
        if new:
            st = state.settings
            if not st["muted"] and st["kinds"].get("claude", True):
                state.deliver({"at": time.time(), "kind": "todo", "cat": "claude", "title": "New to-do for you", "body": item["title"],
                               "group": f"todo:{item['id']}", "quiet": in_quiet(st, datetime.now()), "actions": [], "tab": 4})
            state.system.log("todo", f"New to-do: {item['title'][:60]}")
        return {"ok": True, "new": new}

    @app.get("/api/pc/todos/changes")
    def pc_todos_changes(req: Request):
        need_pc(req)
        return {"changes": state.todos.changes()}

    @app.post("/api/pc/todos/ack")
    def pc_todos_ack(req: Request, d: dict = Body(default={})):
        need_pc(req)
        state.todos.ack([str(k) for k in (d.get("ids") or [])][:50])
        return {"ok": True}

    @app.post("/api/pc/todos/delivery")
    def pc_todos_delivery(req: Request, d: dict = Body(default={})):
        need_pc(req)
        state.todos.set_delivery(str(d.get("id", "")), str(d.get("state", "")), str(d.get("detail", "")))
        return {"ok": True}

    @app.get("/api/pc/todos/photo/{tid}/{file}")
    def pc_todos_photo(req: Request, tid: str, file: str):
        need_pc(req)
        p = state.todos.photo_path(tid, file)
        if not p:
            raise HTTPException(404, "not found")
        return FileResponse(p, media_type="image/jpeg")

    # ------------------------------------------------------------ System tab + widget (stage 6)
    @app.get("/api/system")
    def system_view(req: Request):
        need_app(req)
        return state.system.view()

    @app.post("/api/system/screenshot")
    def system_shot_request(req: Request):
        need_app(req)
        if time.time() - state.helper_at > HELPER_STALE:
            raise HTTPException(409, "PC helper not connected (is the PC on?)")
        state.system.request_shot()
        return {"ok": True}

    @app.get("/api/system/screenshot.jpg")
    def system_shot(req: Request):
        need_app(req)
        p = state.system.shot_path()
        if not p:
            raise HTTPException(404, "no screenshot yet")
        return FileResponse(p, media_type="image/jpeg")

    @app.post("/api/pc/screenshot")
    async def pc_screenshot(req: Request):
        need_pc(req)
        try:
            state.system.save_shot(await req.body())
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.get("/api/widget")
    def widget(req: Request):
        """Small summary for the home-screen widget."""
        need_app(req)
        try:
            st = state.pcw_status()
        except PcWakerError as e:
            raise HTTPException(502, e.msg)
        sessions = (st.get("agent") or {}).get("sessions") or []
        waiting = sum(1 for s in sessions if s.get("status") == "waiting")
        working = sum(1 for s in sessions if s.get("status") not in ("waiting", "shell", "idle", "done", None))
        cv = state.claude.view()
        lv = state.sessions.list_view()
        pend = len(cv.get("pending") or cv.get("approvals") or []) + len(lv["gates"]) + len(lv["proposals"])   # all requests for the phone
        lists = state.docs.summary()["checklists"]          # newest first
        cl = next((c for c in lists if not c.get("finished_at")), lists[0] if lists else None)
        return {"pc": {"online": bool(st.get("pc", {}).get("online")), "helper": time.time() - state.helper_at < HELPER_STALE},
                "claude": {"working": working, "waiting": waiting}, "approvals": pend, "todos": state.todos.open_count(),
                "checklist": ({"title": cl["title"], "done": cl["done"], "total": cl["total"], "failed": cl["failed"],
                                                    "finished": bool(cl.get("finished_at"))} if cl else None),
                "now": time.time()}

    return app


# ---------------------------------------------------------------- CLI

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "setup":
        env = read_env(ENV_FILE)
        updates = {k: v for k, v in DEFAULTS.items() if k not in env}
        if not env.get("PC_TOKEN"):
            updates["PC_TOKEN"] = secrets.token_urlsafe(32)
        write_env(ENV_FILE, updates)
        print(f"Wrote {ENV_FILE}")
    elif cmd == "token-add" and len(sys.argv) > 2:
        print(AppState(load_config()).add_token(sys.argv[2]))
    elif cmd == "token-list":
        for h, r in load_json("tokens.json", {}).items():
            print(h[:8], r["name"], datetime.fromtimestamp(r["created"]).strftime("%Y-%m-%d %H:%M"))
    elif cmd == "token-revoke" and len(sys.argv) > 2:
        toks = load_json("tokens.json", {})
        keep = {h: r for h, r in toks.items() if r["name"] != sys.argv[2]}
        save_json("tokens.json", keep)
        print(f"revoked {len(toks) - len(keep)}; restart: sudo systemctl restart mission-control")
    elif cmd in ("roblox-key", "ha-token"):
        import getpass
        name = "ROBLOX_KEY" if cmd == "roblox-key" else "HA_TOKEN"
        val = getpass.getpass(f"Paste the {name} (hidden): ").strip()
        if not val:
            sys.exit("nothing entered")
        write_env(ENV_FILE, {name: val})
        print(f"{name} saved to {ENV_FILE} (mode 600). Restart: sudo systemctl restart mission-control")
        if name == "ROBLOX_KEY":
            from system_hub import SystemHub as _S
            cfg = load_config()
            h = _S(STATE, cfg, load_json, save_json, pi_health)
            try:
                n = h._analytics_query("DailyActiveUsers", 3)
                print(f"key OK: daily players readable ({len(n)} days)")
                try:
                    r = h._analytics_query("DailyRevenue", 3)
                    print(f"earnings readable ({len(r)} days)")
                except RuntimeError as e:
                    print(f"earnings NOT readable: {e}")
            except RuntimeError as e:
                print(f"key saved, but the test call failed: {e}")
    elif cmd == "pc-token":
        print(load_config()["PC_TOKEN"])
    elif cmd == "serve":
        import uvicorn
        cfg = load_config()
        if not cfg.get("PC_TOKEN"):
            sys.exit(f"{ENV_FILE}: no PC_TOKEN. Run: python3 mcpi.py setup")
        pcw_secrets(cfg)   # fail early if pc-waker.env is unreadable
        uvicorn.run(make_app(AppState(cfg)), host=cfg["BIND"], port=int(cfg["PORT"]),
                    log_level="warning", access_log=False)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
