"""mc_sessions: snapshot of live Claude Code sessions for Mission Control (run by mc-pc every few seconds).

Prints one JSON object to stdout:
  sessions  live sessions from ~/.claude/sessions (title, folder, status, what it waits for, last activity)
  gates     open requests of the phone-gate hook (D:\\ai-hub\\gate\\pending), exact tool input included
  proposals "start a new session" cards a session proposed and nobody has started or withdrawn yet
  watch     (with --watch <sessionId>) the last activity rows of that one session
Everything is read-only. Transcripts are read on the PC; only short rows go to the Pi.
"""
import argparse
import ctypes
import json
import os
import re
import sys
import time
from ctypes import wintypes
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE") or Path.home())
SESSIONS = HOME / ".claude" / "sessions"
PROJECTS = HOME / ".claude" / "projects"
GATE = Path(r"D:\ai-hub\gate")
TAIL_LIST = 4 * 1024 * 1024     # bytes read from a changed transcript for the list (huge request-blob lines are skipped unparsed)
TAIL_WATCH = 6 * 1024 * 1024    # bytes read for the open session (tool results with pictures are huge)
MAX_LINE = 256 * 1024           # longer transcript lines (pictures, big tool output) are skipped unparsed
MAX_ROWS = 80
PROPOSAL_DAYS = 7
START_TOOL = "mcp__ccd_session__start_session"
DISMISS_TOOL = "mcp__ccd_session__dismiss_task"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]


def process_name(pid: int) -> str:
    h = k32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        k32.CloseHandle(h)


