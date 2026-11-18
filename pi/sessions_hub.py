"""Live Claude sessions on the Pi (Claude tab v2): list, activity of the open session, phone-gate requests,
"start a new session" proposals, and Filip's signed answers and messages for the PC helper.

mc-pc posts a snapshot every ~5 s (POST /api/pc/sessions). Activity rows of the session open on the phone
are kept in memory only (never written to disk). Everything Filip sends is signed with the phone's
fingerprint-locked key (same key and check as approvals) and queued for mc-pc in ClaudeHub's PC inbox.
Signed strings:
  gate answer    "gate|<gid>|<decision>|<payload>|<ts>"      decision: allow | deny | answer
  message        "msg|<sessionId>|<text>|<ts>"
  start proposal "start|<key>|<ts>"
  gate settings  "gate-config|<auto>|<enabled 0/1>|<ts>"
  doc start      "docstart|<doc slug>|<ts>"   (types a request into the boss session, which starts a session for a doc)
App cards (stage 11a-1): the Claude desktop app's own approval cards come in the snapshot as gates of kind "appcard"
(id "ac-<request id>"). Allow needs the signature like every gate; Deny is accepted unsigned (one tap), only as deny.
Never "always". mc-pc clicks the card and reports clicked / refused / "waiting for unlock" (held up to 8 h).
"""
import json
import re
import secrets
import threading
import time

