import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import localai_hub as lh


class Claude:
    def __init__(self): self.items = []
    def enqueue(self, x): self.items.append(x)


class Clock:
    t = 1000.0
    def __call__(self): return self.t


SNAP = {"server": {"state": "busy", "model": "qwen", "ctx": 24576, "slots": 1, "busy": 1, "tok_s": 31.5, "speed_src": "slots"},
        "gpu": {"util": 90, "mem_used_mb": 5000, "mem_total_mb": 6144, "temp": 61}, "cpu_pct": 12.5,
        "ram": {"used_gb": 20.1, "total_gb": 31.1, "pct": 64}, "mode": {"mode": "ai", "model": "qwen", "since": 900, "auto": False},
        "job": {"log": {"name": "a.log", "line": "hello", "at": 990}, "agent": {"task": "t", "step": "s", "iteration": 2,
                "last_check": {"cmd": "pytest", "ok": True, "at": 995}, "started": 800, "eta": None, "updated": 999}},
        "report": {"exists": True, "at": 500, "size": 10}}


class HubTests(unittest.TestCase):
    def setUp(self):
        self.c, self.clock = Claude(), Clock()
        self.clock.t = 1000.0
        self.h = lh.LocalAiHub(self.c, self.clock)

    def test_empty_view(self):
        v = self.h.view()
        self.assertFalse(v["live"])
        self.assertIsNone(v["mode"]["mode"])
        self.assertFalse(v["mode"]["known"])
        self.assertFalse(v["report"]["exists"])

    def test_snapshot_view(self):
        self.h.on_snapshot(SNAP)
        v = self.h.view()
        self.assertTrue(v["live"])
        self.assertEqual(v["mode"]["mode"], "ai")
        self.assertEqual(v["server"]["tok_s"], 31.5)
        self.assertEqual(v["job"]["agent"]["last_check"]["cmd"], "pytest")
        self.assertTrue(v["report"]["exists"])
        self.clock.t += 40
        self.assertFalse(self.h.view()["live"])

    def test_garbage_snapshot(self):
        self.h.on_snapshot("x")
        self.h.on_snapshot({"server": "x", "gpu": 3, "job": 5})
        v = self.h.view()
        self.assertEqual(v["server"]["state"], "down")
        self.assertIsNone(v["gpu"])
        self.assertIsNone(v["job"]["agent"])

    def test_watching(self):
        self.assertFalse(self.h.watching())
        self.h.view()
        self.assertTrue(self.h.watching())
        self.clock.t += lh.WATCH_TTL + 1
        self.assertFalse(self.h.watching())

    def test_request_mode_validates(self):
        for bad in (("x", ""), ("ai", "llama"), ("", ""), (None, None)):
            with self.assertRaises(ValueError):
                self.h.request_mode(*bad)
        self.assertEqual(self.c.items, [])

    def test_request_mode_flow(self):
        self.h.on_snapshot(SNAP)
        self.assertFalse(self.h.request_mode("ai", "qwen"))      # already there
        self.assertTrue(self.h.request_mode("gaming", "gptoss"))
        item = self.c.items[0]
        self.assertEqual((item["kind"], item["mode"], item["model"]), ("pc-mode", "gaming", ""))   # no model outside AI
        self.assertTrue(self.h.watching())
        with self.assertRaises(RuntimeError):
            self.h.request_mode("normal")
        self.assertEqual(self.h.mode_view()["switch"]["state"], "requested")
        self.clock.t += 50
        self.h.on_result({"key": item["key"], "ok": True, "detail": "mode=gaming"})
        v = self.h.mode_view()
        self.assertEqual((v["mode"], v["switch"]["state"]), ("gaming", "done"))
        self.assertTrue(self.h.request_mode("normal"))             # allowed again

    def test_switch_failed_and_timeout(self):
        self.assertTrue(self.h.request_mode("ai", "gptoss"))
        self.h.on_result({"key": self.c.items[0]["key"], "ok": False, "detail": "WARNING: server state does not match"})
        v = self.h.mode_view()
        self.assertEqual(v["switch"]["state"], "failed")
        self.assertIsNone(v["mode"])                                # unchanged
        self.clock.t += 1
        self.assertTrue(self.h.request_mode("ai", "qwen"))
        self.clock.t += lh.SWITCH_TTL + 1
        self.assertEqual(self.h.mode_view()["switch"]["state"], "failed")
        self.assertFalse(self.h.watching())
        self.assertTrue(self.h.request_mode("normal"))

    def test_auto_gaming_can_be_left(self):
        self.h.on_mode({"mode": "gaming", "auto": True, "since": 1})
        self.assertTrue(self.h.request_mode("gaming"))              # pin it: no longer auto
        self.assertEqual(self.h.mode_view()["auto"], True)

    def test_report_request(self):
        self.h.request_report()
        self.h.request_report()
        self.assertEqual(len(self.c.items), 1)
        key = self.c.items[0]["key"]
        self.h.on_result({"key": key, "ok": True, "detail": "uploaded"})
        v = self.h.view()
        self.assertEqual((v["report"]["state"], v["report"]["slug"]), ("done", "local-agent-trials-report"))

    def test_other_results_ignored(self):
        self.h.on_result({"key": "restart-1", "ok": True})
        self.h.on_result(None)
        self.assertEqual(self.h.mode_view()["switch"]["state"], "none")


if __name__ == "__main__":
    unittest.main()
