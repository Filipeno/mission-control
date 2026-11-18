# Stage 11e done: PC peek on cards + Claude session widget (MC 0.17.0, 2026-11-18)

Filip chose both extras. Branch `mc-11e`, released as v0.17.0, merged ff to main.

## PC peek on cards
- **PC.** `mc-pc.ps1` `Send-CardShots` now covers every approval (`permission`), `question` and app card (not `plan`), one picture per card id, taken when the card first shows in the sessions snapshot (~5 s). `mc-shot.py --gate <id>` (old `--appcard` still works) calls `mc_peek.py`: if the PC is locked (`LogonUI.exe` runs) it sends an empty body with header `X-PC-Locked: 1` and takes **no** picture; otherwise it grabs all screens and re-encodes to a JPEG of at most 1280 px wide and 150 KB (quality, then size steps).
- **Pi.** `sessions_hub.py`: shots are kept per gate id of any kind (memory only, max 12, hard cap 300 KB, JPEG magic checked); a locked marker is stored as an empty entry. The gate list carries `has_shot` and `shot_locked`. A shot is deleted when its card leaves the snapshot (answered at the PC or the phone, expired), after a 60 s grace for snapshot ordering. Same endpoints as 11a-1 (`GET /api/appcard/{id}/shot`, `POST /api/pc/appcard/{id}/shot`), now accepting hook-format ids too.
- **App.** New `GateShot` (in `AppCardGate.kt`): small thumbnail, tap = full screen (existing `FullScreenShot`); "PC locked: no screenshot taken." when locked. Used on app cards, permission cards and question cards.

## Session widget
- `widget/SessionWidget.kt` (Glance, 3x2, "Claude session" in the widget picker): title, last line, `PINNED`/`LATEST` + Working / Needs you / Idle, the pending permission summary, **Allow** and **Deny**. A question or plan shows "Asks a question / Plan ready" and opens the app (no one-tap answer for those).
- **Which session**: pinned one, else a session that asks, else the latest (`SessionsHub.widget_session`, returned as `session` by `GET /api/widget?pin=<id>`). **Pin**: long-press a session in the Claude tab (pin icon; long-press again unpins).
- **Allow** opens the invisible `GateAnswerActivity` (fingerprint, signed, same as notification buttons). **Deny** is one tap. Pi change: an unsigned, note-less Deny is now accepted for plain hook `permission` gates (it was already so for app cards); Allow, question answers, plan decisions and Deny with a note still need the fingerprint.
- **Refresh**: on every push event, after an answer, after pin change, and every 15 s by a tick thread in `EventService` while a session widget is on a home screen.

## Tests
- `python -m unittest discover -s pc -p "test_*.py"`: 96 tests (new `test_mc_peek.py`: lock check, size cap on worst-case noise, gate selection). `python -m unittest discover -p "test_*.py"` in `pi/`: 44 tests (new `test_sessions_peek.py`: shots for hook/app cards, bad shots, deletion, widget session choice, unsigned Deny rules).
- Pi API scripted against a local FastAPI TestClient with throwaway tokens (scratch, not in the repo): 20 checks (auth, upload, refusals, locked marker, fetch, widget choice and pin, unsigned Allow refused, plain Deny accepted, shot deleted after the card left).
- Debug build OK. Emulator (Medium_Phone, fake Pi): screenshots in `D:\ai-hub\files\app-test\11e\` (card thumbnail, full screen, long-press pin, widget with Allow/Deny, pinned idle widget). Allow tap launches the fingerprint screen (no biometric on the emulator).
- Deployed: `pi/deploy.sh`, mc-pc restarted, release v0.17.0 verified (JSON + APK sha256 match).

## Not verified
- A real fingerprint Allow from the widget, and the real mc-pc screenshot on a real approval (phone checklist on the To-do list).
- The PC-locked case on a real lock screen (unit tested only).
- Widget 15 s refresh on real battery settings (Doze may delay it).
