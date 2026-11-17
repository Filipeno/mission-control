"""Stage 11b on the PC: open helper questions (and answering them) and the daily digest.

Usable with ``python -I``. Modes (first argument):
  questions         print the open helper questions as JSON
  answer            MC_ITEM = {"id", "text"}: run ask.ps1 -AnswerId, move the inbox file to done\\
  digest [DATE]     print the digest ({"date", "text", "counts"}) for today (or DATE)
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9]+$")
FILE_RE = re.compile(r"-question-([0-9]{8}-[0-9]{6}-[a-z0-9]+)\.md$")
MAX_ANSWER = 1000
MAX_SECTION_LINES = 25


def hub_dir():
    return Path(os.environ.get("MC_HUB", r"D:\ai-hub"))


# ------------------------------------------------------------------ helper questions

def _section(text, name):
    m = re.search(r"^## %s\s*\n(.*?)(?=^## |\Z)" % re.escape(name), text, re.S | re.M)
    return m.group(1).strip() if m else ""


def list_questions(hub=None):
    """Open questions: a ``-question-<id>.md`` message in inbox\\claude that has a saved job in state\\questions."""
    hub = Path(hub or hub_dir())
    inbox = hub / "inbox" / "claude"
    out = []
    for f in sorted(inbox.glob("*-question-*.md")):
        m = FILE_RE.search(f.name)
        if not m or not (hub / "state" / "questions" / (m.group(1) + ".json")).exists():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        who = re.search(r"^From:\s*(\S+)", text, re.M)
        out.append({"id": m.group(1), "helper": (who.group(1) if who else m.group(1).split("-")[-1])[:20],
                    "question": _section(text, "Question")[:600],
                    "task": " ".join(_section(text, "Original task").split())[:240],
                    "at": f.stat().st_mtime})
    return out


def answer_question(hub, qid, text, runner=None):
    """Start ``ask.ps1 -AnswerId`` (it re-runs the job: minutes) and move the inbox file to done\\ right away."""
    hub = Path(hub)
    qid, text = str(qid or ""), " ".join(str(text or "").split())
    if not ID_RE.match(qid):
        return {"ok": False, "detail": "bad question id"}
    if not text or len(text) > MAX_ANSWER:
        return {"ok": False, "detail": "answer must be 1-%d characters" % MAX_ANSWER}
    if not (hub / "state" / "questions" / (qid + ".json")).exists():
        return {"ok": False, "detail": "no open question with that id (already answered?)"}
    files = [f for f in (hub / "inbox" / "claude").glob("*-question-%s.md" % qid)]
    if not files:
        return {"ok": False, "detail": "question message not found"}
    ask = hub / "bin" / "ask.ps1"
    shell = os.environ.get("MC_PWSH", "pwsh")
    # -Answer: with a colon so an answer that starts with a dash is still a value
    cmd = [shell, "-NoProfile", "-File", str(ask), "-AnswerId", qid, "-Answer:" + text]
    log = hub / "state" / ("mc-answer-%s.log" % qid)
    try:
        (runner or _spawn)(cmd, log)
    except OSError as e:
        return {"ok": False, "detail": "could not start ask.ps1: %s" % e}
    done = hub / "inbox" / "claude" / "done"
    done.mkdir(parents=True, exist_ok=True)
    for f in files:
        os.replace(f, done / f.name)
    return {"ok": True, "detail": "answer sent to the helper"}


def _spawn(cmd, log):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    with open(log, "ab") as f:
        subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)


# ------------------------------------------------------------------ daily digest

def worklog_lines(paths, date):
    """One-line entries dated ``date`` (``- YYYY-MM-DD HH:MM · ...``). Only the file tail is read; duplicates dropped."""
    seen, out = set(), []
    for p in paths:
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 96 * 1024))
                text = f.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        proj = Path(p).parent.name
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("- " + date):
                continue
            body = line[2:].split(" · ", 1)
            key = (body[1] if len(body) > 1 else line)[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append((line[2:18], proj, body[1].strip() if len(body) > 1 else line[2:]))
    return sorted(out)


def _git(repo, *args, timeout=15):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def git_today(repos, date):
    """(commits, releases): commits as (repo, hash, subject), releases as (repo, tag). Linked worktrees are skipped."""
    d0 = datetime.strptime(date, "%Y-%m-%d")
    since, until = d0.strftime("%Y-%m-%d 00:00"), (d0 + timedelta(days=1)).strftime("%Y-%m-%d 00:00")
    commits, tags = [], []
    for repo in repos:
        repo = Path(repo)
        if not (repo / ".git").is_dir():
            continue
        for line in _git(repo, "log", "--branches", "--since=" + since, "--until=" + until, "--format=%h\x1f%s").splitlines():
            h, _, s = line.partition("\x1f")
            commits.append((repo.name, h, s.strip()))
        for line in _git(repo, "tag", "--list", "--format=%(refname:short)\x1f%(creatordate:short)").splitlines():
            t, _, day = line.partition("\x1f")
            if day.strip() == date:
                tags.append((repo.name, t))
    return commits, tags


def _fmt_reset(epoch, now):
    if not epoch:
        return ""
    s = int(epoch - now)
    if s <= 0:
        return ""
    return " (resets in %dh %02dm)" % (s // 3600, s % 3600 // 60) if s < 86400 else " (resets in %dd %dh)" % (s // 86400, s % 86400 // 3600)


def usage_lines(usage, now=None):
    """Lines from ``usage.ps1 -Json`` (dict); tolerant of missing parts."""
    now = now or time.time()
    out = []
    usage = usage if isinstance(usage, dict) else {}
    wins = (usage.get("claude") or {}).get("windows")
    for w in wins if isinstance(wins, list) else []:
        label = {"five_hour": "Claude 5-hour", "seven_day": "Claude weekly"}.get((w or {}).get("window"))
        if label and isinstance(w.get("used_percent"), (int, float)):
            out.append("%s: %d%% used" % (label, round(w["used_percent"])))
    cw = (usage.get("codex") or {}).get("windows")
    cw = cw[0] if isinstance(cw, list) and cw else None
    if isinstance(cw, dict) and isinstance(cw.get("used_percent"), (int, float)):
        out.append("Codex: %d%% used%s" % (round(cw["used_percent"]), _fmt_reset(cw.get("resets_epoch"), now)))
    for key, label in (("gemini_app", "Gemini app"), ("perplexity", "Perplexity")):
        v = usage.get(key)
        if isinstance(v, dict) and isinstance(v.get("jobs_today"), (int, float)) and isinstance(v.get("daily_cap"), (int, float)):
            out.append("%s: %d of %d jobs left today" % (label, max(0, v["daily_cap"] - v["jobs_today"]), v["daily_cap"]))
    parked = usage.get("parked")
    if parked:
        out.append("Parked helpers: " + ", ".join(str(p) for p in (parked if isinstance(parked, list) else [parked])))
    return out


def load_usage(hub, shell=None):
    """Everything ``usage.ps1 -Json`` prints; {} when it is missing or fails."""
    script = Path(hub) / "bin" / "usage.ps1"
    if not script.exists():
        return {}
    try:
        r = subprocess.run([shell or os.environ.get("MC_PWSH", "pwsh"), "-NoProfile", "-File", str(script), "-Json"],
                           capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        value = json.loads(r.stdout.lstrip("﻿") or "{}")
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _short(t):
    """A worklog entry is ``[type] request -> result . files``: drop the file list and cap the length."""
    if "→" in t and " · " in t:
        t = t.rsplit(" · ", 1)[0]
    return t if len(t) <= 160 else t[:157] + "…"


def build_digest(date, work, commits, tags, usage, now=None):
    """Markdown digest. The Pi adds the "Waiting for you" part (it owns to-dos, approvals, questions)."""
    def cap(lines):
        lines = list(lines)
        if len(lines) > MAX_SECTION_LINES:
            lines = lines[:MAX_SECTION_LINES] + ["…and %d more" % (len(lines) - MAX_SECTION_LINES)]
        return lines

    out = ["# Daily digest %s" % date, ""]
    out += ["## Done today (%d)" % len(work)]
    out += cap("- [%s] %s" % (p, _short(t)) for _t, p, t in work) or ["- Nothing logged."]
    out += ["", "## Commits (%d)" % len(commits)]
    byrepo = {}
    for r, h, s in commits:
        byrepo.setdefault(r, []).append("%s %s" % (h, s[:100]))
    lines = []
    for r, items in byrepo.items():
        lines.append("- %s: %d" % (r, len(items)))
        lines += ["  - " + i for i in items[:4]]
        if len(items) > 4:
            lines.append("  - …and %d more" % (len(items) - 4))
    out += cap(lines) or ["- None."]
    out += ["", "## Releases (%d)" % len(tags)]
    out += ["- %s %s" % (r, t) for r, t in tags] or ["- None."]
    out += ["", "## Usage left"]
    out += ["- " + u for u in usage_lines(usage, now)] or ["- No usage data."]
    short = []
    for u in usage_lines(usage, now):
        if u.startswith(("Claude", "Codex")):
            name, _, rest = u.partition(": ")
            short.append("%s %s" % (name.replace("Claude ", "").replace("-hour", "h"), rest.split(" used")[0]))
    summary = " · ".join(["%d done" % len(work), "%d commits" % len(commits), "%d releases" % len(tags)]
                         + (["used: " + ", ".join(short)] if short else []))
    return {"date": date, "text": "\n".join(out) + "\n", "summary": summary,
            "counts": {"tasks": len(work), "commits": len(commits), "releases": len(tags)}}


def compute(date=None, hub=None, projects=r"D:\projekty", skola="D:\\" + "Škola", usage=None):
    hub = Path(hub or hub_dir())
    date = date or datetime.now().strftime("%Y-%m-%d")
    proj = Path(projects)
    repos = sorted(p for p in proj.iterdir() if p.is_dir()) if proj.is_dir() else []
    logs = [p / "WORKLOG.md" for p in repos] + [proj / "WORKLOG.md"]
    sk = Path(skola)
    if sk.is_dir():
        logs += [sk / "WORKLOG.md"] + [p / "WORKLOG.md" for p in sorted(sk.iterdir()) if p.is_dir()]
    work = worklog_lines([p for p in logs if p.exists()], date)
    commits, tags = git_today(repos, date)
    return build_digest(date, work, commits, tags, usage if usage is not None else load_usage(hub))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if mode == "questions":
        print(json.dumps(list_questions()))
    elif mode == "answer":
        try:
            item = json.loads(os.environ.get("MC_ITEM", "{}"))
            print(json.dumps(answer_question(hub_dir(), item.get("id"), item.get("text"))))
        except (ValueError, TypeError) as e:
            print(json.dumps({"ok": False, "detail": str(e)}))
    elif mode == "digest":
        print(json.dumps(compute(sys.argv[2] if len(sys.argv) > 2 else None)))


if __name__ == "__main__":
    main()
