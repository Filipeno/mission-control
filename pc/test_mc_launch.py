import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_launch as ml

PDF = b"%PDF-1.4 test"
JPG = b"\xff\xd8\xff\xe0 test"


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "Škola")
        for d in ("MAT", "ROB", ".git", "_old"):
            os.makedirs(os.path.join(self.root, d))
        open(os.path.join(self.root, "loose.docx"), "wb").close()
        self.src = os.path.join(self.tmp.name, "src")
        os.makedirs(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def f(self, name, data):
        p = os.path.join(self.src, name)
        open(p, "wb").write(data)
        return {"path": p, "name": name}

    def test_list(self):
        r = ml.list_folders(self.tmp.name, self.root)
        self.assertEqual(r["skola"], ["MAT", "ROB"])
        self.assertIn("src", r["projects"])

    def test_subject_rejects_tricks(self):
        for bad in ("..", ".", "", "MAT/..", "..\\x", "MAT\\", "mat2", "loose.docx", "C:", " MAT", "MAT\0"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ml.subject_dir(self.root, bad)
        self.assertTrue(ml.subject_dir(self.root, "MAT").endswith("MAT"))

    def test_junction_out_of_root(self):
        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(outside)
        link = os.path.join(self.root, "LINK")
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("no symlink right")
        with self.assertRaises(ValueError):
            ml.subject_dir(self.root, "LINK")

    def test_save(self):
        r = ml.save_podklady(self.root, "MAT", "ab12cd34", [self.f("zadani.pdf", PDF), self.f("foto 1.jpg", JPG)], now=0)
        self.assertTrue(r["ok"])
        self.assertTrue(r["podklady"].startswith(os.path.join(self.root, "MAT")))
        self.assertEqual(sorted(r["saved"]), ["foto 1.jpg", "zadani.pdf"])
        self.assertTrue(os.path.isfile(os.path.join(r["podklady"], "zadani.pdf")))

    def test_repeat_same_key(self):
        a = ml.save_podklady(self.root, "MAT", "ab12cd34", [self.f("a.pdf", PDF)])
        b = ml.save_podklady(self.root, "MAT", "ab12cd34", [self.f("a.pdf", PDF)])
        self.assertEqual(a["folder"], b["folder"])
        self.assertTrue(b["repeat"])
        self.assertEqual(len([d for d in os.listdir(os.path.join(self.root, "MAT"))]), 1)

    def test_bad_files(self):
        with self.assertRaises(ValueError):
            ml.save_podklady(self.root, "MAT", "ab12cd34", [self.f("x.exe", b"MZ")])
        with self.assertRaises(ValueError):
            ml.save_podklady(self.root, "MAT", "ab12cd34", [self.f("fake.pdf", b"not a pdf")])
        with self.assertRaises(ValueError):
            ml.save_podklady(self.root, "MAT", "ab12cd34", [])
        self.assertEqual(os.listdir(os.path.join(self.root, "MAT")), [])   # nothing left behind

    def test_names(self):
        used = set()
        self.assertEqual(ml.safe_name("..\\..\\evil.pdf", used), "evil.pdf")
        self.assertEqual(ml.safe_name("evil.pdf", used), "evil-2.pdf")
        self.assertEqual(ml.safe_name("con.pdf", used), "_con.pdf")
        self.assertEqual(ml.safe_name("a:b*c.png", used), "b_c.png")
        with self.assertRaises(ValueError):
            ml.safe_name("noext", used)

    def test_traversal_name_stays_inside(self):
        r = ml.save_podklady(self.root, "ROB", "ffff0000", [self.f("x.pdf", PDF)])
        r2 = ml.save_podklady(self.root, "ROB", "eeee0000", [{"path": os.path.join(self.src, "x.pdf"), "name": "../../../x.pdf"}])
        for p in (r, r2):
            self.assertEqual(os.path.dirname(os.path.dirname(p["podklady"])), os.path.join(self.root, "ROB"))

    def test_too_many(self):
        fs = [self.f(f"{i}.pdf", PDF) for i in range(7)]
        with self.assertRaises(ValueError):
            ml.save_podklady(self.root, "MAT", "ab12cd34", fs)


if __name__ == "__main__":
    unittest.main()
