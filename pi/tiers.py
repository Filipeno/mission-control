"""How strongly an answer from the phone must be confirmed (Filip's decision 2026-11-19, option C).

Tiers:
  "0"  no fingerprint (a signature, if sent, must still be valid)
  "M"  the 5-minute window key (or the every-time key): one fingerprint opens a 5-minute window on the phone
  "H"  the every-time key: a fingerprint for this one answer

H always: change auto-approve, a new session in a non-default (or bypass) permission mode, key registration,
"Allow once" on a Claude app card, and Bash / PowerShell commands that match a destructive pattern
(rm/del -r, git push / force, deploy / publish / release, curl | sh, registry, money). When unsure: H.
Deny is 0 (a deny that carries text is M). Question option picks are 0, free text M.
"""
import json
import re

TIERS = ("0", "M", "H")
RANK = {"0": 0, "M": 1, "H": 2}

# Tools whose allow is routine (M). Anything else (MCP tools, unknown tools) is H unless listed below.
ROUTINE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep", "LS", "WebFetch", "WebSearch",
                 "TodoWrite", "Task", "Agent", "Skill", "BashOutput", "KillShell", "KillBash", "ExitPlanMode",
                 "AskUserQuestion", "mcp__ccd_session__set_session_model", "mcp__ccd_session__set_session_effort"}
SHELL_TOOLS = {"Bash", "PowerShell"}
# Session tools that carry a permission mode: M only for the default mode.
MODE_TOOLS = {"mcp__ccd_session__start_session", "mcp__ccd_session__set_session_permission_mode"}
MAX_COMMAND = 1500       # a longer command is not read with confidence: H

_I = re.IGNORECASE
DESTRUCTIVE = [(name, re.compile(rx, _I)) for name, rx in (
    # deleting things recursively / forcefully
    ("rm -r", r"\brm\s+(?:-\S*\s+)*-[a-z]*[rf]|\brm\s+(?:.*\s)?--(?:recursive|force)\b"),
    ("rmdir", r"\b(?:rmdir|rd)\b\s"),
    ("del /s", r"\b(?:del|erase)\b\s.*?/[sq]\b"),
    ("Remove-Item", r"\b(?:Remove-Item|ri|rm|del|erase|rd|rmdir)\b[^|;\n]*-(?:Recurse|r\b|Force)"),
    ("Remove-Item", r"\bRemove-Item\b"),
    ("find -delete", r"\bfind\b.*\s-delete\b|\bxargs\s+rm\b"),
    ("shred / wipe", r"\b(?:shred|wipe|mkfs\S*|diskpart|format(?:\.com)?\s+[a-z]:|Format-Volume|Clear-Disk|dd\s+if=)"),
    ("git destructive", r"\bgit\b.*\b(?:push\b|clean\s+-\S*f|reset\s+--hard\b|branch\s+-D\b|filter-branch\b|filter-repo\b|update-ref\s+-d\b)"),
    ("force", r"--force\b|--force-with-lease\b|\s\+\w+:\w+"),
    # shipping things
    ("deploy / publish / release", r"\b(?:deploy|publish|release|upload)\w*"),
    ("gh", r"\bgh\s+(?:release|repo\s+(?:create|delete|edit|rename)|pr\s+merge|secret|variable|workflow\s+run|api\b)"),
    ("package push", r"\b(?:npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bdocker\s+push\b|\bcargo\s+publish\b|\bwrangler\b"),
    # running code fetched from the net / hidden code
    ("curl | sh", r"\b(?:curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b.*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|iex|Invoke-Expression|pwsh|powershell|python\d?|node)\b"),
    ("eval", r"\b(?:iex|Invoke-Expression|eval)\b|-e(?:nc|ncodedcommand)?\s+[A-Za-z0-9+/=]{20,}|FromBase64String|base64\s+(?:-d|--decode)"),
    # system / registry / remote machines
    ("registry", r"\breg(?:\.exe)?\s+(?:add|delete|import|load|restore|copy)\b|\bregedit\b|HK(?:LM|CU|CR|U|CC)[:\\]|(?:Set|New|Remove|Rename)-ItemProperty\b|HKEY_"),
    ("system", r"\b(?:shutdown|Stop-Computer|Restart-Computer|schtasks|bcdedit|Set-ExecutionPolicy|netsh|Set-MpPreference|sc(?:\.exe)?\s+(?:stop|delete|config|create)|Stop-Service|Set-Service|New-Service|sudo|systemctl|chmod\s+-R|chown\s+-R|takeown|icacls)\b"),
    ("remote", r"\b(?:ssh|scp|rsync|sftp)\b"),
    # money
    ("money", r"(?<![a-z])(?:pay(?:ments?|pal)?|purchase|buy|stripe|trading[\s_-]?212|t212|invoices?|iban|bank(?:ing)?|withdraw\w*|transfer\s+\d|crypto|wallet|order\s+(?:create|place))(?![a-z])"),
)]


