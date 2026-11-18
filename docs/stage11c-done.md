# Stage 11c done: starting work from the phone (MC 0.16.0, 2026-11-18)

Version note: main already carried 0.15.0 (PC mode switch), so this release is **0.16.0** (versionCode 23).

## What it does
- **New-session sheet** (Claude tab, "+"): folder (any real sub-folder of D:\projekty or D:\Skola, listed by mc-pc every 5 min), model (Sonnet / Haiku / Opus), effort (Low / Medium / High), permission mode (Default / Accept edits / Auto / Bypass with a red warning), first prompt (max 2500 characters). Defaults Sonnet + Low + Default. Choices are remembered per folder (SharedPreferences `mc-newsession`), and the last used folder is preselected.
  Start needs the fingerprint: signed `newsess|<area>|<name>|<model>|<effort>|<permission>|<prompt>|<ts>`. The Pi types a brief into the boss session (same path as "start session for a doc"); the boss calls `start_session` with cwd, model, effort, permission mode and the prompt. `start_session` caps those at the boss's own level, so the brief tells the boss to start at the allowed level and then raise the new session with `set_session_model / effort / permission_mode` (those cards reach the phone). The sheet says this in one muted line.
- **School task from a photo**: ShareActivity also accepts `image/*` and `application/pdf` (SEND and SEND_MULTIPLE, up to 6 files, 25 MB total). The app uploads each file (`POST /api/launch/upload`, streamed with a running cap, stored in the Pi state `launch/`), then sends a signed `skola|<subject>|<ids>|<note>|<ts>`. The Pi first checks a boss session exists (409 otherwise), then queues a `skola-new` job. mc-pc downloads the files, `pc/mc_launch.py` saves them to `D:\Skola\<subject>\Nova uloha <date time>-<key>\podklady\` and reports back; only then the Pi types a Czech brief into the boss, who starts a Sonnet-low session in `D:\Skola\<subject>` with the full homework flow ("Domaci ukol", Czech cards). If the boss is gone after saving, the notification names the saved folder.

## Safety
- Subject must exactly match a real sub-folder name (listing compared), `realpath` must stay directly in the Skola root (junction check), no separators / `..` / drive tricks; the task folder name is generated; file names sanitised, reserved names escaped, only jpg/png/webp/heic/pdf with a magic-byte check, written with `xb`.
- A repeated job (same key) returns the existing folder (marker file in podklady), so a failed callback never makes a second task folder.
- Pi: upload ids are 20 hex chars, PC-only fetch, files deleted once the PC confirmed, 24 h TTL sweep, signatures work once.
- Roots are env-configurable (`MC_PROJECTS_ROOT`, `MC_SKOLA_ROOT`) so tests never touch real Skola.

## Files
pc: `mc_launch.py`, `test_mc_launch.py`, `mc-pc.ps1` (Send-Folders, Save-SkolaTask). pi: `launch_hub.py`, `test_launch_hub.py`, `mcpi.py` (7 endpoints), `sessions_hub.py` (`type_to_boss`), `deploy.sh` (new module in the file list). app: `NewSession.kt`, `ShareActivity.kt`, `ClaudeScreen.kt`, manifest.

## Verified
- `python pc/test_mc_launch.py` 9 tests, `python pi/test_launch_hub.py` 12 tests.
- Pi API with a local FastAPI TestClient, real P-256 test key (21 checks: 401s, 409 without boss, signed once, bad sig 403, unknown folder 400, upload type/size, PC-only fetch, queue item, Czech brief typed only after the PC saved, upload removed).
- PowerShell 5.1 -> Python with Czech subject and file names in a temp Skola root (saved, Czech names intact).
- `gradlew.bat -PcliBuild assembleDebug` OK; emulator (AVD Medium_Phone_API_37.0) against a local mc-pi: sheet, bypass warning, a real Files-app share of a photo (upload reached the Pi). Screenshots in `D:\ai-hub\files\app-test\11c\`.

## Not verified
- Fingerprint signing on a device (the emulator has no fingerprint; the same `signedPostEx` as the other signed requests), so the full Start on the phone and the boss actually calling `start_session` / raising model, effort and mode are untested. Phone checklist: `stage11c-checklist.md`.
- A real run into real D:\Skola (not touched on purpose).
