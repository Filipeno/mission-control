"""Claude tab data on the Pi: what the PC helper reports, approvals, signed answers, ideas.

The PC helper (mc-pc) reports every 15 s: hub status-log tails, HANDOFF summary, pending approvals
(+ shrunk pictures), parked AIs and, every 10 min, usage numbers. Filip's answers and ideas wait here
until mc-pc picks them up (also while the PC sleeps).

Answers are signed by the phone's KeyStore keys (ECDSA P-256, SHA-256) over "id|decision|option|text|ts".
Two keys per app login token: the every-time key (tier H) and the 5-minute window key (tier M); tiers.py says
which answer needs which (an option pick needs none).
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
import tiers

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
        self.keys = load_json("signing-keys.json", {})             # token hash -> every-time public key (tier H)
        self.mkeys = load_json("signing-keys-m.json", {})          # token hash -> 5-minute window public key (tier M)
        self.used_sigs = {}                                        # signature -> when it was used (no replay)
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

    def register_key(self, token_hash: str, spki_b64: str, slot: str = "h", proof: dict = None) -> None:
        """Two key slots per login token (fingerprint option C):
          "h"  every-time key: the first one per login is taken as is (the login password is the trust root);
               replacing it needs a signature by the current one ("keyreg|h|<key>|<ts>"), else log in again.
          "m"  5-minute window key: always needs a signature by the "h" key ("keyreg|m|<key>|<ts>").
        Raises ValueError (bad key) or PermissionError (no valid proof)."""
        if slot not in ("h", "m"):
            raise ValueError("bad key slot")
        der = base64.b64decode(spki_b64)
        p256.public_point(der)   # raises ValueError unless it is a valid P-256 key
        b64 = base64.b64encode(der).decode()
        with self.lock:
            cur = self.keys.get(token_hash) if slot == "h" else self.mkeys.get(token_hash)
        if cur == b64:
            return                                        # already registered (idempotent)
        if slot == "m" or token_hash in self.keys:
            if not self.keys.get(token_hash):
                raise PermissionError("no fingerprint key registered for this phone")
            p = proof or {}
            try:
                self.verify(token_hash, f"keyreg|{slot}|{b64}|{int(p.get('ts') or 0)}", str(p.get("sig") or ""),
                            int(p.get("ts") or 0), tier="H")
            except PermissionError as e:
                raise PermissionError(f"key change needs the current fingerprint key ({e}); log out and log in again") from None
        with self.lock:
            if slot == "h":
                self.keys[token_hash] = b64
                self.mkeys.pop(token_hash, None)          # a window key was vouched for by the old key
                self.save("signing-keys.json", self.keys)
            else:
                self.mkeys[token_hash] = b64
            self.save("signing-keys-m.json", self.mkeys)

    def drop_keys(self, token_hash: str) -> None:
        """Logout: forget both keys of this login."""
        with self.lock:
            if self.keys.pop(token_hash, None) is not None:
                self.save("signing-keys.json", self.keys)
            if self.mkeys.pop(token_hash, None) is not None:
                self.save("signing-keys-m.json", self.mkeys)

    def has_key(self, token_hash: str) -> bool:
        return token_hash in self.keys

    def has_mkey(self, token_hash: str) -> bool:
        return token_hash in self.mkeys

    def verify(self, token_hash: str, msg: str, sig_b64: str, ts: int, tier: str = "H") -> None:
        """Raises PermissionError unless msg was signed by this phone within SIG_MAX_AGE, by a key strong enough
        for [tier]: "H" only the every-time key, "M" also the 5-minute window key, "0" no signature needed
        (one that is sent must still be valid). A signature works once."""
        if tier not in tiers.TIERS:
            raise PermissionError("bad tier")
        if tier == "0" and not sig_b64:
            return
        pems = [p for p in (self.keys.get(token_hash), self.mkeys.get(token_hash) if tier != "H" else None) if p]
        if not self.keys.get(token_hash):
            raise PermissionError("no fingerprint key registered for this phone")
        if abs(time.time() - ts) > SIG_MAX_AGE:
            raise PermissionError("signature too old")
        ok = False
        for pem in pems:
            try:
                ok = p256.verify(p256.public_point(base64.b64decode(pem)), msg.encode(), base64.b64decode(sig_b64))
            except ValueError:
                ok = False
            if ok:
                break
        if not ok:
            raise PermissionError("needs a fresh fingerprint" if tier == "H" and self.mkeys.get(token_hash) else "bad signature")
        with self.lock:                                      # a signed message works once (no replay within the window)
            now = time.time()
            self.used_sigs = {k: t for k, t in self.used_sigs.items() if now - t < SIG_MAX_AGE * 2}
            if sig_b64 in self.used_sigs:
                raise PermissionError("this signed request was already used")
            self.used_sigs[sig_b64] = now

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
        with self.lock:
            a = dict(self.approvals.get(aid) or {})
        tier = tiers.approval_tier(a, decision, option, text)
        # verify() also refuses a signature that was already used (the old check here let a replay through).
        self.verify(token_hash, f"{aid}|{decision}|{option}|{text}|{ts}", str(d.get("sig", "")), ts, tier=tier)
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
            pend = sorted((dict(a, tiers=_tiers(a)) for a in self.approvals.values() if a["status"] == "pending"),
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


def _tiers(a: dict) -> dict:
    """What each answer to this approval needs (the app follows it; answer() checks it): see tiers.approval_tier."""
    return {"approve": tiers.approval_tier(a, "approve", "", ""), "reject": "0", "reject_text": "M", "reply": "M",
            "options": [tiers.approval_tier(a, "option", o, "") for o in a.get("options") or []]}


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
