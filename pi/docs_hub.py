"""Docs & Checklists on the Pi (stage 5, extended in stage 11d part 2).

Files come from the PC (Claude drops Markdown into D:\\ai-hub\\to-phone\\, mc-pc uploads it). A checklist
is Markdown where every "- [ ]" line is an item; "#" lines are sections; anything else is a note.
Filip's results, comments, edits and screenshots live here; mc-pc pulls every change back to the PC.
Kinds: checklist, doc, plan (a Claude plan file: read-only on the phone, approved or rejected through the
phone-gate request) and skola (a finished school output: its review as text + a PDF copy).
Every doc can have an owner, the Claude session that published or owns it; comments go to it as one batch.
"""
import json
import ntpath
import re
import secrets
import shutil
import threading
import time
import unicodedata
from pathlib import Path

ITEM_RE = re.compile(r"^\s*[-*] \[[ xX]\]\s*(.+)$")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.+)$")
STATUSES = ("pass", "fail", "skip")
MAX_SHOT = 4_000_000
MAX_TEXT = 300_000
MAX_PDF = 25_000_000
KINDS = ("checklist", "doc", "plan", "skola")
SID_RE = re.compile(r"^[0-9a-f-]{36}$")


def slugify(name: str) -> str:
    s = re.sub(r"\.md$", "", name.strip(), flags=re.I)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()   # Czech letters lose their marks
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


def clean_owner(o) -> dict:
    o = o if isinstance(o, dict) else {}
    sid = str(o.get("sid") or "")
    return {"sid": sid if SID_RE.match(sid) else "", "title": str(o.get("title") or "")[:100], "cwd": str(o.get("cwd") or "")[:260]}


