"""Loop-agent views and the local-model chat for Mission Control (PC side, 0.20). Stdlib only, run with ``python -I``.

  python -I mc_loop.py serve          answer one Pi request (JSON in MC_ITEM: {key, kind, id?, n?}) and POST it
  python -I mc_loop.py chat <rid>     stream one chat answer from the local llama-server to the Pi (runs hidden)
  python -I mc_loop.py test           print the task list and the newest round, parsed (nothing is sent)

Everything that leaves the PC goes through ``redact()`` first. Reading secret-looking files and env dumps show as
``[hidden]``. Details: docs/loop-view.md.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = Path(os.environ.get("MC_HUB", r"D:\ai-hub"))
LLM_URL = os.environ.get("MC_LLM_URL", "http://127.0.0.1:8080")
ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{3}$")
RID_RE = re.compile(r"^[0-9a-f]{16}$")
MAX_TASKS = 30
MAX_ITEMS = 200
ITEM_CHARS = 2000
MAX_ROUND = 50
HIDDEN = "[hidden]"


def loop_dir(hub=None):
    return Path(hub or HUB) / "loop"


def valid_id(tid):
    return isinstance(tid, str) and bool(ID_RE.match(tid))


# ------------------------------------------------------------------ redaction

_RX = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)"), "[hidden private key]"),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"), "sk-" + HIDDEN),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "[hidden token]"),
    (re.compile(r"\b(?:AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}|xox[abprs]-[A-Za-z0-9\-]{10,})"), "[hidden token]"),
    # a token must hold a digit or punctuation, so plain words ("basic functionality") stay
    (re.compile(r"\b([Bb]earer|BEARER|Basic)(\s+)(?!\[hidden)(?=[A-Za-z._~+/=\-]*[0-9._~+/=\-])[A-Za-z0-9._~+/=\-]{12,}"), r"\1\2" + HIDDEN),
    (re.compile(r"(?i)\b([A-Za-z0-9_\-]*(?:api[_\-]?key|token|secret|passw(?:or)?d|pwd|access[_\-]?key|private[_\-]?key|credential)[A-Za-z0-9_\-]*)"
                r"(\"?'?\s*[:=]\s*\"?'?)(?!\[hidden)([^\s\"',;)}\]]{6,})"), r"\1\2" + HIDDEN),
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:)([^@\s/]+)(@)"), r"\1" + HIDDEN + r"\3"),
    (re.compile(r"\b[0-9a-fA-F]{41,}\b"), "[hidden hex]"),
]
_B64 = re.compile(r"[A-Za-z0-9+_\-]{32,}={0,2}")


def _b64_sub(m):
    s = m.group(0)
    if "--" in s:                                       # Claude's project folder names (D--ai-hub-loop-...)
        return s
    if re.search(r"[A-Z]", s) and re.search(r"[a-z]", s) and re.search(r"[0-9]", s):
        return "[hidden token]"
    return s


def redact(text):
    """Text with secret-looking values replaced. Runs before anything is cut or uploaded."""
    if not text:
        return "" if text is None else str(text)
    s = str(text)
    for rx, rep in _RX:
        s = rx.sub(rep, s)
    return _B64.sub(_b64_sub, s)


_SECRET_NAME = re.compile(
    r"(?i)^(?:\.env(?:\..*)?|.*\.env|secrets?(?:\..*|[-_].*)?|.*\.pass|.*\.keystore|.*\.jks|.*\.pem|.*\.key|.*\.p12|.*\.pfx"
    r"|credentials.*|\.credentials\.json|id_(?:rsa|ed25519|ecdsa|dsa).*|mc-pc\.json|mc-pi\.env|api-keys\.txt|\.prod-secrets"
    r"|.*\.secret|\.netrc|\.npmrc|\.pypirc|\.git-credentials)$")
_SECRET_DIR = re.compile(r"(?i)(?:^|[\\/])(?:\.ssh|\.gemini|secrets|\.aws|\.gnupg)(?:[\\/]|$)")
_ENV_DUMP = re.compile(r"(?i)(?:^|[;&|(]\s*)(?:env|printenv|set|export\s+-p|declare\s+-x|(?:Get-ChildItem|gci|dir|ls)\s+env:\\?\*?)\s*(?:$|[;&|)>])")


def secret_path(p):
    """True for a path whose contents must not leave the PC."""
    p = str(p or "").strip().strip("\"'")
    if not p:
        return False
    name = re.split(r"[\\/]", p)[-1]
    return bool(_SECRET_NAME.match(name) or _SECRET_DIR.search(p))


def secret_command(cmd):
    """True when a shell command dumps the environment or reads a secret-looking file."""
    cmd = str(cmd or "")
    if _ENV_DUMP.search(cmd):
        return True
    return any(secret_path(tok) for tok in re.split(r"[\s;&|<>()=`]+", cmd) if tok)


# ------------------------------------------------------------------ helpers

def _cut(text, n=ITEM_CHARS):
    return text if len(text) <= n else text[:n - 1] + "\u2026"


def _item(k, text, **extra):
    t = redact(text)
    it = {"k": k, "t": _cut(t)}
    if len(t) > ITEM_CHARS:
        it["full"] = len(t)
    it.update({a: b for a, b in extra.items() if b is not None})
    return it


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _epoch(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _repo(p):
    return re.split(r"[\\/]", str(p or "").rstrip("\\/"))[-1][:80]


def tool_summary(name, inp):
    """Short text for a tool call: the command for shells, the path (+ change) for file tools."""
    inp = inp if isinstance(inp, dict) else {}
    path = str(inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or "")
    if name in ("Bash", "PowerShell"):
        return str(inp.get("command") or "")
    if name == "Read":
        extra = " (from line %s)" % inp["offset"] if inp.get("offset") else ""
        return path + extra
    if name in ("Edit", "MultiEdit"):
        if secret_path(path):
            return path + "\n" + HIDDEN
        if name == "MultiEdit":
            return path + " (%d edits)" % len(inp.get("edits") or [])
        return "%s\n- %s\n+ %s" % (path, _cut(str(inp.get("old_string") or ""), 300), _cut(str(inp.get("new_string") or ""), 600))
    if name == "Write":
        return path + "\n" + (HIDDEN if secret_path(path) else _cut(str(inp.get("content") or ""), 600))
    if name in ("Glob", "Grep"):
        return str(inp.get("pattern") or "") + (" in " + path if path else "")
    try:
        return json.dumps(inp, ensure_ascii=False)[:600]
    except (TypeError, ValueError):
        return ""


def _result_text(content):
    if isinstance(content, str):
        return content
    out = []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(str(b.get("text") or ""))
        elif isinstance(b, dict) and b.get("type") == "image":
            out.append("[image]")
    return "\n".join(out)


def _hide_result(name, inp):
    inp = inp if isinstance(inp, dict) else {}
    if name in ("Bash", "PowerShell"):
        return secret_command(inp.get("command"))
    return secret_path(inp.get("file_path") or inp.get("path") or inp.get("notebook_path"))


# ------------------------------------------------------------------ transcript

def parse_round(lines):
    """Claude Code stream-json lines -> {items, total, skipped}. Unknown lines and a broken last line are skipped."""
    items, tools = [], {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue                                        # still being written, or damaged
        if not isinstance(d, dict):
            continue
        typ = d.get("type")
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        content = msg.get("content")
        if typ == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") in ("text", "thinking"):
                    txt = str(b.get("text") or b.get("thinking") or "").strip()
                    if txt:
                        items.append(_item("text", txt))
                elif b.get("type") == "tool_use":
                    name = str(b.get("name") or "tool")[:40]
                    tools[b.get("id")] = (name, b.get("input"))
                    items.append(_item("tool", tool_summary(name, b.get("input")), n=name))
        elif typ == "user" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue                                    # tool_use_result (the duplicate) is never read
                name, inp = tools.get(b.get("tool_use_id"), ("", None))
                txt = HIDDEN if _hide_result(name, inp) else _result_text(b.get("content"))
                items.append(_item("result", txt, e=True if b.get("is_error") else None))
        elif typ == "result":
            bits = [str(d.get("subtype") or "end")]
            if d.get("num_turns") is not None:
                bits.append("%s turns" % d.get("num_turns"))
            if isinstance(d.get("duration_ms"), (int, float)):
                bits.append("%d s" % round(d["duration_ms"] / 1000))
            if d.get("is_error"):
                bits.append("error")
            items.append(_item("end", " \u00b7 ".join(bits)))
    total = len(items)
    return {"items": items[-MAX_ITEMS:], "total": total, "skipped": max(0, total - MAX_ITEMS)}


# ------------------------------------------------------------------ tasks

def _running_ids(ld):
    try:
        return sorted((e.name for e in os.scandir(ld / "work") if e.is_dir() and valid_id(e.name)), reverse=True)
    except OSError:
        return []


def _status(hub, tid):
    """The loop's status.json, if it belongs to this task: (dict, mtime)."""
    p = Path(hub or HUB) / "state" / "local-agent" / "status.json"
    d = _read_json(p)
    if isinstance(d, dict) and str(d.get("task") or "").startswith(tid):
        try:
            return d, p.stat().st_mtime
        except OSError:
            return d, None
    return None, None


