import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sessions_hub as sh

AC = "ac-0b1c2d3e-0000-4000-8000-0123456789ab"
HK = "20261118-120000-ab12"
SID = "11111111-1111-4111-8111-111111111111"
SID2 = "22222222-2222-4222-8222-222222222222"
JPEG = bytes((255, 216)) + b"x" * 100


class Claude:
    def __init__(self): self.items, self.verified = [], 0
    def enqueue(self, x): self.items.append(x)
    def verify(self, *a, tier="H"):
        if tier == "0" and not a[2]: return
        self.verified += 1
        if not a[2]: raise PermissionError("bad signature")


def hub():
    store = {}
    return sh.SessionsHub(Claude(), lambda n, d: store.get(n, d), lambda n, o: store.__setitem__(n, o), lambda ev: None)


def sess(i, title, state="working", updated=None, last="did a thing"):
    return {"id": i, "title": title, "state": state, "updated": updated or time.time(), "last": last, "cwd": "d:/x"}


class Peek(unittest.TestCase):
    def test_shot_for_hook_and_app_cards(self):
        h = hub()
        h.on_snapshot({"sessions": [sess(SID, "A")], "gates": [{"id": HK, "kind": "permission", "tool": "Bash", "input": {"command": "ls"}, "session_id": SID},
                                                              {"id": AC, "kind": "appcard", "tool": "x", "session_id": SID}]})
        h.save_card_shot(HK, JPEG)
        h.save_card_shot(AC, b"", locked=True)
        gates = {g["id"]: g for g in h.list_view()["gates"]}
        self.assertTrue(gates[HK]["has_shot"] and not gates[HK]["shot_locked"])
        self.assertFalse(gates[AC]["has_shot"])
        self.assertTrue(gates[AC]["shot_locked"])
        self.assertEqual(h.card_shot(HK), JPEG)
        self.assertIsNone(h.card_shot(AC))          # a locked PC has no picture to serve

    def test_bad_shots_refused(self):
        h = hub()
        for bad in (b"not a jpeg", bytes((255, 216)) + b"x" * sh.SHOT_BYTES):
            with self.assertRaises(ValueError):
                h.save_card_shot(HK, bad)
        with self.assertRaises(ValueError):
            h.save_card_shot("../etc", JPEG)

    def test_shot_dropped_when_card_gone(self):
        h = hub()
        h.on_snapshot({"sessions": [sess(SID, "A")], "gates": [{"id": HK, "kind": "permission", "tool": "Bash", "input": {}, "session_id": SID}]})
        h.save_card_shot(HK, JPEG)
        h.on_snapshot({"sessions": [sess(SID, "A")], "gates": []})
        self.assertIsNotNone(h.card_shot(HK))        # inside the grace window: the snapshot may just be behind
        h.card_shots[HK] = (JPEG, time.time() - sh.SHOT_GRACE - 1)
        h.on_snapshot({"sessions": [sess(SID, "A")], "gates": []})
        self.assertIsNone(h.card_shot(HK))           # answered / expired: the picture is gone

    def test_widget_session_choice(self):
        h = hub()
        now = time.time()
        h.on_snapshot({"sessions": [sess(SID, "Old", updated=now - 500), sess(SID2, "New", updated=now)],
                       "gates": [{"id": HK, "kind": "permission", "tool": "Bash", "input": {"command": "rm x"}, "session_id": SID}]})
        w = h.widget_session("")                      # nothing pinned: the one that asks wins over the newest
        self.assertEqual((w["id"], w["state"], w["pinned"], w["gate"]["id"]), (SID, "waiting", False, HK))
        w = h.widget_session(SID2)                    # pinned wins
        self.assertEqual((w["id"], w["state"], w["pinned"], w["gate"]), (SID2, "working", True, None))
        w = h.widget_session("33333333-3333-4333-8333-333333333333")   # pin gone: falls back
        self.assertEqual((w["id"], w["pinned"]), (SID, False))

    def test_question_has_no_one_tap_allow(self):
        h = hub()
        h.on_snapshot({"sessions": [sess(SID, "A")], "gates": [{"id": HK, "kind": "question", "tool": "AskUserQuestion",
                       "input": {"questions": [{"question": "Which?"}]}, "session_id": SID}]})
        w = h.widget_session("")
        self.assertEqual(w["state"], "waiting")
        self.assertIsNone(w["gate"])
        self.assertEqual(w["asks"]["kind"], "question")

    def test_unsigned_deny_any_gate(self):
        h = hub()
        Q = "20261118-120001-ff00"
        h.on_snapshot({"sessions": [sess(SID, "A")], "gates": [
            {"id": HK, "kind": "permission", "tool": "Bash", "input": {}, "session_id": SID},
            {"id": Q, "kind": "question", "tool": "AskUserQuestion", "input": {"questions": [{"question": "?"}]}, "session_id": SID}]})
        self.assertTrue(h.answer_gate("t", HK, {"decision": "deny"})["ok"])         # one tap, no signature
        self.assertEqual(h.claude.verified, 0)
        with self.assertRaises(PermissionError):
            h.answer_gate("t", HK, {"decision": "allow"})                              # Allow always needs the fingerprint
        with self.assertRaises(PermissionError):
            h.answer_gate("t", HK, {"decision": "deny", "payload": "because"})         # a note is signed
        n = h.claude.verified
        self.assertTrue(h.answer_gate("t", Q, {"decision": "deny"})["ok"])          # option C: any Deny is one tap
        self.assertEqual(h.claude.verified, n)

    def test_no_sessions_or_stale(self):
        h = hub()
        self.assertIsNone(h.widget_session(""))
        h.on_snapshot({"sessions": [sess(SID, "A")], "gates": []})
        h.snap["at"] = time.time() - sh.FRESH - 5
        self.assertIsNone(h.widget_session(""))


if __name__ == "__main__":
    unittest.main()
