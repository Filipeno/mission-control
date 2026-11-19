"""Starting work from the phone (stage 11c).

Folders: mc-pc reports the real sub-folders of D:\\projekty and D:\\Skola (POST /api/pc/folders); the app picks from them.
New session: a fingerprint-signed request. The Pi types a brief into the boss session (like "start from a doc"), which
calls start_session with the chosen folder, model, effort, permission mode and the prompt. Signed string:
  "newsess|<area>|<name>|<model>|<effort>|<permission>|<prompt>|<ts>"      area: projects | skola
Skola photo: the app uploads each picture / PDF (POST /api/launch/upload, streamed to disk, 25 MB cap in total), then sends
a signed start: "skola|<subject>|<id,id,...>|<note>|<ts>". The Pi queues a job for mc-pc; mc-pc saves the files under
D:\\Skola\\<subject>\\<new task>\\podklady\\ and reports back (POST /api/pc/launch/saved); only then the boss is asked to
start a Czech session in the subject folder.
"""
import os
import re
import secrets
import threading
import time
from pathlib import Path

import tiers

MODELS = ("sonnet", "haiku", "opus")
EFFORTS = ("low", "medium", "high", "xhigh")
PERMS = ("default", "acceptEdits", "auto", "bypassPermissions")
AREAS = {"projects": "D:\\projekty", "skola": "D:\\\u0160kola"}
MAX_PROMPT = 2500          # the typed brief is capped at 3900 characters in all
MAX_NOTE = 400
MAX_UPLOAD = 25 * 1024 * 1024
MAX_FILES = 6
UPLOAD_TTL = 24 * 3600
FOLDERS_FRESH = 3600
ID_RE = re.compile(r"^[0-9a-f]{20}$")
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf")
SKOLA_TEXT_CAP = 3900