def _round_files(folder):
    out = []
    try:
        for e in os.scandir(folder):
            m = re.fullmatch(r"round-(\d+)\.jsonl", e.name)
            if m:
                out.append(int(m.group(1)))
    except OSError:
        pass
    return sorted(out)


def _summary(tid, task, result, running, hub, now):
    task = task if isinstance(task, dict) else {}
    result = result if isinstance(result, dict) else {}
    status = result.get("status") or task.get("status") or ("running" if running else "unknown")
    if running:
        st, mtime = _status(hub, tid)
        status = "running"
        if st and st.get("state") in ("failed", "done"):
            status = "finishing"
        elif mtime and now - mtime > 15 * 60:
            status = "stuck"
    return {"id": tid, "repo": _repo(result.get("repo") or task.get("repo")),
            "goal": _cut(redact(task.get("goal") or ""), 300), "status": str(status)[:20],
            "rounds": _int(result.get("rounds")) or _int(task.get("rounds_done")) or 0,
            "rounds_max": _int(task.get("rounds")) or 0,
            "reason": _cut(redact(result.get("reason") or ""), 300),
            "started": _epoch(result.get("started") or task.get("started")),
            "finished": _epoch(result.get("finished")), "model": str(result.get("model") or task.get("model") or "")[:40],
            "running": running}