SID_RE = re.compile(r"^[0-9a-f-]{36}$")
GID_RE = re.compile(r"^(?:[0-9]{8}-[0-9]{6}-[0-9a-f]{4}|ac-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
CARD_PREFIX = "ac-"
SHOT_MAX = 12           # app card screenshots kept in memory (never written to disk)
KEY_RE = re.compile(r"^(task_[0-9a-f]{6,}|offer-[A-Za-z0-9_-]{4,20})$")
WATCH_TTL = 30          # mc-pc sends activity of the open session while the phone asked within this time
FRESH = 30              # a snapshot older than this = PC helper not reporting
AUTO = ("none", "readonly")
# The boss session: the main Claude Desktop session of Filip's AI team. A side session (one a boss started for a
# single job) runs in a project folder, so only a session whose folder is exactly one of these counts.
BOSS_DIRS = ("d:\\projekty", "d:\\ai-hub")


class SessionsHub:
    def __init__(self, claude, load_json, save_json, deliver):
        self.claude = claude                        # ClaudeHub: signature keys + PC inbox queue
        self.load, self.save, self.deliver = load_json, save_json, deliver
        self.lock = threading.Lock()
        self.snap = {"sessions": [], "gates": [], "proposals": [], "at": 0}
        self.rows = {}                              # sessionId -> {"rows": [...], "at": t}
        self.watch_id, self.watch_at = "", 0.0
        self.results = {}                           # queue key -> {"ok", "detail", "at", "sid", "text", "kind"}
        self.seen = set(self.load("sessions-seen.json", []))     # gate ids / proposal keys already notified
        self.hidden = set(self.load("proposals-hidden.json", []))
        self.config = self.load("gate-config.json", {"auto": "readonly", "enabled": True})
        self.card_answers = {}                      # app card gate id -> queue key of Filip's answer (its result = card status)
        self.card_shots = {}                        # app card gate id -> (jpeg bytes, at)

    # ------------------------------------------------------------ from mc-pc

    def on_snapshot(self, d: dict) -> None:
        sessions = [_clean_session(s) for s in (d.get("sessions") or [])[:60] if isinstance(s, dict)]
        gates = [_clean_gate(g) for g in (d.get("gates") or [])[:20] if isinstance(g, dict) and GID_RE.match(str(g.get("id", "")))]
        ids = [g["id"] for g in gates]
        gates = [g for g in gates if ids.count(g["id"]) == 1]      # a duplicated id is never shown or answered
        props = [_clean_prop(p) for p in (d.get("proposals") or [])[:30] if isinstance(p, dict) and KEY_RE.match(str(p.get("key", "")))]
        titles = {s["id"]: s["title"] for s in sessions}
        notify = []
        with self.lock:
            for g in gates:
                g["session"] = titles.get(g.get("session_id")) or g.get("card_title") or "Claude"
                if g["id"] not in self.seen:
                    self.seen.add(g["id"])
                    notify.append(("gate", g))
            for p in props:
                if p["key"] not in self.seen and p["key"] not in self.hidden:
                    self.seen.add(p["key"])
                    notify.append(("proposal", p))
            self.snap = {"sessions": sessions, "gates": gates, "proposals": props, "at": time.time()}
            w = d.get("watch")
            if isinstance(w, dict) and SID_RE.match(str(w.get("id", ""))):
                self.rows[w["id"]] = {"rows": [_clean_row(r) for r in (w.get("rows") or [])[-100:] if isinstance(r, dict)],
                                      "at": time.time(), "gone": bool(w.get("gone"))}
            for k in [k for k, v in self.rows.items() if time.time() - v["at"] > 600]:
                del self.rows[k]                    # nothing about a chat stays on the Pi for long
            if notify:
                self.seen = set(list(self.seen)[-500:])
                self.save("sessions-seen.json", sorted(self.seen))
        for kind, x in notify:
            if kind == "gate":
                if x["kind"] == "question":
                    qs = (x.get("input") or {}).get("questions") or [{}]
                    title, body = f"{x['session']} asks", str(qs[0].get("question") or "a question")[:200]
                elif x["kind"] == "plan":
                    title, body = f"{x['session']}: plan ready", "Tap to read the plan, comment and approve or reject it."
                elif x["kind"] == "appcard":
                    title, body = f"{x['session']}: app card waiting", x["summary"][:200]
                else:
                    title, body = f"{x['session']} needs permission", x["summary"][:200]
            else:
                title, body = f"{x['session']} proposes a session", x["title"]
            ev = {"at": time.time(), "kind": "claude-" + kind, "cat": "claude", "title": title, "body": body,
                  "group": f"{kind}:{x.get('id') or x.get('key')}", "quiet": False, "actions": [],
                  "sid": x.get("session_id", "")}
            if kind == "gate":
                ev.update(gate=x["id"], gkind=x["kind"], summary=x["summary"][:200])
                if x["kind"] == "plan" and x.get("doc"):
                    ev.update(doc=x["doc"], tab=2, sid="")          # the tap opens the plan in the Docs tab
            self.deliver(ev)

    def on_result(self, d: dict) -> None:
        key = str(d.get("key", ""))[:40]
        with self.lock:
            r = self.results.get(key)
            if r is None:
                return
            ok = d.get("ok")
            r.update(ok=ok if isinstance(ok, bool) else None, detail=str(d.get("detail", ""))[:200], at=time.time())

    def pc_watch(self) -> str:
        with self.lock:
            return self.watch_id if time.time() - self.watch_at < WATCH_TTL else ""

    # ------------------------------------------------------------ for the app

    def list_view(self) -> dict:
        with self.lock:
            s = self.snap
            return {"sessions": s["sessions"], "gates": [self._card_extras(_gate_brief(g)) for g in s["gates"]],
                    "proposals": [p for p in s["proposals"] if p["key"] not in self.hidden],
                    "at": s["at"], "fresh": time.time() - s["at"] < FRESH, "gate_config": dict(self.config)}

    def session_view(self, sid: str) -> dict:
        if sid.startswith(CARD_PREFIX) and GID_RE.match(sid):      # an app card whose session is not in the live list
            g = self.card_gate(sid)
            return {"session": None, "rows": [], "rows_at": None, "gone": False, "gates": [g] if g else [], "proposals": [],
                    "outbox": [], "fresh": time.time() - self.snap["at"] < FRESH}
        if not SID_RE.match(sid):
            raise ValueError("bad session id")
        with self.lock:
            self.watch_id, self.watch_at = sid, time.time()
            s = next((x for x in self.snap["sessions"] if x["id"] == sid), None)
            rows = self.rows.get(sid) or {}
            outbox = sorted(({"key": k, **{f: v[f] for f in ("ok", "detail", "at", "text", "kind")}}
                             for k, v in self.results.items() if v.get("sid") == sid), key=lambda r: -r["at"])[:5]
            return {"session": s, "rows": rows.get("rows", []), "rows_at": rows.get("at"), "gone": rows.get("gone", False),
                    "gates": [self._card_extras(dict(g)) for g in self.snap["gates"] if g.get("session_id") == sid],
                    "proposals": [p for p in self.snap["proposals"] if p["session_id"] == sid and p["key"] not in self.hidden],
                    "outbox": outbox, "fresh": time.time() - self.snap["at"] < FRESH}

    def answer_gate(self, token_hash: str, gid: str, d: dict) -> dict:
        decision = str(d.get("decision", ""))
        payload = str(d.get("payload") or "")[:8000]
        if decision not in ("allow", "deny", "answer") or not GID_RE.match(gid):
            raise ValueError("bad answer")
        if gid.startswith(CARD_PREFIX):
            return self._answer_card(token_hash, gid, decision, payload, d)
        self._verify(token_hash, f"gate|{gid}|{decision}|{payload}", d)
        with self.lock:
            g = next((x for x in self.snap["gates"] if x["id"] == gid), None)
            if not g:
                raise LookupError("this request is no longer open (answered at the PC?)")
            item = {"key": secrets.token_hex(8), "kind": "gate", "id": gid, "decision": decision, "at": time.time()}
            if decision == "answer":
                if g["kind"] != "question":
                    raise ValueError("not a question")
                try:
                    answers = json.loads(payload)
                except ValueError:
                    raise ValueError("bad answers")
                if not isinstance(answers, dict) or not answers:
                    raise ValueError("bad answers")
                item["answers"] = {str(k)[:500]: str(v)[:2000] for k, v in list(answers.items())[:8]}
            else:
                item["text"] = payload[:6000]              # a rejected plan carries Filip's line comments
            self.results[item["key"]] = {"ok": None, "detail": "sent to the PC", "at": time.time(),
                                         "sid": g.get("session_id"), "text": decision, "kind": "gate"}
            self._trim_results()
        self.claude.enqueue(item)
        return {"ok": True, "key": item["key"]}

    def _answer_card(self, token_hash: str, gid: str, decision: str, payload: str, d: dict) -> dict:
        """An app card: Allow only with a valid signature; Deny one tap (a signature, if sent, must still be valid)."""
        if decision not in ("allow", "deny") or payload:
            raise ValueError("an app card takes only Allow or Deny")
        if decision == "allow" or d.get("sig"):
            self._verify(token_hash, f"gate|{gid}|{decision}|", d)
        with self.lock:
            g = next((x for x in self.snap["gates"] if x["id"] == gid), None)
            if not g or g.get("kind") != "appcard":
                raise LookupError("this card is no longer open (answered at the PC?)")
            if not g.get("answerable"):
                raise ValueError("this kind of app card can only be answered at the PC")
            prev = self.results.get(self.card_answers.get(gid, ""))
            if prev and prev.get("ok") is not False:
                raise LookupError("this card was already answered from the phone")
            item = {"key": secrets.token_hex(8), "kind": "appcard", "id": gid, "card": g["card"], "decision": decision,
                    "title": g.get("card_title", ""), "tool": g["tool"], "at": time.time()}
            self.results[item["key"]] = {"ok": None, "detail": "sent to the PC", "at": time.time(),
                                         "sid": g.get("session_id"), "text": decision, "kind": "appcard", "gid": gid}
            self.card_answers[gid] = item["key"]
            self._trim_results()
        self.claude.enqueue(item)
        return {"ok": True, "key": item["key"]}

    def card_answer(self, gid: str):
        """Status of Filip's answer to an app card: {decision, ok, detail, at} or None. Call with the lock held."""
        r = self.results.get(self.card_answers.get(gid, ""))
        return {"decision": r["text"], "ok": r["ok"], "detail": r["detail"], "at": r["at"]} if r else None

    def save_card_shot(self, gid: str, data: bytes) -> None:
        if not GID_RE.match(gid) or not gid.startswith(CARD_PREFIX):
            raise ValueError("bad app card id")
        if not data.startswith(b"\xff\xd8") or len(data) > 4 * 1024 * 1024:
            raise ValueError("not a JPEG (or too big)")
        with self.lock:
            self.card_shots[gid] = (data, time.time())
            for k in sorted(self.card_shots, key=lambda k: self.card_shots[k][1])[:-SHOT_MAX]:
                del self.card_shots[k]

    def card_shot(self, gid: str):
        with self.lock:
            x = self.card_shots.get(gid)
            return x[0] if x else None

    def send_message(self, token_hash: str, sid: str, d: dict) -> dict:
        text = str(d.get("text") or "").strip()[:4000]
        if not SID_RE.match(sid) or not text:
            raise ValueError("empty message")
        self._verify(token_hash, f"msg|{sid}|{text}", d)
        return self._type(sid, text, "message")

    def start_proposal(self, token_hash: str, key: str, d: dict) -> dict:
        if not KEY_RE.match(key) or key.startswith("offer-"):
            raise ValueError("this card can only be answered in Claude Desktop or the Claude app")
        self._verify(token_hash, f"start|{key}", d)
        with self.lock:
            p = next((x for x in self.snap["proposals"] if x["key"] == key), None)
        if not p:
            raise LookupError("this proposal is gone (started or withdrawn)")
        text = f'Start the proposed session "{p["title"]}" (proposal {key}). (Sent from Mission Control on my phone.)'
        r = self._type(p["session_id"], text, "start")
        with self.lock:
            self.hidden.add(key)
            self.save("proposals-hidden.json", sorted(self.hidden)[-300:])
        return r

    def hide_proposal(self, key: str) -> None:
        with self.lock:
            self.hidden.add(key)
            self.save("proposals-hidden.json", sorted(self.hidden)[-300:])

    def set_config(self, token_hash: str, d: dict) -> dict:
        auto, enabled = str(d.get("auto", "")), bool(d.get("enabled", True))
        if auto not in AUTO:
            raise ValueError("bad auto setting")
        self._verify(token_hash, f"gate-config|{auto}|{int(enabled)}", d)
        with self.lock:
            self.config = {"auto": auto, "enabled": enabled}
            self.save("gate-config.json", self.config)
        self.claude.enqueue({"key": secrets.token_hex(8), "kind": "gate-config", "auto": auto, "enabled": enabled, "at": time.time()})
        return dict(self.config)

    def sessions_snapshot(self) -> tuple:
        """(live sessions, snapshot is fresh)"""
        with self.lock:
            return list(self.snap["sessions"]), time.time() - self.snap["at"] < FRESH

    def gate_for_doc(self, doc: str):
        """The open plan request that belongs to this plan Doc, if any."""
        with self.lock:
            g = next((x for x in self.snap["gates"] if x.get("kind") == "plan" and x.get("doc") == doc), None)
            return {"id": g["id"], "session_id": g.get("session_id", ""), "session": g.get("session", ""), "created": g.get("created", 0)} if g else None

    def gate_docs(self) -> set:
        with self.lock:
            return {g["doc"] for g in self.snap["gates"] if g.get("kind") == "plan" and g.get("doc")}

    def boss_session(self):
        """The most recently active main Desktop session in D:\\projekty or D:\\ai-hub (see BOSS_DIRS), or None."""
        with self.lock:
            if time.time() - self.snap["at"] >= FRESH:
                return None
            c = [x for x in self.snap["sessions"] if x["kind"] == "desktop" and x["local"] and x["cwd"].lower().rstrip("\\/") in BOSS_DIRS]
            return max(c, key=lambda x: x["updated"], default=None)

    def start_from_doc(self, token_hash: str, slug: str, text: str, d: dict) -> dict:
        """Types a request into the boss session: it starts a session for this doc (Filip's answer 6)."""
        self._verify(token_hash, f"docstart|{slug}", d)
        b = self.boss_session()
        if not b:
            raise LookupError("No main Claude Desktop session is open in D:\\projekty or D:\\ai-hub (or the PC is not reporting). Open one and try again.")
        r = self._type(b["id"], text, "start")
        r["boss"] = b["title"]
        return r

    def type_to_boss(self, text: str, kind: str = "start", token_hash: str = "", msg: str = "", d: dict = None) -> dict:
        """Stage 11c: types [text] into the boss session. With [msg] the phone's signature over it is checked first."""
        if msg:
            self._verify(token_hash, msg, d or {})
        b = self.boss_session()
        if not b:
            raise LookupError("No main Claude Desktop session is open in D:\\projekty or D:\\ai-hub (or the PC is not reporting). Open one and try again.")
        r = self._type(b["id"], text, kind)
        r["boss"] = b["title"]
        return r

    # ------------------------------------------------------------ helpers

    def _type(self, sid: str, text: str, kind: str) -> dict:
        with self.lock:
            s = next((x for x in self.snap["sessions"] if x["id"] == sid), None)
            if not s:
                raise LookupError("session not running")
            if s["kind"] != "desktop" or not s["local"]:
                raise ValueError("only Claude Desktop sessions can get messages from the phone; use the Claude app")
            item = {"key": secrets.token_hex(8), "kind": "message", "local": s["local"], "title": s["title"],
                    "sid": sid, "text": text, "at": time.time()}
            self.results[item["key"]] = {"ok": None, "detail": "sent to the PC", "at": time.time(), "sid": sid,
                                         "text": text[:300], "kind": kind}
            self._trim_results()
        self.claude.enqueue(item)
        return {"ok": True, "key": item["key"]}

    def card_gate(self, gid: str):
        """One gate with its full input (an app card whose PC session is not in the live list has no session view)."""
        with self.lock:
            g = next((x for x in self.snap["gates"] if x["id"] == gid), None)
            return self._card_extras(dict(g)) if g else None

    def _card_extras(self, g: dict) -> dict:
        if g.get("kind") == "appcard":
            g["answer"] = self.card_answer(g["id"])
            g["has_shot"] = g["id"] in self.card_shots
        return g

    def _verify(self, token_hash: str, msg: str, d: dict) -> None:
        self.claude.verify(token_hash, f"{msg}|{int(d.get('ts') or 0)}", str(d.get("sig", "")), int(d.get("ts") or 0))

    def _trim_results(self) -> None:
        for k in sorted(self.results, key=lambda k: self.results[k]["at"])[:-50]:
            del self.results[k]


def _s(v, n):
    return str(v or "")[:n]


def _clean_session(s: dict) -> dict:
    p = s.get("pending") if isinstance(s.get("pending"), dict) else None
    return {"id": _s(s.get("id"), 40), "local": _s(s.get("local"), 60), "title": _s(s.get("title"), 100),
            "cwd": _s(s.get("cwd"), 200), "state": _s(s.get("state"), 10), "waiting_for": _s(s.get("waiting_for"), 40),
            "kind": _s(s.get("kind"), 10), "rc": bool(s.get("rc")), "rc_id": _s(s.get("rc_id"), 80),
            "updated": float(s.get("updated") or 0), "last": _s(s.get("last"), 200), "last_role": _s(s.get("last_role"), 10),
            "pending": p if p and len(json.dumps(p)) <= 6000 else ({"type": p.get("type")} if p else None)}


def _clean_gate(g: dict) -> dict:
    inp = g.get("input") if isinstance(g.get("input"), dict) else {}
    raw = json.dumps(inp, ensure_ascii=False)
    return {"id": g["id"], "kind": _s(g.get("kind"), 12), "tool": _s(g.get("tool"), 80), "input": inp if len(raw) <= 40000 else {},
            "truncated": bool(g.get("truncated")) or len(raw) > 40000, "session_id": _s(g.get("session_id"), 40),
            "cwd": _s(g.get("cwd"), 200), "agent": _s(g.get("agent"), 60), "created": float(g.get("created") or 0),
            "doc": _s(g.get("doc"), 70), "summary": _summary(_s(g.get("tool"), 80), inp), **_card_fields(g)}


def _card_fields(g: dict) -> dict:
    """Extra fields of an app card gate. The kind is "appcard" exactly when the id says so (a hook request can't pose as one)."""
    if not str(g["id"]).startswith(CARD_PREFIX):
        return {"kind": _s(g.get("kind"), 12) if g.get("kind") != "appcard" else "permission"}
    card = str(g["id"])[len(CARD_PREFIX):]
    return {"kind": "appcard", "card": card, "card_title": _s(g.get("card_title"), 100), "local": _s(g.get("local"), 60),
            "answerable": bool(g.get("answerable")), "input_found": bool(g.get("input_found"))}


def _gate_brief(g: dict) -> dict:
    return {k: g[k] for k in ("id", "kind", "tool", "session_id", "session", "summary", "created", "doc", "card_title", "answerable") if k in g}


def _summary(tool: str, inp: dict) -> str:
    if tool in ("Bash", "PowerShell"):
        return _s(inp.get("description") or inp.get("command"), 300)
    if inp.get("file_path"):
        return re.split(r"[\\/]", str(inp.get("file_path")))[-1][:200]
    if tool == "AskUserQuestion":
        qs = inp.get("questions") or [{}]
        return _s(qs[0].get("question"), 300)
    if tool == "mcp__ccd_session__start_session" and (inp.get("title") or inp.get("prompt")):
        return "Start session: " + _s(inp.get("title") or inp.get("prompt"), 280)
    if tool == "ExitPlanMode":
        return "Plan: " + _s(inp.get("plan"), 280)
    return re.sub(r"^mcp__.+?__", "", tool)


def _clean_prop(p: dict) -> dict:
    return {"key": _s(p.get("key"), 40), "session_id": _s(p.get("session_id"), 40), "session": _s(p.get("session"), 100),
            "title": _s(p.get("title"), 120), "prompt": _s(p.get("prompt"), 6000), "folder": _s(p.get("folder"), 200),
            "model": _s(p.get("model"), 40), "context": _s(p.get("context"), 10), "offer": bool(p.get("offer")),
            "at": float(p.get("at") or 0)}


def _clean_row(r: dict) -> dict:
    out = {"role": _s(r.get("role"), 8), "text": _s(r.get("text"), 1500), "at": float(r.get("at") or 0)}
    if r.get("result"):
        out["result"] = _s(r.get("result"), 200)
    if r.get("detail"):
        out["detail"] = _s(r.get("detail"), 600)
    if r.get("tool"):
        out["tool"] = _s(r.get("tool"), 80)
    if r.get("error"):
        out["error"] = True
    return out
