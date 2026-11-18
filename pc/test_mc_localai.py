import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_localai as m


def fake_get(routes):
    def get(url, timeout=1.5):
        path = "/" + url.split("/", 3)[3]
        r = routes.get(path)
        if r is None:
            raise urllib.error.URLError("refused")
        if isinstance(r, int):
            raise urllib.error.HTTPError(url, r, "x", {}, None)
        return 200, r if isinstance(r, str) else json.dumps(r)
    return get


SLOT = {"id": 0, "n_ctx": 24576, "is_processing": True, "id_task": 7, "next_token": [{"n_decoded": 100, "has_next_token": True}]}


class ModeTests(unittest.TestCase):
    def test_read_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pc-mode.json"
            p.write_text(json.dumps({"mode": "ai", "model": "qwen", "since": "2026-11-18T04:20:52", "auto": False}), encoding="utf-8")
            r = m.read_mode(p)
            self.assertEqual((r["mode"], r["model"], r["auto"]), ("ai", "qwen", False))
            self.assertAlmostEqual(r["since"], m._epoch("2026-11-18T04:20:52"))
            p.write_text(json.dumps({"mode": "gaming", "model": "qwen", "auto": True}), encoding="utf-8")
            r = m.read_mode(p)
            self.assertEqual((r["mode"], r["model"], r["auto"]), ("gaming", None, True))

    def test_bad_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            self.assertIsNone(m.read_mode(p)["mode"])
            p.write_text("{not json", encoding="utf-8")
            self.assertIsNone(m.read_mode(p)["mode"])
            p.write_text('{"mode": "rm -rf"}', encoding="utf-8")
            self.assertIsNone(m.read_mode(p)["mode"])


class StatusTests(unittest.TestCase):
    NOW = 1_800_000_000.0

    def raw(self, **kw):
        d = {"task": "fix tests", "step": 2, "iteration": 3, "started": "2026-11-18T05:00:00",
             "last_check": {"cmd": "pytest -q", "ok": False, "at": 1_799_999_900}}
        d.update(kw)
        return d

    def test_valid(self):
        s = m.parse_status(self.raw(eta=1_800_001_000), self.NOW - 10, self.NOW)
        self.assertEqual((s["task"], s["step"], s["iteration"]), ("fix tests", "2", 3))
        self.assertEqual(s["last_check"], {"cmd": "pytest -q", "ok": False, "at": 1_799_999_900.0})
        self.assertEqual(s["eta"], 1_800_001_000.0)
        self.assertIsNotNone(s["started"])

    def test_none_cases(self):
        self.assertIsNone(m.parse_status(None, 1, self.NOW))
        self.assertIsNone(m.parse_status([], 1, self.NOW))
        self.assertIsNone(m.parse_status({"step": "x"}, 1, self.NOW))
        self.assertIsNone(m.parse_status(self.raw(state="done"), self.NOW, self.NOW))
        self.assertIsNone(m.parse_status(self.raw(), self.NOW - m.AGENT_STALE_S - 1, self.NOW))

    def test_sloppy_fields(self):
        s = m.parse_status({"task": "t", "iteration": "x", "last_check": "oops", "started": "garbage"}, self.NOW, self.NOW)
        self.assertEqual((s["iteration"], s["last_check"], s["started"]), (0, None, None))

    def test_write_then_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "local-agent" / "status.json"
            m.write_status("do it", "step 1", 1, {"cmd": "make", "ok": True, "at": time.time()}, path=p)
            s = m.read_status(p)
            self.assertEqual(s["task"], "do it")
            self.assertTrue(s["last_check"]["ok"])
            self.assertIsNone(m.read_status(Path(d) / "nope.json"))
            m.write_status("do it", state="done", path=p)
            self.assertIsNone(m.read_status(p))