def _paths(tid, hub=None):
    """(folder, task.json-ish dict, result dict or None, running) for a task id, or LookupError."""
    if not valid_id(tid):
        raise ValueError("bad task id")
    ld = loop_dir(hub)
    done = ld / "done" / tid
    if done.is_dir():
        return done, _read_json(done / "task.json"), _read_json(done / "result.json"), False
    work = ld / "work" / tid
    if work.is_dir():
        return work, _read_json(ld / "queue" / (tid + ".json")), None, True
    raise LookupError("task not found")


def list_tasks(hub=None, now=None, limit=MAX_TASKS):
    now = time.time() if now is None else now
    ld = loop_dir(hub)
    out = []
    running = _running_ids(ld)
    for tid in running:
        if not (ld / "done" / tid).is_dir():
            out.append(_summary(tid, _read_json(ld / "queue" / (tid + ".json")), None, True, hub, now))
    try:
        done = sorted((e.name for e in os.scandir(ld / "done") if e.is_dir() and valid_id(e.name)), reverse=True)
    except OSError:
        done = []
    for tid in done[:limit]:
        f = ld / "done" / tid
        out.append(_summary(tid, _read_json(f / "task.json"), _read_json(f / "result.json"), False, hub, now))
    return {"tasks": out}


def task_detail(tid, hub=None, now=None):
    now = time.time() if now is None else now
    folder, task, result, running = _paths(tid, hub)
    task = task if isinstance(task, dict) else {}
    result = result if isinstance(result, dict) else {}
    out = _summary(tid, task, result, running, hub, now)
    out.update({"check": _cut(redact(result.get("check") or task.get("check") or ""), 400),
                "total_seconds": _int(result.get("total_seconds"))})
    details = result.get("round_details") if isinstance(result.get("round_details"), list) else []
    if not details and isinstance(task.get("round_log"), list):
        details = task["round_log"]
    rounds = {}
    for r in details:
        if isinstance(r, dict) and _int(r.get("round")):
            n = _int(r.get("round"))
            rounds[n] = {"n": n, "turns": _int(r.get("turns")), "seconds": _int(r.get("agent_seconds")),
                         "check_exit": _int(r.get("check_exit")), "timed_out": r.get("timed_out") is True}
    for n in _round_files(folder):
        rounds.setdefault(n, {"n": n, "turns": None, "seconds": None, "check_exit": None, "timed_out": False})
    out["rounds"] = [rounds[n] for n in sorted(rounds) if 1 <= n <= MAX_ROUND]
    tail = result.get("check_output_tail") or task.get("last_out") or ""
    out["check_output_tail"] = redact(str(tail))[-1500:]
    reviews = []
    for rv in result.get("reviews") or task.get("reviews") or []:
        if isinstance(rv, dict):
            reviews.append({"n": _int(rv.get("n")), "verdict": str(rv.get("verdict") or "")[:20],
                            "notes": [_cut(redact(str(x)), 400) for x in (rv.get("notes") or [])[:8]]})
    out["reviews"] = reviews
    return out


