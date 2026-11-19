"""Local AI snapshot for Mission Control (PC side). Read-only, stdlib only, deliberately usable with ``python -I``.

``python -I mc_localai.py`` prints one JSON snapshot: PC mode, llama.cpp server state, GPU / CPU / RAM, the current
job (newest trial log + loop-agent status file) and the trials report. mc-pc.ps1 sends it to mc-pi every ~5 s while
the phone looks at the Local AI card.

Loop-agent status file (``D:\\ai-hub\\state\\local-agent\\status.json``), written by the future loop agent with
``write_status()`` (atomic) or by hand. JSON object::

    {"task": "fix the tests in X",          # string, what the loop works on (required)
     "step": "editing config.py",            # string or number, the current step (optional)
     "iteration": 3,                          # integer, loop round (optional, default 0)
     "last_check": {"cmd": "pytest -q",       # the last verification run (optional)
                    "ok": false,
                    "at": "2026-11-18T05:10:00"},   # ISO time (local if no zone) or unix seconds
     "started": "2026-11-18T05:00:00",        # ISO time or unix seconds
     "eta": "2026-11-18T05:30:00",            # optional, same formats
     "state": "running"}                      # optional: running (default) | done | failed

The card shows "no loop running" when the file is absent, unreadable, has no task, is in state done/failed or was
not touched for ``AGENT_STALE_S`` seconds.
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HUB = Path(os.environ.get("MC_HUB", r"D:\ai-hub"))
LLM = Path(os.environ.get("MC_LLM", r"D:\llm"))
LLM_URL = os.environ.get("MC_LLM_URL", "http://127.0.0.1:8080")
AGENT_STALE_S = 15 * 60
MODES = ("normal", "ai", "gaming")
MODELS = ("", "qwen", "gptoss")
SPEED_KEEP_S = 30           # the last measured speed stays visible this long after generation stops


def status_path(hub=None):
    return Path(hub or HUB) / "state" / "local-agent" / "status.json"


def report_path(hub=None):
    return Path(hub or HUB) / "files" / "local-agent-trials" / "report.md"


def logs_dir(llm=None):
    return Path(llm or LLM) / "trials" / "logs"


def mode_path(hub=None):
    return Path(hub or HUB) / "state" / "pc-mode.json"


def _epoch(value):
    """Unix seconds from a number or an ISO string (a string without a zone is local time)."""
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


def _num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ PC mode

def read_mode(path=None):
    d = _read_json(path or mode_path())
    if not isinstance(d, dict) or d.get("mode") not in MODES:
        return {"mode": None, "model": None, "since": None, "auto": False}
    model = d.get("model") if d.get("model") in MODELS and d.get("mode") == "ai" else None
    return {"mode": d["mode"], "model": model or None, "since": _epoch(d.get("since")), "auto": bool(d.get("auto"))}


# ------------------------------------------------------------------ loop-agent status

def parse_status(raw, mtime=None, now=None):
    """Validated status dict for the card, or None = "no loop running"."""
    now = time.time() if now is None else now
    if not isinstance(raw, dict):
        return None
    task = str(raw.get("task") or "").strip()
    if not task:
        return None
    state = str(raw.get("state") or "running").lower()
    if state not in ("running", "done", "failed"):
        state = "running"
    if state != "running":
        return None
    if mtime is not None and now - mtime > AGENT_STALE_S:
        return None
    lc = raw.get("last_check")
    last = None
    if isinstance(lc, dict) and str(lc.get("cmd") or "").strip():
        last = {"cmd": str(lc["cmd"])[:200], "ok": lc.get("ok") is True, "at": _epoch(lc.get("at"))}
    it = _num(raw.get("iteration"))
    return {"task": task[:200], "step": str(raw.get("step") if raw.get("step") is not None else "")[:200],
            "iteration": int(it) if it is not None and it >= 0 else 0, "last_check": last,
            "started": _epoch(raw.get("started")), "eta": _epoch(raw.get("eta")),
            "updated": mtime}


def read_status(path=None, now=None):
    p = Path(path or status_path())
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    return parse_status(_read_json(p), mtime, now)


def write_status(task, step="", iteration=0, last_check=None, started=None, eta=None, state="running", path=None):
    """Atomic writer for the loop agent: ``python -c "import mc_localai as m; m.write_status('task', 'step', 2)"``."""
    p = Path(path or status_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"task": task, "step": step, "iteration": iteration, "started": started or datetime.now().isoformat(timespec="seconds"),
            "state": state}
    if last_check:
        data["last_check"] = last_check
    if eta:
        data["eta"] = eta
    fd, tmp = tempfile.mkstemp(prefix=".status-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ------------------------------------------------------------------ trial logs, report

def tail_line(path, size=4096):
    """Last non-empty line of a file another process may still be writing; "" for an empty or unreadable one."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            f.seek(max(0, end - size))
            data = f.read()
    except OSError:
        return ""
    for line in reversed(data.decode("utf-8", "replace").splitlines()):
        if line.strip():
            return line.strip()[:200]
    return ""


