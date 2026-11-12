"""Claude tab data on the Pi: what the PC helper reports, approvals, signed answers, ideas.

The PC helper (mc-pc) reports every 15 s: hub status-log tails, HANDOFF summary, pending approvals
(+ shrunk pictures), parked AIs and, every 10 min, usage numbers. Filip's answers and ideas wait here
until mc-pc picks them up (also while the PC sleeps).

Answers must be signed by the phone's fingerprint-locked KeyStore key (ECDSA P-256, SHA-256) over
"id|decision|option|text|ts". The public key is registered once per app login token.
"""
import base64
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

import p256

ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9]{4}$")
SIG_MAX_AGE = 300          # an answer signed longer ago than this is refused
KEEP_ANSWERED_S = 30 * 86400
MAX_PICTURE = 3_000_000
MAX_AUDIO = 8_000_000
DECISIONS = ("approve", "reject", "option", "reply")


class ClaudeHub:
    def __init__(self, state_dir: Path, load_json, save_json):
        self.dir = state_dir
        self.load, self.save = load_json, save_json
        self.lock = threading.Lock()
        self.report = load_json("claude-report.json", {})          # logs, handoff, parked, at
        self.usage = load_json("usage.json", {})                   # ai -> numbers, last good ones kept
        self.approvals = load_json("approvals.json", {})           # id -> request + status
        self.queue = load_json("pc-inbox.json", [])                # answers + ideas for mc-pc
        self.keys = load_json("signing-keys.json", {})             # token hash -> PEM public key
        (state_dir / "pictures").mkdir(parents=True, exist_ok=True)
        (state_dir / "audio").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ from the PC helper

    def on_report(self, r: dict) -> list:
        """Store a report. Returns approvals that are new (for a phone notification)."""
        new = []
        with self.lock:
            self.report = {
                "logs": {str(k)[:60]: {"text": str((v or {}).get("text", ""))[-4000:], "at": (v or {}).get("at")}
                         for k, v in list((r.get("logs") or {}).items())[:20]},
                "handoff": str(r.get("handoff") or "")[:5000],
                "parked": {str(k)[:40]: float(v) for k, v in (r.get("parked") or {}).items()
                           if isinstance(v, (int, float))},
                "at": time.time(),
            }
            self.save("claude-report.json", self.report)
            for ai, u in (r.get("usage") or {}).items():
                if not isinstance(u, dict) or ai not in ("claude", "codex", "gemini", "antigravity"):
                    continue
                old = self.usage.get(ai) or {}
                if u.get("error") and old.get("windows"):
                    old = dict(old, error=str(u["error"])[:120], checked_at=u.get("at"))   # keep last good numbers
                    self.usage[ai] = old
                else:
                    self.usage[ai] = _clean_usage(u)
            self.save("usage.json", self.usage)
            seen = set()
            for a in (r.get("approvals") or [])[:50]:
                aid = str(a.get("id", ""))
                if not ID_RE.match(aid):
                    continue
                seen.add(aid)
                cur = self.approvals.get(aid)
                if cur is None:
                    cur = {"status": "pending"}
                    new.append(aid)
                cur.update({
                    "id": aid, "type": str(a.get("type", "question"))[:20], "title": str(a.get("title", ""))[:200],
                    "text": str(a.get("text", ""))[:3000],
                    "options": [str(o)[:60] for o in (a.get("options") or [])][:6],
                    "pictures": min(int(a.get("pictures") or 0), 6), "session": str(a.get("session", ""))[:120],
                    "created": a.get("created"),
                })
                self.approvals[aid] = cur
            # Gone from the PC without an answer from the phone = withdrawn (answered at the PC, or stopped).
            for aid, cur in self.approvals.items():
                if cur["status"] == "pending" and aid not in seen:
                    cur["status"] = "withdrawn"
                    cur["closed_at"] = time.time()
            self._prune()
            self.save("approvals.json", self.approvals)
        return [self.approvals[i] for i in new]

    def save_picture(self, aid: str, n: int, data: bytes) -> None:
        if not ID_RE.match(aid) or not 0 <= n < 6 or len(data) > MAX_PICTURE or data[:2] != b"\xff\xd8":
            raise ValueError("bad picture")
        (self.dir / "pictures" / f"{aid}-{n}.jpg").write_bytes(data)

    def picture_path(self, aid: str, n: int):
        p = self.dir / "pictures" / f"{aid}-{n}.jpg"
        return p if ID_RE.match(aid) and p.is_file() else None

    def pc_inbox(self) -> list:
        with self.lock:
            return [dict(q) for q in self.queue][:20]

    def ack(self, keys: list) -> None:
        with self.lock:
            self.queue = [q for q in self.queue if q["key"] not in set(keys)]
            self.save("pc-inbox.json", self.queue)

    def audio_path(self, audio_id: str):
        p = self.dir / "audio" / f"{audio_id}.m4a"
        return p if re.match(r"^[a-zA-Z0-9_-]{8,40}$", audio_id) and p.is_file() else None

    # ------------------------------------------------------------ from the phone

    def register_key(self, token_hash: str, spki_b64: str) -> None:
        der = base64.b64decode(spki_b64)
        p256.public_point(der)   # raises ValueError unless it is a valid P-256 key
        with self.lock:
            self.keys[token_hash] = base64.b64encode(der).decode()
            self.save("signing-keys.json", self.keys)

    def has_key(self, token_hash: str) -> bool:
        return token_hash in self.keys

    def verify(self, token_hash: str, msg: str, sig_b64: str, ts: int) -> None:
        """Raises PermissionError unless msg was signed by this phone's fingerprint key within SIG_MAX_AGE."""
        pem = self.keys.get(token_hash)
        if not pem:
            raise PermissionError("no fingerprint key registered for this phone")
        if abs(time.time() - ts) > SIG_MAX_AGE:
            raise PermissionError("signature too old")
        try:
            ok = p256.verify(p256.public_point(base64.b64decode(pem)), msg.encode(), base64.b64decode(sig_b64))
        except ValueError:
            ok = False
        if not ok:
            raise PermissionError("bad signature")

    def enqueue(self, item: dict) -> None:
        with self.lock:
            self.queue.append(item)
            self.save("pc-inbox.json", self.queue)

    def answer(self, token_hash: str, aid: str, d: dict) -> dict:
        decision = str(d.get("decision", ""))
        option, text = str(d.get("option") or "")[:60], str(d.get("text") or "")[:4000]
        ts = int(d.get("ts") or 0)
        if decision not in DECISIONS:
            raise ValueError("bad decision")
        pem = self.keys.get(token_hash)
        if not pem:
            raise PermissionError("no fingerprint key registered for this phone")
        if abs(time.time() - ts) > SIG_MAX_AGE:
            raise PermissionError("signature too old")
        msg = f"{aid}|{decision}|{option}|{text}|{ts}".encode()
        try:
            ok = p256.verify(p256.public_point(base64.b64decode(pem)), msg, base64.b64decode(str(d.get("sig", ""))))
        except ValueError:
            ok = False
        if not ok:
            raise PermissionError("bad signature")
        with self.lock:
            a = self.approvals.get(aid)
            if not a or a["status"] != "pending":
                raise LookupError("not pending (already answered or withdrawn)")
            if decision == "option" and option not in a["options"]:
                raise ValueError("unknown option")
            a.update(status="answered", decision=decision, option=option, answer_text=text, closed_at=time.time())
            self.queue.append({"key": secrets.token_hex(8), "kind": "answer", "id": aid, "title": a["title"],
                               "decision": decision, "option": option, "text": text, "at": time.time()})
            self.save("approvals.json", self.approvals)
            self.save("pc-inbox.json", self.queue)
            return dict(a)

    def add_idea(self, text: str, audio: bytes = None) -> None:
        item = {"key": secrets.token_hex(8), "kind": "idea", "text": text[:4000], "at": time.time()}
        if audio:
            if len(audio) > MAX_AUDIO:
                raise ValueError("audio too large")
            aid = secrets.token_urlsafe(12)
            (self.dir / "audio" / f"{aid}.m4a").write_bytes(audio)
            item["audio_id"] = aid
        with self.lock:
            self.queue.append(item)
            self.save("pc-inbox.json", self.queue)

    # ------------------------------------------------------------ for the app

    def view(self) -> dict:
        with self.lock:
            pend = sorted((a for a in self.approvals.values() if a["status"] == "pending"),
                          key=lambda a: a.get("created") or 0)
            recent = sorted((a for a in self.approvals.values() if a["status"] != "pending"),
                            key=lambda a: -(a.get("closed_at") or 0))[:5]
            return {"approvals": pend, "recent_approvals": recent, "usage": self.usage,
                    "parked": self.report.get("parked", {}), "logs": self.report.get("logs", {}),
                    "handoff": self.report.get("handoff", ""), "report_at": self.report.get("at"),
                    "queued": len(self.queue)}

    def _prune(self) -> None:
        cut = time.time() - KEEP_ANSWERED_S
        for aid in [k for k, a in self.approvals.items() if a["status"] != "pending" and (a.get("closed_at") or 0) < cut]:
            del self.approvals[aid]
            for p in (self.dir / "pictures").glob(f"{aid}-*.jpg"):
                p.unlink(missing_ok=True)


def _clean_usage(u: dict) -> dict:
    out = {"at": u.get("at"), "plan": str(u.get("plan") or "")[:30]}
    if u.get("error"):
        out["error"] = str(u["error"])[:120]
    wins = []
    for w in (u.get("windows") or [])[:4]:
        if isinstance(w, dict):
            wins.append({"name": str(w.get("name") or "")[:30], "seconds": int(w.get("seconds") or 0),
                         "used_pct": float(w["used_pct"]) if isinstance(w.get("used_pct"), (int, float)) else None,
                         "resets_at": float(w["resets_at"]) if isinstance(w.get("resets_at"), (int, float)) else None})
    out["windows"] = wins
    for k in ("limit_reached", "reset_credits", "app_jobs_today", "app_jobs_max", "source_at"):
        if k in u:
            out[k] = u[k]
    return out
