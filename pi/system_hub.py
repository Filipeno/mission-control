"""System tab data for mc-pi (stage 6): Pi / mini PC / services / Vaultwarden backup age / Slime Keepers
numbers / PC screenshot / timeline. Python standard library only (the Pi is armv7l).

A background thread refreshes everything every minute; GET /api/system just returns the cached snapshot.
Nothing here writes to anything outside mc-pi's own state folder. The Roblox and Home Assistant keys come from
mc-pi.env (git-ignored) and never leave the Pi.
"""
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

VAULT_STATUS = Path("/var/lib/vaultwarden-backup/status.json")
VAULT_PC_PULL = Path("/var/lib/vaultwarden-backup/pc-pull.json")
VAULT_PI_STALE_H, VAULT_PC_STALE_H = 48, 72      # same limits as the PC pull task
TIMELINE_KEEP, TIMELINE_DAYS = 400, 8
ROBLOX_PUBLIC_EVERY, ROBLOX_ANALYTICS_EVERY = 300, 3600
SERVICES = [("pc-waker", "pc-waker"), ("mission-control", "mission-control"),
            ("bp-gateway", "bp-gateway"), ("cloudflared", "Cloudflare tunnel")]


def _http_json(url: str, headers=None, body=None, timeout=10, method=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"))
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})


