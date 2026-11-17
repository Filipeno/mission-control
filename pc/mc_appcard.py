"""mc_appcard: finds the Claude desktop app's own pending approval cards in its main.log (stage 11a spike).

The desktop app logs every card it raises and how it ended:
  <ts> [info] Emitted tool permission request <id> for <tool> in session <local_id>
  <ts> [info] Received permission response for <id>: once|always|deny (tool: <tool>)
  <ts> [info] Permission request <id> for <tool> aborted
  <ts> [info] Starting app {            (a restart drops every card that was still open)
A card is pending when it was emitted after the last app start and has neither a response nor an abort line.
The log has no tool input; the session title comes from the app's own session files.

Commands (all print one JSON object):
  list                       pending cards with session titles
  check <id> [--expect-title T] [--tool T] [--since N] [--card-name NAME]
                             may this card be answered? {ok, reason, card}
                             (--since/--card-name: the re-check right before the click)
  offset                     current end of main.log (bytes), for "wait" and "confirm"
  wait --from N [--tool T] [--timeout S]
                             first card emitted after byte offset N
  confirm <id> --from N [--timeout S]
                             waits for the response line of <id> written after offset N
Read-only. Never touches the app.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE") or Path.home())
LOCALAPP = Path(os.environ.get("LOCALAPPDATA") or (HOME / "AppData" / "Local"))
LOG_DIR = LOCALAPP / "Claude" / "Logs"
DESKTOP_SESSIONS = LOCALAPP / "Claude-Data"            # <account>/claude-code-sessions/<org>/<user>/local_*.json
CLI_SESSIONS = HOME / ".claude" / "sessions"
QUESTION_TOOLS = {"AskUserQuestion"}                   # a question card, not Allow/Deny: never answered here

TS = r"(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
RE_EMIT = re.compile(TS + r" \[\w+\] Emitted tool permission request (?P<id>" + UUID +
                     r") for (?P<tool>\S+) in session (?P<session>local_" + UUID + r")\s*$")
RE_RESP = re.compile(TS + r" \[\w+\] Received permission response for (?P<id>" + UUID +
                     r"): (?P<decision>\w+)(?: \(tool: (?P<tool>[^)\s]+))?")
RE_ABORT = re.compile(TS + r" \[\w+\] Permission request (?P<id>" + UUID + r") for (?P<tool>\S+) aborted")
RE_START = re.compile(TS + r" \[\w+\] Starting app\b")


def parse(lines):
    """All cards since the last app start: {id: {id, tool, session, at, state, decision}} in log order."""
    cards = {}
    for line in lines:
        if "ermission" not in line and "Starting app" not in line:
            continue
        m = RE_START.match(line)
        if m:
            cards = {}                                   # the app restarted: older cards are gone
            continue
        m = RE_EMIT.match(line)
        if m:
            cards[m["id"]] = {"id": m["id"], "tool": m["tool"], "session": m["session"], "at": m["ts"],
                              "state": "pending", "decision": ""}
            continue
        m = RE_RESP.match(line)
        if m and m["id"] in cards:
            cards[m["id"]].update(state="answered", decision=m["decision"], answered_at=m["ts"])
            continue
        m = RE_ABORT.match(line)
        if m and m["id"] in cards:
            cards[m["id"]].update(state="aborted", answered_at=m["ts"])
    return cards


def pending(cards):
    return [c for c in cards.values() if c["state"] == "pending"]


# What the card itself says for a tool (UIA name of the card group, app 5.11492.5, seen live).
# A tool not listed here is refused at the pre-click check until its card has been seen and added.
CARD_PHRASE = {
    "mcp__ccd_session__start_session": "Permission request: start the session",
}


def card_matches(tool, card_name):
    phrase = CARD_PHRASE.get(tool)
    return bool(phrase) and norm(card_name).startswith(phrase)


def check(cards, request_id, titles, expect_title="", tool="", since_lines=None, card_name=None):
    """Decide whether <request_id> may be clicked. Returns (ok, reason, card).
    since_lines: log lines written since the button search began; any other card emitted for the
    same session in them means the window may show a different card now.
    card_name: the UIA name of the card that was found; it must fit the card's tool."""
    if not re.fullmatch(UUID, request_id or ""):
        return False, "bad request id", None
    c = cards.get(request_id)
    if not c:
        return False, "unknown request id (not in the log since the last app start)", None
    c = dict(c, title=titles.get(c["session"], ""))
    if c["state"] != "pending":
        return False, f"card already {c['state']}" + (f" ({c['decision']})" if c["decision"] else ""), c
    if c["tool"] in QUESTION_TOOLS:
        return False, f"{c['tool']} is a question card, not Allow/Deny", c
    if tool and c["tool"] != tool:
        return False, f"tool mismatch: card is {c['tool']}, expected {tool}", c
    if not c["title"]:
        return False, "session title unknown", c
    dupes = [s for s, t in titles.items() if norm(t) == norm(c["title"])]
    if len(dupes) > 1:
        return False, f"title '{c['title']}' is used by {len(dupes)} sessions", c
    if expect_title and norm(expect_title) != norm(c["title"]):
        return False, f"title mismatch: session is '{c['title']}', expected '{expect_title}'", c
    # Question cards have no Allow/Deny buttons, so they cannot be confused with this one.
    same = [p for p in pending(cards) if p["session"] == c["session"] and p["tool"] not in QUESTION_TOOLS]
    if len(same) != 1:
        return False, f"{len(same)} cards pending in that session (need exactly 1)", c
    if since_lines is not None:
        newer = [n for n in parse(since_lines).values() if n["session"] == c["session"] and n["id"] != c["id"]]
        if newer:
            return False, f"{len(newer)} new card(s) in that session since the search began", c
    if card_name is not None and not card_matches(c["tool"], card_name):
        return False, f"card on screen '{norm(card_name)[:120]}' does not fit {c['tool']}", c
    return True, "", c


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def read_log(log_dir=LOG_DIR):
    """main.log, plus main1.log when main.log has no app start yet (a card can be older than the rotation)."""
    lines = []
    main = Path(log_dir) / "main.log"
    data = _read(main)
    if "Starting app" not in data:
        lines += _read(Path(log_dir) / "main1.log").splitlines()
    lines += data.splitlines()
    return lines


