"""Laptop-as-second-host helpers for mc-pc (PC side). Stdlib only, meant for ``python -I``.

mc-pc.ps1 calls it with a verb and passes values in environment variables (never on a command line):

  report   env MC_STATUS = optional output of ``laptop-mode.ps1 status -Json``  -> the ``laptop`` block of the PC report
  app-ok   env MC_APP    = app name from the phone                              -> {"ok": true|false}
  result   env MC_ACTION (open|mode|clip|auto), MC_CODE (exit code), MC_OUT (script output), MC_MODE
                                                                                -> {"ok", "detail"} for Send-Result

Everything is read tolerantly: a missing or broken file or output becomes ``unknown`` / a plain failure text, never an
exception. The result detail never contains clipboard text, and a phone string never reaches a command line: the app
name must match laptop-apps.json exactly AND use a plain character set before mc-pc passes it as one argument.
"""
import json
import os
import re
import sys

LAPTOP_DIR = os.environ.get("MC_LAPTOP_DIR") or r"D:\projekty\pc-laptop"
MODES = ("monitor", "app", "own", "unknown")
SAFE_APP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ().,_+-]{0,59}$")
MAX_APPS = 20


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def mode_path():
    base = os.environ.get("MC_LAPTOP_STATE") or os.path.join(os.environ.get("LOCALAPPDATA") or "", "pc-laptop")
    return os.path.join(base, "mode.json")


def apps_path():
    return os.path.join(LAPTOP_DIR, "config", "laptop-apps.json")


def load_apps(path=None):
    """Names from laptop-apps.json that are safe to pass on (exactly as written in the file)."""
    d = _read_json(path or apps_path())
    out = []
    for a in d.get("apps", []) if isinstance(d, dict) and isinstance(d.get("apps"), list) else []:
        n = a.get("name") if isinstance(a, dict) else None
        if isinstance(n, str) and SAFE_APP.match(n) and n not in out:
            out.append(n)
    return out[:MAX_APPS]


def app_ok(name, path=None):
    return isinstance(name, str) and name in load_apps(path)


def _unix(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v == v and 1 <= v <= 4102444800:
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return _unix(int(v.strip()))
    return None


def parse_state(d):
    """mode / since / manual from a mode.json or a ``status -Json`` object; None when it holds no usable mode."""
    if not isinstance(d, dict):
        return None
    mode = str(d.get("mode") or "").strip().lower()
    if mode not in ("monitor", "app", "own"):
        return None
    return {"mode": mode, "mode_since": _unix(d.get("since")), "manual": d.get("manual") is True}


def parse_status(text):
    """Output of ``laptop-mode.ps1 status -Json`` (one JSON line, maybe with noise around it) -> dict or None."""
    for line in reversed(str(text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                return d
    return None


def build_report(status_text="", mode_file=None, apps_file=None):
    """The ``laptop`` block for POST /api/pc/report. mode.json is the fresh source for the mode; the (older) status
    run adds the monitor stream and is the fallback when mode.json is unreadable."""
    status = parse_status(status_text)
    st = parse_state(_read_json(mode_file or mode_path())) or parse_state(status) or \
        {"mode": "unknown", "mode_since": None, "manual": False}
    return {"mode": st["mode"], "mode_since": st["mode_since"], "manual": st["manual"], "apps": load_apps(apps_file),
            "monitor_stream": bool(status and status.get("monitor_stream") is True)}


def _clean(text, n=120):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or "")).strip()[:n]


def build_result(action, code, out, mode=""):
    """Send-Result payload for a finished laptop script. Never echoes clipboard text."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = 1
    out = str(out or "")
    if action == "clip":
        if code != 0:
            return {"ok": False, "detail": "clipboard not sent (exit %d)" % code}
        m = re.search(r"\b(\d{1,7})\s+char", out)
        return {"ok": True, "detail": "sent %s chars" % m.group(1) if m else "sent"}
    if action == "auto":
        return {"ok": code == 0, "detail": "auto on" if code == 0 else "auto failed (exit %d)" % code}
    d = parse_status(out)
    if action == "open":
        if isinstance(d, dict) and "ok" in d:
            return {"ok": d.get("ok") is True and code == 0, "detail": _clean(d.get("detail")) or ("opened" if code == 0 else "failed")}
        return {"ok": code == 0, "detail": "opened" if code == 0 else "failed (exit %d)" % code}
    if action == "mode":
        got = _clean(d.get("mode"), 10) if isinstance(d, dict) else ""
        shown = got if got in MODES else _clean(mode, 10)
        return {"ok": code == 0, "detail": ("mode=" + shown) if code == 0 else "mode switch failed (exit %d)" % code}
    return {"ok": False, "detail": "unknown action"}


def main(argv):
    verb = argv[1] if len(argv) > 1 else "report"
    env = os.environ.get
    if verb == "report":
        out = build_report(env("MC_STATUS", ""))
    elif verb == "app-ok":
        out = {"ok": app_ok(env("MC_APP", ""))}
    elif verb == "result":
        out = build_result(env("MC_ACTION", ""), env("MC_CODE", "1"), env("MC_OUT", ""), env("MC_MODE", ""))
    else:
        return 2
    sys.stdout.write(json.dumps(out, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
