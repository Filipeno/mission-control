"""Tiny RC queue helper, deliberately usable with ``python -I``."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def queue_path(hub=None):
    return Path(hub or os.environ.get("MC_HUB", r"D:\ai-hub")) / "state" / "rc-queue.json"


def read_queue(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def write_queue(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".rc-queue-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def append(path, item, now=None):
    if not isinstance(item, dict) or not str(item.get("id") or ""):
        raise ValueError("bad item")
    sid = str(item.get("local") or "")
    if not sid.startswith("local_"):
        sid = str(item["id"])
    rows = read_queue(path)
    if not any(r.get("session_id") == sid for r in rows if isinstance(r, dict)):
        rows.append({"session_id": sid, "id": str(item["id"]), "title": str(item.get("title") or "")[:200],
                     "queued_at": now or datetime.now(timezone.utc).isoformat()})
        write_queue(path, rows)
    return rows


def prune(path, live_sessions, now=None):
    live = {str(s.get("id")): s for s in live_sessions if isinstance(s, dict)}
    rows = [r for r in read_queue(path) if isinstance(r, dict) and r.get("id") in live and not live[r["id"]].get("rc")]
    write_queue(path, rows)
    return rows


def main():
    try:
        item = json.loads(os.environ.get("MC_ITEM", "{}"))
        append(queue_path(), item)
        print('{"ok":true,"detail":"queued"}')
    except (ValueError, TypeError) as e:
        print(json.dumps({"ok": False, "detail": str(e)}))


if __name__ == "__main__":
    main()
