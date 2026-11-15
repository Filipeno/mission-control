"""Filip's to-do list on the Pi (stage 11d, part 1).

Items come from the PC (todo.ps1 writes D:\\ai-hub\\todo\\open\\<id>.json, mc-pc uploads it). Filip answers on
the phone: Done / Can't, a note, photos. Ticking needs no fingerprint (it is information, not an approval).
A closed item waits here until mc-pc picks the result up and puts it in the source session's mailbox, so
nothing is lost while the PC sleeps. A double tap is counted once (a closed item ignores later results).
A phone-test checklist can be attached: finishing it closes the item ("Done, 2 failed").
"""
import json
import re
import secrets
import threading
import time
from pathlib import Path

ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9]{4}$")
SID_RE = re.compile(r"^[0-9a-f-]{36}$")
KINDS = ("test", "bios", "signin", "hardware", "uninstall", "other")
MAX_PHOTO = 4_000_000
MAX_PHOTOS = 8
KEEP_DONE_S = 30 * 86400


def _s(v, n):
    return str(v or "")[:n]


class TodoHub:
    def __init__(self, state_dir: Path):
        self.dir = state_dir / "todo"
        (self.dir / "photos").mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.items = self._load()

    def _load(self):
        try:
            return json.loads((self.dir / "items.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        tmp = self.dir / "items.json.tmp"
        tmp.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / "items.json")

    def _item(self, tid):
        if not ID_RE.match(str(tid)) or tid not in self.items:
            raise LookupError("not found")
        return self.items[tid]

    # ------------------------------------------------------------ from the PC
    def upload(self, d: dict):
        """Idempotent on the id. Returns (item, is_new)."""
        tid = str(d.get("id", ""))
        if not ID_RE.match(tid) or not str(d.get("title", "")).strip():
            raise ValueError("bad to-do")
        with self.lock:
            if tid in self.items:
                return dict(self.items[tid]), False
            sess = d.get("session") if isinstance(d.get("session"), dict) else {}
            sid = _s(sess.get("sid"), 40)
            kind = _s(d.get("kind"), 12)
            self.items[tid] = {
                "id": tid, "title": _s(d.get("title"), 160).strip(), "steps": _s(d.get("steps"), 12000),
                "kind": kind if kind in KINDS else "other", "project": _s(d.get("project"), 80),
                "source": _s(d.get("source"), 20),
                "session": {"sid": sid if SID_RE.match(sid) else "", "title": _s(sess.get("title"), 100)},
                "created": float(d.get("created") or time.time()), "status": "open", "note": "", "photos": [],
                "checklist": _s(d.get("checklist"), 80) or None,      # slug of the attached checklist doc
                "closed_at": None, "summary": "", "pc_ack": False, "delivery": None,
            }
            self._save()
            return dict(self.items[tid]), True

    def changes(self) -> list:
        """Closed items whose result the PC has not taken yet."""
        with self.lock:
            return [{"id": i["id"], "title": i["title"], "status": i["status"], "note": i["note"], "photos": list(i["photos"]),
                     "closed_at": i["closed_at"], "summary": i["summary"], "checklist": i["checklist"],
                     "session": dict(i["session"]), "kind": i["kind"], "project": i["project"]}
                    for i in self.items.values() if i["status"] != "open" and not i["pc_ack"]]

    def ack(self, ids: list) -> None:
        with self.lock:
            for tid in ids:
                if tid in self.items:
                    self.items[tid]["pc_ack"] = True
            self._prune()
            self._save()

    def set_delivery(self, tid: str, state: str, detail: str) -> None:
        with self.lock:
            if tid in self.items:
                self.items[tid]["delivery"] = {"state": _s(state, 20), "detail": _s(detail, 120), "at": time.time()}
                self._save()

    def photo_path(self, tid: str, name: str):
        p = self.dir / "photos" / name
        ok = ID_RE.match(tid) and re.match(r"^[0-9a-z-]+-\d+-[a-z0-9]+\.jpg$", name) and name.startswith(tid + "-")
        return p if ok and p.is_file() else None

    # ------------------------------------------------------------ for the app
    def _brief(self, i):
        return {"id": i["id"], "title": i["title"], "kind": i["kind"], "project": i["project"], "source": i["source"],
                "session": i["session"].get("title") or "", "created": i["created"], "status": i["status"],
                "photos": len(i["photos"]), "checklist": i["checklist"], "summary": i["summary"],
                "closed_at": i["closed_at"], "delivery": i["delivery"], "has_note": bool(i["note"])}

    def view(self) -> dict:
        with self.lock:
            op = sorted((i for i in self.items.values() if i["status"] == "open"), key=lambda i: i["created"])
            dn = sorted((i for i in self.items.values() if i["status"] != "open"), key=lambda i: -(i["closed_at"] or 0))[:40]
            return {"open": [self._brief(i) for i in op], "done": [self._brief(i) for i in dn], "open_count": len(op)}

    def open_count(self) -> int:
        with self.lock:
            return sum(1 for i in self.items.values() if i["status"] == "open")

    def get(self, tid: str) -> dict:
        with self.lock:
            i = dict(self._item(tid))
            i["session"] = dict(i["session"])
            return i

    # ------------------------------------------------------------ from the phone
    def set_note(self, tid: str, note: str) -> None:
        with self.lock:
            i = self._item(tid)
            if i["status"] == "open":
                i["note"] = _s(note, 4000)
                self._save()

    def add_photo(self, tid: str, data: bytes) -> str:
        if len(data) > MAX_PHOTO or data[:2] != b"\xff\xd8":
            raise ValueError("JPEG only, max 4 MB")
        with self.lock:
            i = self._item(tid)
            if i["status"] != "open":
                raise ValueError("this item is already closed")
            if len(i["photos"]) >= MAX_PHOTOS:
                raise ValueError("at most 8 photos")
            name = f"{tid}-{len(i['photos'])}-{secrets.token_hex(3)}.jpg"
            (self.dir / "photos" / name).write_bytes(data)
            i["photos"].append(name)
            self._save()
            return name

    def result(self, tid: str, status: str, note=None):
        """Done or Can't. Returns (item, changed). A second result for a closed item changes nothing."""
        if status not in ("done", "cant"):
            raise ValueError("bad status")
        with self.lock:
            i = self._item(tid)
            if i["status"] != "open":
                return dict(i), False
            if note is not None:
                i["note"] = _s(note, 4000)
            i["status"], i["closed_at"] = status, time.time()
            i["summary"] = "Done" if status == "done" else "Can't do it"
            self._save()
            return dict(i), True

    def reopen(self, tid: str) -> dict:
        """A mistaken tap: allowed until the PC has delivered the result."""
        with self.lock:
            i = self._item(tid)
            if i["status"] == "open":
                return dict(i)
            if i["pc_ack"]:
                raise ValueError("already delivered to Claude")
            i.update(status="open", closed_at=None, summary="", delivery=None)
            self._save()
            return dict(i)

    def close_from_checklist(self, tid: str, summary: str):
        """The attached checklist was finished. Returns (item, changed)."""
        with self.lock:
            if tid not in self.items:
                return None, False
            i = self.items[tid]
            if i["status"] != "open":
                return dict(i), False
            i["status"], i["closed_at"], i["summary"] = "done", time.time(), _s(summary, 120)
            self._save()
            return dict(i), True

    def _prune(self) -> None:
        cut = time.time() - KEEP_DONE_S
        for tid in [k for k, i in self.items.items() if i["status"] != "open" and i["pc_ack"] and (i["closed_at"] or 0) < cut]:
            for n in self.items[tid]["photos"]:
                (self.dir / "photos" / n).unlink(missing_ok=True)
            del self.items[tid]
