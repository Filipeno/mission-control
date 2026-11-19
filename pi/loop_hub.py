"""Loop-agent views and the local-model chat (Pi side, 0.20).

The Pi is a relay with a small RAM cache. Nothing here is written to disk: task lists, transcripts and chat text
live only in memory (chat at most ``CHAT_KEEP`` seconds after it ends).

Flow (loop views): the app GETs a view -> if the cache is old the Pi puts a request into an in-memory queue ->
mc-pc gets it with ``loop_req`` in ``/api/pc/command`` -> ``mc_loop.py serve`` reads ``D:\\ai-hub\\loop`` (redacted)
and POSTs ``/api/pc/loop`` -> the app's next GET (it polls while ``state`` is ``loading``) shows the data.

Flow (chat): the app POSTs the messages -> the Pi checks the limits and queues ``chat_req`` -> ``mc_loop.py chat``
GETs the messages, streams the answer from the local llama-server and POSTs the partial text -> the app polls.

An mc-pc without this feature never reports ``caps``; the app then gets a clear "update mc-pc" message (409).
"""
import re
import secrets
import threading
import time

ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{3}$")
KINDS = ("tasks", "task", "round", "morning")
MAX_ROUND = 50
REQ_RETRY = 20            # a request the PC did not answer is asked again after this long
CACHE_MAX = 24            # cached views (task list + task details + rounds)
CAPS_TTL = 120            # the PC's capability list counts this long after its last report
MORNING_SLUG = "loop-morning"

CHAT_MAX_CHARS = 4000     # per message
CHAT_MAX_ASSISTANT = 20000   # model answers are cut to this, never rejected
CHAT_MAX_MSGS = 200       # the newest ones are passed on; the PC trims to the running model's context
CHAT_MAX_TOTAL = 120000   # characters of the whole conversation (RAM bound only, not the model limit)
CHAT_PER_MIN = 12
CHAT_TOKENS = 800
CHAT_TIMEOUT = 120
CHAT_KEEP = 600

OLD_PC = "Update mc-pc on the PC: it does not know the loop views and chat yet (restart it after updating)."


def valid_id(tid):
    return isinstance(tid, str) and bool(ID_RE.match(tid))


def ttl_for(kind, data):
    """How long a cached view counts as fresh. A running task refreshes every 5 s, a finished round rarely changes."""
    running = isinstance(data, dict) and data.get("running") is True
    if kind == "tasks":
        return 10
    if kind == "task":
        return 5 if running else 30
    if kind == "round":
        return 5 if running else 600
    return 0


class Busy(Exception):
    """409: one chat at a time, or the PC/mode is not ready."""


class Limited(Exception):
    """429: too many chat messages per minute."""


