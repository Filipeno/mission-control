# Stage 11a-2 done: Claude app health, Remote Control fix, hub self-test, helper usage (MC 0.13.0, 2026-11-18)

## What it does
- **Claude app card (System tab).** mc-pc sends `health` in every report (15 s): whether Claude.exe runs (same test as the watchdog), the watchdog's `down_since` / `last_ok`, and the last watchdog run (write time of `D:\ai-hub\state\claude-app-watchdog.json`, which the watchdog rewrites every minute). The Pi (`pi/health_hub.py`, class HealthHub) adds Remote Control counts from the live session snapshot (desktop sessions, `rc` = has a bridge session id). **Restart Claude app** (one tap, no fingerprint) -> `POST /api/system/claude/restart` -> PC inbox item `claude-restart` -> `Restart-ClaudeApp` in mc-pc.ps1 stops the Claude processes and starts the app the way the watchdog does; result goes back through `/api/pc/result` and shows on the card. Repeat taps within 60 s are ignored. Notification "Claude app is down" once when it has been down 5 min (re-armed on recovery); the watchdog's own phone doc is unchanged.
- **Fix Remote Control.** There was no "sweeper log": the live session list from the PC already knows which desktop chats have Remote Control off, so the list comes from there. "Turn on" -> `POST /api/system/rc/enable {id}` -> PC inbox item `rc-queue` -> `pc/mc_health.py` appends `{session_id, id, title, queued_at}` to the JSON array `D:\ai-hub\state\rc-queue.json` (`session_id` = the `local_...` id when known; this is what `set_remote_control` takes). The Pi shows "Queued" until the chat shows Remote Control on (or 24 h pass). The queue is only worked off by Claude, see the rule below.
- **Hub self-test card.** mc-pc sends `state\selftest.json`; rows are green/red with seconds and detail; "stale" after 36 h. Notification "Hub self-test failed" (names of the failing helpers) once per new run (`at`) that has failures. "Hub self-test" also joins the System tab's problem count.
- **Helper usage.** mc-pc runs `usage.ps1 -Json` every 10 min (with the usage numbers) and sends `helpers`; `GET /api/claude` returns it; the Claude tab shows a "Helpers today" card under Usage (Gemini app / Perplexity jobs left, Codex % + reset, parked helpers, success rates).

## Rule for the global CLAUDE.md (NOT applied here: the orchestrator adds it)
Under "## Remote Control" add:

> - Remote Control queue: at the start of every turn, if `D:\ai-hub\state\rc-queue.json` exists and is not empty, run `set_remote_control` (enabled true, `session_id` = each entry's `session_id`) for every entry (skip an entry whose chat no longer exists), then remove those entries from the file (rewrite the JSON array; leave `[]`). Filip queues them from the Mission Control System tab. Say in one line which chats you switched on.

## Tests
- `python -m unittest pc/test_mc_health.py pi/test_health_hub.py pc/test_mc_appgate.py pc/test_mc_appcard.py`: 58 tests OK.
- Pi API, scripted against a local FastAPI TestClient (test tokens only, not in the repo): 28 checks (401, 409 with the helper offline, report -> view, RC counts, 404 for an RC-on / unknown chat, queue item with `local`, idempotent enable, queued flag, restart item once, rate limit, result -> done, down notification once + re-arm, self-test notification once, problems list, `helpers` in `/api/claude`). Deployed to the real Pi with `pi/deploy.sh` (service active).
- PC: `Get-HealthReport` run for real (claude running true, watchdog_at, self-test rows, helpers from `usage.ps1 -Json`); `mc-pc.ps1 -TestRestart` (dry run). The real restart was NOT run.
- `gradlew.bat -PcliBuild assembleDebug` OK; app run on the emulator (AVD Medium_Phone) against a local mc-pi with seeded data: screenshots in `D:\ai-hub\files\app-test\11a2\` (System: Claude app, Remote Control off, queued row after a tap, self-test with one red row; Claude tab: Helpers today).

## Not verified
- A real Restart Claude app tap and the "app down 5 min" push (the Pi logic is tested; the PC kill/start is a dry run). On the phone checklist.
- The RC queue is only filled; nothing consumes it until the CLAUDE.md rule above is applied.
- `rc_off` counts only `desktop` sessions; chats whose Pi snapshot is stale (PC off) show the last known state.