class LaunchHub:
    def __init__(self, claude, sessions, state_dir: Path, deliver=None, clock=time.time):
        self.claude, self.sessions, self.deliver, self.clock = claude, sessions, deliver or (lambda m: None), clock
        self.dir = Path(state_dir) / "launch"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.folders = {"projects": [], "skola": [], "at": 0}
        self.uploads = {}                        # id -> {"name", "size", "at"}
        self.jobs = {}                           # queue key -> {"state", "detail", "at", "subject"}
        self.sweep()

    # ------------------------------------------------------------ from mc-pc

    def on_folders(self, d: dict) -> None:
        def names(v):
            return [str(x)[:100] for x in (v or [])[:200] if isinstance(x, str) and x and not re.search(r'[\\/:*?"<>|\0]', x) and x not in (".", "..")]
        d = d if isinstance(d, dict) else {}
        with self.lock:
            self.folders = {"projects": names(d.get("projects")), "skola": names(d.get("skola")), "at": self.clock()}

    def folders_view(self) -> dict:
        with self.lock:
            f = dict(self.folders)
        f["fresh"] = self.clock() - f["at"] < FOLDERS_FRESH
        f["areas"] = dict(AREAS)
        return f

    def file_path(self, uid: str):
        p = self.dir / f"{uid}.bin"
        return p if ID_RE.match(uid) and p.is_file() else None

    def on_saved(self, d: dict) -> None:
        """mc-pc says whether it saved the files. On success the boss is asked to start the Czech session."""
        d = d if isinstance(d, dict) else {}
        key = str(d.get("key") or "")
        with self.lock:
            job = self.jobs.get(key)
        if not job:
            return
        subject = job["subject"]
        if d.get("ok") is not True:
            self._finish(key, "failed", str(d.get("detail") or "mc-pc could not save the files")[:200], subject, job)
            return
        folder, task = str(d.get("folder") or ""), str(d.get("task") or "")
        prefix = AREAS["skola"] + "\\" + subject + "\\"
        if not folder.startswith(prefix) or ".." in folder or not task:
            self._finish(key, "failed", "mc-pc returned an odd folder", subject, job)
            return
        pod = folder + "\\podklady"
        text = skola_brief(subject, folder, pod, task, job.get("note", ""), [str(x)[:80] for x in (d.get("saved") or [])[:6]])
        try:
            self.sessions.type_to_boss(text, kind="start")
        except LookupError as e:
            self._finish(key, "saved", f"Saved to {folder}, but {e}", subject, job, notify=True)
            return
        self._finish(key, "started", f"Asked your main session to start it ({task})", subject, job, notify=True)

    # ------------------------------------------------------------ from the phone

    def upload(self, name: str, chunks, declared: int = None) -> dict:
        """Stores one picture / PDF. [chunks] is an iterator of bytes; stops at the cap. Raises ValueError."""
        name = os.path.basename(str(name or "").replace("\\", "/"))[:80]
        if os.path.splitext(name)[1].lower() not in EXTS:
            raise ValueError("pictures and PDF only")
        if declared is not None and declared > MAX_UPLOAD:
            raise ValueError("file is over 25 MB")
        self.sweep()
        uid = secrets.token_hex(10)
        p = self.dir / f"{uid}.bin"
        n = 0
        try:
            with open(p, "wb") as fh:
                for c in chunks:
                    n += len(c)
                    if n > MAX_UPLOAD:
                        raise ValueError("file is over 25 MB")
                    fh.write(c)
            if n == 0:
                raise ValueError("empty file")
        except BaseException:
            p.unlink(missing_ok=True)
            raise
        with self.lock:
            self.uploads[uid] = {"name": name, "size": n, "at": self.clock()}
        return {"id": uid, "size": n, "name": name}

    def new_session(self, token_hash: str, d: dict) -> dict:
        area, name = str(d.get("area") or ""), str(d.get("name") or "")
        model, effort, perm = str(d.get("model") or ""), str(d.get("effort") or ""), str(d.get("permission") or "")
        prompt = str(d.get("prompt") or "").strip()
        if area not in AREAS:
            raise ValueError("bad area")
        if name not in self.folders_view().get(area, []):
            raise ValueError("unknown folder (the PC has not listed it)")
        if model not in MODELS or effort not in EFFORTS or perm not in PERMS:
            raise ValueError("bad model, effort or permission mode")
        if not prompt:
            raise ValueError("Write the first prompt.")
        if len(prompt) > MAX_PROMPT:
            raise ValueError(f"The prompt is over {MAX_PROMPT} characters.")
        path = AREAS[area] + "\\" + name
        msg = f"newsess|{area}|{name}|{model}|{effort}|{perm}|{prompt}"
        text = session_brief(path, model, effort, perm, prompt, area == "skola")
        if len(text) > SKOLA_TEXT_CAP:
            raise ValueError("The prompt is too long to hand over.")
        r = self.sessions.type_to_boss(text, kind="start", token_hash=token_hash, msg=msg, d=d, tier=tiers.new_session_tier(perm))
        return {"ok": True, "boss": r.get("boss", ""), "folder": path}

    def skola_start(self, token_hash: str, d: dict) -> dict:
        subject, note = str(d.get("subject") or ""), str(d.get("note") or "").strip()
        ids = [str(i) for i in (d.get("files") or [])]
        if subject not in self.folders_view()["skola"]:
            raise ValueError("unknown subject (the PC has not listed it)")
        if not 1 <= len(ids) <= MAX_FILES or len(set(ids)) != len(ids) or not all(ID_RE.match(i) for i in ids):
            raise ValueError(f"1 to {MAX_FILES} uploaded files please")
        if len(note) > MAX_NOTE:
            raise ValueError(f"The note is over {MAX_NOTE} characters.")
        with self.lock:
            metas = [self.uploads.get(i) for i in ids]
        if not all(metas) or not all(self.file_path(i) for i in ids):
            raise ValueError("an uploaded file expired; share it again")
        if sum(m["size"] for m in metas) > MAX_UPLOAD:
            raise ValueError("files are over 25 MB together")
        self.claude.verify(token_hash, f"skola|{subject}|{','.join(ids)}|{note}|{int(d.get('ts') or 0)}", str(d.get("sig", "")), int(d.get("ts") or 0), tier="M")
        if not self.sessions.boss_session():           # fail before anything is queued or saved
            raise LookupError("No main Claude Desktop session is open in D:\\projekty or D:\\ai-hub (or the PC is not reporting). Open one and try again.")
        key = "skola-" + secrets.token_hex(6)
        item = {"key": key, "kind": "skola-new", "subject": subject, "note": note, "at": self.clock(),
                "files": [{"id": i, "name": m["name"]} for i, m in zip(ids, metas)]}
        with self.lock:
            self.jobs[key] = {"state": "queued", "detail": "waiting for the PC", "at": self.clock(), "subject": subject, "note": note, "files": ids}
        self.claude.enqueue(item)
        return {"ok": True, "key": key}

    # ------------------------------------------------------------ internals

    def _finish(self, key, state, detail, subject, job, notify=True):
        with self.lock:
            self.jobs[key] = dict(job, state=state, detail=detail, at=self.clock())
            for k in sorted(self.jobs, key=lambda k: self.jobs[k]["at"])[:-20]:
                del self.jobs[k]
        for i in job.get("files", []):
            self._drop(i)
        if notify:
            self.deliver({"at": self.clock(), "kind": "skola-start", "cat": "claude", "title": "School task: " + subject,
                          "body": detail[:200], "group": "skola:" + key, "quiet": False, "actions": [], "tab": 1})

    def _drop(self, uid: str) -> None:
        (self.dir / f"{uid}.bin").unlink(missing_ok=True)
        with self.lock:
            self.uploads.pop(uid, None)

    def sweep(self) -> None:
        """Delete abandoned uploads (also files left from before a restart)."""
        cut = self.clock() - UPLOAD_TTL
        for p in self.dir.glob("*.bin"):
            try:
                if p.stat().st_mtime < cut:
                    p.unlink(missing_ok=True)
            except OSError:
                pass
        with self.lock:
            for i in [i for i, m in self.uploads.items() if m["at"] < cut]:
                del self.uploads[i]


