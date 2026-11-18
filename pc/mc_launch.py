"""Starting work from the phone (stage 11c): folder list and the Skola photo saver. Standard library only.

  python -I mc_launch.py folders      -> JSON {"projects": [...], "skola": [...]}
  python -I mc_launch.py skola-save   -> reads MC_ITEM {"key","subject","files":[{"path","name"}]}, prints JSON {"ok","detail",...}

Roots come from env MC_PROJECTS_ROOT / MC_SKOLA_ROOT (tests use temp folders; defaults are the real ones).
Files are written only under <Skola root>\\<subject>\\<new task folder>\\podklady\\ . The subject must be exactly
the name of a real sub-folder; the task folder name is made here; file names are sanitised; only pictures and PDFs
(checked by their first bytes) are accepted; nothing is ever overwritten.
"""
import json
import os
import re
import sys
import time

PROJECTS_ROOT = os.environ.get("MC_PROJECTS_ROOT", "D:\\projekty")
SKOLA_ROOT = os.environ.get("MC_SKOLA_ROOT", "D:\\\u0160kola")
MAX_FILES = 6
MAX_TOTAL = 25 * 1024 * 1024
SKIP_DIRS = {"node_modules", "__pycache__", "$recycle.bin", "system volume information"}
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MAGIC = {                                   # extension -> first-bytes check
    ".jpg": lambda b: b[:3] == b"\xff\xd8\xff", ".jpeg": lambda b: b[:3] == b"\xff\xd8\xff",
    ".png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n", ".pdf": lambda b: b[:5] == b"%PDF-",
    ".webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    ".heic": lambda b: b[4:8] == b"ftyp", ".heif": lambda b: b[4:8] == b"ftyp",
}


def list_dirs(root: str) -> list:
    try:
        names = os.listdir(root)
    except OSError:
        return []
    out = []
    for n in names:
        if n.startswith((".", "_")) or n.lower() in SKIP_DIRS:
            continue
        if os.path.isdir(os.path.join(root, n)):
            out.append(n)
    return sorted(out, key=str.lower)[:200]


def list_folders(projects_root: str = None, skola_root: str = None) -> dict:
    return {"projects": list_dirs(projects_root or PROJECTS_ROOT), "skola": list_dirs(skola_root or SKOLA_ROOT)}


def subject_dir(skola_root: str, subject: str) -> str:
    """The real folder of a subject, or raises ValueError. Exact name match against the listing, then a realpath check."""
    subject = str(subject or "")
    if not subject or subject != subject.strip() or any(c in subject for c in '/\\:*?"<>|\0') or subject in (".", ".."):
        raise ValueError("bad subject name")
    try:
        names = os.listdir(skola_root)
    except OSError:
        raise ValueError("Skola folder not found")
    if subject not in names:
        raise ValueError("unknown subject")
    root = os.path.realpath(skola_root)
    p = os.path.realpath(os.path.join(skola_root, subject))
    if not os.path.isdir(p) or os.path.dirname(p).lower() != root.lower():
        raise ValueError("subject is not a plain folder in Skola")
    return p


def safe_name(name: str, used: set, ext_ok: bool = True) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/")) or "file"
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if ext not in MAGIC:
        raise ValueError(f"file type {ext or '(none)'} is not accepted (pictures and PDF only)")
    stem = re.sub(r"[^\w .()\-]", "_", stem, flags=re.UNICODE).strip(" .")[:60] or "file"
    if stem.lower() in RESERVED:
        stem = "_" + stem
    cand, n = stem + ext, 2
    while cand.lower() in used:
        cand = f"{stem}-{n}{ext}"
        n += 1
    used.add(cand.lower())
    return cand


def task_folder_name(key: str, now: float = None) -> str:
    return time.strftime("Nov\u00e1 \u00faloha %Y-%m-%d %H%M", time.localtime(now if now is not None else time.time())) + "-" + re.sub(r"[^0-9a-f]", "", str(key).lower())[:4]


def save_podklady(skola_root: str, subject: str, key: str, files: list, now: float = None) -> dict:
    """Copy picked-up files into a new task folder. Safe to repeat with the same key: the existing folder is returned."""
    sdir = subject_dir(skola_root, subject)
    if not files or len(files) > MAX_FILES:
        raise ValueError(f"1 to {MAX_FILES} files please")
    key4 = re.sub(r"[^0-9a-f]", "", str(key).lower())[:4]
    if len(key4) < 4:
        raise ValueError("bad key")
    # Repeat of the same job (the PC retried after a failed callback): reuse the folder carrying this key.
    marker = f".mc-{str(key)[:16]}"
    for n in os.listdir(sdir):
        t = os.path.join(sdir, n)
        if n.startswith("Nov\u00e1 \u00faloha ") and os.path.isfile(os.path.join(t, "podklady", marker)):
            saved = sorted(f for f in os.listdir(os.path.join(t, "podklady")) if f != marker)
            return {"ok": True, "detail": "already saved", "folder": t, "task": n, "podklady": os.path.join(t, "podklady"), "saved": saved, "repeat": True}
    total = 0
    blobs = []
    used = set()
    for f in files:
        with open(f["path"], "rb") as fh:
            data = fh.read(MAX_TOTAL + 1)
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError("files are over 25 MB together")
        name = safe_name(f.get("name"), used)
        if not MAGIC[os.path.splitext(name)[1]](data):
            raise ValueError(f"{name}: the file content does not match its type")
        blobs.append((name, data))
    tname = task_folder_name(key, now)
    task = os.path.join(sdir, tname)
    pod = os.path.join(task, "podklady")
    n = 2
    while os.path.exists(task):
        task = os.path.join(sdir, f"{tname}-{n}")
        pod = os.path.join(task, "podklady")
        n += 1
    os.makedirs(pod)
    open(os.path.join(pod, marker), "wb").close()
    for name, data in blobs:
        with open(os.path.join(pod, name), "xb") as fh:
            fh.write(data)
    return {"ok": True, "detail": "saved", "folder": task, "task": os.path.basename(task), "podklady": pod, "saved": [b[0] for b in blobs]}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "folders":
            out = list_folders()
        elif cmd == "skola-save":
            it = json.loads(os.environ.get("MC_ITEM", "{}"))
            out = save_podklady(SKOLA_ROOT, it.get("subject"), it.get("key"), it.get("files") or [])
        else:
            out = {"ok": False, "detail": "unknown command"}
    except (ValueError, OSError, KeyError) as e:
        out = {"ok": False, "detail": str(e)[:200]}
    sys.stdout.buffer.write(json.dumps(out).encode("utf-8"))


if __name__ == "__main__":
    main(sys.argv)