class LogTests(unittest.TestCase):
    def test_newest_log_and_tail(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, c = (Path(d) / n for n in ("a.md", "b.out", "c.log"))
            a.write_text("old\n", encoding="utf-8"); os.utime(a, (1000, 1000))
            b.write_text("", encoding="utf-8"); os.utime(b, (2000, 2000))
            c.write_text("first\nsecond line\n\n  \n", encoding="utf-8"); os.utime(c, (3000, 3000))
            r = m.newest_log(d)
            self.assertEqual((r["name"], r["line"]), ("c.log", "second line"))
            c.unlink()
            r = m.newest_log(d)
            self.assertEqual((r["name"], r["line"]), ("b.out", ""))
            self.assertIsNone(m.newest_log(Path(d) / "missing"))

    def test_tail_big_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "big.log"
            p.write_text("x" * 50000 + "\nlast\n", encoding="utf-8")
            self.assertEqual(m.tail_line(p), "last")

    def test_report_info(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "report.md"
            self.assertFalse(m.report_info(p)["exists"])
            p.write_text("hi", encoding="utf-8")
            self.assertTrue(m.report_info(p)["exists"])


class ServerTests(unittest.TestCase):
    def test_down(self):
        s, mem = m.server_state(None, 100.0, get=fake_get({}))
        self.assertEqual(s["state"], "down")

    def test_loading(self):
        s, _ = m.server_state(None, 100.0, get=fake_get({"/health": 503}))
        self.assertEqual(s["state"], "loading")

    def test_idle(self):
        routes = {"/health": {"status": "ok"}, "/v1/models": {"data": [{"id": "qwen"}]},
                  "/slots": [dict(SLOT, is_processing=False)]}
        s, _ = m.server_state(None, 100.0, get=fake_get(routes))
        self.assertEqual((s["state"], s["model"], s["ctx"], s["slots"], s["busy"]), ("idle", "qwen", 24576, 1, 0))
        self.assertIsNone(s["tok_s"])

    def test_busy_speed_from_slots_delta(self):
        routes = {"/health": {"status": "ok"}, "/slots": [SLOT]}
        s1, mem1 = m.server_state(None, 100.0, get=fake_get(routes))
        self.assertEqual(s1["state"], "busy")
        self.assertIsNone(s1["tok_s"])
        routes["/slots"] = [dict(SLOT, next_token=[{"n_decoded": 150}])]
        s2, mem2 = m.server_state(mem1, 105.0, get=fake_get(routes))
        self.assertEqual((s2["tok_s"], s2["speed_src"]), (10.0, "slots"))
        # generation ended: the last speed stays for a while, then is gone
        routes["/slots"] = [dict(SLOT, is_processing=False)]
        s3, mem3 = m.server_state(mem2, 110.0, get=fake_get(routes))
        self.assertEqual(s3["tok_s"], 10.0)
        s4, _ = m.server_state(mem3, 110.0 + m.SPEED_KEEP_S + 1, get=fake_get(routes))
        self.assertIsNone(s4["tok_s"])

    def test_new_task_resets_delta(self):
        routes = {"/health": {"status": "ok"}, "/slots": [dict(SLOT, id_task=9, next_token=[{"n_decoded": 5}])]}
        prev = {"task": 7, "n": 100, "t": 100.0}
        s, _ = m.server_state(prev, 105.0, get=fake_get(routes))
        self.assertIsNone(s["tok_s"])

    def test_metrics_preferred(self):
        text = "# HELP x\nllamacpp:prompt_tokens_seconds 150.5\nllamacpp:predicted_tokens_seconds 33.25\n"
        routes = {"/health": {}, "/slots": [SLOT], "/metrics": text}
        s, _ = m.server_state(None, 100.0, get=fake_get(routes))
        self.assertEqual((s["tok_s"], s["prompt_tok_s"], s["speed_src"]), (33.25, 150.5, "metrics"))

    def test_garbage_slots(self):
        routes = {"/health": {}, "/slots": "<html>", "/v1/models": "nope"}
        s, _ = m.server_state(None, 100.0, get=fake_get(routes))
        self.assertEqual((s["state"], s["slots"]), ("idle", 0))


class HardwareTests(unittest.TestCase):
    def test_parse_gpu(self):
        g = m.parse_gpu("99, 5777, 6144, 60\n")
        self.assertEqual(g, {"util": 99.0, "mem_used_mb": 5777.0, "mem_total_mb": 6144.0, "temp": 60.0})
        self.assertIsNone(m.parse_gpu(""))
        self.assertIsNone(m.parse_gpu("garbage"))
        self.assertEqual(m.parse_gpu("5, [N/A], 6144, 40")["mem_used_mb"], None)

    def test_snapshot_shape(self):
        with tempfile.TemporaryDirectory() as d:
            hub, llm = Path(d) / "hub", Path(d) / "llm"
            (llm / "trials" / "logs").mkdir(parents=True)
            (llm / "trials" / "logs" / "a.log").write_text("hello\n", encoding="utf-8")
            snap, _ = m.snapshot(now=time.time(), hub=hub, llm=llm, get=fake_get({}))
            json.dumps(snap)
            self.assertEqual(snap["server"]["state"], "down")
            self.assertEqual(snap["job"]["log"]["line"], "hello")
            self.assertIsNone(snap["job"]["agent"])
            self.assertFalse(snap["report"]["exists"])


if __name__ == "__main__":
    unittest.main()