# Plain-language approvals (ai-hub questions) say "push it?" or "delete the old files?" rather than a command.
WORDS = re.compile(r"\b(?:push(?:es|ed|ing)?|force[ds]?|delete[sd]?|deleting|remove[sd]?|removing|wipe[sd]?|drop|erase|"
                   r"overwrite|reset|uninstall|format)\b", _I)


def destructive(text: str) -> str:
    """The name of the first destructive pattern found in [text], or ""."""
    for name, rx in DESTRUCTIVE:
        if rx.search(text or ""):
            return name
    return ""


def command_tier(command: str) -> str:
    """A shell command: H if it matches a destructive pattern or can't be read with confidence, else M."""
    c = str(command or "").strip()
    if not c or len(c) > MAX_COMMAND:
        return "H"
    return "H" if destructive(c) else "M"


def allow_tier(gate: dict) -> str:
    """The tier for allowing a phone-gate (permission or plan; app cards are always H)."""
    kind, tool = gate.get("kind"), str(gate.get("tool") or "")
    inp = gate.get("input") if isinstance(gate.get("input"), dict) else {}
    if kind == "appcard":
        return "H"
    if kind == "plan" or tool == "ExitPlanMode":
        return "M"
    if gate.get("truncated"):
        return "H"
    if tool in SHELL_TOOLS:
        return command_tier(inp.get("command"))
    if tool in MODE_TOOLS:
        mode = str(inp.get("permission_mode") or inp.get("mode") or "default")
        return "M" if mode == "default" and not destructive(json.dumps(inp, ensure_ascii=False)) else "H"
    if tool in ROUTINE_TOOLS:
        return "M"
    return "H"                                  # an MCP or unknown tool: unsure


def answer_tier(gate: dict, decision: str, payload: str) -> str:
    """The tier of one answer to a phone-gate (decision allow | deny | answer)."""
    if decision == "deny":
        return "M" if payload else "0"
    if decision == "allow":
        return allow_tier(gate)
    if decision == "answer":
        return question_tier(gate, payload)
    return "H"


def question_tier(gate: dict, payload: str) -> str:
    """0 when every answer is one (or, for multi-select, several comma-joined) of the offered option labels, else M."""
    try:
        answers = json.loads(payload)
    except ValueError:
        return "M"
    if not isinstance(answers, dict) or not answers:
        return "M"
    qs = (gate.get("input") or {}).get("questions") or []
    labels = {}
    for q in qs if isinstance(qs, list) else []:
        if isinstance(q, dict):
            labels[str(q.get("question", ""))] = {str((o or {}).get("label", "")) if isinstance(o, dict) else str(o)
                                                  for o in (q.get("options") or [])}
    for question, answer in answers.items():
        offered = labels.get(str(question))
        if not offered:
            return "M"
        a = str(answer)
        if a not in offered and not all(p.strip() in offered for p in a.split(",")):
            return "M"
    return "0"


def approval_tier(approval: dict, decision: str, option: str, text: str) -> str:
    """The tier of an answer to an ai-hub approval (Claude tab): approve | reject | option | reply."""
    if decision == "reject":
        return "M" if text else "0"
    if decision == "option":
        if text:
            return "M"
        return "H" if _risky(option) else "0"
    if decision == "reply":
        return "M"
    if decision == "approve":
        what = " ".join(str(approval.get(k) or "") for k in ("title", "text")) + " " + (text or "")
        return "H" if _risky(what) else "M"
    return "H"


def _risky(text: str) -> bool:
    return bool(destructive(text) or WORDS.search(text or ""))


def new_session_tier(permission: str) -> str:
    return "M" if permission == "default" else "H"
