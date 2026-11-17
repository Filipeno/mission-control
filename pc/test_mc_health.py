import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_health as h


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "state" / "rc-queue.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_append_and_dedupe(self):
        item = {"id": "a", "local": "local_a", "title": "One"}
        h.append(self.path, item, "now")
        h.append(self.path, item, "later")
        self.assertEqual(h.read_queue(self.path), [{"session_id": "local_a", "id": "a", "title": "One", "queued_at": "now"}])

    def test_atomic_write_is_json(self):
        h.append(self.path, {"id": "a", "title": "One"})
        self.assertEqual(json.loads(self.path.read_text())[0]["session_id"], "a")
        self.assertFalse(list(self.path.parent.glob(".rc-queue-*")))

    def test_bad_item(self):
        with self.assertRaises(ValueError):
            h.append(self.path, {})

    def test_prune(self):
        h.append(self.path, {"id": "a"})
        h.append(self.path, {"id": "b"})
        self.assertEqual(h.prune(self.path, [{"id": "a", "rc": False}, {"id": "b", "rc": True}]),
                         [{"session_id": "a", "id": "a", "title": "", "queued_at": h.read_queue(self.path)[0]["queued_at"]}])


if __name__ == "__main__":
    unittest.main()
