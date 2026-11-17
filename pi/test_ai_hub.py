import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_hub import AiHub

QID = "20261117-234110-codex"


class Claude:
    def __init__(self): self.items = []; self.approvals = []
    def enqueue(self, x): self.items.append(x)
    def view(self): return {"approvals": self.approvals}


class Todos:
    def view(self): return {"open": [{"title": "Plug in the USB hub"}]}


class Docs:
    def __init__(self): self.up = []
    def upload(self, kind, name, text, **kw): self.up.append((kind, name, text, kw)); return {"slug": name[:-3]}


def stamp(h, m, day=18): return datetime(2026, 11, day, h, m).timestamp()


class AiHubTests(unittest.TestCase):
    def setUp(self):
        self.store, self.events, self.now = {}, [], [stamp(12, 0)]
        self.st = {"muted": False, "kinds": {"claude": True}, "digest_on": True, "digest_time": "20:00"}
        self.claude, self.docs = Claude(), Docs()
        self.h = self.make()

    def make(self):
        return AiHub(lambda n, d: self.store.get(n, d), lambda n, v: self.store.__setitem__(n, v), self.events.append,
                     self.claude, Todos(), self.docs, lambda: self.st, lambda: False, clock=lambda: self.now[0])

    def q(self, qid=QID): return {"id": qid, "helper": "codex", "question": "May I run the build?", "task": "t", "at": 1.0}

    # questions
    def test_new_question_notifies_once_even_after_restart(self):
        self.h.on_pc_questions([self.q()]); self.h.on_pc_questions([self.q()])
        self.assertEqual([e["title"] for e in self.events], ["Helper question waiting"])
        self.h = self.make(); self.h.on_pc_questions([self.q()])
        self.assertEqual(len(self.events), 1)

    def test_answer_flow_and_duplicates(self):
        self.h.on_pc_questions([self.q()])
        r = self.h.answer(QID, "  yes\n go ")
        self.assertEqual((r["duplicate"], self.claude.items[0]["text"], self.claude.items[0]["kind"]), (False, "yes go", "helper-answer"))
        self.assertTrue(self.h.answer(QID, "again")["duplicate"]); self.assertEqual(len(self.claude.items), 1)
        self.h.on_pc_questions([self.q()])
        self.assertEqual(self.h.questions()[0]["state"], "sent")
        self.h.on_result({"key": "hq-" + QID, "ok": True, "detail": "x"})
        self.assertEqual(self.h.questions()[0]["state"], "answered")
        self.assertTrue(self.h.answer(QID, "late")["duplicate"])

    def test_failed_answer_reopens_and_validation(self):
        self.h.on_pc_questions([self.q()]); self.h.answer(QID, "a")
        self.h.on_result({"key": "hq-" + QID, "ok": False, "detail": "no pwsh"})
        c = self.h.questions()[0]; self.assertEqual((c["state"], c["error"]), ("open", "no pwsh"))
        for bad in ("", "x" * 1001): self.assertRaises(ValueError, self.h.answer, QID, bad)
        self.assertRaises(ValueError, self.h.answer, "../x", "a")
        self.assertRaises(LookupError, self.h.answer, "20200101-000000-gemini", "a")

    def test_gone_from_inbox_counts_as_answered_and_is_pruned(self):
        self.h.on_pc_questions([self.q()]); self.h.on_pc_questions([])
        self.assertEqual(self.h.questions()[0]["state"], "answered")
        self.now[0] += 25 * 3600; self.h.on_pc_questions([])
        self.assertEqual(self.h.questions(), [])

    def test_muted_no_notification(self):
        self.st["muted"] = True; self.h.on_pc_questions([self.q()]); self.assertEqual(self.events, [])

    # digest
    def digest(self, day="2026-11-18"):
        return {"date": day, "text": "# Daily digest\n", "summary": "3 done · 5 commits", "counts": {"tasks": 3, "commits": 5, "releases": 0}}

    def test_want_digest_window_and_send_once_at_time(self):
        self.now[0] = stamp(12, 0); self.assertFalse(self.h.want_digest())
        self.now[0] = stamp(19, 40); self.assertTrue(self.h.want_digest())
        self.h.on_digest(self.digest()); self.assertEqual(self.events, [])      # before 20:00: stored, not sent
        self.assertFalse(self.h.want_digest())
        self.now[0] = stamp(20, 1); self.assertTrue(self.h.want_digest())        # older than 15 min: refresh
        self.h.on_digest(self.digest())
        self.assertEqual([e["title"] for e in self.events], ["Daily digest"])
        self.assertIn("1 waiting for you", self.events[0]["body"]); self.assertEqual(self.docs.up[0][1], "daily-digest-2026-11-18.md")
        self.assertIn("To-do: Plug in the USB hub", self.docs.up[0][2])
        self.h.on_digest(self.digest()); self.assertEqual(len(self.events), 1)   # once per day
        self.assertFalse(self.h.want_digest())

    def test_timer_tick_sends_stored_digest_when_time_arrives(self):
        self.now[0] = stamp(19, 50); self.h.on_digest(self.digest())
        self.now[0] = stamp(20, 0); self.h.tick(); self.assertEqual(len(self.events), 1)

    def test_off_and_stale_and_late(self):
        self.st["digest_on"] = False; self.now[0] = stamp(20, 5); self.h.on_digest(self.digest()); self.assertEqual(self.events, [])
        self.st["digest_on"] = True; self.h.tick(); self.assertEqual(len(self.events), 1)   # turned on later the same evening
        self.events.clear(); self.h.fired = ""; self.h.on_digest(self.digest("2026-11-17")); self.h.tick(); self.assertEqual(self.events, [])
        self.now[0] = stamp(23, 30); self.h.on_digest(self.digest()); self.assertEqual(self.events, [])   # past the 3 h grace

    def test_force_sends_now_without_using_up_the_day(self):
        self.now[0] = stamp(9, 0); self.h.request_now(); self.assertTrue(self.h.want_digest())
        self.h.on_digest(self.digest()); self.assertEqual(len(self.events), 1); self.assertFalse(self.h.force)
        self.now[0] = stamp(19, 40); self.h.on_digest(self.digest()); self.now[0] = stamp(20, 0); self.h.tick()
        self.assertEqual(len(self.events), 2)

    def test_quiet_flag_and_bad_digest(self):
        self.assertRaises(ValueError, self.h.on_digest, {"date": "x", "text": "a"})
        self.assertRaises(ValueError, self.h.on_digest, {"date": "2026-11-18", "text": "a" * 30000})


if __name__ == "__main__":
    unittest.main()