def newest_log(directory=None):
    d = Path(directory or logs_dir())
    best, best_t = None, -1.0
    try:
        for e in os.scandir(d):
            if e.is_file():
                t = e.stat().st_mtime
                if t > best_t:
                    best, best_t = e, t
    except OSError:
        return None
    if best is None:
        return None
    return {"name": best.name, "line": tail_line(best.path), "at": best_t}


def report_info(path=None):
    p = Path(path or report_path())
    try:
        st = p.stat()
    except OSError:
        return {"exists": False, "at": None, "size": 0}
    return {"exists": True, "at": st.st_mtime, "size": st.st_size}


# ------------------------------------------------------------------ llama.cpp server

def _get(url, timeout=1.5):
    with urllib.request.urlopen(url, timeout=timeout) as r:      # 127.0.0.1 only
        return r.status, r.read(200_000).decode("utf-8", "replace")


def _slot_progress(slot):
    """(task id, tokens decoded so far) of one /slots entry; the field sits in next_token[0] in recent builds."""
    nt = slot.get("next_token")
    if isinstance(nt, list) and nt and isinstance(nt[0], dict):
        nt = nt[0]
    n = _num(nt.get("n_decoded")) if isinstance(nt, dict) else None
    if n is None:
        n = _num(slot.get("n_decoded"))
    return slot.get("id_task"), n


def parse_metrics(text):
    """predicted / prompt tokens per second from the Prometheus text of /metrics (only there with --metrics)."""
    out = {}
    for line in str(text).splitlines():
        if line.startswith("#") or " " not in line:
            continue
        name, _, val = line.partition(" ")
        if name.endswith("predicted_tokens_seconds"):
            out["tok_s"] = _num(val)
        elif name.endswith("prompt_tokens_seconds"):
            out["prompt_tok_s"] = _num(val)
    return out


def server_state(prev, now, base=None, get=_get):
    """(server dict, new speed memory). ``prev`` = {"task", "n", "t", "tok_s", "tok_at"} from the last sample."""
    base = (base or LLM_URL).rstrip("/")
    srv = {"state": "down", "model": None, "ctx": None, "slots": 0, "busy": 0, "tok_s": None, "prompt_tok_s": None, "speed_src": None}
    mem = {}
    try:
        code, _ = get(base + "/health")
    except Exception as e:                                      # refused / timeout: server not running
        reason = getattr(e, "code", None)
        if reason == 503:
            srv["state"] = "loading"
        return srv, mem or prev
    srv["state"] = "idle" if code == 200 else "loading"
    try:
        _, body = get(base + "/v1/models")
        data = json.loads(body).get("data") or []
        if data and isinstance(data[0], dict):
            srv["model"] = str(data[0].get("id") or "")[:60] or None
    except Exception:
        pass
    slots = []
    try:
        _, body = get(base + "/slots")
        v = json.loads(body)
        slots = [s for s in v if isinstance(s, dict)] if isinstance(v, list) else []
    except Exception:
        pass
    srv["slots"] = len(slots)
    srv["busy"] = sum(1 for s in slots if s.get("is_processing"))
    if slots:
        srv["ctx"] = int(_num(slots[0].get("n_ctx")) or 0) or None
        if srv["state"] == "idle" and srv["busy"]:
            srv["state"] = "busy"
    # speed: /metrics when the server runs with --metrics, else the decoded-token delta between two samples
    try:
        _, body = get(base + "/metrics")
        m = parse_metrics(body)
        if m.get("tok_s"):
            srv["tok_s"], srv["prompt_tok_s"], srv["speed_src"] = m["tok_s"], m.get("prompt_tok_s"), "metrics"
    except Exception:
        pass
    mem = {}
    busy_slot = next((s for s in slots if s.get("is_processing")), None)
    if busy_slot is not None:
        task, n = _slot_progress(busy_slot)
        if n is not None:
            mem = {"task": task, "n": n, "t": now}
            if srv["tok_s"] is None and prev and prev.get("task") == task and prev.get("n") is not None and now > prev.get("t", now):
                dn, dt = n - prev["n"], now - prev["t"]
                if dn > 0 and dt >= 0.5:
                    srv["tok_s"], srv["speed_src"] = round(dn / dt, 1), "slots"
                    mem["tok_s"], mem["tok_at"] = srv["tok_s"], now
    if srv["tok_s"] is None and prev and prev.get("tok_s") and now - prev.get("tok_at", 0) <= SPEED_KEEP_S:
        srv["tok_s"], srv["speed_src"] = prev["tok_s"], "slots"
        mem.setdefault("tok_s", prev["tok_s"]); mem.setdefault("tok_at", prev["tok_at"])
    return srv, mem


