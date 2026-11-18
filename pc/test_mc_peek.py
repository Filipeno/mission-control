import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_peek as mp

AC = "ac-0b1c2d3e-0000-4000-8000-0123456789ab"
HK = "20261118-120000-ab12"


class Peek(unittest.TestCase):
    def test_locked_detected(self):
        run = lambda *a, **k: SimpleNamespace(stdout="LogonUI.exe    1234 Console  1  20,000 K")
        self.assertTrue(mp.is_locked(run))
        run = lambda *a, **k: SimpleNamespace(stdout="INFO: No tasks are running which match the specified criteria.")
        self.assertFalse(mp.is_locked(run))

    def test_lock_check_failure_is_not_locked(self):
        def boom(*a, **k): raise OSError("no tasklist")
        self.assertFalse(mp.is_locked(boom))

    def test_jpeg_capped(self):
        from PIL import Image
        import os
        noisy = Image.frombytes("RGB", (3000, 1600), os.urandom(3000 * 1600 * 3))   # worst case: incompressible
        data = mp.to_jpeg(noisy)
        self.assertTrue(data.startswith(bytes((255, 216))))
        self.assertLessEqual(len(data), mp.MAX_BYTES)
        import io
        self.assertLessEqual(Image.open(io.BytesIO(data)).width, mp.MAX_WIDTH)

    def test_small_flat_image_kept(self):
        from PIL import Image
        import io
        data = mp.to_jpeg(Image.new("RGB", (800, 450), (10, 20, 30)))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (800, 450))

    def test_gates_needing_shot(self):
        gates = [{"id": AC, "kind": "appcard"}, {"id": HK, "kind": "permission"}, {"id": "20261118-120001-ff00", "kind": "question"},
                 {"id": "20261118-120002-ff01", "kind": "plan"}, {"id": "bad id", "kind": "permission"}, {"id": AC, "kind": "appcard"}]
        self.assertEqual(mp.gates_needing_shot(gates, set()), [AC, HK, "20261118-120001-ff00"])
        self.assertEqual(mp.gates_needing_shot(gates, {AC}), [HK, "20261118-120001-ff00"])
        self.assertEqual(mp.gates_needing_shot(None, set()), [])


if __name__ == "__main__":
    unittest.main()
