import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import launch_hub as lh


class Claude:
    def __init__(self): self.items, self.verified, self.bad, self.tiers = [], [], False, []
    def enqueue(self, x): self.items.append(x)
    def verify(self, th, msg, sig, ts, tier="H"):
        if self.bad or sig != "good":
            raise PermissionError("bad signature")
        self.verified.append(msg)
        self.tiers.append(tier)


class Sessions:
    def __init__(self): self.boss, self.typed = {"id": "x"}, []
    def boss_session(self): return self.boss
    def type_to_boss(self, text, kind="start", token_hash="", msg="", d=None, tier="H"):
        if msg:
            Claude_.verify(token_hash, msg + f"|{int((d or {}).get('ts') or 0)}", str((d or {}).get("sig", "")), 0, tier=tier)
        if not self.boss:
            raise LookupError("No main Claude Desktop session is open")
        self.typed.append((text, kind, msg))
        return {"ok": True, "boss": "Boss"}


Claude_ = Claude()


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        global Claude_
        self.c = Claude_ = Claude()
        self.s = Sessions()
        self.events = []
        self.h = lh.LaunchHub(self.c, self.s, Path(self.tmp.name), self.events.append)
        self.h.on_folders({"projects": ["mission-control", "bad/name", ".."], "skola": ["MAT", "ROB"]})

    def tearDown(self):
        self.tmp.cleanup()

    def sess(self, **k):
        d = {"area": "projects", "name": "mission-control", "model": "sonnet", "effort": "low", "permission": "default",
             "prompt": "fix the thing", "ts": 1, "sig": "good"}
        d.update(k)
        return d

    def test_folders_cleaned(self):
        v = self.h.folders_view()
        self.assertEqual(v["projects"], ["mission-control"])
        self.assertEqual(v["skola"], ["MAT", "ROB"])
        self.assertTrue(v["fresh"])

    def test_new_session_brief(self):
        r = self.h.new_session("th", self.sess())
        self.assertEqual(r["folder"], "D:\\projekty\\mission-control")
        text, kind, msg = self.s.typed[0]
        self.assertIn('cwd "D:\\projekty\\mission-control"', text)
        self.assertIn("<<<PROMPT\nfix the thing\nPROMPT>>>", text)
        self.assertEqual(msg, "newsess|projects|mission-control|sonnet|low|default|fix the thing")
        self.assertEqual(self.c.tiers, ["M"])                         # default permission mode: the 5-minute window

    def test_new_session_mode_tier(self):
        for perm in ("acceptEdits", "auto", "bypassPermissions"):
            self.h.new_session("th", self.sess(permission=perm))
        self.assertEqual(self.c.tiers, ["H", "H", "H"])               # any other mode: a fresh fingerprint

    def test_skola_session_czech_note(self):
        self.h.new_session("th", self.sess(area="skola", name="MAT"))
        self.assertIn("Czech", self.s.typed[0][0])

    def test_new_session_rejects(self):
        for bad in (dict(name="nope"), dict(area="x"), dict(model="gpt"), dict(effort="max"), dict(permission="root"),
                    dict(prompt=" "), dict(prompt="x" * 2501), dict(name="../x")):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.h.new_session("th", self.sess(**bad))
        with self.assertRaises(PermissionError):
            self.h.new_session("th", self.sess(sig="bad"))
        self.assertEqual(self.s.typed, [])

    def test_max_prompt_fits_cap(self):
        self.h.new_session("th", self.sess(prompt="x" * 2500, name="mission-control"))
        self.assertLessEqual(len(self.s.typed[0][0]), lh.SKOLA_TEXT_CAP)

    def test_no_boss(self):
        self.s.boss = None
        with self.assertRaises(LookupError):
            self.h.new_session("th", self.sess())

    def test_upload_rules(self):
        r = self.h.upload("a.jpg", iter([b"\xff\xd8\xff", b"abc"]))
        self.assertEqual(r["size"], 6)
        self.assertTrue(self.h.file_path(r["id"]).is_file())
        with self.assertRaises(ValueError):
            self.h.upload("a.exe", iter([b"x"]))
        with self.assertRaises(ValueError):
            self.h.upload("a.pdf", iter([]))
        with self.assertRaises(ValueError):
            self.h.upload("a.pdf", iter([b"x"]), declared=lh.MAX_UPLOAD + 1)
        big = (b"x" * (1024 * 1024) for _ in range(26))
        with self.assertRaises(ValueError):
            self.h.upload("a.pdf", big)
        self.assertEqual(len(list((Path(self.tmp.name) / "launch").glob("*.bin"))), 1)   # failed ones leave nothing
        self.assertEqual(self.h.upload("../../x.pdf", iter([b"%PDF"]))["name"], "x.pdf")

    def up(self, n=1):
        return [self.h.upload(f"p{i}.jpg", iter([b"\xff\xd8\xff"]))["id"] for i in range(n)]

    def skola(self, ids, **k):
        d = {"subject": "MAT", "files": ids, "note": "do p. 5", "ts": 1, "sig": "good"}
        d.update(k)
        return self.h.skola_start("th", d)

    def test_skola_flow(self):
        ids = self.up(2)
        r = self.skola(ids)
        it = self.c.items[0]
        self.assertEqual((it["kind"], it["subject"], len(it["files"])), ("skola-new", "MAT", 2))
        self.assertEqual(self.c.verified[0], f"skola|MAT|{','.join(ids)}|do p. 5|1")
        self.assertEqual(self.s.typed, [])                          # nothing typed before the PC saved the files
        self.h.on_saved({"key": r["key"], "ok": True, "folder": "D:\\\u0160kola\\MAT\\Nov\u00e1 \u00faloha 1", "task": "Nov\u00e1 \u00faloha 1",
                         "saved": ["p0.jpg", "p1.jpg"]})
        text = self.s.typed[0][0]
        self.assertIn("podklady", text)
        self.assertIn("domácí úkol", text)
        self.assertIn("do p. 5", text)
        self.assertIsNone(self.h.file_path(ids[0]))                 # uploads removed after the PC saved them
        self.assertEqual(self.events[-1]["kind"], "skola-start")

    def test_skola_rejects(self):
        ids = self.up(1)
        for bad in (dict(subject="XXX"), dict(subject="../MAT"), dict(files=[]), dict(files=["../etc"]), dict(files=ids + ids),
                    dict(note="x" * 401), dict(files=["a" * 20]), dict(sig="bad")):
            with self.assertRaises((ValueError, PermissionError), msg=str(bad)):
                self.skola(bad.pop("files", ids), **bad)
        self.assertEqual(self.c.items, [])

    def test_skola_no_boss_fails_before_queue(self):
        ids = self.up(1)
        self.s.boss = None
        with self.assertRaises(LookupError):
            self.skola(ids)
        self.assertEqual(self.c.items, [])

    def test_saved_failure_and_odd_folder(self):
        r = self.skola(self.up(1))
        self.h.on_saved({"key": r["key"], "ok": False, "detail": "unknown subject"})
        self.assertEqual(self.h.jobs[r["key"]]["state"], "failed")
        r2 = self.skola(self.up(1))
        self.h.on_saved({"key": r2["key"], "ok": True, "folder": "D:\\other\\x", "task": "t"})
        self.assertEqual(self.h.jobs[r2["key"]]["state"], "failed")
        self.h.on_saved({"key": "unknown", "ok": True})
        self.assertEqual(self.s.typed, [])

    def test_boss_gone_after_save_names_folder(self):
        r = self.skola(self.up(1))
        self.s.boss = None
        self.h.on_saved({"key": r["key"], "ok": True, "folder": "D:\\\u0160kola\\MAT\\T", "task": "T", "saved": []})
        self.assertIn("D:\\\u0160kola\\MAT\\T", self.events[-1]["body"])


if __name__ == "__main__":
    unittest.main()