class LoopHub:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.queue = []          # requests for the PC (RAM only), handed out once
        self.pending = {}        # key -> time asked
        self.cache = {}          # key -> {"data", "at", "error"}
        self.caps = set()
        self.caps_at = 0.0
        self.morning = {"state": "none", "at": None, "detail": "", "slug": MORNING_SLUG}
        self.chat = None         # the one current chat: {"rid", "messages", "state", "text", ...}
        self.chat_starts = []
        self.chat_queue = []

    # ------------------------------------------------------------ PC capabilities
    def on_caps(self, caps):
        if isinstance(caps, list):
            with self.lock:
                self.caps = {str(c) for c in caps[:20]}
                self.caps_at = self.clock()

    def supports(self, cap):
        with self.lock:
            return cap in self.caps and self.clock() - self.caps_at < CAPS_TTL

    # ------------------------------------------------------------ requests to the PC
    @staticmethod
    def key(kind, tid=None, n=None):
        return "%s:%s:%s" % (kind, tid or "", n or "")

    def _ask(self, key, item, now):
        asked = self.pending.get(key)
        if asked is not None and now - asked < REQ_RETRY:
            return
        self.pending[key] = now
        self.queue = [q for q in self.queue if q["key"] != key] + [dict(item, key=key)]

    def pc_requests(self):
        """For ``/api/pc/command``: the queued loop requests, handed out once."""
        with self.lock:
            q, self.queue = self.queue[:10], self.queue[10:]
            return q

    def on_data(self, d):
        """``POST /api/pc/loop`` from mc-pc: {key, ok, data | detail}."""
        if not isinstance(d, dict):
            raise ValueError("bad body")
        key = str(d.get("key") or "")
        kind = key.split(":", 1)[0]
        if kind not in KINDS:
            raise ValueError("bad key")
        now = self.clock()
        ok = d.get("ok") is True
        with self.lock:
            self.pending.pop(key, None)
            if kind == "morning":
                self.morning.update(state="done" if ok else "failed", detail=str(d.get("detail") or "")[:200], done_at=now)
                return
            self.cache[key] = {"data": d.get("data") if ok else None, "at": now,
                               "error": "" if ok else (str(d.get("detail") or "failed")[:200])}
            if len(self.cache) > CACHE_MAX:
                for k in sorted(self.cache, key=lambda k: self.cache[k]["at"])[:len(self.cache) - CACHE_MAX]:
                    if k != key:
                        del self.cache[k]

    # ------------------------------------------------------------ views for the app
    def view(self, kind, tid=None, n=None, pc_online=True):
        """{state: ok | loading | error, detail, at, data}. Raises Busy when there is nothing to show and nobody to ask."""
        if kind in ("task", "round") and not valid_id(tid):
            raise ValueError("bad task id")
        if kind == "round" and not (isinstance(n, int) and 1 <= n <= MAX_ROUND):
            raise ValueError("bad round")
        key = self.key(kind, tid, n)
        can_ask = pc_online and self.supports("loop")
        with self.lock:
            now = self.clock()
            c = self.cache.get(key)
            fresh = c is not None and now - c["at"] < (ttl_for(kind, c["data"]) if not c["error"] else 5)
            if not fresh and can_ask:
                item = {"kind": kind}
                if tid:
                    item["id"] = tid
                if n:
                    item["n"] = n
                self._ask(key, item, now)
            loading = key in self.pending and now - self.pending[key] < REQ_RETRY * 2
        if c is None:
            if not can_ask:
                raise Busy("PC helper not connected (is the PC on?)" if not pc_online else OLD_PC)
            return {"state": "loading", "detail": "", "at": None, "data": None, "pc_online": pc_online}
        if c["error"]:
            return {"state": "loading" if loading else "error", "detail": c["error"], "at": c["at"], "data": None, "pc_online": pc_online}
        return {"state": "ok", "detail": "", "at": c["at"], "data": c["data"], "pc_online": pc_online, "refreshing": loading}

    def request_morning(self, pc_online=True):
        if not pc_online:
            raise Busy("PC helper not connected (is the PC on?)")
        if not self.supports("loop"):
            raise Busy(OLD_PC)
        with self.lock:
            now = self.clock()
            if self.morning["state"] == "requested" and now - float(self.morning["at"] or 0) < 60:
                return
            self.pending.pop(self.key("morning"), None)
            self._ask(self.key("morning"), {"kind": "morning"}, now)
            self.morning = {"state": "requested", "at": now, "detail": "", "slug": MORNING_SLUG}

    def morning_view(self):
        with self.lock:
            m = dict(self.morning)
            if m["state"] == "requested" and self.clock() - float(m["at"] or 0) > 60:
                m.update(state="failed", detail="The PC did not answer")
            return {"state": m["state"], "slug": MORNING_SLUG, "detail": m["detail"], "requested_at": m["at"]}

    # ------------------------------------------------------------ chat
    def _chat_expire(self, now):
        c = self.chat
        if not c:
            return
        if c["state"] in ("queued", "running") and now - c["at"] > CHAT_TIMEOUT + 10:
            c.update(state="error", error="No answer from the PC in time", ended=now)
            c["messages"] = None
        if c["state"] not in ("queued", "running") and now - (c.get("ended") or now) > CHAT_KEEP:
            self.chat = None

    def chat_busy(self):
        with self.lock:
            self._chat_expire(self.clock())
            return bool(self.chat and self.chat["state"] in ("queued", "running"))

    def start_chat(self, messages, mode, pc_online=True):
        """Validated chat request -> rid. ``mode`` is the Pi's view of the PC mode (localai.mode_view())."""
        if not pc_online:
            raise Busy("PC helper not connected (is the PC on?)")
        if not self.supports("chat"):
            raise Busy(OLD_PC)
        if not isinstance(mode, dict) or mode.get("mode") != "ai":
            raise Busy("Chat needs the PC in AI mode (switch it in the PC card).")
        if not isinstance(messages, list) or not messages:
            raise ValueError("no messages")
        clean = []
        for m in messages[-200:]:
            if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
                raise ValueError("bad message")
            if m["role"] == "assistant":
                m = {"role": "assistant", "content": m["content"][:CHAT_MAX_ASSISTANT]}
            elif len(m["content"]) > CHAT_MAX_CHARS:
                raise ValueError("a message is longer than %d characters" % CHAT_MAX_CHARS)
            if m["content"].strip():
                clean.append({"role": m["role"], "content": m["content"]})
        if not clean or clean[-1]["role"] != "user":
            raise ValueError("the last message must be yours")
        clean = clean[-CHAT_MAX_MSGS:]
        while len(clean) > 1 and sum(len(m["content"]) for m in clean) > CHAT_MAX_TOTAL:
            clean.pop(0)
        while clean and clean[0]["role"] != "user":
            clean.pop(0)
        with self.lock:
            now = self.clock()
            self._chat_expire(now)
            if self.chat and self.chat["state"] in ("queued", "running"):
                raise Busy("The model is still answering. Wait or press Stop.")
            self.chat_starts = [t for t in self.chat_starts if now - t < 60]
            if len(self.chat_starts) >= CHAT_PER_MIN:
                raise Limited("Too many messages. Wait a minute.")
            self.chat_starts.append(now)
            rid = secrets.token_hex(8)
            self.chat = {"rid": rid, "messages": clean, "state": "queued", "text": "", "model": None, "error": "",
                         "at": now, "updated": now, "ended": None}
            self.chat_queue.append({"rid": rid})
            return rid

    def pc_chat_requests(self):
        with self.lock:
            q, self.chat_queue = self.chat_queue, []
            return q

    def _chat(self, rid):
        if not isinstance(rid, str) or not re.fullmatch(r"[0-9a-f]{16}", rid):
            raise ValueError("bad chat id")
        c = self.chat
        if not c or c["rid"] != rid:
            raise LookupError("no such chat")
        return c

    def pc_chat_get(self, rid):
        """The messages for mc-pc, once. They are dropped from RAM as soon as the PC has them."""
        with self.lock:
            self._chat_expire(self.clock())
            c = self._chat(rid)
            if c["state"] != "queued" or c["messages"] is None:
                raise LookupError("chat is not waiting")
            msgs, c["messages"] = c["messages"], None
            c.update(state="running", updated=self.clock())
            return {"rid": rid, "messages": msgs, "max_tokens": CHAT_TOKENS, "timeout_s": CHAT_TIMEOUT}

    def pc_chat_update(self, rid, d):
        """Partial / final text from mc-pc. Returns {"stop": bool} so the PC can end the stream."""
        if not isinstance(d, dict):
            raise ValueError("bad body")
        with self.lock:
            now = self.clock()
            c = self._chat(rid)
            if c["state"] != "running":
                return {"stop": True}
            c["text"] = str(d.get("text") or "")[:20000]
            if d.get("model"):
                c["model"] = str(d["model"])[:60]
            c["updated"] = now
            if d.get("error"):
                c.update(state="error", error=str(d["error"])[:200], ended=now)
            elif d.get("done") is True:
                c.update(state="done", ended=now)
            return {"stop": False}

    def chat_view(self, rid):
        with self.lock:
            self._chat_expire(self.clock())
            c = self._chat(rid)
            return {"rid": rid, "state": c["state"], "text": c["text"], "model": c["model"], "error": c["error"]}

    def stop_chat(self, rid):
        with self.lock:
            c = self._chat(rid)
            if c["state"] == "queued":
                c.update(state="stopped", ended=self.clock(), messages=None)
                self.chat_queue = [q for q in self.chat_queue if q["rid"] != rid]
            elif c["state"] == "running":          # the PC's next update gets {"stop": true} and ends the stream
                c.update(state="stopped", ended=self.clock())

    def chat_status(self, mode, pc_online=True):
        """For the Local AI card: may the app offer the chat, and why not."""
        if not pc_online:
            return {"available": False, "reason": "The PC is off or its helper is not connected.", "busy": False}
        if not self.supports("chat"):
            return {"available": False, "reason": OLD_PC, "busy": False}
        if not isinstance(mode, dict) or mode.get("mode") != "ai":
            return {"available": False, "reason": "Chat needs the PC in AI mode.", "busy": False}
        return {"available": True, "reason": "", "busy": self.chat_busy()}