def session_brief(path: str, model: str, effort: str, perm: str, prompt: str, skola: bool) -> str:
    title = re.sub(r"\s+", " ", prompt)[:50]
    return (f'Mission Control: Filip asked on his phone (fingerprint-confirmed) to start a new session. Call start_session now '
            f'(initiation "user_asked", context "fresh") with cwd "{path}", model: the current {model} model id, effort "{effort}", '
            f'permission_mode "{perm}", title "{title}", and a background of at least 80 characters saying the session was started from '
            f"Filip's phone in that folder"
            + (" (a school folder: the session must answer in Czech and follow D:\\\u0160kola\\CLAUDE.md)" if skola else "")
            + f". Its prompt is the text between the markers, exactly as written.\n"
              f"If the tool caps model, effort or permission mode at your own level, start it at the allowed level, then raise the new session "
              f"with set_session_model / set_session_effort / set_session_permission_mode (the approval cards reach his phone). "
              f"Then tell him in one line what you started and at what settings.\n<<<PROMPT\n{prompt}\nPROMPT>>>")


def skola_brief(subject: str, folder: str, pod: str, task: str, note: str, saved: list) -> str:
    t = (f"Mission Control: Filip poslal z telefonu zadání domácího úkolu (fotka nebo PDF). Soubory ({', '.join(saved)}) jsou uložené v `{pod}`. "
         f'Spusť teď start_session (initiation "user_asked", context "fresh") s cwd "{AREAS["skola"]}\\{subject}", model sonnet, effort low, '
         f"s názvem „{subject}: {task}“ a s kontextem aspoň 80 znaků (úkol z telefonu, složka {folder}). Zadání pro novou session, přesně mezi značkami:\n"
         f"<<<PROMPT\n"
         f"Jde o domácí úkol, plný režim podle D:\\Škola\\CLAUDE.md (kartu s volbou režimu přeskoč). Odpovídej česky a otázky dávej jen přes karty v češtině. "
         f"Zadání, které Filip vyfotil nebo poslal jako PDF, je v `{pod}`: nejdřív si je celé přečti (obrázky otevři). "
         f"Pak postupuj podle „Domácí úkol“: nejdřív karta (termín, požadavky učitele, úroveň), potom plné vyptávání a jeden plán ke schválení; nic nestav, dokud Filip nepotvrdí. "
         f"Složka úlohy je `{folder}` (název „Nová úloha…“ po přečtení zadání přejmenuj na název úlohy; podklady v ní nech)."
         + (f" Poznámka od Filipa: {note}" if note else "") +
         f"\nPROMPT>>>\nPak Filipovi jednou větou řekni, že session běží.")
    return t[:SKOLA_TEXT_CAP]
