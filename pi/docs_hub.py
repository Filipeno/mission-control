"""Docs & Checklists on the Pi (stage 5).

Files come from the PC (Claude drops Markdown into D:\\ai-hub\\to-phone\\, mc-pc uploads it). A checklist
is Markdown where every "- [ ]" line is an item; "#" lines are sections; anything else is a note.
Filip's results, comments, edits and screenshots live here; mc-pc pulls every change back to the PC.
"""
import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

ITEM_RE = re.compile(r"^\s*[-*] \[[ xX]\]\s*(.+)$")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.+)$")
STATUSES = ("pass", "fail", "skip")
MAX_SHOT = 4_000_000
MAX_TEXT = 300_000


def slugify(name: str) -> str:
    s = re.sub(r"\.md$", "", name.strip(), flags=re.I).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60]
    if not s:
        raise ValueError("bad name")
    return s


def parse(text: str) -> list:
    blocks, n, prev_blank = [], 0, True
    for line in text.splitlines():
        m = ITEM_RE.match(line)
        if m:
            blocks.append({"t": "item", "id": n, "text": m.group(1).strip()})
            n += 1
            prev_blank = False
            continue
        h = HEAD_RE.match(line)
        if h:
            blocks.append({"t": "h", "level": len(h.group(1)), "text": h.group(2).strip()})
            prev_blank = True
        elif line.strip():
            if blocks and blocks[-1]["t"] == "p" and not prev_blank:   # wrapped lines form one paragraph
                blocks[-1]["text"] += " " + line.strip()
            else:
                blocks.append({"t": "p", "text": line.strip()})
        prev_blank = not line.strip()
    return blocks


def title_of(text: str, slug: str) -> str:
    for line in text.splitlines():
        h = HEAD_RE.match(line)
        if h:
            return h.group(2).strip()[:120]
    return slug


