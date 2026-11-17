"""Tests for mc_appgate (app cards as phone gates, lock-hold, expiry). Run: python -m unittest pc/test_mc_appgate.py -v"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mc_appcard  # noqa: E402
import mc_appgate as g  # noqa: E402

S1 = "local_11111111-1111-4111-8111-111111111111"
S2 = "local_22222222-2222-4222-8222-222222222222"
A = "aaaaaaaa-0000-4000-8000-000000000001"
B = "bbbbbbbb-0000-4000-8000-000000000002"
Q = "cccccccc-0000-4000-8000-000000000003"
START = "mcp__ccd_session__start_session"
SID1 = "99999999-0000-4000-8000-000000000001"


def card(i, tool=START, s=S1, at="2026-11-17 12:00:00"):
    return {"id": i, "tool": tool, "session": s, "at": at, "state": "pending", "decision": ""}


SESSIONS = [{"id": SID1, "local": S1, "cwd": "D:\\projekty", "title": "Boss"}]
TITLES = {S1: "Boss chat", S2: "Other chat"}


class BuildGates(unittest.TestCase):
    def test_full_brief_from_transcript(self):
        brief = "x" * 20000
        blocks = {SID1: [{"name": "Bash", "input": {"command": "ls"}},
                         {"name": START, "input": {"title": "old", "prompt": "older"}},
                         {"name": START, "input": {"title": "New one", "prompt": brief}}]}
        out = g.build_gates([card(A)], TITLES, SESSIONS, lambda sid: blocks.get(sid, []))
        self.assertEqual(len(out), 1)
        x = out[0]
        self.assertEqual(x["id"], "ac-" + A)
        self.assertEqual(x["kind"], "appcard")
        self.assertEqual(x["card"], A)
        self.assertEqual(x["input"]["prompt"], brief)          # the newest open start_session, whole
        self.assertFalse(x["truncated"])
        self.assertTrue(x["input_found"])
        self.assertEqual(x["session_id"], SID1)
        self.assertEqual(x["card_title"], "Boss chat")         # the app's own title, used as -ExpectTitle
        self.assertTrue(x["answerable"])
        self.assertGreater(x["created"], 0)

    def test_gate_id_fits_the_pi(self):
        import re
        self.assertTrue(re.match(r"^ac-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", g.gate_id(A)))

    def test_question_cards_and_bad_ids_skipped(self):
        out = g.build_gates([card(Q, tool="AskUserQuestion"), card("not-a-uuid")], TITLES, SESSIONS, lambda s: [])
        self.assertEqual(out, [])

    def test_no_transcript_input(self):
        out = g.build_gates([card(B, s=S2)], TITLES, SESSIONS, lambda s: [])
        self.assertEqual(out[0]["input"], {})
        self.assertFalse(out[0]["input_found"])
        self.assertEqual(out[0]["session_id"], "")
        self.assertEqual(out[0]["card_title"], "Other chat")

    def test_unknown_tool_not_answerable(self):
        out = g.build_gates([card(B, tool="mcp__ccd_session__delete_session")], TITLES, SESSIONS, lambda s: [])
        self.assertFalse(out[0]["answerable"])

    def test_huge_input_cut_to_fit(self):
        blocks = [{"name": START, "input": {"title": "t", "prompt": "y" * 100000}}]
        out = g.build_gates([card(A)], TITLES, SESSIONS, lambda s: blocks)
        self.assertTrue(out[0]["truncated"])
        self.assertLessEqual(len(json.dumps(out[0]["input"])), g.MAX_INPUT)
        self.assertEqual(out[0]["input"]["title"], "t")

    def test_pending_from_log(self):
        lines = [f"2026-11-17 12:00:00 [info] Emitted tool permission request {A} for {START} in session {S1}",
                 f"2026-11-17 12:00:01 [info] Emitted tool permission request {B} for {START} in session {S2}",
                 f"2026-11-17 12:00:05 [info] Received permission response for {B}: deny (tool: {START})"]
        out = g.build_gates(mc_appcard.pending(mc_appcard.parse(lines)), TITLES, SESSIONS, lambda s: [])
        self.assertEqual([x["card"] for x in out], [A])        # B answered at the PC: its phone card closes


def item(**kw):
    d = {"card": A, "decision": "allow", "title": "Boss chat", "tool": START, "at": 1000.0}
    d.update(kw)
    return d


class Decide(unittest.TestCase):
    def d(self, it, now=1100.0, locked=False, state="pending"):
        return g.decide(it, now, lambda: locked, lambda c: state)

    def test_run_when_unlocked(self):
        self.assertEqual(self.d(item())[0], "run")

    def test_held_while_locked(self):
        act, detail = self.d(item(), locked=True)
        self.assertEqual(act, "held")
        self.assertIn("waiting for unlock", detail)

    def test_held_until_8h_then_expired(self):
        self.assertEqual(self.d(item(), now=1000 + 8 * 3600 - 1, locked=True)[0], "held")
        self.assertEqual(self.d(item(), now=1000 + 8 * 3600 + 1, locked=True)[0], "expired")
        self.assertEqual(self.d(item(), now=1000 + 8 * 3600 + 1, locked=False)[0], "expired")

    def test_gone_when_answered_at_pc(self):
        self.assertEqual(self.d(item(), state="answered", locked=True)[0], "gone")
        self.assertEqual(self.d(item(), state="aborted")[0], "gone")
        self.assertEqual(self.d(item(), state="unknown")[0], "gone")

    def test_refuses_bad_items(self):
        self.assertEqual(self.d(item(decision="always"))[0], "refused")     # never "Always allow"
        self.assertEqual(self.d(item(decision="once"))[0], "refused")
        self.assertEqual(self.d(item(card="x"))[0], "refused")
        self.assertEqual(self.d(item(tool="a b; rm"))[0], "refused")
        self.assertEqual(self.d(item(title="  "))[0], "refused")


class Answer(unittest.TestCase):
    def a(self, it, code=0, res=None, locked=False, state="pending"):
        calls = []

        def run(x):
            calls.append(x)
            return code, res or {}
        r = g.answer(it, now=1100.0, locked=lambda: locked, state_of=lambda c: state, run=run)
        return r, calls

    def test_done(self):
        r, calls = self.a(item(), 0, {"ok": True, "method": "mouse",
                                      "confirmedBy": f"2026-11-17 12:00:09 [info] Received permission response for {A}: once"})
        self.assertEqual(r["state"], "done")
        self.assertTrue(r["ok"])
        self.assertIn("Allow once", r["detail"])
        self.assertIn("12:00:09", r["detail"])
        self.assertEqual(len(calls), 1)

    def test_held_never_runs(self):
        r, calls = self.a(item(), locked=True)
        self.assertEqual((r["state"], r["ok"]), ("held", None))
        self.assertEqual(calls, [])

    def test_refusal_reason_goes_back(self):
        r, _ = self.a(item(), 4, {"ok": False, "reason": "title mismatch: session is 'X', expected 'Boss chat'"})
        self.assertEqual(r["state"], "refused")
        self.assertFalse(r["ok"])
        self.assertIn("title mismatch", r["detail"])

    def test_locked_during_click_is_held(self):
        r, _ = self.a(item(), 3, {"ok": False, "reason": "PC locked"})
        self.assertEqual(r["state"], "held")

    def test_gone_and_expired_never_run(self):
        r, calls = self.a(item(), state="answered")
        self.assertEqual((r["state"], calls), ("gone", []))
        r, calls = self.a(item(at=1100.0 - 8 * 3600 - 5))
        self.assertEqual((r["state"], calls), ("expired", []))

    def test_title_goes_in_env_not_argv(self):
        captured = {}

        class P:
            returncode, stdout, stderr = 4, b'{"ok": false, "reason": "x"}', b""

        def fake_run(args, **kw):
            captured["args"], captured["env"] = args, kw.get("env")
            return P()
        old = g.subprocess.run
        g.subprocess.run = fake_run
        try:
            code, res = g.run_answer(item(title="-Decision allow"))
        finally:
            g.subprocess.run = old
        self.assertEqual(code, 4)
        self.assertNotIn("-Decision allow", captured["args"])
        self.assertEqual(captured["env"]["MC_EXPECT_TITLE"], "-Decision allow")
        self.assertIn("-ExpectTitleEnv", captured["args"])


if __name__ == "__main__":
    unittest.main()