class SystemHub:
    def __init__(self, state_dir: Path, cfg: dict, load_json, save_json, pi_health):
        self.dir = Path(state_dir)
        self.cfg = cfg
        self.load_json, self.save_json = load_json, save_json
        self.pi_health = pi_health
        self.lock = threading.Lock()
        self.timeline = load_json("system-timeline.json", [])[-TIMELINE_KEEP:]
        self.snap = {}
        self.prev_services = {}
        self.pc_stats = {}            # sent by mc-pc in its report
        self.pc_stats_at = 0.0
        self.shot_req_at = 0.0        # set by the app, consumed by the PC helper
        self.shot_at = load_json("system-shot.json", {}).get("at")
        self.roblox_pub = {"at": 0}
        self.roblox_an = {"at": 0}
        self.visits_day = load_json("roblox-visits-day.json", {})
        self._seen_vault = (load_json("system-seen.json", {}) or {}).get("vault")

    # ---------------------------------------------------------------- timeline
    def log(self, kind: str, text: str, at: float = None) -> None:
        with self.lock:
            self.timeline.append({"at": at or time.time(), "kind": kind, "text": text[:160]})
            cut = time.time() - TIMELINE_DAYS * 86400
            self.timeline = [e for e in self.timeline if e["at"] > cut][-TIMELINE_KEEP:]
            self.save_json("system-timeline.json", self.timeline)

    # ---------------------------------------------------------------- PC side
    def on_pc_report(self, stats) -> None:
        if isinstance(stats, dict):
            keep = {}
            for k in ("cpu_temp", "gpu_temp", "cpu_load", "gpu_load", "ram_pct"):
                v = stats.get(k)
                if isinstance(v, (int, float)):
                    keep[k] = round(float(v), 1)
            self.pc_stats, self.pc_stats_at = keep, time.time()

    def pc_stats_now(self) -> dict:
        fresh = time.time() - self.pc_stats_at < 90
        return dict(self.pc_stats, fresh=fresh) if fresh else {"fresh": False}

    def request_shot(self) -> None:
        self.shot_req_at = time.time()

    def take_shot_request(self) -> bool:
        if self.shot_req_at and time.time() - self.shot_req_at < 60:
            self.shot_req_at = 0.0
            return True
        return False

    def save_shot(self, data: bytes) -> None:
        if len(data) < 500 or len(data) > 8_000_000 or data[:3] != b"\xff\xd8\xff":
            raise ValueError("not a JPEG")
        tmp = self.dir / "screenshot.tmp"
        tmp.write_bytes(data)
        os.chmod(tmp, 0o600)
        tmp.replace(self.dir / "screenshot.jpg")
        self.shot_at = time.time()
        self.save_json("system-shot.json", {"at": self.shot_at})
        self.log("screenshot", "PC screenshot taken")

    def shot_path(self):
        p = self.dir / "screenshot.jpg"
        return p if p.exists() else None

    # ---------------------------------------------------------------- collectors
    def _services(self) -> list:
        out = []
        for unit, label in SERVICES:
            try:
                s = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True,
                                   timeout=3).stdout.strip() or "unknown"
            except (OSError, subprocess.TimeoutExpired):
                s = "unknown"
            out.append({"id": unit, "name": label, "ok": s == "active", "detail": "Up" if s == "active" else s})
            was = self.prev_services.get(unit)
            if was is not None and was != (s == "active"):
                self.log("service", f"{label} {'is back up' if s == 'active' else 'went down'}")
            self.prev_services[unit] = s == "active"
        return out

    def _vault(self) -> dict:
        now = time.time()
        res = {"name": "Vaultwarden backup", "ok": False, "detail": "no data"}
        try:
            st = json.loads(VAULT_STATUS.read_text())
        except (OSError, ValueError):
            return res
        last = st.get("last_success") or 0
        age_h = (now - last) / 3600 if last else None
        pc = {}
        try:
            pc = json.loads(VAULT_PC_PULL.read_text())
        except (OSError, ValueError):
            pass
        pc_age_h = (now - pc["at"]) / 3600 if pc.get("at") else None
        ok = bool(st.get("ok")) and age_h is not None and age_h < VAULT_PI_STALE_H \
            and pc_age_h is not None and pc_age_h < VAULT_PC_STALE_H and pc.get("cloud", "ok") == "ok"
        detail = "no backup yet" if age_h is None else _ago_h(age_h)
        if pc_age_h is None:
            detail += " · PC copy unknown"
        elif pc_age_h >= VAULT_PC_STALE_H:
            detail += f" · PC copy {_ago_h(pc_age_h)}"
        if last and last != self._seen_vault:
            if self._seen_vault is not None:
                self.log("vault", "Vaultwarden backup saved", at=last)
            self._seen_vault = last
            self.save_json("system-seen.json", {"vault": last})
        return {"name": "Vaultwarden backup", "ok": ok, "detail": detail, "age_h": age_h,
                "pc_copy": pc.get("newest"), "pc_at": pc.get("at")}

    def _tunnel(self, cloudflared_ok: bool) -> dict:
        pub = (self.cfg.get("NTFY_PUBLIC") or "").rstrip("/")
        extra = ""
        ok = cloudflared_ok
        if cloudflared_ok and pub:
            try:
                urllib.request.urlopen(pub + "/v1/health", timeout=6).read()
            except urllib.error.HTTPError:
                pass                       # it answered; that is what we need
            except (urllib.error.URLError, OSError):
                ok, extra = False, "address does not answer"
        return {"ok": ok, "detail": "Up" if ok else (extra or "down")}

    def _mini_pc(self) -> dict:
        url = (self.cfg.get("HA_URL") or "").rstrip("/")
        if not url:
            return {"configured": False}
        host = url.split("//")[-1].split("/")[0].split(":")[0]
        port = int(url.split(":")[-1].split("/")[0]) if url.count(":") > 1 else 80
        up = False
        try:
            socket.create_connection((host, port), timeout=3).close()
            up = True
        except OSError:
            pass
        ha_ok, sensors = False, {}
        if up:
            try:
                urllib.request.urlopen(url + "/manifest.json", timeout=5).read()
                ha_ok = True
            except urllib.error.HTTPError:
                ha_ok = True
            except (urllib.error.URLError, OSError):
                ha_ok = False
            if self.cfg.get("HA_TOKEN"):
                for key, env in (("temp", "HA_TEMP"), ("disk_pct", "HA_DISK"), ("uptime", "HA_UPTIME")):
                    ent = self.cfg.get(env)
                    if not ent:
                        continue
                    try:
                        _, j = _http_json(f"{url}/api/states/{ent}", {"Authorization": f"Bearer {self.cfg['HA_TOKEN']}"}, timeout=6)
                        v = j.get("state")
                        if key == "uptime":
                            sensors[key] = _uptime_s(v)
                        elif v not in (None, "unknown", "unavailable"):
                            sensors[key] = round(float(v), 1)
                    except (urllib.error.URLError, OSError, ValueError, KeyError):
                        pass
        r = {"configured": True, "up": up, "ha": ha_ok, "ok": up and ha_ok, **sensors}
        if self.snap.get("mini_pc", {}).get("ok") not in (None, r["ok"]) and "mini_pc" in self.snap:
            self.log("service", "Mini PC is back up" if r["ok"] else "Mini PC / Home Assistant not answering")
        return r

    def _roblox_public(self) -> dict:
        uid = self.cfg.get("ROBLOX_UNIVERSE")
        if not uid or time.time() - self.roblox_pub["at"] < ROBLOX_PUBLIC_EVERY:
            return self.roblox_pub
        try:
            _, j = _http_json(f"https://games.roblox.com/v1/games?universeIds={uid}", timeout=10)
            g = (j.get("data") or [{}])[0]
            visits = int(g.get("visits") or 0)
            today = datetime.now().strftime("%Y-%m-%d")
            if self.visits_day.get("date") != today:
                self.visits_day = {"date": today, "start": visits}
                self.save_json("roblox-visits-day.json", self.visits_day)
            self.roblox_pub = {"at": time.time(), "name": g.get("name", "Roblox game"), "playing": int(g.get("playing") or 0),
                               "visits": visits, "visits_today": max(0, visits - self.visits_day.get("start", visits)),
                               "favorites": int(g.get("favoritedCount") or 0)}
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
            self.roblox_pub = dict(self.roblox_pub, at=time.time() - ROBLOX_PUBLIC_EVERY + 60, error=str(e)[:100])
        return self.roblox_pub

    def _analytics_query(self, metric: str, days: int) -> list:
        """Open Cloud Analytics Query API (beta): POST a query, poll the long-running operation.
        Returns [(date 'YYYY-MM-DD', value)]. Raises RuntimeError with a short reason."""
        uid, key = self.cfg["ROBLOX_UNIVERSE"], self.cfg["ROBLOX_KEY"]
        h = {"x-api-key": key}
        base = f"https://apis.roblox.com/analytics-query-api/v1/universes/{uid}"
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        body = {"metric": metric, "granularity": "OneDay",
                "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
        try:
            code, j = _http_json(base + "/metrics", h, body, timeout=15)
            deadline = time.time() + 30
            while True:
                if j.get("done") or "response" in j or "values" in j or "rows" in j:
                    break
                op = j.get("path") or j.get("operationId") or j.get("id") or ""
                op = op.split("/")[-1]
                if not op:
                    raise RuntimeError("unexpected answer from Roblox")
                if time.time() > deadline:
                    raise RuntimeError("Roblox took too long")
                time.sleep(2)
                try:
                    code, j = _http_json(f"{base}/operations/metrics/{op}", h, timeout=15)
                except urllib.error.HTTPError as e:
                    if e.code != 202:
                        raise
                    j = {"path": op}
        except urllib.error.HTTPError as e:
            msg = ""
            try:
                msg = json.loads(e.read()).get("message", "")
            except (ValueError, OSError):
                pass
            raise RuntimeError(f"Roblox says {e.code}: {msg[:120]}".strip())
        except (urllib.error.URLError, OSError):
            raise RuntimeError("Roblox not reachable")
        return _parse_series(j)

    def _roblox_analytics(self) -> dict:
        if not self.cfg.get("ROBLOX_KEY"):
            return {"at": 0, "state": "no_key"}
        if time.time() - self.roblox_an["at"] < ROBLOX_ANALYTICS_EVERY:
            return self.roblox_an
        res = {"at": time.time(), "state": "ok"}
        try:
            dau = self._analytics_query("DailyActiveUsers", 7)
            res["players"] = [{"day": d, "n": int(v)} for d, v in dau]
        except RuntimeError as e:
            res.update(state="error", error=str(e))
        if res["state"] == "ok":
            try:
                rev = self._analytics_query("DailyRevenue", 7)
                res["revenue"] = [{"day": d, "robux": round(v)} for d, v in rev]
            except RuntimeError as e:
                res["revenue_error"] = str(e)
        self.roblox_an = res
        return res

    # ---------------------------------------------------------------- snapshot
    def refresh(self) -> None:
        pi = self.pi_health()
        services = self._services()
        vault = self._vault()
        tunnel = self._tunnel(next(s["ok"] for s in services if s["id"] == "cloudflared"))
        mini = self._mini_pc()
        rb_pub, rb_an = self._roblox_public(), self._roblox_analytics()
        with self.lock:
            self.snap = {"at": time.time(), "pi": pi, "services": services, "vault": vault, "tunnel": tunnel,
                         "mini_pc": mini, "roblox": {"public": rb_pub, "analytics": rb_an}}

    def view(self) -> dict:
        with self.lock:
            s = dict(self.snap)
            tl = list(self.timeline)
        s["pc"] = self.pc_stats_now()
        s["shot"] = {"at": self.shot_at, "requested": time.time() - self.shot_req_at < 60}
        s["timeline"] = tl[::-1][:120]
        problems = []
        if s.get("pi") and not s["pi"].get("healthy", True):
            problems.append("Pi")
        if s.get("mini_pc", {}).get("configured") and not s["mini_pc"].get("ok"):
            problems.append("Mini PC")
        for sv in s.get("services", []):
            if not sv["ok"]:
                problems.append(sv["name"])
        if s.get("vault") and not s["vault"]["ok"]:
            problems.append("Vaultwarden backup")
        if s.get("tunnel") and not s["tunnel"]["ok"] and "Cloudflare tunnel" not in problems:
            problems.append("Cloudflare tunnel")
        s["problems"] = problems
        return s

    def run(self) -> None:
        while True:
            try:
                self.refresh()
            except Exception as e:   # noqa: BLE001 - keep the loop alive
                print(f"system refresh: {e}", flush=True)
            time.sleep(60)


def _ago_h(h: float) -> str:
    if h < 1:
        return f"{max(1, int(h * 60))} min ago"
    if h < 48:
        return f"{int(h)} h ago"
    return f"{int(h // 24)} d ago"


def _uptime_s(v):
    """HA 'uptime' sensors are either a timestamp (boot time) or a number of hours/days."""
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - t).total_seconds())
    except ValueError:
        try:
            return int(float(v) * 3600)
        except (TypeError, ValueError):
            return None


def _parse_series(j: dict) -> list:
    """Tolerant reader for the beta response: finds (time, value) pairs wherever they are nested."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            t = o.get("time") or o.get("timestamp") or o.get("startTime") or o.get("date")
            v = o.get("value") if "value" in o else o.get("values")
            if isinstance(t, str) and isinstance(v, (int, float, str)) and str(v).replace(".", "", 1).replace("-", "", 1).isdigit():
                out.append((t[:10], float(v)))
                return
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            if len(o) == 2 and isinstance(o[0], str) and isinstance(o[1], (int, float)):
                out.append((o[0][:10], float(o[1])))
                return
            for x in o:
                walk(x)

    walk(j.get("response", j))
    out.sort()
    return out
