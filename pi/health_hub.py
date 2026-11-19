"""Health data reported by the PC helper for the System and Claude views."""
import time
from datetime import datetime, timezone


REPORT_FRESH = 90
QUEUE_TTL = 24 * 3600


def _epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class HealthHub:
    def __init__(self, state_dir, load_json, save_json, deliver, claude, sessions):
        self.load, self.save, self.deliver = load_json, save_json, deliver
        self.claude, self.sessions = claude, sessions
        self.health = load_json("health-report.json", {}) or {}
        self.report_at = float(self.health.pop("_report_at", 0) or 0)
        self.queued = load_json("rc-queued.json", {}) or {}
        self.restart = load_json("health-restart.json", {"state": "none", "detail": "", "at": None}) or {}
        self.notified = load_json("health-notified.json", {}) or {}

    def _save_health(self):
        data = dict(self.health)
        data["_report_at"] = self.report_at
        self.save("health-report.json", data)

    def _save_queue(self):
        self.save("rc-queued.json", self.queued)

    def _sessions(self):
        rows, _fresh = self.sessions.sessions_snapshot()
        return rows

    def _prune_queue(self, rows=None):
        now = time.time()
        rows = self._sessions() if rows is None else rows
        by_id = {str(s.get("id")): s for s in rows if s.get("kind") == "desktop"}
        kept = {sid: at for sid, at in self.queued.items()
                if sid in by_id and not by_id[sid].get("rc") and now - float(at or 0) <= QUEUE_TTL}
        if kept != self.queued:
            self.queued = kept
            self._save_queue()

    def on_pc_report(self, health):
        if not isinstance(health, dict):
            return
        if not isinstance(health.get("helpers"), dict):          # helpers arrive every 10 min only: keep the last ones
            health = dict(health, helpers=self.health.get("helpers"))
        self.health = health
        self.report_at = time.time()
        self._save_health()
        self._notify()

    def _notify(self):
        now = time.time()
        claude = self.health.get("claude") or {}
        running = claude.get("running") is True
        down = _epoch(claude.get("down_since"))
        if running:
            if self.notified.pop("claude_down", None) is not None:
                self.save("health-notified.json", self.notified)
        elif down and now - down >= 300 and not self.notified.get("claude_down"):
            self.deliver({"at": now, "kind": "claude-app-down", "cat": "system", "title": "Claude app is down",
                          "body": "Not running for %d min" % int((now - down) // 60), "group": "claude-app-down",
                          "quiet": False, "actions": []})
            self.notified["claude_down"] = True
            self.save("health-notified.json", self.notified)
        selftest = self.health.get("selftest") or {}
        at, failed = selftest.get("at"), selftest.get("failed") or []
        if at and at != self.notified.get("selftest_at"):
            self.notified["selftest_at"] = at
            self.save("health-notified.json", self.notified)
            if failed:
                self.deliver({"at": now, "kind": "selftest-failed", "cat": "system", "title": "Hub self-test failed",
                              "body": ", ".join(str(x) for x in failed)[:400], "group": "selftest-failed",
                              "quiet": False, "actions": []})

    def on_result(self, d):
        key = str((d or {}).get("key") or "")
        if key.startswith("bitwarden-"):
            self._bitwarden_result(d)
            return
        if not key.startswith("restart-"):
            return
        self.restart = {"state": "done" if d.get("ok") is True else "failed",
                        "detail": str(d.get("detail") or "")[:200], "at": time.time()}
        self.save("health-restart.json", self.restart)

    def request_restart(self):
        now = time.time()
        if self.restart.get("state") == "requested" and now - float(self.restart.get("at") or 0) < 60:
            return
        self.claude.enqueue({"key": "restart-%d" % int(now), "kind": "claude-restart", "at": now})
        self.restart = {"state": "requested", "detail": "", "at": now}
        self.save("health-restart.json", self.restart)

    def request_bitwarden(self):
        # Opens Bitwarden desktop on the PC. No secret is involved: the PC helper only starts / focuses the app.
        now = time.time()
        self.claude.enqueue({"key": "bitwarden-%d" % int(now), "kind": "bitwarden-open", "at": now})

    def _bitwarden_result(self, d):
        ok = d.get("ok") is True
        detail = str(d.get("detail") or "")[:200]
        if ok and not detail.startswith("PC is locked"):
            title = "Bitwarden is open on the PC"
            body = ("Choose 'Log in with device' there, then approve in the Bitwarden app on this phone. "
                    "Check the fingerprint phrase matches.")
        elif ok:
            title, body = "Bitwarden started, but the PC is locked", "Unlock the PC, then choose 'Log in with device'."
        else:
            title, body = "Could not open Bitwarden on the PC", detail or "unknown error"
        self.deliver({"at": time.time(), "kind": "bitwarden-open", "cat": "system", "title": title, "body": body,
                      "group": "bitwarden-open", "quiet": False, "actions": []})

    def request_rc(self, sid):
        sid = str(sid or "")
        rows = self._sessions()
        row = next((s for s in rows if str(s.get("id")) == sid and s.get("kind") == "desktop" and not s.get("rc")), None)
        if not row:
            raise LookupError("desktop session not found")
        self._prune_queue(rows)
        if sid not in self.queued:
            now = time.time()
            self.claude.enqueue({"key": "rc-" + sid, "kind": "rc-queue", "id": sid,
                                 "local": row.get("local", ""), "title": row.get("title", ""), "at": now})
            self.queued[sid] = now
            self._save_queue()

    def helpers(self):
        value = self.health.get("helpers")
        return value if isinstance(value, dict) else None

    def view(self):
        now = time.time()
        rows = self._sessions()
        self._prune_queue(rows)
        known = now - self.report_at < REPORT_FRESH
        c = self.health.get("claude") or {}
        down = _epoch(c.get("down_since"))
        running = c.get("running") is True
        st = self.health.get("selftest") or {}
        at = _epoch(st.get("at"))
        failed = [str(x) for x in (st.get("failed") or [])]
        results = st.get("results") if isinstance(st.get("results"), dict) else {}
        rc_off = [s for s in rows if s.get("kind") == "desktop" and not s.get("rc")]
        app = {"known": known, "running": running, "down_min": (now - down) / 60 if down and not running else None,
               "watchdog_at": c.get("watchdog_at") if isinstance(c.get("watchdog_at"), (int, float)) else None,
               "rc_on": sum(1 for s in rows if s.get("kind") == "desktop" and s.get("rc")), "rc_off": len(rc_off),
               "rc_off_list": [{"id": s.get("id"), "local": s.get("local"), "title": s.get("title"),
                                "queued": str(s.get("id")) in self.queued} for s in rc_off],
               "restart": dict(self.restart)}
        selftest = {"known": known and at is not None, "at": at, "age_h": (now - at) / 3600 if at else None,
                    "ok": not failed, "stale": bool(at and now - at > 36 * 3600), "failed": failed,
                    "rows": [{"name": str(n), "ok": bool(v.get("ok")), "seconds": v.get("seconds"),
                              "detail": str(v.get("detail") or "")} for n, v in results.items() if isinstance(v, dict)]}
        problems = []
        if known and not running:
            problems.append("Claude app")
        if selftest["known"] and failed:
            problems.append("Hub self-test")
        return {"claude_app": app, "selftest": selftest, "problems_add": problems}