# ------------------------------------------------------------------ GPU / CPU / RAM

def gpu_stats():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return parse_gpu(out)
    except (OSError, subprocess.SubprocessError):
        return None


def parse_gpu(text):
    parts = [p.strip() for p in str(text).strip().splitlines()[0].split(",")] if str(text).strip() else []
    if len(parts) < 4:
        return None
    u, used, total, temp = (_num(p) for p in parts[:4])
    if total is None:
        return None
    return {"util": u, "mem_used_mb": used, "mem_total_mb": total, "temp": temp}


class _Mem(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def ram_stats():
    try:
        m = _Mem(); m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        used = (m.ullTotalPhys - m.ullAvailPhys) / 2 ** 30
        return {"used_gb": round(used, 1), "total_gb": round(m.ullTotalPhys / 2 ** 30, 1), "pct": float(m.dwMemoryLoad)}
    except (AttributeError, OSError):
        return None


def _cpu_times():
    class FT(ctypes.Structure):
        _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]
    idle, kern, user = FT(), FT(), FT()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    val = lambda f: (f.hi << 32) | f.lo
    return val(idle), val(kern) + val(user)       # kernel time includes idle


def cpu_percent(interval=0.25):
    try:
        i1, t1 = _cpu_times(); time.sleep(interval); i2, t2 = _cpu_times()
        total = t2 - t1
        return round(100.0 * (1 - (i2 - i1) / total), 1) if total > 0 else None
    except (AttributeError, OSError):
        return None


# ------------------------------------------------------------------ snapshot

def _state_file():
    return Path(tempfile.gettempdir()) / "mc-localai-state.json"


def agent_extra(agent, hub=None):
    """0.20: id, planned rounds and last check-output line of the running loop task (mc_loop.agent_extra)."""
    if not agent:
        return agent
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))      # -I leaves the script folder out of sys.path
        import mc_loop
        agent.update(mc_loop.agent_extra(agent.get("task"), hub))
    except Exception:                                                 # noqa: BLE001 - the card works without it
        pass
    return agent


def snapshot(now=None, prev=None, hub=None, llm=None, get=_get):
    now = time.time() if now is None else now
    srv, mem = server_state(prev, now, get=get)
    log = newest_log(logs_dir(llm))
    out = {"at": now, "mode": read_mode(mode_path(hub)), "server": srv, "gpu": gpu_stats(),
           "cpu_pct": cpu_percent(), "ram": ram_stats(),
           "job": {"log": log, "agent": agent_extra(read_status(status_path(hub), now), hub)},
           "report": report_info(report_path(hub))}
    return out, mem


def main(argv):
    if len(argv) > 1 and argv[1] == "mode":
        print(json.dumps(read_mode()))
        return
    sf = _state_file()
    prev = _read_json(sf) if sf.exists() else None
    snap, mem = snapshot(prev=prev if isinstance(prev, dict) else None)
    try:
        sf.write_text(json.dumps(mem), encoding="utf-8")
    except OSError:
        pass
    print(json.dumps(snap, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
