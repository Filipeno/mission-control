import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_loop as ml

TID = "20261119-044821-c84"
RUN = "20261119-130000-abc"


def line(d):
    return json.dumps(d)


def assistant(*blocks):
    return line({"type": "assistant", "message": {"id": "chatcmpl-x", "role": "assistant", "content": list(blocks),
                                                  "usage": {"input_tokens": 10, "output_tokens": 0}}, "session_id": "s", "uuid": "u"})


def tool_result(tid, content, err=False, dup=None):
    return line({"type": "user", "message": {"role": "user", "content": [
        {"tool_use_id": tid, "type": "tool_result", "content": content, "is_error": err}]},
        "tool_use_result": dup if dup is not None else {"stdout": content}})


# Shaped like a real round-N.jsonl (Claude Code stream-json with a local Qwen model)
ROUND = [
    line({"type": "system", "subtype": "init", "cwd": "D:\\x", "session_id": "s", "tools": ["Bash"], "model": "qwen",
          "apiKeySource": "ANTHROPIC_API_KEY"}),
    line({"type": "system", "subtype": "dev_intent", "kind": "android_app"}),
    assistant({"type": "text", "text": "First, let me read the test file."}),
    assistant({"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "D:/r/pc/test_mc_peek.py"}}),
    tool_result("t1", "1\timport sys\n2\timport unittest"),
    assistant({"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "python -m unittest pc.test_x"}}),
    tool_result("t2", [{"type": "text", "text": "FAILED (errors=1)"}], err=True),
    assistant({"type": "tool_use", "id": "t3", "name": "Read", "input": {"file_path": "D:/r/.env"}}),
    tool_result("t3", "OPENAI_API_KEY=abcdefghijklmnop"),
    assistant({"type": "tool_use", "id": "t4", "name": "Bash", "input": {"command": "printenv"}}),
    tool_result("t4", "PATH=/usr/bin\nHOME=/home/x"),
    assistant({"type": "tool_use", "id": "t5", "name": "Edit", "input": {"file_path": "D:/r/a.py", "old_string": "x = 1", "new_string": "x = 2"}}),
    tool_result("t5", "The file D:/r/a.py has been updated."),
    line({"type": "result", "subtype": "success", "num_turns": 6, "duration_ms": 291000, "is_error": False}),
    '{"type": "assistant", "message": {"content": [{"type": "text", "te',          # still being written
]


class Redact(unittest.TestCase):
    def test_openai_and_anthropic_keys(self):
        self.assertEqual(ml.redact("key sk-abcdefghijklmnop1234 end"), "key sk-[hidden] end")
        self.assertNotIn("abcdefghijklmnopqrst", ml.redact("sk-ant-abcdefghijklmnopqrst"))

    def test_github_tokens(self):
        self.assertEqual(ml.redact("ghp_" + "a1B2" * 9), "[hidden token]")
        self.assertEqual(ml.redact("github_pat_" + "x" * 30), "[hidden token]")

    def test_bearer(self):
        self.assertEqual(ml.redact("Authorization: Bearer abc.def-ghi_jkl123"), "Authorization: Bearer [hidden]")
        self.assertEqual(ml.redact("Authorization: Basic dXNlcjpwYXNzd29yZA=="), "Authorization: Basic [hidden]")
        self.assertEqual(ml.redact("# Test basic functionality"), "# Test basic functionality")
        self.assertEqual(ml.redact("C:\\Users\\f\\.claude\\projects\\D--ai-hub-loop-worktrees-20261119-044821-c84\\x"),
                         "C:\\Users\\f\\.claude\\projects\\D--ai-hub-loop-worktrees-20261119-044821-c84\\x")

    def test_key_value_pairs(self):
        self.assertEqual(ml.redact("api_key=supersecret1"), "api_key=[hidden]")
        self.assertEqual(ml.redact('"apiKey": "supersecret1"'), '"apiKey": "[hidden]"')
        self.assertEqual(ml.redact("PASSWORD = hunter2hunter"), "PASSWORD = [hidden]")
        self.assertEqual(ml.redact("max_tokens=800"), "max_tokens=800")        # short values stay

    def test_env_line(self):
        # fake values are built at run time so secret scanners (gitleaks pre-push) do not flag the test file
        self.assertEqual(ml.redact("GITHUB_" + "TOKEN=" + "abcdef" + "123456\nDEBUG=1"), "GITHUB_TOKEN=[hidden]\nDEBUG=1")

    def test_url_password(self):
        self.assertEqual(ml.redact("postgres://filip:pa55word@db:5432/x"), "postgres://filip:[hidden]@db:5432/x")

    def test_long_hex_and_base64(self):
        self.assertEqual(ml.redact("h " + "ab12" * 16), "h [hidden hex]")
        sha1 = "b43cda8" + "0" * 33
        self.assertEqual(ml.redact(sha1), sha1)                                  # a git commit id (40) stays
        self.assertEqual(ml.redact("t " + "Ab1" * 12), "t [hidden token]")
        self.assertEqual(ml.redact("test_kinds_constant_has_correct_values"), "test_kinds_constant_has_correct_values")

    def test_private_key_and_aws(self):
        self.assertEqual(ml.redact("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"), "[hidden private key]")
        self.assertEqual(ml.redact("AKIA" + "ABCDEFGHIJKLMNOP"), "[hidden token]")

    def test_plain_text_unchanged(self):
        s = "Ran 5 tests in 0.000s\nOK — Český čaj"
        self.assertEqual(ml.redact(s), s)

    def test_secret_paths_and_commands(self):
        for p in (".env", "D:/x/.env.local", "secrets.h", "upload.keystore", "release.pass", "C:/Users/f/.ssh/config",
                  "credentials.json", "mc-pc.json", "api-keys.txt", "id_rsa"):
            self.assertTrue(ml.secret_path(p), p)
        for p in ("pc/mc_loop.py", "README.md", "mc-pi.env.example", ""):
            self.assertFalse(ml.secret_path(p), p)
        for c in ("env", "printenv | sort", "set", "Get-ChildItem env:", "cat .env", "type D:\\x\\secrets.h"):
            self.assertTrue(ml.secret_command(c), c)
        for c in ("set -e", "python -m unittest pc.test_x", "git status", "envsubst < a"):
            self.assertFalse(ml.secret_command(c), c)


class Transcript(unittest.TestCase):
    def test_parse_real_shape(self):
        r = ml.parse_round(ROUND)
        ks = [i["k"] for i in r["items"]]
        self.assertEqual(ks, ["text", "tool", "result", "tool", "result", "tool", "result", "tool", "result", "tool", "result", "end"])
        self.assertEqual(r["items"][1], {"k": "tool", "t": "D:/r/pc/test_mc_peek.py", "n": "Read"})
        self.assertEqual(r["items"][3]["t"], "python -m unittest pc.test_x")
        self.assertEqual(r["items"][4], {"k": "result", "t": "FAILED (errors=1)", "e": True})
        self.assertEqual(r["items"][6]["t"], "[hidden]")                         # read of .env
        self.assertEqual(r["items"][8]["t"], "[hidden]")                         # env dump
        self.assertEqual(r["items"][9]["t"], "D:/r/a.py\n- x = 1\n+ x = 2")
        self.assertEqual(r["items"][11]["t"], "success \u00b7 6 turns \u00b7 291 s")
        self.assertEqual((r["total"], r["skipped"]), (12, 0))

    def test_no_ids_usage_or_duplicates(self):
        text = json.dumps(ml.parse_round(ROUND))
        for word in ("chatcmpl", "session_id", "usage", "tool_use_result", "stdout", "apiKeySource", "dev_intent"):
            self.assertNotIn(word, text)

    def test_item_cut_and_round_limit(self):
        big = ml.parse_round([assistant({"type": "text", "text": "y" * 5000})])["items"][0]
        self.assertEqual(len(big["t"]), ml.ITEM_CHARS)
        self.assertEqual(big["full"], 5000)
        self.assertTrue(big["t"].endswith("\u2026"))
        many = ml.parse_round([assistant({"type": "text", "text": "step %d" % i}) for i in range(250)])
        self.assertEqual((len(many["items"]), many["total"], many["skipped"]), (200, 250, 50))
        self.assertEqual(many["items"][-1]["t"], "step 249")                     # the newest are kept

    def test_secret_write_hidden(self):
        r = ml.parse_round([assistant({"type": "tool_use", "id": "w", "name": "Write", "input": {"file_path": "a/.env", "content": "X=1"}})])
        self.assertEqual(r["items"][0]["t"], "a/.env\n[hidden]")

    def test_redaction_applies_to_text(self):
        r = ml.parse_round([assistant({"type": "text", "text": "use Bearer abcdefgh12345678"})])
        self.assertEqual(r["items"][0]["t"], "use Bearer [hidden]")


class Tasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = Path(self.tmp.name)
        d = self.hub / "loop" / "done" / TID
        d.mkdir(parents=True)
        (d / "task.json").write_text(json.dumps({"id": TID, "repo": "D:\\projekty\\mission-control", "goal": "Write tests",
                                                 "check": "python -m unittest", "rounds": 3, "model": "qwen"}), encoding="utf-8")
        (d / "result.json").write_text(json.dumps({
            "id": TID, "status": "failed", "reason": "review rejected twice", "rounds": 2, "total_seconds": 650,
            "started": "2026-11-19T12:20:32", "finished": "2026-11-19T12:31:45", "repo": "D:\\projekty\\mission-control",
            "model": "qwen", "check": "python -m unittest", "check_output_tail": "Ran 5 tests\r\nOK\r\n",
            "round_details": [{"round": 1, "agent_seconds": 291, "turns": 19, "check_exit": 0, "timed_out": False},
                              {"round": 2, "agent_seconds": 359, "turns": 23, "check_exit": 1, "timed_out": False}],
            "reviews": [{"n": 1, "verdict": "reject", "notes": ["token=abcdefghij leaked"]}]}), encoding="utf-8")
        (d / "round-1.jsonl").write_text("\n".join(ROUND), encoding="utf-8")
        (self.hub / "loop" / "done" / "not-a-task").mkdir()
        w = self.hub / "loop" / "work" / RUN
        w.mkdir(parents=True)
        (w / "round-1.jsonl").write_text(ROUND[2] + "\n", encoding="utf-8")
        (self.hub / "loop" / "queue").mkdir()
        (self.hub / "loop" / "queue" / (RUN + ".json")).write_text(json.dumps(
            {"id": RUN, "repo": "D:\\projekty\\x", "goal": "Run", "rounds": 3, "rounds_done": 0, "status": "running",
             "last_out": "....F\nFAILED (failures=1)\n"}), encoding="utf-8")
        st = self.hub / "state" / "local-agent"
        st.mkdir(parents=True)
        (st / "status.json").write_text(json.dumps({"task": RUN + ": Run", "state": "running"}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_running_first(self):
        ts = ml.list_tasks(self.hub)["tasks"]
        self.assertEqual([t["id"] for t in ts], [RUN, TID])
        self.assertEqual((ts[0]["status"], ts[0]["running"], ts[0]["rounds_max"], ts[0]["repo"]), ("running", True, 3, "x"))
        self.assertEqual((ts[1]["status"], ts[1]["rounds"], ts[1]["repo"], ts[1]["goal"]), ("failed", 2, "mission-control", "Write tests"))
        self.assertEqual(ts[1]["started"], datetime_ts("2026-11-19T12:20:32"))

    def test_stuck_when_status_old(self):
        p = self.hub / "state" / "local-agent" / "status.json"
        old = time.time() - 3600
        os.utime(p, (old, old))
        self.assertEqual(ml.list_tasks(self.hub)["tasks"][0]["status"], "stuck")

    def test_detail(self):
        d = ml.task_detail(TID, self.hub)
        self.assertEqual([r["n"] for r in d["rounds"]], [1, 2])
        self.assertEqual(d["rounds"][1], {"n": 2, "turns": 23, "seconds": 359, "check_exit": 1, "timed_out": False})
        self.assertEqual(d["check_output_tail"], "Ran 5 tests\r\nOK\r\n")
        self.assertEqual(d["reviews"][0]["notes"], ["token=[hidden] leaked"])
        live = ml.task_detail(RUN, self.hub)
        self.assertEqual((live["running"], [r["n"] for r in live["rounds"]]), (True, [1]))
        self.assertEqual(live["check_output_tail"], "....F\nFAILED (failures=1)\n")

    def test_round(self):
        r = ml.round_data(TID, 1, self.hub)
        self.assertEqual((r["id"], r["n"], r["running"], r["total"]), (TID, 1, False, 12))
        self.assertTrue(ml.round_data(RUN, 1, self.hub)["running"])

    def test_ids_validated(self):
        for bad in ("../done", "20261119-044821-C84", "20261119-044821-c84/..", "", None, "x" * 19):
            self.assertRaises(ValueError, ml.task_detail, bad, self.hub)
        self.assertRaises(ValueError, ml.round_data, TID, 0, self.hub)
        self.assertRaises(ValueError, ml.round_data, TID, 51, self.hub)

    def test_missing(self):
        self.assertRaises(LookupError, ml.task_detail, "20991231-000000-000", self.hub)
        self.assertRaises(LookupError, ml.round_data, TID, 2, self.hub)
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        self.assertEqual(ml.list_tasks(Path(empty.name)), {"tasks": []})
        self.assertRaises(LookupError, ml.morning_text, Path(empty.name))

    def test_agent_extra(self):
        self.assertEqual(ml.agent_extra(RUN + ": Run", self.hub), {"id": RUN, "rounds": 3, "check_line": "FAILED (failures=1)"})
        self.assertEqual(ml.agent_extra("no id here", self.hub), {})

    def test_serve_posts_answer_and_errors(self):
        sent = []
        post = lambda cfg, m, p, b=None: sent.append((m, p, b)) or {"slug": "loop-morning"}
        ml.serve({"key": "task:%s:" % TID, "kind": "task", "id": TID}, {}, self.hub, post)
        self.assertEqual(sent[-1][1], "/api/pc/loop")
        self.assertTrue(sent[-1][2]["ok"])
        self.assertEqual(sent[-1][2]["data"]["id"], TID)
        ml.serve({"key": "task:x:", "kind": "task", "id": "../x"}, {}, self.hub, post)
        self.assertEqual(sent[-1][2], {"key": "task:x:", "ok": False, "detail": "bad task id"})
        ml.serve({"key": "morning::", "kind": "morning"}, {}, self.hub, post)
        self.assertFalse(sent[-1][2]["ok"])
        (self.hub / "files").mkdir()
        (self.hub / "files" / "loop-morning.md").write_text("# Loop\nsk-abcdefghijklmnopqrs\n", encoding="utf-8")
        ml.serve({"key": "morning::", "kind": "morning"}, {}, self.hub, post)
        self.assertEqual(sent[-2][1], "/api/pc/docs/upload")
        self.assertEqual(sent[-2][2]["text"], "# Loop\nsk-[hidden]\n")
        self.assertEqual(sent[-1][2], {"key": "morning::", "ok": True, "data": {"slug": "loop-morning"}})


def datetime_ts(s):
    from datetime import datetime
    return datetime.fromisoformat(s).timestamp()


class Chat(unittest.TestCase):
    class Resp:
        def __init__(self, lines): self.lines = lines
        def __iter__(self): return iter(self.lines)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def sse(self, *pieces):
        out = [b": keep-alive\n"]
        for p in pieces:
            out.append(("data: " + json.dumps({"model": "qwen3-coder", "choices": [{"delta": {"content": p}}]}) + "\n").encode())
        out.append(("data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "hmm"}}]}) + "\n").encode())
        return out + [b"data: [DONE]\n", b"data: {\"choices\": [{\"delta\": {\"content\": \"late\"}}]}\n"]

    def test_stream_to_pi(self):
        calls, sent = [], []
        def post(cfg, m, p, b=None):
            sent.append((m, p, b))
            return {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 800, "timeout_s": 120} if m == "GET" else {"stop": False}
        def open_url(req, timeout):
            if "/v1/" not in req.full_url:
                raise OSError("no /slots")
            calls.append((req.full_url, req.get_header("Authorization"), json.loads(req.data)))
            return self.Resp(self.sse("Hel", "lo"))
        t = iter(range(0, 100))
        self.assertEqual(ml.chat("0123456789abcdef", {"llm_key": ""}, post, open_url, clock=lambda: float(next(t)), base="http://l"), "done")
        self.assertEqual(calls[0][0], "http://l/v1/chat/completions")
        self.assertIsNone(calls[0][1])                                           # no key configured: no header
        self.assertEqual(calls[0][2], {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 800, "stream": True})
        self.assertEqual(sent[-1], ("POST", "/api/pc/chat/0123456789abcdef", {"text": "Hello", "model": "qwen3-coder", "done": True}))

    def test_key_and_stop(self):
        sent, hdr = [], []
        def post(cfg, m, p, b=None):
            sent.append(b)
            return {"messages": [], "max_tokens": 5} if m == "GET" else {"stop": True}
        def open_url(req, timeout):
            if "/v1/" not in req.full_url:
                raise OSError("no /slots")
            hdr.append(req.get_header("Authorization"))
            return self.Resp(self.sse("a", "b", "c"))
        t = iter(range(0, 100))
        self.assertEqual(ml.chat("0123456789abcdef", {"llm_key": "k"}, post, open_url, clock=lambda: float(next(t)), base="http://l"), "stopped")
        self.assertEqual(hdr, ["Bearer k"])
        self.assertEqual(len(sent), 2)                                           # GET + the first partial, then it stops

    def test_server_down(self):
        sent = []
        def post(cfg, m, p, b=None):
            sent.append(b)
            return {"messages": []} if m == "GET" else {}
        def open_url(req, timeout):
            raise OSError("refused")
        self.assertEqual(ml.chat("0123456789abcdef", {}, post, open_url), "error")
        self.assertEqual(sent[-1], {"text": "", "error": "The local model server is not running"})

    def test_bad_rid(self):
        self.assertRaises(ValueError, ml.chat, "../x", {}, None)

    def test_trim_history_keeps_newest_and_user_start(self):
        msgs = []
        for i in range(40):
            msgs.append({"role": "user", "content": "q%d " % i + "x" * 2000})
            msgs.append({"role": "assistant", "content": "a%d " % i + "y" * 2000})
        msgs.append({"role": "user", "content": "last question"})
        for ctx in (24576, 16384):
            out = ml.trim_history(msgs, ctx, 800)
            self.assertEqual(out[-1]["content"], "last question")
            self.assertEqual(out[0]["role"], "user")
            self.assertLessEqual(sum(ml.est_tokens(m) for m in out), ctx - 800 - ml.CHAT_MARGIN)
            self.assertGreater(len(out), 10)                                     # not just the last message
            names = [m["content"][:3] for m in out[:-1]]
            self.assertEqual(names, [m["content"][:3] for m in msgs[len(msgs) - 1 - len(out) + 1:-1]])  # contiguous newest tail
        self.assertGreater(len(ml.trim_history(msgs, 24576, 800)), len(ml.trim_history(msgs, 16384, 800)))

    def test_trim_history_small_untouched_and_huge_single(self):
        small = [{"role": "user", "content": "my name is Filip"}, {"role": "assistant", "content": "ok"},
                 {"role": "user", "content": "what is my name?"}]
        self.assertEqual(ml.trim_history(small, 16384, 800), small)
        huge = ml.trim_history([{"role": "user", "content": "z" * 100000}], 16384, 800)
        self.assertEqual(len(huge), 1)
        self.assertLess(ml.est_tokens(huge[0]), 16384)

    def test_server_ctx_and_history_reaches_model(self):
        def open_url(req, timeout):
            if req.full_url.endswith("/slots"):
                return self.Json([{"id": 0, "n_ctx": 4096}])
            return self.Resp(self.sse("ok"))
        self.assertEqual(ml.server_ctx("http://l", {}, open_url), 4096)
        self.assertEqual(ml.server_ctx("http://l", {}, lambda r, timeout: (_ for _ in ()).throw(OSError())), ml.DEFAULT_CTX)
        hist = [{"role": "user", "content": "u%d " % i + "x" * 1500} if i % 2 == 0 else
                {"role": "assistant", "content": "a%d " % i + "y" * 1500} for i in range(30)] + [{"role": "user", "content": "now"}]
        sent = []
        def post(cfg, m, p, b=None):
            return {"messages": hist, "max_tokens": 800} if m == "GET" else {"stop": False}
        def open2(req, timeout):
            if req.full_url.endswith("/slots"):
                return self.Json([{"n_ctx": 8192}])
            sent.append(json.loads(req.data)["messages"])
            return self.Resp(self.sse("ok"))
        t = iter(range(0, 100))
        ml.chat("0123456789abcdef", {}, post, open2, clock=lambda: float(next(t)), base="http://l")
        self.assertEqual(sent[0][-1]["content"], "now")
        self.assertGreater(len(sent[0]), 3)                                      # history, not only the last message
        self.assertLess(len(sent[0]), len(hist))                                 # trimmed from the oldest end to the small ctx

    class Json:
        def __init__(self, obj): self.b = json.dumps(obj).encode()
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): return False


class TablesToCardsTest(unittest.TestCase):
    def test_table_becomes_list(self):
        t = "Tasks: 2\n\n| id | status | reason |\n|---|---|---|\n| a1 | failed | x y |\n| b2 | stuck | z |\n\nend"
        want = "Tasks: 2\n\n- **a1**\n  - status: failed\n  - reason: x y\n- **b2**\n  - status: stuck\n  - reason: z\n\nend"
        self.assertEqual(ml.tables_to_cards(t), want)

    def test_plain_text_unchanged(self):
        self.assertEqual(ml.tables_to_cards("a\nb\n"), "a\nb\n")


if __name__ == "__main__":
    unittest.main()
