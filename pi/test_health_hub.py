import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from health_hub import HealthHub


class Claude:
    def __init__(self): self.items = []
    def enqueue(self, x): self.items.append(x)


class Sessions:
    def __init__(self): self.rows = []
    def sessions_snapshot(self): return self.rows, True


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.saved = {}; self.events = []; self.c = Claude(); self.s = Sessions()
        self.h = HealthHub(self.dir.name, lambda n, d: self.saved.get(n, d), lambda n, x: self.saved.__setitem__(n, x), self.events.append, self.c, self.s)

    def report(self, running=True, failed=None, at="2026-01-01T00:00:00+00:00"):
        self.h.on_pc_report({"claude": {"running": running, "down_since": "2020-01-01T00:00:00+00:00", "watchdog_at": 1}, "selftest": {"at": at, "failed": failed or [], "results": {"x": {"ok": True, "seconds": 1, "detail": "ok"}}}})

    def test_view_counts_and_queue(self):
        self.s.rows = [{"id": "a", "local": "local_a", "title": "A", "kind": "desktop", "rc": False}, {"id": "b", "local": "local_b", "title": "B", "kind": "desktop", "rc": True}]
        self.report(); self.h.request_rc("a"); v = self.h.view()
        self.assertEqual((v["claude_app"]["rc_on"], v["claude_app"]["rc_off"]), (1, 1)); self.assertTrue(v["claude_app"]["rc_off_list"][0]["queued"])

    def test_down_notification_rearms(self):
        self.report(False); self.report(False); self.assertEqual(len(self.events), 1)
        self.report(True); self.report(False); self.assertEqual(len(self.events), 2)

    def test_selftest_once_per_run_and_stale(self):
        self.report(failed=["codex"]); self.report(failed=["codex"]); self.report(failed=["codex"], at="2026-01-02T00:00:00+00:00")
        self.assertEqual(sum(x["kind"] == "selftest-failed" for x in self.events), 2)
        self.assertTrue(self.h.view()["selftest"]["stale"])

    def test_restart_rate_limit(self):
        self.h.request_restart(); self.h.request_restart(); self.assertEqual(len(self.c.items), 1)


if __name__ == "__main__":
    unittest.main()