def quote_line(text: str, line) -> str:
    lines = text.splitlines()
    if isinstance(line, int) and 0 <= line < len(lines):
        return re.sub(r"\s+", " ", lines[line]).strip()[:90]
    return ""


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
        (self.dir / "pdf").mkdir(exist_ok=True)
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
    def upload(self, kind: str, name: str, text: str, todo: str = "", owner=None, source: str = "", subject: str = "",
               title: str = "", pdf_failed: str = "", file: str = "") -> dict:
        if kind not in KINDS or len(text) > MAX_TEXT:
            raise ValueError("bad upload")
        if kind == "skola" and not text.strip():
            text = "(No review came with this output.)"
        slug = slugify(name)
        own = clean_owner(owner)
        with self.lock:
            old = self.index.get(slug)
            if old and (self.dir / f"{slug}.md").exists():
                if self._text(slug) == text:
                    changed = False
                    for k, v in (("todo", todo), ("source", source[:260]), ("subject", subject[:80]), ("pdf_failed", pdf_failed[:200]), ("file", file[:100])):
                        if v and old.get(k) != v:
                            old[k] = v
                            changed = True
                    if (own["sid"] or own["cwd"]) and old.get("owner") != own:
                        old["owner"] = own
                        changed = True
                    if changed:
                        self._save("index.json", self.index)
                    return old
                v = old.get("version", 1)
                shutil.copy(self.dir / f"{slug}.md", self.dir / "old" / f"{slug}.v{v}.md")
                if (self.dir / f"{slug}.data.json").exists():
                    shutil.move(self.dir / f"{slug}.data.json", self.dir / "old" / f"{slug}.v{v}.data.json")
            (self.dir / f"{slug}.md").write_text(text, encoding="utf-8")
            self.index[slug] = {"slug": slug, "kind": kind, "title": (title.strip()[:120] or title_of(text, slug)), "file": (file or name)[:100],
                                "version": (old or {}).get("version", 0) + 1, "updated": time.time(),
                                "updated_by": "Claude", "seq": (old or {}).get("seq", 0), "acked": (old or {}).get("acked", 0),
                                "owner": own if (own["sid"] or own["cwd"]) else (old or {}).get("owner") or own,
                                "source": source[:260] or (old or {}).get("source", ""),
                                "subject": subject[:80] or (old or {}).get("subject", "")}
            if pdf_failed:
                self.index[slug]["pdf_failed"] = pdf_failed[:200]
            elif (old or {}).get("pdf"):
                self.index[slug]["pdf"] = old["pdf"]
            if todo or (old or {}).get("todo"):
                self.index[slug]["todo"] = todo or old["todo"]       # the to-do item this checklist belongs to
            self._save("index.json", self.index)
            return self.index[slug]

    def save_pdf(self, slug: str, data: bytes) -> None:
        if len(data) > MAX_PDF or data[:4] != b"%PDF":
            raise ValueError("PDF only, max 25 MB")
        with self.lock:
            m = self._meta(slug)
            if m["kind"] != "skola":
                raise ValueError("only school outputs have a PDF")
            (self.dir / "pdf" / f"{slug}.pdf").write_bytes(data)       # the last version only
            m["pdf"] = {"size": len(data), "at": time.time()}
            m.pop("pdf_failed", None)
            self._save("index.json", self.index)

    def pdf_path(self, slug: str):
        p = self.dir / "pdf" / f"{slug}.pdf"
        with self.lock:
            m = self.index.get(slug)
        return p if m and m.get("pdf") and p.is_file() else None

    def delete(self, slug: str) -> None:
        """Removes a doc and its files (cleanup from the PC)."""
        with self.lock:
            if slug not in self.index:
                raise LookupError("not found")
            del self.index[slug]
            for p in list(self.dir.glob(f"{slug}.*")) + [self.dir / "pdf" / f"{slug}.pdf"] + list((self.dir / "shots").glob(f"{slug}-*.jpg")):
                if p.is_file() and (p.name == f"{slug}.pdf" or p.name.startswith(slug + ".") or p.name.startswith(slug + "-")):
                    p.unlink(missing_ok=True)
            self.events = [e for e in self.events if e.get("slug") != slug]
            self._save("index.json", self.index)
            self._save("events.json", self.events)

    def changes(self) -> list:
        with self.lock:
            out = []
            for slug, m in self.index.items():
                if m.get("seq", 0) > m.get("acked", 0):
                    out.append({"slug": slug, "kind": m["kind"], "title": m["title"], "seq": m["seq"],
                                "export": self.export(slug), "shots": self._shots(slug),
                                "text": self._text(slug) if m["kind"] != "checklist" else None})
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

    def _open_comments(self, slug):
        return sum(1 for c in self._data(slug)["comments"] if not c.get("resolved"))

    def open_comment_count(self, slug: str) -> int:
        with self.lock:
            return self._open_comments(slug) if slug in self.index else 0

    def summary(self, resolve=lambda meta: None, gate_docs=()) -> dict:
        with self.lock:
            cl, docs, plans, skola = [], [], [], []
            for slug, m in sorted(self.index.items(), key=lambda kv: -kv[1].get("updated", 0)):
                d = self._data(slug)
                upd = m.get("changed") or m["updated"]
                if m["kind"] == "checklist":
                    total = sum(1 for b in parse(self._text(slug)) if b["t"] == "item")
                    st = [v.get("status") for v in d["items"].values()]
                    cl.append({"slug": slug, "title": m["title"], "total": total,
                               "done": sum(1 for s in st if s in STATUSES), "failed": st.count("fail"),
                               "finished_at": d.get("finished_at"), "updated": upd})
                    continue
                row = {"slug": slug, "title": m["title"], "updated": upd, "by": m.get("changed_by") or m.get("updated_by", "Claude"),
                       "open_comments": sum(1 for c in d["comments"] if not c.get("resolved")),
                       "unsent": sum(1 for c in d["comments"] if not c.get("resolved") and not c.get("sent")),
                       "owner": resolve(m)}
                if m["kind"] == "doc":
                    docs.append(row)
                elif m["kind"] == "plan":
                    row["waiting"] = slug in gate_docs
                    plans.append(row)
                else:
                    row.update(subject=m.get("subject") or "Other", pdf=bool(m.get("pdf")), pdf_failed=m.get("pdf_failed", ""),
                               file=m.get("file", ""))
                    skola.append(row)
            plans.sort(key=lambda r: (not r["waiting"], -r["updated"]))
            return {"checklists": cl, "docs": docs, "plans": plans, "skola": skola}

    def meta(self, slug: str) -> dict:
        """A copy of the stored meta (the owner as uploaded, not resolved)."""
        with self.lock:
            return dict(self._meta(slug))

    def get(self, slug: str, resolve=lambda meta: None, gate=None) -> dict:
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
                m["owner"] = resolve(m)
                m["source_name"] = ntpath.basename(m.get("source") or "")
                m["unsent"] = sum(1 for c in d["comments"] if not c.get("resolved") and not c.get("sent"))
                if m["kind"] == "plan":
                    m["gate"] = gate
                if m["kind"] == "skola":
                    m["has_pdf"] = bool(m.get("pdf"))
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
                raise ValueError("only docs can be edited (plans and school outputs are read-only)")
            v = m.get("version", 1)
            shutil.copy(self.dir / f"{slug}.md", self.dir / "old" / f"{slug}.v{v}.md")
            (self.dir / f"{slug}.md").write_text(text, encoding="utf-8")
            m.update(version=v + 1, title=title_of(text, slug), edited=True)
            self._touch(slug)

    def mark_sent(self, slug, ids) -> int:
        """Comments that went to Claude another way (a plan rejected with them as feedback)."""
        with self.lock:
            self._meta(slug)
            d = self._data(slug)
            n = 0
            for c in d["comments"]:
                if c["id"] in ids and not c.get("sent"):
                    c["sent"] = time.time()
                    n += 1
            self._put(slug, d)
            return n

    def batch(self, slug) -> tuple:
        """(text, ids) of the open comments that were not sent yet, as: Line 12 ("quoted line"): comment."""
        with self.lock:
            return self._batch(slug)

    def _batch(self, slug) -> tuple:
        text = self._text(slug)
        out, ids = [], []
        mine = [c for c in self._data(slug)["comments"] if not c.get("resolved") and not c.get("sent")]
        mine.sort(key=lambda c: (c["line"] if isinstance(c.get("line"), int) else 10**9, c.get("at", 0)))   # in document order
        for c in mine:
            ids.append(c["id"])
            if isinstance(c.get("line"), int):
                q = quote_line(text, c["line"])
                out.append(f'Line {c["line"] + 1}' + (f' ("{q}")' if q else "") + f": {c['text']}")
            elif c.get("item") is not None:
                out.append(f"Item {c['item'] + 1}: {c['text']}")
            else:
                out.append(f"General: {c['text']}")
        return "\n".join(out), ids

    def event(self, slug, kind, owner=None):
        """Filip tapped Finish (checklist) or Send to Claude / Send to session (doc)."""
        with self.lock:
            m = self._meta(slug)
            if kind == "finish":
                d = self._data(slug)
                d["finished_at"] = time.time()
                self._put(slug, d)
            ev = {"key": secrets.token_hex(6), "kind": kind, "slug": slug, "title": m["title"],
                  "at": time.time(), "summary": self._summary_line(slug), "todo": m.get("todo") or ""}
            if kind == "send":
                batch, ids = self._batch(slug)
                if not ids and not m.get("edited"):
                    raise ValueError("There are no new comments to send.")
                d = self._data(slug)
                for c in d["comments"]:
                    if c["id"] in ids:
                        c["sent"] = time.time()
                m["edited"] = False
                self._put(slug, d)
                ev.update(batch=batch, count=len(ids), owner=owner or m.get("owner") or {}, source=m.get("source", ""),
                          doc_kind=m["kind"], version=m.get("version", 1))
            self.events.append(ev)
            self._save("events.json", self.events)

    def todo_of(self, slug):
        with self.lock:
            return (self.index.get(slug) or {}).get("todo") or ""

    def result_phrase(self, slug) -> str:
        """"Done, 2 failed" for a finished checklist that belongs to a to-do item."""
        with self.lock:
            d = self._data(slug)
            items = [b for b in parse(self._text(slug)) if b["t"] == "item"]
            st = {k: v.get("status") for k, v in d["items"].items()}
            failed = sum(1 for b in items if st.get(str(b["id"])) == "fail")
            open_n = sum(1 for b in items if st.get(str(b["id"])) not in STATUSES)
            out = f"Done, {failed} failed" if failed else "Done, all passed"
            return out + (f", {open_n} not checked" if open_n else "")

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
        if m["kind"] != "checklist":
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