def cut(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def read_tail(path: Path, nbytes: int) -> list:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > nbytes:
                f.seek(size - nbytes)
                f.readline()                                 # drop the partial first line
            data = f.read()
    except OSError:
        return []
    out = []
    for line in data.split(b"\n"):
        if not line.strip() or line.startswith(b'{"type":"api-request'):
            continue
        if len(line) > MAX_LINE:
            m = re.search(rb'"tool_use_id":"([^"]+)"', line[:4096])
            if m:                                            # keep the "this tool finished" fact, drop the payload
                out.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": m.group(1).decode(), "content": "(large output)"}]}})
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def ts(e) -> float:
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(e.get("timestamp")).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def tool_summary(name: str, inp: dict) -> str:
    inp = inp if isinstance(inp, dict) else {}
    short = re.sub(r"^mcp__.+__", "", name).replace("_", " ").replace("-", " ").strip().capitalize() or name
    if name in ("Bash", "PowerShell"):
        if inp.get("description"):
            return f"{name}: {cut(inp.get('description'), 120)}"
        return f"{name}: {cut(inp.get('command'), 160)}"
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        p = str(inp.get("file_path") or inp.get("notebook_path") or "")
        return f"{name}: {os.path.basename(p) or p}"
    if name in ("Grep", "Glob"):
        return f"{name}: {cut(inp.get('pattern'), 100)}"
    if name in ("Agent", "Task"):
        return f"Subagent: {cut(inp.get('description'), 100)}"
    if name == "WebSearch":
        return f"Web search: {cut(inp.get('query'), 100)}"
    if name == "WebFetch":
        return f"Web page: {cut(inp.get('url'), 100)}"
    if name == "AskUserQuestion":
        qs = inp.get("questions") or []
        return "Question: " + cut(qs[0].get("question") if qs else "", 140)
    if name == START_TOOL:
        return f"Proposes a session: {cut(inp.get('title'), 100)}"
    if name == "mcp__ccd_turn__update_plan" or name == "mcp__ccd_turn__wrap_up":
        return ""
    return short


def find_transcript(sid: str):
    for p in PROJECTS.glob(f"*/{sid}.jsonl"):
        return p
    return None


def build_rows(entries: list) -> tuple:
    """Activity rows + tool_use ids that have no result yet."""
    rows, by_id, open_ids = [], {}, {}
    for e in entries:
        t = e.get("type")
        if t not in ("user", "assistant") or e.get("isMeta"):
            continue
        msg = e.get("message") or {}
        content = msg.get("content")
        at = ts(e)
        if t == "user":
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tid = b.get("tool_use_id")
                        open_ids.pop(tid, None)
                        r = by_id.get(tid)
                        if r is not None:
                            res = b.get("content")
                            first = text_of(res) if not isinstance(res, str) else res
                            r["result"] = cut(first, 200)
                            r["error"] = bool(b.get("is_error"))
            txt = text_of(content).strip()
            if txt and not txt.startswith("<"):
                rows.append({"role": "user", "text": txt[:1500], "at": at})
            elif txt.startswith("<cross-session-message"):
                rows.append({"role": "note", "text": "Message from another session", "at": at})
        else:
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    rows.append({"role": "claude", "text": b["text"].strip()[:1500], "at": at})
                elif b.get("type") == "tool_use":
                    s = tool_summary(b.get("name", ""), b.get("input"))
                    open_ids[b.get("id")] = b
                    if not s:
                        continue
                    r = {"role": "tool", "text": s, "at": at, "tool": b.get("name", "")}
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    if b.get("name") in ("Bash", "PowerShell") and inp.get("command"):
                        r["detail"] = str(inp["command"])[:600]
                    by_id[b.get("id")] = r
                    rows.append(r)
    return rows, open_ids


def proposals_from(entries: list, sid: str, title: str, cwd: str) -> list:
    props, dismissed, started = {}, set(), set()
    pending_use = {}
    for e in entries:
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == START_TOOL:
                inp = b.get("input") or {}
                if inp.get("proposal_id"):
                    started.add(str(inp["proposal_id"]))
                elif inp.get("initiation") in ("own_initiative", "offer"):
                    pending_use[b.get("id")] = (inp, ts(e))
            elif b.get("type") == "tool_use" and b.get("name") == DISMISS_TOOL:
                dismissed.add(str((b.get("input") or {}).get("task_id")))
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in pending_use:
                inp, at = pending_use.pop(b["tool_use_id"])
                res = text_of(b.get("content")) if not isinstance(b.get("content"), str) else b.get("content")
                m = re.search(r"\b(task_[0-9a-f]{6,})\b", res or "")
                if m and inp.get("initiation") == "own_initiative":
                    props[m.group(1)] = (inp, at)
    out = []
    now = time.time()
    for tid, (inp, at) in props.items():
        if tid in dismissed or tid in started or now - at > PROPOSAL_DAYS * 86400:
            continue
        out.append({"key": tid, "session_id": sid, "session": title, "title": cut(inp.get("title"), 120),
                    "prompt": str(inp.get("prompt") or "")[:6000], "folder": inp.get("cwd") or cwd,
                    "model": inp.get("model") or "", "context": inp.get("context") or "", "at": at})
    # An "offer" card waits inside the desktop app until it is answered there.
    for _id, (inp, at) in pending_use.items():
        if inp.get("initiation") == "offer":
            out.append({"key": f"offer-{_id[-10:]}", "session_id": sid, "session": title, "offer": True,
                        "title": cut(inp.get("title"), 120), "prompt": str(inp.get("prompt") or "")[:6000],
                        "folder": inp.get("cwd") or cwd, "model": inp.get("model") or "", "at": at})
    return out


def live_sessions():
    out = []
    for f in SESSIONS.glob("*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not s.get("pid") or process_name(s["pid"]) != "claude.exe":
            continue
        out.append(s)
    return out


def gates() -> list:
    out = []
    for f in sorted((GATE / "pending").glob("*.json")):
        try:
            g = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if process_name(g.get("pid", 0)) not in ("python.exe", "pythonw.exe", "py.exe"):
            try:
                f.unlink()                                   # the hook is gone (answered at the PC)
            except OSError:
                pass
            continue
        inp = g.get("input") or {}
        raw = json.dumps(inp, ensure_ascii=False)
        g["truncated"] = len(raw) > 20000
        if g["truncated"]:
            g["input"] = {k: (v[:8000] + "\n… (cut, see the PC)" if isinstance(v, str) and len(v) > 8000 else v)
                          for k, v in inp.items()}
        g.pop("transcript", None)
        out.append(g)
    # Answers nobody waits for any more (the PC answered first) are cleaned up after 10 min.
    for f in (GATE / "answered").glob("*.json"):
        try:
            if time.time() - f.stat().st_mtime > 600:
                f.unlink()
        except OSError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    result = {"sessions": [], "gates": gates(), "proposals": [], "at": time.time()}
    cache_path = Path(os.environ.get("TEMP") or ".") / "mc-sessions-cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    new_cache = {}
    for s in live_sessions():
        sid = s.get("sessionId")
        tp = find_transcript(sid)
        try:
            st = tp.stat() if tp else None
            stamp = [st.st_size, int(st.st_mtime)] if st else [0, 0]
        except OSError:
            stamp = [0, 0]
        c = cache.get(sid)
        if c and c.get("stamp") == stamp and sid != a.watch:
            d = c["data"]                                    # transcript unchanged: reuse what was derived from it
        else:
            entries = read_tail(tp, TAIL_WATCH if sid == a.watch else TAIL_LIST) if tp else []
            rows, open_ids = build_rows(entries)
            first_user = next((r["text"] for r in rows if r["role"] == "user"), "")
            last = next((r for r in reversed(rows) if r["role"] in ("claude", "tool", "user")), None)
            pending = None
            if open_ids:
                b = list(open_ids.values())[-1]
                if b.get("name") == "AskUserQuestion":
                    pending = {"type": "question", "questions": (b.get("input") or {}).get("questions") or []}
                else:
                    pending = {"type": "permission", "tool": b.get("name"), "summary": tool_summary(b.get("name", ""), b.get("input"))}
            title0 = s.get("name") if s.get("nameSource") != "derived" and s.get("name") else (cut(first_user, 80) or s.get("name") or "Claude")
            d = {"title": cut(title0, 100), "pending": pending, "last": cut(last["text"], 160) if last else "",
                 "last_role": last["role"] if last else "", "rows_at": rows[-1]["at"] if rows else 0,
                 "proposals": proposals_from(entries, sid, cut(title0, 100), s.get("cwd") or "")}
            if sid == a.watch:
                result["watch"] = {"id": sid, "rows": rows[-MAX_ROWS:]}
        new_cache[sid] = {"stamp": stamp, "data": d}
        status = s.get("status") or "idle"
        waiting = s.get("waitingFor") or ""
        state = "waiting" if waiting else ("working" if status == "busy" else "idle")
        result["sessions"].append({
            "id": sid, "local": s.get("hostSessionId") or "", "title": d["title"], "cwd": s.get("cwd") or "",
            "state": state, "waiting_for": waiting, "kind": {"claude-desktop": "desktop", "sdk-cli": "remote"}.get(s.get("entrypoint"), "cli"),
            "rc": bool(s.get("bridgeSessionId")), "rc_id": s.get("bridgeSessionId") or "",
            "updated": max((s.get("statusUpdatedAt") or s.get("updatedAt") or 0) / 1000, d["rows_at"]),
            "last": d["last"], "last_role": d["last_role"], "pending": d["pending"] if waiting else None,
        })
        result["proposals"] += d["proposals"]
    try:
        cache_path.write_text(json.dumps(new_cache), encoding="utf-8")
    except OSError:
        pass
    if a.watch and "watch" not in result:
        result["watch"] = {"id": a.watch, "rows": [], "gone": True}
    data = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if a.out:
        tmp = a.out + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, a.out)
    else:
        sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()
