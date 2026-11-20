import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_laptop as m


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.mode = self.d / "mode.json"
        self.apps = self.d / "laptop-apps.json"
        self.apps.write_text(json.dumps({"apps": [{"name": "ROBOGUIDE"}, {"name": "Laptop workspace"}, {"name": "Notepad (test)"},
                                                   {"name": 'Evil" & calc'}, {"name": "ROBOGUIDE"}, {"x": 1}, "str"]}))

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, status="", **k):
        return m.build_report(status, str(self.mode), str(self.apps))

    def test_missing_or_bad_mode_file_is_unknown(self):
        r = self.report()
        self.assertEqual((r["mode"], r["mode_since"], r["manual"], r["monitor_stream"]), ("unknown", None, False, False))
        for bad in ("{", "[1]", "null", '{"mode": "sideways"}', '{"mode": 5}', ""):
            self.mode.write_text(bad)
            self.assertEqual(self.report()["mode"], "unknown", bad)

    def test_good_mode_file(self):
        self.mode.write_text(json.dumps({"mode": "Monitor", "since": 1763499000, "app": None, "reason": "x", "manual": True}))
        r = self.report()
        self.assertEqual((r["mode"], r["mode_since"], r["manual"]), ("monitor", 1763499000, True))

    def test_bad_since_and_manual_types(self):
        self.mode.write_text(json.dumps({"mode": "own", "since": "2026-11-20", "manual": "yes"}))
        r = self.report()
        self.assertEqual((r["mode"], r["mode_since"], r["manual"]), ("own", None, False))
        self.mode.write_text(json.dumps({"mode": "app", "since": "1763499000"}))
        self.assertEqual(self.report()["mode_since"], 1763499000)

    def test_status_gives_monitor_stream_and_is_the_fallback(self):
        status = 'warning noise\n{"mode":"app","since":1763499500,"manual":false,"monitor_stream":true,"mwb":false}\n'
        r = self.report(status)                       # no mode.json: the status run supplies the mode
        self.assertEqual((r["mode"], r["mode_since"], r["monitor_stream"]), ("app", 1763499500, True))
        self.mode.write_text(json.dumps({"mode": "own", "since": 1763500000}))
        r = self.report(status)                       # mode.json is fresher and wins
        self.assertEqual((r["mode"], r["monitor_stream"]), ("own", True))
        self.assertFalse(self.report("not json {")["monitor_stream"])
        self.assertFalse(self.report('{"monitor_stream": "true"}')["monitor_stream"])

    def test_apps_are_names_only_deduped_and_safe(self):
        self.assertEqual(m.load_apps(str(self.apps)), ["ROBOGUIDE", "Laptop workspace", "Notepad (test)"])
        self.assertEqual(m.load_apps(str(self.d / "nope.json")), [])
        self.apps.write_text("garbage")
        self.assertEqual(self.report()["apps"], [])

    def test_app_allow_list_exact_match_only(self):
        a = str(self.apps)
        self.assertTrue(m.app_ok("ROBOGUIDE", a))
        self.assertTrue(m.app_ok("Notepad (test)", a))
        for bad in ("robo guide", "robogui", "ROBOGUIDE ", "ROBOGUIDE; calc", 'Evil" & calc', "", None, 5, "../x"):
            self.assertFalse(m.app_ok(bad, a), bad)

    def test_open_result_shows_detail_as_is(self):
        r = m.build_result("open", 1, '{"ok":false,"detail":"PC is locked"}')
        self.assertEqual(r, {"ok": False, "detail": "PC is locked"})
        r = m.build_result("open", 0, 'x\n{"ok":true,"detail":"window up: ROBOGUIDE"}')
        self.assertEqual(r, {"ok": True, "detail": "window up: ROBOGUIDE"})
        self.assertFalse(m.build_result("open", 3, '{"ok":true,"detail":"d"}')["ok"])       # exit code wins
        self.assertFalse(m.build_result("open", 0, '{"ok":false,"detail":"d"}')["ok"])
        self.assertEqual(m.build_result("open", 0, "no json"), {"ok": True, "detail": "opened"})
        self.assertEqual(m.build_result("open", 2, ""), {"ok": False, "detail": "failed (exit 2)"})
        self.assertEqual(len(m.build_result("open", 1, json.dumps({"ok": False, "detail": "x" * 500}))["detail"]), 120)

    def test_mode_result(self):
        self.assertEqual(m.build_result("mode", 0, '{"mode":"monitor","since":1}', "monitor"), {"ok": True, "detail": "mode=monitor"})
        self.assertEqual(m.build_result("mode", 0, "", "own"), {"ok": True, "detail": "mode=own"})
        self.assertEqual(m.build_result("mode", 0, '{"mode":"<script>"}', "own")["detail"], "mode=own")
        self.assertEqual(m.build_result("mode", 1, "boom", "own"), {"ok": False, "detail": "mode switch failed (exit 1)"})
        self.assertEqual(m.build_result("auto", 0, "", "auto"), {"ok": True, "detail": "auto on"})

    def test_clip_result_never_contains_text(self):
        secret = "hunter2-password-from-the-clipboard"
        for code, out in ((0, "Sent 42 characters to the laptop. " + secret), (0, secret), (1, secret), (0, "")):
            r = m.build_result("clip", code, out)
            self.assertNotIn("hunter2", json.dumps(r))
        self.assertEqual(m.build_result("clip", 0, "Sent 42 characters"), {"ok": True, "detail": "sent 42 chars"})
        self.assertEqual(m.build_result("clip", 0, secret), {"ok": True, "detail": "sent"})
        self.assertFalse(m.build_result("clip", 1, secret)["ok"])

    def test_bad_inputs_do_not_raise(self):
        self.assertFalse(m.build_result("format", 0, "")["ok"])
        self.assertFalse(m.build_result("open", "x", None)["ok"])

    def test_cli_with_env_vars(self):
        env = dict(os.environ, MC_LAPTOP_DIR=str(self.d), MC_LAPTOP_STATE=str(self.d), MC_ACTION="clip", MC_CODE="0",
                   MC_OUT="sent 7 chars", MC_APP="ROBOGUIDE")
        (self.d / "config").mkdir()
        (self.d / "config" / "laptop-apps.json").write_text(self.apps.read_text())
        run = lambda verb: json.loads(subprocess.run([sys.executable, "-I", str(Path(m.__file__)), verb], env=env,
                                                     capture_output=True, text=True).stdout)
        self.assertEqual(run("result"), {"ok": True, "detail": "sent 7 chars"})
        self.assertEqual(run("app-ok"), {"ok": True})
        self.assertEqual(run("report")["mode"], "unknown")
        env["MC_APP"] = "calc"
        self.assertEqual(run("app-ok"), {"ok": False})


if __name__ == "__main__":
    unittest.main()
