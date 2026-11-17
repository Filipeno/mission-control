"""mc_appgate: the Claude desktop app's own approval cards as phone gates (stage 11a-1).

mc_sessions.py adds one gate of kind "appcard" per pending card (see mc_appcard.py for how the cards are found in
main.log). The gate carries the tool, the session, the app's own session title, and the full tool input read from
the session transcript (the tool_use that has no tool_result yet), so a start_session brief is shown whole.

Filip's answer comes back through the Pi's PC inbox as {"kind": "appcard", "card": <request id>, "decision", "title",
"tool", "at"}. mc-pc.ps1 hands it to `python mc_appgate.py answer` (item JSON in env MC_ITEM, never argv), which:
  - refuses an answer older than 8 h ("expired"),
  - drops it when the card is no longer pending (answered or aborted at the PC: "gone"),
  - holds it while the PC is locked ("held": mc-pc keeps the item and tries again on the next poll),
  - otherwise runs mc-appcard.ps1 (all the spike's checks; title and card name go through env, never argv).
Prints one JSON object {"state": done|refused|held|expired|gone, "ok": bool|null, "detail": text}.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I leaves the script folder out of sys.path
import mc_appcard  # noqa: E402

HERE = Path(__file__).resolve().parent
PREFIX = "ac-"                       # gate id = "ac-" + the app's request id (the Pi tells app cards apart by it)
HOLD_S = 8 * 3600                    # Filip: an answer held for a locked PC expires after 8 h
MAX_INPUT = 38000                    # the Pi keeps gate input up to 40000 characters of JSON
TOOL_RE = re.compile(r"^[A-Za-z0-9_]{1,120}$")
UUID_RE = re.compile(r"^" + mc_appcard.UUID + r"$")
PS = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def gate_id(card_id: str) -> str:
    return PREFIX + card_id


def card_epoch(at: str) -> float:
    try:
        return time.mktime(time.strptime(at, "%Y-%m-%d %H:%M:%S"))      # main.log uses local time
    except (TypeError, ValueError):
        return time.time()


def find_input(open_blocks: list, tool: str):
    """The open tool_use of this tool in the transcript: (input, found). Found only when exactly ONE is open:
    with two the card could belong to either, so nothing is shown as "the request" (and the card is not answerable)."""
    mine = [b for b in (open_blocks or []) if isinstance(b, dict) and b.get("name") == tool]
    if len(mine) != 1:
        return {}, False
    inp = mine[0].get("input")
    return (inp if isinstance(inp, dict) else {}), True


def fit_input(inp: dict):
    """(input, truncated). Kept whole up to MAX_INPUT; longer string fields are cut so the rest still fits."""
    raw = json.dumps(inp, ensure_ascii=False)
    if len(raw) <= MAX_INPUT:
        return inp, False
    out = {}
    for k, v in inp.items():
        out[k] = v[:30000] + "\n… (cut, see the PC)" if isinstance(v, str) and len(v) > 30000 else v
    if len(json.dumps(out, ensure_ascii=False)) > MAX_INPUT:
        out = {k: (v[:4000] + "\n… (cut, see the PC)" if isinstance(v, str) and len(v) > 4000 else v) for k, v in out.items()}
    return out, True


def build_gates(cards: list, titles: dict, sessions: list, open_blocks_of) -> list:
    """Gates for the pending Allow/Deny cards.
    cards: mc_appcard.pending(...); titles: {local_id: app title}; sessions: mc_sessions' live session dicts
    (id, local, cwd, title); open_blocks_of(sid) -> open tool_use blocks of that session's transcript."""
    by_local = {s.get("local"): s for s in sessions if s.get("local")}
    out = []
    for c in cards:
        if c.get("tool") in mc_appcard.QUESTION_TOOLS or not UUID_RE.match(c.get("id", "")):
            continue
        s = by_local.get(c["session"]) or {}
        inp, found = find_input(open_blocks_of(s["id"]) if s.get("id") else [], c["tool"])
        inp, truncated = fit_input(inp)
        out.append({
            "id": gate_id(c["id"]), "kind": "appcard", "card": c["id"], "tool": c["tool"], "input": inp,
            "input_found": found, "truncated": truncated, "session_id": s.get("id", ""), "local": c["session"],
            "card_title": titles.get(c["session"], ""), "cwd": s.get("cwd", ""), "created": card_epoch(c.get("at", "")),
            "answerable": c["tool"] in mc_appcard.CARD_PHRASE and found,
        })
    return out


