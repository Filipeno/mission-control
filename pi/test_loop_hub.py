import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loop_hub as lh

TID = "20261119-044821-c84"
AI = {"mode": "ai", "model": "qwen"}


class Clock:
    t = 1000.0
    def __call__(self): return self.t


class Views(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.clock.t = 1000.0
        self.h = lh.LoopHub(self.clock)
        self.h.on_caps(["loop", "chat"])

    def test_first_view_asks_the_pc_once(self):
        v = self.h.view("tasks")
        self.assertEqual((v["state"], v["data"]), ("loading", None))
        self.assertEqual(self.h.pc_requests(), [{"kind": "tasks", "key": "tasks::"}])
        self.h.view("tasks")
        self.assertEqual(self.h.pc_requests(), [])                     # still pending: not asked again
        self.clock.t += lh.REQ_RETRY + 1
        self.h.view("tasks")
        self.assertEqual(len(self.h.pc_requests()), 1)                 # no answer: asked again

    def test_request_shapes(self):
        self.h.view("task", TID)
        self.h.view("round", TID, 2)
        self.assertEqual(self.h.pc_requests(), [{"kind": "task", "id": TID, "key": "task:%s:" % TID},
                                                {"kind": "round", "id": TID, "n": 2, "key": "round:%s:2" % TID}])

    def test_answer_cached_until_ttl(self):
        self.h.view("task", TID)
        self.h.pc_requests()
        self.h.on_data({"key": "task:%s:" % TID, "ok": True, "data": {"id": TID, "running": False}})
        v = self.h.view("task", TID)
        self.assertEqual((v["state"], v["data"]["id"]), ("ok", TID))
        self.assertEqual(self.h.pc_requests(), [])
        self.clock.t += 31
        v = self.h.view("task", TID)
        self.assertEqual(v["state"], "ok")                             # old data is shown while it refreshes
        self.assertTrue(v["refreshing"])
        self.assertEqual(len(self.h.pc_requests()), 1)

    def test_running_task_refreshes_every_5_s(self):
        self.h.on_data({"key": "round:%s:1" % TID, "ok": True, "data": {"running": True, "items": []}})
        self.clock.t += 4
        self.h.view("round", TID, 1)
        self.assertEqual(self.h.pc_requests(), [])
        self.clock.t += 2
        self.h.view("round", TID, 1)
        self.assertEqual(len(self.h.pc_requests()), 1)

    def test_error_from_pc(self):
        self.h.view("task", TID)
        self.h.on_data({"key": "task:%s:" % TID, "ok": False, "detail": "task not found"})
        v = self.h.view("task", TID)
        self.assertEqual((v["state"], v["detail"]), ("error", "task not found"))

    def test_bad_input(self):
        for bad in ("../x", "20261119-044821-C84", None, TID + "/.."):
            self.assertRaises(ValueError, self.h.view, "task", bad)
        self.assertRaises(ValueError, self.h.view, "round", TID, 0)
        self.assertRaises(ValueError, self.h.view, "round", TID, 51)
        self.assertRaises(ValueError, self.h.on_data, {"key": "evil::", "ok": True})

    def test_pc_offline_or_old(self):
        self.assertRaises(lh.Busy, self.h.view, "tasks", pc_online=False)
        old = lh.LoopHub(self.clock)                                   # mc-pc never reported caps
        with self.assertRaises(lh.Busy) as e:
            old.view("tasks")
        self.assertIn("Update mc-pc", str(e.exception))
        self.assertEqual(old.pc_requests(), [])
        self.clock.t += lh.CAPS_TTL + 1                                # caps expire with the PC's reports
        self.assertFalse(self.h.supports("loop"))

    def test_offline_still_shows_cache(self):
        self.h.on_data({"key": "tasks::", "ok": True, "data": {"tasks": []}})
        self.clock.t += 60
        v = self.h.view("tasks", pc_online=False)
        self.assertEqual((v["state"], v["pc_online"]), ("ok", False))
        self.assertEqual(self.h.pc_requests(), [])

    def test_cache_bounded(self):
        for i in range(lh.CACHE_MAX + 10):
            self.clock.t += 1
            self.h.on_data({"key": "round:%s:%d" % (TID, i % 50 + 1), "ok": True, "data": {}})
            self.h.on_data({"key": "task:2026111%d-000000-000:" % (i % 10), "ok": True, "data": {}})
        self.assertLessEqual(len(self.h.cache), lh.CACHE_MAX)

    def test_morning(self):
        self.h.request_morning()
        self.assertEqual(self.h.pc_requests(), [{"kind": "morning", "key": "morning::"}])
        self.assertEqual(self.h.morning_view()["state"], "requested")
        self.h.request_morning()                                       # a second tap while waiting: no new request
        self.assertEqual(self.h.pc_requests(), [])
        self.h.on_data({"key": "morning::", "ok": True, "data": {"slug": "loop-morning"}})
        self.assertEqual(self.h.morning_view(), {"state": "done", "slug": "loop-morning", "detail": "", "requested_at": 1000.0})
        self.h.request_morning()
        self.h.on_data({"key": "morning::", "ok": False, "detail": "loop-morning.md does not exist yet"})
        self.assertEqual(self.h.morning_view()["state"], "failed")
        self.assertRaises(lh.Busy, self.h.request_morning, False)


class Chat(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.clock.t = 1000.0
        self.h = lh.LoopHub(self.clock)
        self.h.on_caps(["loop", "chat"])

    def start(self, text="hi", mode=AI):
        return self.h.start_chat([{"role": "user", "content": text}], mode)

    def test_flow(self):
        rid = self.start()
        self.assertEqual(self.h.pc_chat_requests(), [{"rid": rid}])
        self.assertEqual(self.h.chat_view(rid)["state"], "queued")
        got = self.h.pc_chat_get(rid)
        self.assertEqual(got, {"rid": rid, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 800, "timeout_s": 120})
        self.assertIsNone(self.h.chat["messages"])                    # the text left the Pi's RAM
        self.assertRaises(LookupError, self.h.pc_chat_get, rid)       # handed out once
        self.assertEqual(self.h.pc_chat_update(rid, {"text": "Hel", "model": "qwen3"}), {"stop": False})
        self.assertEqual(self.h.chat_view(rid), {"rid": rid, "state": "running", "text": "Hel", "model": "qwen3", "error": ""})
        self.h.pc_chat_update(rid, {"text": "Hello", "done": True})
        self.assertEqual(self.h.chat_view(rid)["state"], "done")
        self.clock.t += lh.CHAT_KEEP + 1
        self.assertRaises(LookupError, self.h.chat_view, rid)         # forgotten after 10 min

    def test_one_at_a_time(self):
        self.start()
        with self.assertRaises(lh.Busy):
            self.start()
        self.assertTrue(self.h.chat_busy())

    def test_stop_while_running(self):
        rid = self.start()
        self.h.pc_chat_requests()
        self.h.pc_chat_get(rid)
        self.h.stop_chat(rid)
        self.assertEqual(self.h.chat_view(rid)["state"], "stopped")
        self.assertEqual(self.h.pc_chat_update(rid, {"text": "x"}), {"stop": True})
        self.assertFalse(self.h.chat_busy())                          # free again at once

    def test_stop_before_the_pc_took_it(self):
        rid = self.start()
        self.h.stop_chat(rid)
        self.assertEqual(self.h.pc_chat_requests(), [])               # dropped from the PC queue
        self.assertIsNone(self.h.chat["messages"])
        self.assertRaises(LookupError, self.h.pc_chat_get, rid)

    def test_rate_limit(self):
        for i in range(lh.CHAT_PER_MIN):
            rid = self.start()
            self.h.pc_chat_get(rid)
            self.h.pc_chat_update(rid, {"text": "ok", "done": True})
        self.assertRaises(lh.Limited, self.start)
        self.clock.t += 61
        self.start()

    def test_limits_and_validation(self):
        self.assertRaises(ValueError, self.start, "x" * (lh.CHAT_MAX_CHARS + 1))
        self.assertRaises(ValueError, self.h.start_chat, [], AI)
        self.assertRaises(ValueError, self.h.start_chat, [{"role": "system", "content": "x"}], AI)
        self.assertRaises(ValueError, self.h.start_chat, [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}], AI)
        self.assertRaises(ValueError, self.h.start_chat, "hi", AI)
        long = [{"role": "user" if i % 2 == 0 else "assistant", "content": "m%d " % i + "z" * 3000} for i in range(31)]
        rid = self.h.start_chat(long, AI)
        msgs = self.h.pc_chat_get(rid)["messages"]
        self.assertLessEqual(len(msgs), lh.CHAT_MAX_MSGS)
        self.assertLessEqual(sum(len(m["content"]) for m in msgs), lh.CHAT_MAX_TOTAL)
        self.assertEqual((msgs[0]["role"], msgs[-1]["content"][:4]), ("user", "m30 "))

    def test_needs_ai_mode_pc_and_new_mc_pc(self):
        with self.assertRaises(lh.Busy) as e:
            self.start(mode={"mode": "gaming"})
        self.assertIn("AI mode", str(e.exception))
        self.assertRaises(lh.Busy, self.h.start_chat, [{"role": "user", "content": "x"}], AI, False)
        old = lh.LoopHub(self.clock)
        with self.assertRaises(lh.Busy) as e:
            old.start_chat([{"role": "user", "content": "x"}], AI)
        self.assertIn("Update mc-pc", str(e.exception))
        self.assertEqual(self.h.chat_status({"mode": "normal"}), {"available": False, "reason": "Chat needs the PC in AI mode.", "busy": False})
        self.assertEqual(self.h.chat_status(AI), {"available": True, "reason": "", "busy": False})

    def test_timeout_frees_the_slot(self):
        rid = self.start()
        self.clock.t += lh.CHAT_TIMEOUT + 11
        v = self.h.chat_view(rid)
        self.assertEqual((v["state"], v["error"]), ("error", "No answer from the PC in time"))
        self.h.on_caps(["loop", "chat"])                               # the PC's next report
        self.start()

    def test_bad_rid(self):
        self.assertRaises(ValueError, self.h.chat_view, "../../x")
        self.assertRaises(LookupError, self.h.chat_view, "0" * 16)


if __name__ == "__main__":
    unittest.main()
