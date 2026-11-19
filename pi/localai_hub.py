"""PC mode switch + live "Local AI" card (Pi side).

mc-pc posts a snapshot (see pc/mc_localai.py) every ~5 s while the phone watches the card (the Pi tells it with
``watching()`` in the command reply) and the PC mode with every regular report. The Pi only adds fields to the
existing API, so an older app keeps working.
"""
import threading
import time

MODES = ("normal", "ai", "gaming")
MODELS = ("", "qwen", "gptoss")
WATCH_TTL = 20            # the card counts as "watched" this long after the app's last GET
SNAP_FRESH = 30           # a snapshot older than this is shown as "no live data"
SWITCH_TTL = 300          # a switch the PC never reports back is dropped after this long (pc-mode waits <= 240 s)
REPORT_SLUG = "local-agent-trials-report"
REPORT_NAME = REPORT_SLUG + ".md"


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _text(v, n):
    return None if v is None else str(v)[:n]


def clean_snapshot(d):
    """Shape the PC's snapshot; unknown or malformed parts become None."""
    if not isinstance(d, dict):
        return None
    srv = d.get("server") if isinstance(d.get("server"), dict) else {}
    gpu = d.get("gpu") if isinstance(d.get("gpu"), dict) else None
    ram = d.get("ram") if isinstance(d.get("ram"), dict) else None
    job = d.get("job") if isinstance(d.get("job"), dict) else {}
    log = job.get("log") if isinstance(job.get("log"), dict) else None
    agent = job.get("agent") if isinstance(job.get("agent"), dict) else None
    rep = d.get("report") if isinstance(d.get("report"), dict) else {}
    lc = agent.get("last_check") if agent and isinstance(agent.get("last_check"), dict) else None
    state = srv.get("state") if srv.get("state") in ("down", "loading", "idle", "busy") else "down"
    return {
        "server": {"state": state, "model": _text(srv.get("model"), 60), "ctx": _num(srv.get("ctx")),
                   "slots": int(_num(srv.get("slots")) or 0), "busy": int(_num(srv.get("busy")) or 0),
                   "tok_s": _num(srv.get("tok_s")), "prompt_tok_s": _num(srv.get("prompt_tok_s")),
                   "speed_src": _text(srv.get("speed_src"), 10)},
        "gpu": {k: _num(gpu.get(k)) for k in ("util", "mem_used_mb", "mem_total_mb", "temp")} if gpu else None,
        "cpu_pct": _num(d.get("cpu_pct")),
        "ram": {k: _num(ram.get(k)) for k in ("used_gb", "total_gb", "pct")} if ram else None,
        "log": {"name": _text(log.get("name"), 120), "line": _text(log.get("line"), 200), "at": _num(log.get("at"))} if log else None,
        "agent": {"task": _text(agent.get("task"), 200), "step": _text(agent.get("step"), 200),
                  "iteration": int(_num(agent.get("iteration")) or 0),
                  "last_check": {"cmd": _text(lc.get("cmd"), 200), "ok": lc.get("ok") is True, "at": _num(lc.get("at"))} if lc else None,
                  "started": _num(agent.get("started")), "eta": _num(agent.get("eta")),
                  "updated": _num(agent.get("updated")),
                  # 0.20: the task id (opens "How it thinks"), planned rounds, last line of the check output
                  "id": _text(agent.get("id"), 20), "rounds": int(_num(agent.get("rounds")) or 0),
                  "check_line": _text(agent.get("check_line"), 200)} if agent else None,
        "report_exists": rep.get("exists") is True,
        "report_at": _num(rep.get("at")),
    }


def clean_mode(m):
    if not isinstance(m, dict) or m.get("mode") not in MODES:
        return None
    model = m.get("model") if m.get("model") in MODELS and m.get("mode") == "ai" else None
    return {"mode": m["mode"], "model": model or None, "since": _num(m.get("since")), "auto": m.get("auto") is True}