def round_data(tid, n, hub=None):
    if not isinstance(n, int) or not 1 <= n <= MAX_ROUND:
        raise ValueError("bad round")
    folder, _, _, running = _paths(tid, hub)
    p = folder / ("round-%d.jsonl" % n)
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 30_000_000))                  # a huge round: its end is what matters
            text = f.read().decode("utf-8", "replace")
    except OSError:
        raise LookupError("round not found")
    r = parse_round(text.splitlines())
    r.update({"id": tid, "n": n, "running": running})
    return r


def agent_extra(task_text, hub=None):
    """For the Local AI card: id, planned rounds and the last check-output line of the running task (or {})."""
    m = re.match(r"^(\d{8}-\d{6}-[0-9a-f]{3})\b", str(task_text or ""))
    if not m:
        return {}
    tid = m.group(1)
    q = _read_json(loop_dir(hub) / "queue" / (tid + ".json"))
    q = q if isinstance(q, dict) else {}
    last = ""
    for line in reversed(str(q.get("last_out") or "").splitlines()):
        if line.strip():
            last = line.strip()
            break
    return {"id": tid, "rounds": _int(q.get("rounds")) or 0, "check_line": _cut(redact(last), 200) or None}


# ------------------------------------------------------------------ talking to the Pi

def config(path=None):
    p = Path(path or os.environ.get("MC_PC_CONFIG") or HERE / "mc-pc.json")
    d = _read_json(p)
    if not isinstance(d, dict) or not d.get("url") or not d.get("token"):
        raise RuntimeError("mc-pc.json missing or incomplete")
    return d