class DocsHub:
    def __init__(self, state_dir: Path):
        self.dir = state_dir / "docs"
        (self.dir / "shots").mkdir(parents=True, exist_ok=True)
        (self.dir / "old").mkdir(exist_ok=True)
        self.lock = threading.Lock()
        self.index = self._load("index.json", {})        # slug -> meta
        self.events = self._load("events.json", [])     # finish / send, for the PC

    # ------------------------------------------------------------ files
    def _load(self, name, default):
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _save(self, name, obj):
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / name)

    def _text(self, slug):
        return (self.dir / f"{slug}.md").read_text(encoding="utf-8")

    def _touch(self, slug, by="Filip"):
        m = self.index[slug]
        m["seq"] = m.get("seq", 0) + 1
        m["changed"] = time.time()
        m["changed_by"] = by
        self._save("index.json", self.index)

    def _meta(self, slug):
        if slug not in self.index:
            raise LookupError("not found")
        return self.index[slug]

    # ------------------------------------------------------------ from the PC
    def upload(self, kind: str, name: str, text: str) -> dict:
        if kind not in ("checklist", "doc") or len(text) > MAX_TEXT:
            raise ValueError("bad upload")
        slug = slugify(name)
        with self.lock:
            old = self.index.get(slug)
            if old and (self.dir / f"{slug}.md").exists():
                if self._text(slug) == text:
                    return old
                v = old.get("version", 1)
                shutil.copy(self.dir / f"{slug}.md", self.dir / "old" / f"{slug}.v{v}.md")
                if (self.dir / f"{slug}.data.json").exists():
                    shutil.move(self.dir / f"{slug}.data.json", self.dir / "old" / f"{slug}.v{v}.data.json")
            (self.dir / f"{slug}.md").write_text(text, encoding="utf-8")
            self.index[slug] = {"slug": slug, "kind": kind, "title": title_of(text, slug), "file": name[:100],
                                "version": (old or {}).get("version", 0) + 1, "updated": time.time(),
                                "updated_by": "Claude", "seq": (old or {}).get("seq", 0), "acked": (old or {}).get("acked", 0)}
            self._save("index.json", self.index)
            return self.index[slug]

    def changes(self) -> list:
        with self.lock:
            out = []
            for slug, m in self.index.items():
                if m.get("seq", 0) > m.get("acked", 0):
                    out.append({"slug": slug, "kind": m["kind"], "title": m["title"], "seq": m["seq"],
                                "export": self.export(slug), "shots": self._shots(slug),
                                "text": self._text(slug) if m["kind"] == "doc" else None})
            return out

    def ack(self, acks: list) -> None:
        with self.lock:
            for a in acks:
                m = self.index.get(str(a.get("slug")))
                if m:
                    m["acked"] = max(m.get("acked", 0), int(a.get("seq", 0)))
            self._save("index.json", self.index)

    def take_events(self) -> list:
        with self.lock:
            return list(self.events)

    def ack_events(self, keys: list) -> None:
        with self.lock:
            self.events = [e for e in self.events if e["key"] not in set(keys)]
            self._save("events.json", self.events)

    def shot_path(self, slug: str, file: str):
        p = self.dir / "shots" / file
        return p if re.match(r"^[a-z0-9-]+-\d+-[a-z0-9]+\.jpg$", file) and file.startswith(slug + "-") and p.is_file() else None

    def _shots(self, slug):
        return sorted(p.name for p in (self.dir / "shots").glob(f"{slug}-*.jpg"))

    # ------------------------------------------------------------ data per file
    def _data(self, slug):
        return self._load(f"{slug}.data.json", {"items": {}, "comments": [], "finished_at": None})

    def _put(self, slug, d, by="Filip"):
        self._save(f"{slug}.data.json", d)
        self._touch(slug, by)

    def summary(self) -> dict:
        with self.lock:
            cl, docs = [], []
            for slug, m in sorted(self.index.items(), key=lambda kv: -kv[1].get("updated", 0)):
                d = self._data(slug)
                if m["kind"] == "checklist":
                    total = sum(1 for b in parse(self._text(slug)) if b["t"] == "item")
                    st = [v.get("status") for v in d["items"].values()]
                    cl.append({"slug": slug, "title": m["title"], "total": total,
                               "done": sum(1 for s in st if s in STATUSES), "failed": st.count("fail"),
                               "finished_at": d.get("finished_at"), "updated": m.get("changed") or m["updated"]})
                else:
                    docs.append({"slug": slug, "title": m["title"], "updated": m.get("changed") or m["updated"],
                                 "by": m.get("changed_by") or m.get("updated_by", "Claude"),
                                 "open_comments": sum(1 for c in d["comments"] if not c.get("resolved"))})
            return {"checklists": cl, "docs": docs}

    def get(self, slug: str) -> dict:
        with self.lock:
            m = dict(self._meta(slug))
            text = self._text(slug)
            d = self._data(slug)
            m["comments"] = d["comments"]
            if m["kind"] == "checklist":
                m["blocks"] = parse(text)
                m["items"] = d["items"]
                m["finished_at"] = d.get("finished_at")
            else:
                m["text"] = text
            return m

    # ------------------------------------------------------------ from the phone
    def set_item(self, slug, item_id, status=None, note=None):
        with self.lock:
            if self._meta(slug)["kind"] != "checklist":
                raise ValueError("not a checklist")
            d = self._data(slug)
            it = d["items"].setdefault(str(int(item_id)), {})
            if status is not None:
                if status not in STATUSES + ("",):
                    raise ValueError("bad status")
                it["status"] = status or None
            if note is not None:
                it["note"] = str(note)[:2000]
            it["at"] = time.time()
            self._put(slug, d)
            return it

    def comment(self, slug, text, item_id=None, line=None):
        text = str(text).strip()[:2000]
        if not text:
            raise ValueError("empty comment")
        with self.lock:
            self._meta(slug)
            d = self._data(slug)
            c = {"id": secrets.token_hex(4), "text": text, "at": time.time(), "by": "Filip", "resolved": False}
            if item_id is not None:
                c["item"] = int(item_id)
            if line is not None:
                c["line"] = int(line)
            d["comments"].append(c)
            self._put(slug, d)
            return c

    def resolve(self, slug, cid):
        with self.lock:
            d = self._data(slug)
            for c in d["comments"]:
                if c["id"] == cid:
                    c["resolved"] = True
            self._put(slug, d)

    def add_shot(self, slug, item_id, data: bytes) -> str:
        if len(data) > MAX_SHOT or data[:2] != b"\xff\xd8":
            raise ValueError("JPEG only, max 4 MB")
        with self.lock:
            self._meta(slug)
            name = f"{slug}-{int(item_id)}-{secrets.token_hex(3)}.jpg"
            (self.dir / "shots" / name).write_bytes(data)
            d = self._data(slug)
            d["items"].setdefault(str(int(item_id)), {}).setdefault("shots", []).append(name)
            self._put(slug, d)
            return name

    def set_text(self, slug, text: str):
        if len(text) > MAX_TEXT:
            raise ValueError("too long")
        with self.lock:
            m = self._meta(slug)
            if m["kind"] != "doc":
                raise ValueError("only docs can be edited")
            v = m.get("version", 1)
            shutil.copy(self.dir / f"{slug}.md", self.dir / "old" / f"{slug}.v{v}.md")
            (self.dir / f"{slug}.md").write_text(text, encoding="utf-8")
            m.update(version=v + 1, title=title_of(text, slug))
            self._touch(slug)

    def event(self, slug, kind):
        """Filip tapped Finish (checklist) or Send to Claude (doc)."""
        with self.lock:
            m = self._meta(slug)
            if kind == "finish":
                d = self._data(slug)
                d["finished_at"] = time.time()
                self._put(slug, d)
            self.events.append({"key": secrets.token_hex(6), "kind": kind, "slug": slug, "title": m["title"],
                                "at": time.time(), "summary": self._summary_line(slug)})
            self._save("events.json", self.events)

    def _summary_line(self, slug):
        m = self.index[slug]
        d = self._data(slug)
        if m["kind"] != "checklist":
            open_c = sum(1 for c in d["comments"] if not c.get("resolved"))
            return f"{open_c} open comment(s), version {m.get('version', 1)}"
        items = [b for b in parse(self._text(slug)) if b["t"] == "item"]
        st = {k: v.get("status") for k, v in d["items"].items()}
        done = sum(1 for b in items if st.get(str(b["id"])) in STATUSES)
        failed = [b["text"] for b in items if st.get(str(b["id"])) == "fail"]
        s = f"{done} of {len(items)} done, {len(failed)} failed"
        return s + (": " + "; ".join(f[:80] for f in failed[:5]) if failed else "")

    # ------------------------------------------------------------ export for Claude
    def export(self, slug) -> str:
        m = self.index[slug]
        d = self._data(slug)
        text = self._text(slug)
        when = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""
        if m["kind"] == "doc":
            out = [f"# Comments on {m['title']}", f"Version {m.get('version', 1)}, exported {when(time.time())}", ""]
            lines = text.splitlines()
            for c in d["comments"]:
                ref = lines[c["line"]][:100] if c.get("line") is not None and c["line"] < len(lines) else ""
                out.append(f"- {'[resolved] ' if c.get('resolved') else ''}line {c.get('line', '?') + 1 if isinstance(c.get('line'), int) else '?'}"
                           f" ({ref!r}): {c['text']} ({when(c['at'])})")
            return "\n".join(out) + "\n"
        icon = {"pass": "✅ pass", "fail": "❌ fail", "skip": "⏭ skip"}
        out = [f"# Results: {m['title']}", f"Source file: {m.get('file', '')} (version {m.get('version', 1)})",
               f"Summary: {self._summary_line(slug)}" + (f", finished {when(d.get('finished_at'))}" if d.get("finished_at") else ""), ""]
        coms = {}
        for c in d["comments"]:
            coms.setdefault(c.get("item"), []).append(c)
        for b in parse(text):
            if b["t"] == "h":
                out += ["", "#" * min(b["level"] + 1, 6) + " " + b["text"]]
            elif b["t"] == "item":
                it = d["items"].get(str(b["id"]), {})
                out.append(f"- {icon.get(it.get('status'), '⬜ open')}: {b['text']}")
                if it.get("note"):
                    out.append(f"  - Note: {it['note']}")
                for c in coms.get(b["id"], []):
                    out.append(f"  - Comment ({when(c['at'])}): {c['text']}")
                for s in it.get("shots", []):
                    out.append(f"  - Screenshot: {s}")
        return "\n".join(out) + "\n"
