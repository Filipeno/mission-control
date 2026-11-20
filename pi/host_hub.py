"""The laptop as a second host in Mission Control (Pi side).

The laptop agent pushes its own status (``POST /api/host/report``, bearer host token, LAN / VPN only); the PC helper adds
what only the PC knows (laptop mode, app list, monitor stream) to its normal report. Everything the phone can do goes
through the PC (mc-pc runs fixed scripts), the laptop itself never receives a command. Wake is a magic packet sent
from here. Nothing is trusted: every field is cleaned (type, range, length) before it is stored or shown.

Public repo: no addresses, MACs or tokens in this file; they come from ``mc-pi.env`` (see ``mc-pi.env.example``).
"""
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import threading
import time

# Filip's tier scale (pi/tiers.py): "0" none, "M" the 5-minute fingerprint window, "H" every time. One line to change.
HOST_TIERS = {"wake": "0", "open": "M", "mode": "M", "clip": "M"}
MODES = ("monitor", "app", "own", "auto")            # what the phone may ask for
SHOWN_MODES = ("monitor", "app", "own", "unknown")   # what the PC reports
HOST_ID = "laptop"

MAX_BODY = 8192
REPORT_GAP = 5            # a host may report at most once per this many seconds (429)
STALE_FACTOR = 3          # stale = this many times the host's own next_in_s
WAKE_TIMEOUT = 120        # a wake the laptop never answers is reported as failed after this long
WAKE_COOLDOWN = 10
JOB_TTL = 120             # a PC job the PC never answers (mc-pc kills its own after 90 s) is dropped after this long
JOB_SHOW = 60             # a finished job stays visible on the tile this long
PC_FRESH = 90             # PC-side facts (mode, apps) older than this are shown as unknown
PROBE_FRESH = 60
PROBE_PORTS = (22, 47990)
LOW_BATTERY = 20
STREAM_MIN = 60           # a stream shorter than this that ends is not "died"
MC_STOP_WINDOW = 30
EVENT_PER_HOUR = 3
SLOW_MBPS = 1000


class HostError(Exception):
    """Carries the HTTP status the endpoint should answer with."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


# ------------------------------------------------------------------ cleaning

def _num(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return None
    return v if lo <= v <= hi else None


def _int(v, lo, hi):
    n = _num(v, lo, hi)
    return None if n is None else int(n)


def _bool(v):
    return v if isinstance(v, bool) else None


def _text(v, n):
    if v is None or isinstance(v, (dict, list)):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(v)).strip()[:n]


def _dict(v):
    return v if isinstance(v, dict) else {}


def parse_body(raw):
    """JSON object from a request body of at most MAX_BODY bytes."""
    if len(raw) > MAX_BODY:
        raise HostError(413, "body too large")
    try:
        d = json.loads(raw.decode("utf-8") if raw else "{}")
    except (ValueError, UnicodeDecodeError):
        raise HostError(400, "bad JSON")
    if not isinstance(d, dict):
        raise HostError(400, "JSON object expected")
    return d


def clean_report(d):
    """The laptop's report, reduced to known keys with sane types. None when it is not an object."""
    if not isinstance(d, dict):
        return None
    pw, nt, ap, bk = _dict(d.get("power")), _dict(d.get("net")), _dict(d.get("apollo")), _dict(d.get("backup"))
    status = _text(bk.get("status"), 10).lower()
    ntype = _text(nt.get("type"), 12).lower()
    return {
        "v": _int(d.get("v"), 0, 100) or 1,
        "next_in_s": _int(d.get("next_in_s"), 5, 600) or 15,
        "power": {"mains": _bool(pw.get("mains")), "battery_pct": _int(pw.get("battery_pct"), 0, 100)},
        "net": {"type": ntype if ntype in ("ethernet", "wifi", "other") else "unknown",
                "speed_mbps": _int(nt.get("speed_mbps"), 0, 1000000), "name": _text(nt.get("name"), 40)},
        "apollo": {"service": _bool(ap.get("service")), "web": _bool(ap.get("web")),
                   "stream_active": _bool(ap.get("stream_active"))},
        "moonlight_running": _bool(d.get("moonlight_running")),
        "backup": {"status": status if status in ("ok", "failed") else "unknown",
                   "last_ok": _int(bk.get("last_ok"), 1, 4102444800), "at": _int(bk.get("at"), 1, 4102444800),
                   "detail": _text(bk.get("detail"), 120)},
        "uptime_s": _int(d.get("uptime_s"), 0, 10 ** 9),
    }


