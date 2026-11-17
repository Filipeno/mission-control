"""Tests for mc_appcard (log parser + matcher). Run: python -m unittest pc/test_mc_appcard.py -v"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mc_appcard as m  # noqa: E402

S1 = "local_11111111-1111-4111-8111-111111111111"
S2 = "local_22222222-2222-4222-8222-222222222222"
A = "aaaaaaaa-0000-4000-8000-000000000001"
B = "bbbbbbbb-0000-4000-8000-000000000002"
C = "cccccccc-0000-4000-8000-000000000003"
D = "dddddddd-0000-4000-8000-000000000004"
START = "mcp__ccd_session__start_session"


def emit(i, tool, s, t="12:00:00"):
    return f"2026-11-17 {t} [info] Emitted tool permission request {i} for {tool} in session {s}"


def resp(i, d, tool=START, t="12:00:05"):
    return f"2026-11-17 {t} [info] Received permission response for {i}: {d} (tool: {tool})"


def abort(i, tool, t="12:00:06"):
    return f"2026-11-17 {t} [info] Permission request {i} for {tool} aborted"


def respond_call(i, d):
    return f"2026-11-17 12:00:05 [info] LocalSessions.respondToToolPermission: requestId={i}, decision={d}, hasUpdatedInput=true"


TITLES = {S1: "MC card test (just says hi)", S2: "Other chat"}


class Parse(unittest.TestCase):
    def test_states(self):
        cards = m.parse([emit(A, START, S1), respond_call(A, "deny"), resp(A, "deny"),
                         emit(B, "AskUserQuestion", S2), abort(B, "AskUserQuestion"),
                         emit(C, START, S2), "2026-11-17 12:00:07 [info] unrelated permission line"])
        self.assertEqual(cards[A]["state"], "answered")
        self.assertEqual(cards[A]["decision"], "deny")
        self.assertEqual(cards[B]["state"], "aborted")
        self.assertEqual(cards[C]["state"], "pending")
        self.assertEqual([c["id"] for c in m.pending(cards)], [C])

    def test_response_without_tool_suffix(self):
        line = f"2026-11-17 12:00:05 [info] Received permission response for {A}: once (tool: {START}"
        cards = m.parse([emit(A, START, S1), line])
        self.assertEqual(cards[A]["decision"], "once")

    def test_app_restart_drops_open_cards(self):
        cards = m.parse([emit(A, START, S1), "2026-11-17 12:01:00 [info] Starting app {", emit(B, START, S2)])
        self.assertNotIn(A, cards)
        self.assertEqual([c["id"] for c in m.pending(cards)], [B])

    def test_response_for_unknown_id_ignored(self):
        self.assertEqual(m.parse([resp(A, "once")]), {})


class Check(unittest.TestCase):
    def cards(self, *extra):
        return m.parse([emit(A, START, S1), *extra])

    def test_ok(self):
        ok, reason, c = m.check(self.cards(), A, TITLES, "MC card test (just says hi)", START)
        self.assertTrue(ok, reason)
        self.assertEqual(c["title"], TITLES[S1])

    def test_title_whitespace_is_normalised(self):
        ok, _, _ = m.check(self.cards(), A, TITLES, "  MC card test   (just says hi) ")
        self.assertTrue(ok)

    def test_wrong_title(self):
        ok, reason, _ = m.check(self.cards(), A, TITLES, "Some other chat")
        self.assertFalse(ok)
        self.assertIn("title mismatch", reason)

    def test_two_pending_same_session(self):
        ok, reason, _ = m.check(self.cards(emit(B, "mcp__ccd_session_mgmt__set_remote_control", S1)), A, TITLES)
        self.assertFalse(ok)
        self.assertIn("2 cards pending", reason)

    def test_pending_question_in_same_session_is_fine(self):
        ok, reason, _ = m.check(self.cards(emit(B, "AskUserQuestion", S1)), A, TITLES)
        self.assertTrue(ok, reason)

    def test_pending_in_other_session_is_fine(self):
        ok, reason, _ = m.check(self.cards(emit(B, START, S2)), A, TITLES)
        self.assertTrue(ok, reason)

    def test_unknown_id(self):
        ok, reason, c = m.check(self.cards(), D, TITLES)
        self.assertFalse(ok)
        self.assertIn("unknown request id", reason)
        self.assertIsNone(c)

    def test_bad_id(self):
        ok, reason, _ = m.check(self.cards(), "../../x", TITLES)
        self.assertFalse(ok)
        self.assertEqual(reason, "bad request id")

    def test_already_answered(self):
        ok, reason, _ = m.check(self.cards(resp(A, "once")), A, TITLES)
        self.assertFalse(ok)
        self.assertIn("already answered (once)", reason)

    def test_aborted(self):
        ok, reason, _ = m.check(self.cards(abort(A, START)), A, TITLES)
        self.assertFalse(ok)
        self.assertIn("aborted", reason)

    def test_tool_mismatch(self):
        ok, reason, _ = m.check(self.cards(), A, TITLES, tool="mcp__ccd_session_mgmt__delete_session")
        self.assertFalse(ok)
        self.assertIn("tool mismatch", reason)

    def test_question_card_refused(self):
        ok, reason, _ = m.check(m.parse([emit(C, "AskUserQuestion", S2)]), C, TITLES)
        self.assertFalse(ok)
        self.assertIn("question card", reason)

    def test_duplicate_title_refused(self):
        ok, reason, _ = m.check(self.cards(), A, {S1: "Same", S2: " Same "})
        self.assertFalse(ok)
        self.assertIn("used by 2 sessions", reason)

    def test_recheck_ok(self):
        ok, reason, _ = m.check(self.cards(), A, TITLES, since_lines=[emit(B, START, S2)],
                                card_name="Permission request: start the session “MC card test (just says hi)”")
        self.assertTrue(ok, reason)

    def test_recheck_new_card_same_session_since_search(self):
        # B came and went (answered) while the buttons were being searched: the window may show B's card.
        lines = [emit(B, START, S1, "12:00:01"), resp(B, "deny", t="12:00:02")]
        ok, reason, _ = m.check(self.cards(*lines), A, TITLES, since_lines=lines,
                                card_name="Permission request: start the session “x”")
        self.assertFalse(ok)
        self.assertIn("new card(s) in that session", reason)

    def test_recheck_card_text_must_fit_tool(self):
        ok, reason, _ = m.check(self.cards(), A, TITLES, since_lines=[],
                                card_name="Permission request: turn Remote Control off")
        self.assertFalse(ok)
        self.assertIn("does not fit", reason)

    def test_recheck_unknown_tool_card_refused(self):
        cards = m.parse([emit(C, "mcp__ccd_session_mgmt__set_remote_control", S2)])
        ok, reason, _ = m.check(cards, C, TITLES, since_lines=[], card_name="Permission request: start the session “x”")
        self.assertFalse(ok)
        self.assertIn("does not fit", reason)

    def test_unknown_title_refused(self):
        ok, reason, _ = m.check(self.cards(), A, {})
        self.assertFalse(ok)
        self.assertEqual(reason, "session title unknown")


class Cli(unittest.TestCase):
    """The same commands mc-appcard.ps1 runs, against a fixture log dir."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        (d / "main1.log").write_text(emit(D, START, S2, "11:00:00") + "\n", encoding="utf-8")
        (d / "main.log").write_text("\n".join([emit(A, START, S1), emit(B, START, S1), emit(C, START, S2)]) + "\n",
                                    encoding="utf-8")
        (d / "titles.json").write_text(json.dumps(TITLES), encoding="utf-8")
        self.d = d

    def tearDown(self):
        self.dir.cleanup()

    def run_cli(self, *args):
        buf = io.BytesIO()

        class W:
            buffer = buf
        old = sys.stdout
        sys.stdout = W()
        try:
            m.main([*args, "--log-dir", str(self.d), "--titles", str(self.d / "titles.json")])
        finally:
            sys.stdout = old
        return json.loads(buf.getvalue().decode("utf-8"))

    def test_list_reads_rotated_log_when_no_app_start(self):
        ids = [c["id"] for c in self.run_cli("list")["cards"]]
        self.assertEqual(ids, [D, A, B, C])

    def test_list_ignores_rotated_log_after_app_start(self):
        p = self.d / "main.log"
        p.write_text("2026-11-17 10:00:00 [info] Starting app {\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
        ids = [c["id"] for c in self.run_cli("list")["cards"]]
        self.assertEqual(ids, [A, B, C])

    def test_check_two_pending(self):
        r = self.run_cli("check", A)
        self.assertFalse(r["ok"])
        self.assertIn("2 cards pending", r["reason"])

    def test_wait_and_confirm(self):
        off = self.run_cli("offset")["offset"]
        with open(self.d / "main.log", "a", encoding="utf-8") as f:
            f.write(emit("eeeeeeee-0000-4000-8000-000000000005", START, S2, "12:05:00") + "\n")
        r = self.run_cli("wait", "--from", str(off), "--tool", START, "--timeout", "1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["card"]["title"], "Other chat")
        off2 = self.run_cli("offset")["offset"]
        with open(self.d / "main.log", "a", encoding="utf-8") as f:
            f.write(resp(C, "once") + "\n")
        r = self.run_cli("confirm", C, "--from", str(off2), "--timeout", "1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["decision"], "once")

    def test_check_since_offset(self):
        p = self.d / "main.log"                          # app start: the rotated log's card D is gone, C is alone in S2
        p.write_text("2026-11-17 10:00:00 [info] Starting app {\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertTrue(self.run_cli("check", C)["ok"])
        off = self.run_cli("offset")["offset"]
        with open(self.d / "main.log", "a", encoding="utf-8") as f:
            f.write(emit("eeeeeeee-0000-4000-8000-000000000005", START, S2, "12:05:00") + "\n")
            f.write(resp("eeeeeeee-0000-4000-8000-000000000005", "once", t="12:05:01") + "\n")
        r = self.run_cli("check", C, "--since", str(off), "--card-name", "Permission request: start the session “x”")
        self.assertFalse(r["ok"])
        self.assertIn("new card(s)", r["reason"])

    def test_confirm_times_out(self):
        off = self.run_cli("offset")["offset"]
        r = self.run_cli("confirm", C, "--from", str(off), "--timeout", "0.5")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
