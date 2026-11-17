import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_digest as d

QID = "20261117-234110-codex"


def make_hub(tmp, qid=QID, with_job=True):
    hub = Path(tmp) / "hub"
    (hub / "inbox" / "claude").mkdir(parents=True)
    (hub / "state" / "questions").mkdir(parents=True)
    (hub / "bin").mkdir()
    (hub / "inbox" / "claude" / ("2026-11-17-2341-from-codex-question-%s.md" % qid)).write_text(
        "# Question from codex\nFrom: codex   To: claude   Date: x   Id: %s\n## Question\nMay I run the build?\n## Original task\n# Task: do\nthings\n## How to answer\nx\n" % qid, encoding="utf-8")
    if with_job:
        (hub / "state" / "questions" / (qid + ".json")).write_text("{}", encoding="utf-8")
    return hub


class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_list_parses_question(self):
        hub = make_hub(self.tmp.name)
        q = d.list_questions(hub)
        self.assertEqual(len(q), 1)
        self.assertEqual((q[0]["id"], q[0]["helper"], q[0]["question"]), (QID, "codex", "May I run the build?"))
        self.assertIn("Task: do", q[0]["task"])

    def test_list_skips_without_saved_job_and_done(self):
        hub = make_hub(self.tmp.name, with_job=False)
        self.assertEqual(d.list_questions(hub), [])
        hub = make_hub(tempfile.mkdtemp())
        (hub / "inbox" / "claude" / "done").mkdir()
        for f in (hub / "inbox" / "claude").glob("*.md"):
            os.replace(f, hub / "inbox" / "claude" / "done" / f.name)
        self.assertEqual(d.list_questions(hub), [])

    def test_answer_runs_ask_and_moves_file(self):
        hub = make_hub(self.tmp.name)
        calls = []
        r = d.answer_question(hub, QID, "  yes,\n do it  ", runner=lambda cmd, log: calls.append(cmd))
        self.assertTrue(r["ok"])
        self.assertEqual(calls[0][-3:], ["-AnswerId", QID, "-Answer:yes, do it"])
        self.assertEqual(list((hub / "inbox" / "claude").glob("*.md")), [])
        self.assertEqual(len(list((hub / "inbox" / "claude" / "done").glob("*.md"))), 1)

    def test_answer_validation(self):
        hub = make_hub(self.tmp.name)
        run = lambda cmd, log: self.fail("must not run")
        for qid, text in (("../x", "a"), (QID, ""), (QID, "x" * 1001), ("20200101-000000-gemini", "a")):
            self.assertFalse(d.answer_question(hub, qid, text, runner=run)["ok"])

    def test_answer_dash_text_stays_a_value_and_start_failure_keeps_file(self):
        hub = make_hub(self.tmp.name)
        def boom(cmd, log): raise OSError("no pwsh")
        self.assertFalse(d.answer_question(hub, QID, "-Force", runner=boom)["ok"])
        self.assertEqual(len(list((hub / "inbox" / "claude").glob("*.md"))), 1)
        calls = []
        d.answer_question(hub, QID, "-Force", runner=lambda c, l: calls.append(c))
        self.assertEqual(calls[0][-1], "-Answer:-Force")


class DigestTests(unittest.TestCase):
    def test_worklog_only_today_and_dedupes(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = Path(t) / "a" / "WORKLOG.md", Path(t) / "WORKLOG.md"
            a.parent.mkdir()
            a.write_text("## Log\n- 2026-11-17 09:00 · [fix] old → x\n- 2026-11-18 10:00 · [fix] new → y · f.py\n", encoding="utf-8")
            b.write_text("- 2026-11-18 10:00 · [fix] new → y · f.py\n- 2026-11-18 11:00 · [test] t → ok\n", encoding="utf-8")
            rows = d.worklog_lines([a, b], "2026-11-18")
            self.assertEqual([r[0][-5:] for r in rows], ["10:00", "11:00"])

    def test_git_today_commits_tags_and_skips_worktree(self):
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t) / "r"
            repo.mkdir()
            env = dict(os.environ, GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@b", GIT_COMMITTER_NAME="a", GIT_COMMITTER_EMAIL="a@b")
            g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], env=env, check=True, capture_output=True)
            g("init", "-q")
            (repo / "f").write_text("1")
            g("add", "f")
            g("commit", "-q", "-m", "first")
            g("tag", "v1.0")
            wt = Path(t) / "wt"
            wt.mkdir()
            (wt / ".git").write_text("gitdir: x")
            today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
            commits, tags = d.git_today([repo, wt], today)
            self.assertEqual([c[2] for c in commits], ["first"])
            self.assertEqual(tags, [("r", "v1.0")])
            self.assertEqual(d.git_today([repo], "2001-01-01"), ([], []))

    def test_usage_lines(self):
        u = {"claude": {"windows": [{"window": "five_hour", "used_percent": 61.0}, {"window": "seven_day", "used_percent": 34.0}]},
             "codex": {"windows": [{"used_percent": 79.0, "resets_epoch": 2000}]},
             "gemini_app": {"jobs_today": 3, "daily_cap": 25}, "perplexity": {"jobs_today": 0, "daily_cap": 30}, "parked": ["agy"]}
        lines = d.usage_lines(u, now=1000)
        self.assertIn("Claude 5-hour: 61% used", lines)
        self.assertIn("Gemini app: 22 of 25 jobs left today", lines)
        self.assertTrue(any(l.startswith("Codex: 79% used (resets in") for l in lines))
        self.assertIn("Parked helpers: agy", lines)
        self.assertEqual(d.usage_lines({}), [])

    def test_build_digest(self):
        r = d.build_digest("2026-11-18", [("2026-11-18 10:00", "p", "did it")], [("p", "abc", "msg")] * 6, [("p", "v1")], {})
        self.assertEqual(r["counts"], {"tasks": 1, "commits": 6, "releases": 1})
        self.assertIn("- [p] did it", r["text"])
        self.assertIn("…and 2 more", r["text"])
        self.assertIn("No usage data", r["text"])

    def test_short_drops_file_list_and_caps(self):
        self.assertEqual(d._short("[fix] a → b · f.py, g.py"), "[fix] a → b")
        self.assertEqual(d._short("[fix] no arrow · x"), "[fix] no arrow · x")
        self.assertEqual(len(d._short("x" * 300)), 158)


if __name__ == "__main__":
    unittest.main()