# ------------------------------------------------------------------ answering

def pc_locked() -> bool:
    """The lock screen (LogonUI.exe) is running: same test as mc-appcard.ps1."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq LogonUI.exe", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "logonui.exe" in r.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return True                                       # unknown: hold rather than click into a locked PC


def card_state(card_id: str) -> str:
    c = mc_appcard.parse(mc_appcard.read_log()).get(card_id)
    return c["state"] if c else "unknown"


def validate(item: dict) -> str:
    if not UUID_RE.match(str(item.get("card", ""))):
        return "bad card id"
    if item.get("decision") not in ("allow", "deny"):          # never "always"
        return "bad decision"
    if not TOOL_RE.match(str(item.get("tool", ""))):
        return "bad tool name"
    if not str(item.get("title", "")).strip():
        return "no session title"
    return ""


def decide(item: dict, now: float, locked, state_of) -> tuple:
    """What to do with an answer now: ("expired"|"gone"|"held"|"run"|"refused", detail).
    locked() and state_of(card_id) are passed in so tests need neither a lock screen nor a log."""
    bad = validate(item)
    if bad:
        return "refused", bad
    age = now - float(item.get("at") or 0)
    if age > HOLD_S:
        return "expired", "expired: the PC stayed locked for 8 h, nothing clicked"
    st = state_of(item["card"])
    if st != "pending":
        return "gone", "the card is no longer open at the PC (answered or closed there)" if st != "unknown" \
            else "the card is not in the app's log any more (app restarted?)"
    if locked():
        until = time.strftime("%H:%M", time.localtime(float(item.get("at") or now) + HOLD_S))
        return "held", f"waiting for unlock (expires {until})"
    return "run", ""


def run_answer(item: dict) -> tuple:
    """Runs mc-appcard.ps1 for this answer: (exit code, result dict)."""
    env = dict(os.environ, MC_EXPECT_TITLE=str(item["title"]))
    args = [str(PS), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "mc-appcard.ps1"),
            "-Answer", item["card"], "-Decision", item["decision"], "-ExpectTitleEnv", "-Tool", item["tool"]]
    try:
        r = subprocess.run(args, capture_output=True, timeout=120, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return 99, {"reason": "mc-appcard.ps1 timed out"}
    text = r.stdout.decode("utf-8", "replace").strip()
    res = {}
    for line in reversed(text.splitlines()):
        try:
            res = json.loads(line)
            break
        except ValueError:
            continue
    if not res:
        res = {"reason": (text or r.stderr.decode("utf-8", "replace"))[-300:] or "no output"}
    return r.returncode, res


def answer(item: dict, now=None, locked=pc_locked, state_of=card_state, run=run_answer) -> dict:
    act, detail = decide(item, time.time() if now is None else now, locked, state_of)
    if act == "held":
        return {"state": "held", "ok": None, "detail": detail}
    if act != "run":
        return {"state": act, "ok": False, "detail": detail}
    code, res = run(item)
    if code == 0 and res.get("ok"):
        how = "Allow once" if item["decision"] == "allow" else "Deny"
        m = re.match(r"\S+ (\d\d:\d\d:\d\d)", str(res.get("confirmedBy", "")))
        return {"state": "done", "ok": True,
                "detail": f"clicked {how} at the PC" + (f" ({m.group(1)})" if m else "") + (f", {res['method']}" if res.get("method") else "")}
    if code == 3:                                          # locked between the check and the click
        until = time.strftime("%H:%M", time.localtime(float(item.get("at") or 0) + HOLD_S))
        return {"state": "held", "ok": None, "detail": f"waiting for unlock (expires {until})"}
    return {"state": "refused", "ok": False, "detail": "refused: " + str(res.get("reason") or f"exit {code}")[:180]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["answer"]:
        try:
            item = json.loads(os.environ.get("MC_ITEM", "") or "{}")
        except ValueError:
            item = {}
        r = answer(item if isinstance(item, dict) else {})
    else:
        r = {"state": "refused", "ok": False, "detail": "usage: mc_appgate.py answer (item in env MC_ITEM)"}
    sys.stdout.buffer.write(json.dumps(r, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