def clean_pc_laptop(d):
    """The ``laptop`` block of the PC helper's report. None when missing or not an object."""
    if not isinstance(d, dict):
        return None
    mode = _text(d.get("mode"), 10).lower()
    apps, seen = [], set()
    for a in d.get("apps") if isinstance(d.get("apps"), list) else []:
        a = _text(a, 60)
        if a and a not in seen:
            seen.add(a)
            apps.append(a)
    return {"mode": mode if mode in SHOWN_MODES else "unknown", "mode_since": _int(d.get("mode_since"), 1, 4102444800),
            "manual": d.get("manual") is True, "apps": apps[:20], "monitor_stream": d.get("monitor_stream") is True}


# ------------------------------------------------------------------ network helpers

def parse_nets(text):
    nets = []
    for part in str(text or "").split(","):
        part = part.strip()
        if part:
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                pass
    return nets


def net_allowed(ip, nets):
    """True when [ip] is inside one of the allowed networks. Loopback (a tunnel connector on the Pi) never is."""
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    if a.is_loopback or a.is_unspecified:
        return False
    return any(a.version == n.version and a in n for n in nets)


def magic_packet(mac):
    digits = re.sub(r"[^0-9A-Fa-f]", "", str(mac or ""))
    if len(digits) != 12:
        raise ValueError("bad MAC address")
    return b"\xff" * 6 + bytes.fromhex(digits) * 16


def send_wol(mac, broadcast="255.255.255.255", source_ip="", port=9, repeat=3):
    """Broadcast the magic packet (same ten lines as pc-waker's wol.py; that project stays untouched)."""
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if source_ip:
            s.bind((source_ip, 0))
        for _ in range(repeat):
            s.sendto(packet, (broadcast, port))


def tcp_probe(ip, ports=PROBE_PORTS, timeout=0.5):
    for p in ports:
        try:
            with socket.create_connection((ip, p), timeout=timeout):
                return True
        except OSError:
            pass
    return False


# ------------------------------------------------------------------ the hub