class LocalAiHub:
    def __init__(self, claude, clock=time.time):
        self.claude, self.clock = claude, clock
        self.lock = threading.Lock()
        self.snap = None
        self.snap_at = 0.0
        self.mode = None
        self.mode_at = 0.0
        self.watch_at = 0.0
        self.switch = {"state": "none", "target": None, "model": None, "at": None, "detail": ""}
        self.report = {"state": "none", "at": None, "detail": ""}

    # ------------------------------------------------------------ from the PC
    def on_mode(self, m):
        m = clean_mode(m)
        if m:
            with self.lock:
                self.mode, self.mode_at = m, self.clock()

    def on_snapshot(self, d):
        s = clean_snapshot(d)
        if s is None:
            return
        with self.lock:
            self.snap, self.snap_at = s, self.clock()
        self.on_mode((d or {}).get("mode"))

    def on_result(self, d):
        key = str((d or {}).get("key") or "")
        now = self.clock()
        with self.lock:
            if key.startswith("mode-"):
                ok = d.get("ok") is True
                self.switch.update(state="done" if ok else "failed", detail=str(d.get("detail") or "")[:200], done_at=now)
                if ok and self.switch.get("target"):            # the PC's own mode report follows within seconds
                    self.mode = {"mode": self.switch["target"], "model": self.switch.get("model"), "since": now, "auto": False}
                    self.mode_at = now
            elif key.startswith("localai-report-"):
                self.report = {"state": "done" if d.get("ok") is True else "failed", "at": now, "detail": str(d.get("detail") or "")[:200]}

    def watching(self):
        """True while the phone looks at the card or a mode switch is running: mc-pc then reports every ~5 s."""
        with self.lock:
            now = self.clock()
            return now - self.watch_at < WATCH_TTL or self._switching(now)

    def _switching(self, now):
        s = self.switch
        return s["state"] == "requested" and now - float(s["at"] or 0) < SWITCH_TTL

    # ------------------------------------------------------------ from the app
    def request_mode(self, mode, model=""):
        mode, model = str(mode or ""), str(model or "")
        if mode not in MODES:
            raise ValueError("bad mode")
        if model not in MODELS:
            raise ValueError("bad model")
        if mode != "ai":
            model = ""
        with self.lock:
            now = self.clock()
            if self._switching(now):
                raise RuntimeError("a switch is already running")
            cur = self.mode
            if cur and cur["mode"] == mode and (mode != "ai" or not model or cur["model"] == model) and not cur["auto"]:
                return False                                   # already there
            self.claude.enqueue({"key": "mode-%d" % int(now), "kind": "pc-mode", "mode": mode, "model": model, "at": now})
            self.switch = {"state": "requested", "target": mode, "model": model or None, "at": now, "done_at": None, "detail": ""}
            return True

    def request_report(self):
        with self.lock:
            now = self.clock()
            if self.report["state"] == "requested" and now - float(self.report["at"] or 0) < 60:
                return
            self.claude.enqueue({"key": "localai-report-%d" % int(now), "kind": "localai-report", "name": REPORT_NAME, "at": now})
            self.report = {"state": "requested", "at": now, "detail": ""}

    # ------------------------------------------------------------ views
    def mode_view(self):
        """For the PC card in /api/system."""
        with self.lock:
            now = self.clock()
            sw = dict(self.switch)
            if sw["state"] == "requested" and not self._switching(now):
                sw = {"state": "failed", "target": sw["target"], "model": sw["model"], "at": sw["at"], "detail": "PC did not answer in time"}
            m = self.mode or {"mode": None, "model": None, "since": None, "auto": False}
            return {"known": self.mode is not None and now - self.mode_at < 90, **m, "switch": sw}

    def view(self):
        with self.lock:
            self.watch_at = self.clock()
        out = self.mode_view()
        with self.lock:
            now = self.clock()
            s = self.snap
            live = s is not None and now - self.snap_at < SNAP_FRESH
            r = dict(self.report)
            out = {"mode": out, "live": live, "age_s": now - self.snap_at if s else None}
            if s:
                out.update({k: s[k] for k in ("server", "gpu", "cpu_pct", "ram")})
                out["job"] = {"log": s["log"], "agent": s["agent"]}
                out["report"] = {"exists": s["report_exists"], "at": s["report_at"], "slug": REPORT_SLUG,
                                 "state": r["state"], "detail": r["detail"], "requested_at": r["at"]}
            else:
                out["report"] = {"exists": False, "at": None, "slug": REPORT_SLUG, "state": r["state"], "detail": r["detail"], "requested_at": r["at"]}
            return out
