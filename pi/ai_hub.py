"""Stage 11b on the Pi: helper questions and the daily digest.

Questions: mc-pc reports the open helper questions (``QUESTION id=...`` jobs) with every report. A new one
raises one notification. Filip's typed answer waits as a PC inbox item (``helper-answer``); the card shows
"answered" once mc-pc confirms that ``ask.ps1 -AnswerId`` was started.

Digest: mc-pc computes the digest of the day when the Pi asks for it (``want_digest``, shortly before the
set time). At the set time the Pi adds the "Waiting for you" part, stores the result as a Doc and notifies once.
"""
import re
import threading
import time
from datetime import datetime

ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9]+$")
MAX_ANSWER = 1000
KEEP_ANSWERED_S = 24 * 3600
LEAD_S = 30 * 60            # the PC starts computing this long before the set time
GRACE_S = 3 * 3600          # a digest still goes out this long after the set time (PC was off, etc.)
REFRESH_S = 15 * 60
MAX_DIGEST = 20000


def _s(v, n):
    return str(v if v is not None else "")[:n]


def _minutes(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


class AiHub:
    def __init__(self, load_json, save_json, deliver, claude, todos, docs, settings, in_quiet, clock=time.time):
        self.load, self.save, self.deliver = load_json, save_json, deliver
        self.claude, self.todos, self.docs = claude, todos, docs
        self.settings, self.in_quiet, self.clock = settings, in_quiet, clock       # settings: callable -> dict
        self.lock = threading.Lock()
        self.q = load_json("ai-questions.json", {}) or {}
        self.notified = set(load_json("ai-questions-notified.json", []) or [])
        self.digest = load_json("ai-digest.json", None)
        self.fired = (load_json("ai-digest-fired.json", {}) or {}).get("date", "")
        self.force = False
        self.last_failed = {}

    # ------------------------------------------------------------ helper questions
    def _notify_ok(self):
        st = self.settings()
        return not st.get("muted") and (st.get("kinds") or {}).get("claude", True)

    def on_pc_questions(self, rows):
        if not isinstance(rows, list):
            return
        now = self.clock()
        seen = set()
        new = []
        with self.lock:
            for r in rows[:50]:
                if not isinstance(r, dict) or not ID_RE.match(str(r.get("id") or "")):
                    continue
                qid = r["id"]
                seen.add(qid)
                cur = self.q.get(qid)
                if cur is None:
                    cur = self.q[qid] = {"id": qid, "helper": _s(r.get("helper"), 20), "question": _s(r.get("question"), 600),
                                         "task": _s(r.get("task"), 240), "at": float(r.get("at") or now),
                                         "state": "open", "answered_at": None, "error": ""}
                    if qid not in self.notified:
                        new.append(cur)
            for qid, cur in self.q.items():
                if qid not in seen and cur["state"] in ("open", "sent"):
                    cur["state"], cur["answered_at"], cur["error"] = "answered", now, ""     # gone from the inbox: answered
            for qid in [k for k, c in self.q.items() if c["state"] == "answered" and now - (c["answered_at"] or now) > KEEP_ANSWERED_S]:
                del self.q[qid]
            for cur in new:
                self.notified.add(cur["id"])
            self.notified &= set(self.q) | {c["id"] for c in new}
            self._save_q()
        for cur in new:
            if self._notify_ok():
                self.deliver({"at": now, "kind": "helper-question", "cat": "claude", "title": "Helper question waiting",
                              "body": ("%s: %s" % (cur["helper"], cur["question"]))[:200], "group": "hq:" + cur["id"],
                              "quiet": bool(self.in_quiet()), "actions": [], "tab": 1})

    def _save_q(self):
        self.save("ai-questions.json", self.q)
        self.save("ai-questions-notified.json", sorted(self.notified))

    def answer(self, qid, text):
        """Queue the answer for mc-pc. A second answer for the same question is ignored (duplicate)."""
        qid, text = str(qid or ""), " ".join(str(text or "").split())
        if not ID_RE.match(qid):
            raise ValueError("bad question id")
        if not text or len(text) > MAX_ANSWER:
            raise ValueError("answer must be 1-%d characters" % MAX_ANSWER)
        with self.lock:
            cur = self.q.get(qid)
            if cur is None:
                raise LookupError("question not found")
            if cur["state"] != "open":
                return {"ok": True, "duplicate": True, "state": cur["state"]}
            cur["state"], cur["error"] = "sent", ""
            self._save_q()
        self.claude.enqueue({"key": "hq-" + qid, "kind": "helper-answer", "id": qid, "text": text, "at": self.clock()})
        return {"ok": True, "duplicate": False, "state": "sent"}

    def on_result(self, d):
        key = str((d or {}).get("key") or "")
        if not key.startswith("hq-"):
            return
        with self.lock:
            cur = self.q.get(key[3:])
            if not cur or cur["state"] != "sent":
                return
            if d.get("ok") is True:
                cur["state"], cur["answered_at"], cur["error"] = "answered", self.clock(), ""
            else:
                cur["state"], cur["error"] = "open", _s(d.get("detail"), 200)
            self._save_q()

    def questions(self):
        with self.lock:
            rows = sorted(self.q.values(), key=lambda c: c["at"])
            return [dict(c) for c in rows]

    def open_questions(self):
        return [c for c in self.questions() if c["state"] in ("open", "sent")]

    # ------------------------------------------------------------ daily digest
    def _today(self):
        return datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d")

    def _due(self, st, now_dt):
        """Seconds since the set time (negative = before it), or None when the digest is off or the time is bad."""
        if not st.get("digest_on"):
            return None
        try:
            t = _minutes(st.get("digest_time", "20:00"))
        except ValueError:
            return None
        return (now_dt.hour * 60 + now_dt.minute - t) * 60 + now_dt.second

    def want_digest(self):
        """True when mc-pc should compute and send the digest now."""
        now = self.clock()
        if self.force:
            return True
        due = self._due(self.settings(), datetime.fromtimestamp(now))
        if due is None or self.fired == self._today() or not -LEAD_S <= due <= GRACE_S:
            return False
        d = self.digest
        return not (d and d.get("date") == self._today() and now - d.get("at", 0) < REFRESH_S)

    def on_digest(self, d):
        if not isinstance(d, dict) or not isinstance(d.get("text"), str) or len(d["text"]) > MAX_DIGEST \
                or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(d.get("date") or "")):
            raise ValueError("bad digest")
        counts = d.get("counts") if isinstance(d.get("counts"), dict) else {}
        self.digest = {"date": d["date"], "text": d["text"], "summary": _s(d.get("summary"), 200), "at": self.clock(),
                       "counts": {k: int(counts.get(k) or 0) for k in ("tasks", "commits", "releases")}}
        self.save("ai-digest.json", self.digest)
        self.tick()

    def request_now(self):
        """Phone button: ask mc-pc for a fresh digest and send it as soon as it arrives."""
        self.force = True

    def waiting_lines(self):
        out = []
        todos = self.todos.view().get("open") or []
        for t in todos[:8]:
            out.append("- To-do: %s" % _s(t.get("title"), 100))
        if len(todos) > 8:
            out.append("- …and %d more to-dos" % (len(todos) - 8))
        for a in (self.claude.view().get("approvals") or [])[:8]:
            out.append("- Approval: %s" % _s(a.get("title"), 100))
        for q in self.open_questions()[:8]:
            out.append("- Helper question (%s): %s" % (q["helper"], _s(q["question"], 100)))
        return out

    def tick(self):
        """Send the digest once per day, at or after the set time (or right away after 'send now')."""
        now = self.clock()
        d = self.digest
        if not d or d.get("date") != self._today():
            return False
        st = self.settings()
        due = self._due(st, datetime.fromtimestamp(now))
        with self.lock:
            forced = self.force
            if forced and now - d.get("at", 0) > 120:
                return False                                   # wait for the fresh one the PC is computing
            if not forced and not (due is not None and 0 <= due <= GRACE_S and self.fired != d["date"]):
                return False
            if forced:
                self.force = False                             # a test send does not use up the evening's digest
            else:
                self.fired = d["date"]
                self.save("ai-digest-fired.json", {"date": self.fired})
        waiting = self.waiting_lines()
        text = d["text"] + "\n## Waiting for you (%d)\n%s\n" % (len(waiting), "\n".join(waiting) or "- Nothing.")
        slug = None
        try:
            slug = self.docs.upload("doc", "daily-digest-%s.md" % d["date"], text, title="Daily digest %s" % d["date"])["slug"]
        except (ValueError, OSError):
            pass
        if self._notify_ok():
            body = d.get("summary") or "Digest ready"
            if waiting:
                body += " · %d waiting for you" % len(waiting)
            self.deliver({"at": now, "kind": "digest", "cat": "claude", "title": "Daily digest", "body": body[:300],
                          "group": "digest:" + d["date"], "quiet": bool(self.in_quiet()), "actions": [], "tab": 2})
        return slug or True

    def run(self):
        while True:
            try:
                self.tick()
            except Exception as e:      # the loop must survive anything
                print("digest tick failed: %s" % e, flush=True)
            time.sleep(30)

    def digest_view(self):
        d = self.digest or {}
        return {"on": bool(self.settings().get("digest_on")), "time": self.settings().get("digest_time"),
                "last_date": d.get("date"), "fired_today": self.fired == self._today(), "pending": bool(self.force)}