class HostHub:
    def __init__(self, load_json, save_json, deliver, claude, cfg, helper_ok, settings_fn, quiet_fn, syslog,
                 clock=time.time, sender=send_wol, probe=tcp_probe):
        self.load_json, self.save_json, self.deliver, self.claude = load_json, save_json, deliver, claude
        self.cfg, self.helper_ok, self.settings_fn, self.quiet_fn, self.syslog = cfg, helper_ok, settings_fn, quiet_fn, syslog
        self.clock, self.sender, self.probe = clock, sender, probe
        self.lock = threading.RLock()
        self.nets = parse_nets(cfg.get("HOST_ALLOW_NETS"))
        self.st = {}                        # host id -> runtime state (reports are not persisted; the agent re-sends)
        self.pc = None                      # the PC's view of the laptop (mode, apps, monitor stream)
        self.pc_at = 0.0
        self.pc_cap_at = 0.0                # last PC report that advertised the "laptop" capability
        self.job = None                     # the one PC job (open / mode / clip) in flight or just finished
        self.mc_stop_at = 0.0
        self.last_wake_try = -1e9
        self.probe_up, self.probe_at = None, 0.0
        saved = load_json("host-state.json", {})
        self.notified = saved.get("notified") if isinstance(saved.get("notified"), dict) else {}
        self.events = {}                    # (host, kind) -> [times] for the 3-per-hour limit
        self.saved_seen = _dict(saved.get("last_seen"))

    # ------------------------------------------------------------ registry and auth
    def _hosts(self):
        h = self.load_json("hosts.json", {})
        return h if isinstance(h, dict) else {}

    def add_token(self, hid=HOST_ID, name="Laptop", kind="laptop"):
        if not re.fullmatch(r"[a-z0-9-]{1,20}", hid or ""):
            raise ValueError("bad host id")
        tok = secrets.token_urlsafe(32)
        with self.lock:
            hosts = self._hosts()
            hosts[hid] = {"name": name[:40], "kind": kind[:20], "token_sha256": hashlib.sha256(tok.encode()).hexdigest(),
                          "created": self.clock(), "seen": None}
            self.save_json("hosts.json", hosts)
        return tok

    def revoke(self, hid):
        with self.lock:
            hosts = self._hosts()
            gone = hosts.pop(hid, None) is not None
            self.save_json("hosts.json", hosts)
            return gone

    def list_hosts(self):
        return [(i, r.get("name", ""), r.get("created"), r.get("seen")) for i, r in sorted(self._hosts().items())]

    def host_for_token(self, tok):
        """The host id that owns [tok] (never read from a request body). hosts.json is re-read on every call, so a CLI
        add or revoke applies at once; the compare runs over all hosts in constant time per entry."""
        if not tok:
            return None
        h = hashlib.sha256(tok.encode()).hexdigest()
        found = None
        for hid, rec in self._hosts().items():
            if isinstance(rec, dict) and hmac.compare_digest(str(rec.get("token_sha256", "")), h):
                found = hid
        return found

    def net_ok(self, ip):
        return net_allowed(ip, self.nets)

    def _state(self, hid):
        return self.st.setdefault(hid, {"rep": None, "at": 0.0, "last_report": -1e9, "wake_at": 0.0, "wake_note": "",
                                        "wake_notified": True, "stream": False, "stream_since": 0.0})

    # ------------------------------------------------------------ from the laptop
    def on_report(self, hid, d):
        rep = clean_report(d)
        if rep is None:
            raise HostError(400, "bad report")
        with self.lock:
            now = self.clock()
            s = self._state(hid)
            if now - s["last_report"] < REPORT_GAP:
                raise HostError(429, "too many reports")
            gap = now - s["at"] if s["rep"] else 1e9
            s["last_report"] = now
            prev_stream = s["stream"] and gap < STALE_FACTOR * (s["rep"] or rep)["next_in_s"] + 5
            s["rep"], s["at"] = rep, now
            s["wake_note"] = ""
            self._seen(hid, now)
            self._edges(hid, s, rep, now, prev_stream)

    def _seen(self, hid, now):
        if now - float(self.saved_seen.get(hid) or 0) < 300:
            return
        self.saved_seen[hid] = now
        self._save()

    def _save(self):
        self.save_json("host-state.json", {"notified": self.notified, "last_seen": self.saved_seen})

    def _edges(self, hid, s, rep, now, prev_stream):
        n = self.notified.setdefault(hid, {})
        changed = False
        # battery: once per discharge
        mains, pct = rep["power"]["mains"], rep["power"]["battery_pct"]
        if mains is True and n.get("battery"):
            n["battery"], changed = False, True
        elif mains is False and pct is not None and pct < LOW_BATTERY and not n.get("battery"):
            n["battery"], changed = True, True
            self._notify("host-battery-low", "battery low", f"{pct} % left and not charging.")
        # backup: once per failed run (its "at")
        bk = rep["backup"]
        if bk["status"] == "failed":
            key = bk["at"] or 0
            if n.get("backup_at") != key:
                n["backup_at"], changed = key, True
                self._notify("host-backup-failed", "backup failed", bk["detail"] or "The last backup did not finish.")
        # stream: died = was on for a minute, then ended without MC stopping it, while the PC is up
        cur = rep["apollo"]["stream_active"] is True
        if cur and not prev_stream:
            s["stream_since"] = now
        elif prev_stream and not cur:
            if now - s["stream_since"] >= STREAM_MIN and not self._mc_stopping(now) and self.helper_ok():
                self._notify("host-stream-died", "stream ended", "The stream stopped without being closed from Mission Control.")
        s["stream"] = cur
        # slow link while streaming: quiet, once a day
        sp = rep["net"]["speed_mbps"]
        day = int(now // 86400)
        if cur and sp is not None and 0 < sp < SLOW_MBPS and n.get("slow_day") != day:
            n["slow_day"], changed = day, True
            self._notify("host-slow-link", "slow link", f"Network link is {sp} Mbit/s; streams may stutter.", quiet=True)
        if changed:
            self._save()

    def on_event(self, hid, d):
        if not isinstance(d, dict):
            raise HostError(400, "bad event")
        kind = re.sub(r"[^a-z0-9-]", "", _text(d.get("kind"), 30).lower())
        if not kind:
            raise HostError(400, "bad kind")
        key, title, body = _text(d.get("key"), 40), _text(d.get("title"), 80), _text(d.get("body"), 200)
        with self.lock:
            now = self.clock()
            ts = [t for t in self.events.get((hid, kind), []) if now - t < 3600]
            if len(ts) >= EVENT_PER_HOUR:
                self.events[(hid, kind)] = ts
                raise HostError(429, "too many events of this kind")
            ts.append(now)
            self.events[(hid, kind)] = ts
        self._notify("host-ev-" + kind, title or kind, body, group_extra=key)

    # ------------------------------------------------------------ from the PC helper
    def on_pc_report(self, d):
        """[d] is the whole PC report: its ``laptop`` block and the ``caps`` list."""
        d = _dict(d)
        block = clean_pc_laptop(d.get("laptop"))
        caps = d.get("caps") if isinstance(d.get("caps"), list) else []
        with self.lock:
            now = self.clock()
            if "laptop" in caps:
                self.pc_cap_at = now
            if block is not None:
                self.pc, self.pc_at = block, now

    def on_result(self, d):
        key = _text(_dict(d).get("key"), 80)
        if not key.startswith("host-"):
            return
        ok, detail = d.get("ok") is True, _text(d.get("detail"), 160)
        with self.lock:
            now = self.clock()
            j = self.job
            if not j or j["key"] != key or j["state"] != "requested":
                return
            self.job = dict(j, state="done" if ok else "failed", detail=detail, done_at=now)
            self.mc_stop_at = now
            if ok and j["action"] == "mode" and j["arg"] in ("monitor", "app", "own") and self.pc:
                self.pc = dict(self.pc, mode=j["arg"], mode_since=int(now), manual=True)
                self.pc_at = now
            if ok and j["action"] == "mode" and j["arg"] == "auto" and self.pc:
                self.pc = dict(self.pc, manual=False)
            if j["action"] == "open":
                if ok:
                    self._notify("host-open-done", f"{j['arg']} is open on the PC", detail, quiet=True)
                else:
                    self._notify("host-open-failed", f"could not open {j['arg']}", detail or "The PC did not open it.")

    # ------------------------------------------------------------ periodic (status watcher, every 15 s)
    def tick(self):
        with self.lock:
            now = self.clock()
            s = self.st.get(HOST_ID)
            if s and s["wake_at"] and not s["wake_notified"] and now - s["wake_at"] >= WAKE_TIMEOUT:
                s["wake_notified"] = True
                if s["at"] < s["wake_at"]:                 # no report since the wake
                    s["wake_note"] = "Wake sent, laptop did not answer"
                    self._notify("host-wake-failed", "did not wake", "Wake sent, laptop did not answer. Not confirmed.")
            j = self.job
            if j and j["state"] == "requested" and now - j["at"] >= JOB_TTL:
                self.job = dict(j, state="failed", detail="PC did not answer in time", done_at=now)
                if j["action"] == "open":
                    self._notify("host-open-failed", f"could not open {j['arg']}", "PC did not answer in time.")
            ip = _text(self.cfg.get("HOST_LAPTOP_IP"), 45)
            online = bool(s and s["rep"] and self._fresh(s, now))
        if ip and not online:                               # outside the lock: the probe can take a second
            up = self.probe(ip)
            with self.lock:
                self.probe_up, self.probe_at = up, self.clock()

    # ------------------------------------------------------------ from the app
    def _fresh(self, s, now):
        return bool(s["rep"]) and now - s["at"] < STALE_FACTOR * s["rep"]["next_in_s"]

    def wake_configured(self):
        try:
            magic_packet(self.cfg.get("HOST_LAPTOP_MAC"))
            return True
        except ValueError:
            return False

    def request_wake(self):
        with self.lock:
            now = self.clock()
            if not self.wake_configured():
                raise HostError(409, "Wake is not set up on the Pi")
            s = self._state(HOST_ID)
            if self._fresh(s, now):
                raise HostError(409, "The laptop is already online")
            if now - self.last_wake_try < WAKE_COOLDOWN:
                raise HostError(429, "Wait a few seconds before waking again")
            try:
                self.sender(self.cfg.get("HOST_LAPTOP_MAC"), self.cfg.get("HOST_LAPTOP_BCAST") or "255.255.255.255",
                            self.cfg.get("HOST_LAPTOP_SOURCE_IP") or "")
            except OSError as e:
                raise HostError(502, f"Could not send the packet: {e}")
            self.last_wake_try = now
            s.update(wake_at=now, wake_note="", wake_notified=False)
            self.syslog("host", "Wake sent to the laptop (not confirmed until it reports)")
            return {"ok": True, "state": "waking"}

    def _running(self, now):
        j = self.job
        return bool(j) and j["state"] == "requested" and now - j["at"] < JOB_TTL

    def _mc_stopping(self, now):
        return (self._running(now) and self.job["action"] == "mode") or now - self.mc_stop_at <= MC_STOP_WINDOW

    def request(self, action, token_hash, d):
        """open / mode / clip: run a fixed script on the PC through mc-pc. Raises HostError."""
        if action not in ("open", "mode", "clip"):
            raise HostError(400, "unknown action")
        d = _dict(d)
        with self.lock:
            now = self.clock()
            arg = ""
            if action == "mode":
                arg = _text(d.get("mode"), 10)
                if arg not in MODES:
                    raise HostError(400, "bad mode")
            elif action == "open":
                arg = _text(d.get("app"), 60)
                apps = self.pc["apps"] if self.pc and now - self.pc_at < PC_FRESH else []
                if arg not in apps:
                    raise HostError(400, "The PC did not list this app")
            if now - self.pc_cap_at > PC_FRESH:
                raise HostError(409, "The PC helper does not support the laptop yet (update mc-pc first)")
            if not self.helper_ok():
                raise HostError(409, "PC helper not connected (is the PC on?)")
            if self._running(now):
                raise HostError(409, "A laptop job is already running")
            if action == "clip" and not self._fresh(self._state(HOST_ID), now):
                raise HostError(409, "The laptop is not online")
            try:
                ts = int(d.get("ts") or 0)
            except (TypeError, ValueError):
                raise HostError(400, "bad ts")
            try:
                self.claude.verify(token_hash, f"host|{action}|{arg}|{ts}", str(d.get("sig", "")), ts, tier=HOST_TIERS[action])
            except PermissionError as e:
                raise HostError(403, str(e))
            key = f"host-{action}-{int(now * 1000)}"
            item = {"key": key, "kind": "laptop-" + action, "at": now}
            if action == "open":
                item["app"] = arg
            elif action == "mode":
                item["mode"] = arg
            self.claude.enqueue(item)
            self.job = {"key": key, "action": action, "arg": arg, "state": "requested", "detail": "", "at": now, "done_at": None}
            if action == "mode":
                self.mc_stop_at = now
            self.syslog("host", f"Laptop {action} requested from the phone")
            return {"ok": True, "key": key}

    # ------------------------------------------------------------ views
    def _job_view(self, action, now):
        j = self.job
        if not j or j["action"] != action:
            return None
        if j["state"] == "requested":
            if now - j["at"] >= JOB_TTL:
                return {"state": "failed", "arg": j["arg"], "detail": "PC did not answer in time", "at": j["at"]}
        elif now - (j["done_at"] or 0) > JOB_SHOW:
            return None
        return {"state": j["state"], "arg": j["arg"], "detail": j["detail"], "at": j["at"]}

    def laptop_view(self):
        """``hosts.laptop`` for GET /api/home, or None when no laptop token was ever made."""
        with self.lock:
            if HOST_ID not in self._hosts():
                return None
            now = self.clock()
            s = self._state(HOST_ID)
            rep = s["rep"] or {}
            fresh = self._fresh(s, now)
            waking = bool(s["wake_at"]) and not fresh and now - s["wake_at"] < WAKE_TIMEOUT and s["at"] < s["wake_at"]
            probe = self.probe_up if now - self.probe_at < PROBE_FRESH else None
            if fresh:
                state = "online"
            elif waking:
                state = "waking"
            elif probe is False:
                state = "asleep"
            else:
                state = "unknown"
            pcf = self.pc if self.pc and now - self.pc_at < PC_FRESH else None
            net = rep.get("net") or {}
            warnings = []
            if fresh and net.get("speed_mbps") is not None and 0 < net["speed_mbps"] < SLOW_MBPS:
                warnings.append("slow_link")
            note = s["wake_note"] if not fresh and not waking else ""
            return {
                "id": HOST_ID, "name": "Laptop", "state": state,
                "since": s["at"] - (rep.get("uptime_s") or 0) if fresh and rep.get("uptime_s") is not None else None,
                "last_seen": s["at"] or self.saved_seen.get(HOST_ID),
                "power": rep.get("power") or {}, "net": net, "apollo": rep.get("apollo") or {},
                "moonlight_running": rep.get("moonlight_running"),
                "monitor_stream": pcf["monitor_stream"] if pcf else None,
                "mode": {"value": pcf["mode"] if pcf else "unknown", "since": pcf["mode_since"] if pcf else None,
                         "known": bool(pcf) and pcf["mode"] != "unknown", "manual": bool(pcf and pcf["manual"])},
                "backup": rep.get("backup") or {"status": "unknown"},
                "apps": list(pcf["apps"]) if pcf else [],
                "pending": {"wake": waking, "wake_note": note, "open": self._job_view("open", now),
                            "mode": self._job_view("mode", now), "clip": self._job_view("clip", now), "chain": None},
                "pc_helper": bool(self.helper_ok()),
                "pc_laptop_support": now - self.pc_cap_at <= PC_FRESH,
                "wake_configured": self.wake_configured(),
                "warnings": warnings, "tiers": dict(HOST_TIERS),
            }

    # ------------------------------------------------------------ notifications
    def _notify(self, kind, title, body, quiet=False, group_extra=""):
        self.syslog("host", f"Laptop: {title}" + (f" ({body})" if body else ""))
        st = self.settings_fn()
        if st.get("muted") or not st.get("kinds", {}).get("host", True):
            return
        self.deliver({"at": self.clock(), "kind": kind, "cat": "host", "title": "Laptop: " + title, "body": body[:200],
                      "group": f"host:laptop:{kind}" + (f":{group_extra}" if group_extra else ""),
                      "quiet": bool(quiet) or bool(self.quiet_fn()), "actions": []})