def _read(p: Path, start=0):
    try:
        with open(p, "rb") as f:
            f.seek(start)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def titles_index():
    """local_<id> -> session title as the app shows it (its own session file), else the CLI session name."""
    out = {}
    for f in CLI_SESSIONS.glob("*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if s.get("hostSessionId") and s.get("name"):
            out[s["hostSessionId"]] = s["name"]
    for f in DESKTOP_SESSIONS.glob("*/claude-code-sessions/*/*/local_*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if s.get("isArchived"):
            out.pop(s.get("sessionId"), None)            # archived: never answered here, not a title clash
        elif s.get("sessionId") and s.get("title"):
            out[s["sessionId"]] = s["title"]
    return out


def log_size(log_dir=LOG_DIR):
    try:
        return (Path(log_dir) / "main.log").stat().st_size
    except OSError:
        return 0


def new_lines(log_dir, offset):
    size = log_size(log_dir)
    if size < offset:                                    # rotated: read the new file from the start
        offset = 0
    return _read(Path(log_dir) / "main.log", offset).splitlines()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "check", "offset", "wait", "confirm"])
    ap.add_argument("id", nargs="?", default="")
    ap.add_argument("--expect-title", default="")
    ap.add_argument("--tool", default="")
    ap.add_argument("--from", dest="offset", type=int, default=0)
    ap.add_argument("--since", type=int, default=-1, help="check: no other card for that session after this offset")
    ap.add_argument("--card-name", default=None, help="check: UIA name of the card on screen; must fit the tool")
    ap.add_argument("--timeout", type=float, default=10)
    ap.add_argument("--log-dir", default=str(LOG_DIR))
    ap.add_argument("--titles", default="", help="JSON file {local_id: title} instead of the app's files (tests)")
    a = ap.parse_args(argv)
    titles = json.loads(Path(a.titles).read_text(encoding="utf-8")) if a.titles else None

    if a.cmd == "offset":
        return out({"offset": log_size(a.log_dir)})
    if a.cmd == "list":
        t = titles if titles is not None else titles_index()
        cards = [dict(c, title=t.get(c["session"], "")) for c in pending(parse(read_log(a.log_dir)))]
        return out({"ok": True, "cards": cards})
    if a.cmd == "check":
        t = titles if titles is not None else titles_index()
        since = new_lines(a.log_dir, a.since) if a.since >= 0 else None
        ok, reason, c = check(parse(read_log(a.log_dir)), a.id, t, a.expect_title, a.tool, since, a.card_name)
        return out({"ok": ok, "reason": reason, "card": c})
    if a.cmd == "wait":
        end = time.time() + a.timeout
        while time.time() < end:
            for c in parse(new_lines(a.log_dir, a.offset)).values():
                if not a.tool or c["tool"] == a.tool:
                    t = titles if titles is not None else titles_index()
                    return out({"ok": True, "card": dict(c, title=t.get(c["session"], ""))})
            time.sleep(0.5)
        return out({"ok": False, "reason": "no new card"})
    if a.cmd == "confirm":
        end = time.time() + a.timeout
        while True:
            for line in new_lines(a.log_dir, a.offset):
                m = RE_RESP.match(line)
                if m and m["id"] == a.id:
                    return out({"ok": True, "decision": m["decision"], "line": line.strip()})
                m = RE_ABORT.match(line)
                if m and m["id"] == a.id:
                    return out({"ok": False, "reason": "card aborted", "line": line.strip()})
            if time.time() >= end:
                return out({"ok": False, "reason": "no response line within timeout"})
            time.sleep(0.3)


def out(obj):
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