def pi(cfg, method, path, body=None, timeout=20):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(str(cfg["url"]).rstrip("/") + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + str(cfg["token"]), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", "replace")
    return json.loads(text) if text.strip() else {}


def tables_to_cards(text):
    """Markdown tables -> one bullet per row ('**id** - header: value, ...'); the Docs viewer has no table support."""
    out, rows = [], []

    def cells(l):
        return [c.strip() for c in l.strip().strip("|").split("|")]

    def flush():
        if len(rows) >= 2 and all(set(c) <= set("-: ") and c for c in cells(rows[1])):
            head = cells(rows[0])
            for r in rows[2:]:
                v = cells(r)
                out.append("- **" + (v[0] if v else "") + "**")
                for h, x in zip(head[1:], v[1:]):
                    out.append("  - " + h + ": " + x)
        else:
            out.extend(rows)
        rows.clear()

    for l in text.split("\n"):
        if l.lstrip().startswith("|"):
            rows.append(l)
        else:
            flush()
            out.append(l)
    flush()
    return "\n".join(out)


def morning_text(hub=None):
    p = Path(hub or HUB) / "files" / "loop-morning.md"
    try:
        return p, tables_to_cards(redact(p.read_text(encoding="utf-8-sig")))
    except OSError:
        raise LookupError("loop-morning.md does not exist yet (the loop runner writes it after a night run)")


def answer(item, hub=None, now=None):
    """The Pi request -> the body for POST /api/pc/loop (morning: also the doc upload, done by serve())."""
    if not isinstance(item, dict):
        raise ValueError("bad request")
    kind = item.get("kind")
    if kind == "tasks":
        return list_tasks(hub, now)
    if kind == "task":
        return task_detail(item.get("id"), hub, now)
    if kind == "round":
        return round_data(item.get("id"), _int(item.get("n")), hub)
    raise ValueError("unknown request")


def serve(item, cfg, hub=None, post=pi):
    key = str(item.get("key") or "")[:80] if isinstance(item, dict) else ""
    try:
        if isinstance(item, dict) and item.get("kind") == "morning":
            path, text = morning_text(hub)
            r = post(cfg, "POST", "/api/pc/docs/upload", {"kind": "doc", "name": "loop-morning.md", "text": text,
                                                          "source": str(path), "title": "Loop morning summary"})
            body = {"key": key, "ok": True, "data": {"slug": (r or {}).get("slug")}}
        else:
            body = {"key": key, "ok": True, "data": answer(item, hub)}
    except (LookupError, ValueError) as e:
        body = {"key": key, "ok": False, "detail": str(e).strip("'\"")}
    except Exception as e:                                         # noqa: BLE001 - the Pi shows the reason
        body = {"key": key, "ok": False, "detail": "PC error: %s" % e}
    post(cfg, "POST", "/api/pc/loop", body)
    return body


# ------------------------------------------------------------------ chat with the local model

def _llm_headers(cfg):
    h = {"Content-Type": "application/json"}
    if cfg.get("llm_key"):
        h["Authorization"] = "Bearer " + str(cfg["llm_key"])
    return h


def sse_deltas(lines):
    """Text pieces from an OpenAI-style SSE stream (llama-server). Reasoning deltas are left out."""
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            d = json.loads(data)
        except ValueError:
            continue
        ch = (d.get("choices") or [{}])[0] if isinstance(d, dict) else {}
        piece = (ch.get("delta") or {}).get("content") if isinstance(ch, dict) else None
        yield (piece or ""), (d.get("model") if isinstance(d, dict) else None)


def chat(rid, cfg, post=pi, open_url=urllib.request.urlopen, clock=time.monotonic, base=None):
    if not RID_RE.match(str(rid or "")):
        raise ValueError("bad chat id")
    req = post(cfg, "GET", "/api/pc/chat/" + rid)
    msgs = req.get("messages") or []
    max_tokens = int(req.get("max_tokens") or 800)
    limit = float(req.get("timeout_s") or 120)
    body = json.dumps({"messages": msgs, "max_tokens": max_tokens, "stream": True}).encode("utf-8")
    base = (base or LLM_URL).rstrip("/")
    text, model, start, last = "", None, clock(), 0.0
    try:
        r = open_url(urllib.request.Request(base + "/v1/chat/completions", data=body, method="POST", headers=_llm_headers(cfg)),
                     timeout=min(limit, 60))
    except urllib.error.HTTPError as e:
        post(cfg, "POST", "/api/pc/chat/" + rid, {"text": "", "error": "The model server answered %s" % e.code})
        return "error"
    except OSError:
        post(cfg, "POST", "/api/pc/chat/" + rid, {"text": "", "error": "The local model server is not running"})
        return "error"
    with r:
        for piece, m in sse_deltas(r):
            text += piece
            model = model or m
            now = clock()
            if now - start > limit:
                text += "\n\n(stopped: %d s limit)" % limit
                break
            if now - last >= 0.7:
                last = now
                if post(cfg, "POST", "/api/pc/chat/" + rid, {"text": text, "model": model}).get("stop"):
                    return "stopped"
    post(cfg, "POST", "/api/pc/chat/" + rid, {"text": text, "model": model, "done": True})
    return "done"


# ------------------------------------------------------------------ main

def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "test":
        tasks = list_tasks()["tasks"]
        print(json.dumps({"tasks": len(tasks), "first": tasks[:3]}, ensure_ascii=True, indent=1))
        if tasks:
            d = task_detail(tasks[0]["id"])
            print(json.dumps({k: d[k] for k in ("id", "status", "rounds", "check")}, ensure_ascii=True))
            if d["rounds"]:
                r = round_data(tasks[0]["id"], d["rounds"][-1]["n"])
                kinds = {}
                for it in r["items"]:
                    kinds[it["k"]] = kinds.get(it["k"], 0) + 1
                print(json.dumps({"round": r["n"], "total": r["total"], "kinds": kinds, "sample": r["items"][:4]}, ensure_ascii=True, indent=1))
        return 0
    cfg = config()
    if cmd == "serve":
        item = json.loads(os.environ.get("MC_ITEM") or "{}")
        body = serve(item, cfg)
        print(json.dumps({"ok": body["ok"], "detail": body.get("detail", "")}, ensure_ascii=True))
        return 0
    if cmd == "chat" and len(argv) > 2:
        try:
            print(chat(argv[2], cfg))
        except Exception as e:                                     # noqa: BLE001
            try:
                pi(cfg, "POST", "/api/pc/chat/" + argv[2], {"text": "", "error": "PC error: %s" % e})
            except Exception:                                      # noqa: BLE001
                pass
            return 1
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
