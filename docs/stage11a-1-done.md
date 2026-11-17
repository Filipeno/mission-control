# Stage 11a-1 done: the Claude desktop app's own approval cards on the phone (MC 0.12.0, 2026-11-17)

Spike notes: `stage11a-spike.md`. Filip's decisions: fingerprint for Allow only, Deny one tap; a PC lock keeps the answer and clicks on unlock (expires after 8 h); never "Always allow".

## What it does
- **PC, finding cards.** `mc_sessions.py` (every mc-pc loop) adds one gate of kind `appcard` (id `ac-<request id>`) per pending Allow/Deny card in `main.log` (`mc_appcard.py`). `mc_appgate.py` fills it: tool, session id, the app's own session title, and the full tool input from the session transcript's open `tool_use` (a start_session brief is whole). The input is shown only when exactly ONE tool_use of that tool is open; otherwise the card says details were not found and cannot be answered from the phone. mc-pc then sends a fresh PC screenshot per card (`mc-shot.py --appcard ac-<id>`). A card answered at the PC drops out of the snapshot, so the phone card closes.
- **Pi.** `sessions_hub.py` stores and serves `appcard` gates (kind is `appcard` only for ids starting `ac-`; hook gates must have hook-format ids; duplicate ids are dropped). Allow needs a valid fingerprint signature (`gate|<id>|allow||<ts>`); Deny is accepted unsigned, only as deny; "always" and a deny note are refused. Push: "<session>: app card waiting". New: `GET /api/appcard/{id}/shot` (app), `POST /api/pc/appcard/{id}/shot` (PC, screenshot kept in memory only). The card carries `answer` {decision, ok, detail} = what the PC did.
- **App.** `AppCardGate.kt`: tool, session, full input (scrollable), screenshot (tap to zoom), **Allow once** (fingerprint) and **Deny** (one tap). The notification has only Deny. It stays on screen after the answer to show the result: "sent", "waiting for unlock (expires HH:MM)", "clicked Allow once at the PC", or the refusal reason (then you can try again).
- **PC, answering.** `mc_appgate.py answer` (item in env `MC_ITEM`) runs `mc-appcard.ps1 -Answer <id> -Decision … -ExpectTitleEnv -Tool …` (the title goes in env `MC_EXPECT_TITLE`, never argv) with all spike checks. Results: `done` / `refused: <reason>` / `held` (PC locked: the item is not acked and retried each poll; the phone shows "waiting for unlock") / `gone` (answered at the PC first) / `expired` (8 h). Every action goes to `mc-pc.log`.

## Tests
- `python -m unittest pc/test_mc_appgate.py pc/test_mc_appcard.py`: 50 tests (log parser, gate building, hold queue, expiry, env title).
- Pi API, scripted against a local FastAPI TestClient with a test token and key (not in the repo): 30 checks (snapshot, kind spoofing, full input, screenshot upload/auth, unsigned Allow refused, bad signature, always, notes, Deny unsigned, queue item, second answer, waiting for unlock, refusal then retry, gone).
- `gradlew.bat -PcliBuild assembleDebug` OK.
- **Live end to end on this PC** (real Pi API, real mc-pc, real cards from throwaway sessions in default mode): see the section below.

## Live result
Two throwaway sessions in default mode (Haiku, low, started by the orchestrator) each raised a start_session card; each was answered through the real Pi API (test token + test key, removed afterwards from the Pi):
| Card | Answer | Result |
|---|---|---|
| `e0fd47fe…` "MC e2e card A" | Deny, unsigned | Pi accepted, mc-pc clicked (method invoke), `19:21:50 Received permission response … deny`. The phone showed a wrong "refused" text because mc-pc could not parse the script's output (console wrapping): fixed (`parse_result`, exit 0 = confirmed), unit tested. |
| `7a7f96e2…` "MC e2e card B" | Allow, fingerprint-style signature (ECDSA, verified on the Pi) | Pi accepted, mc-pc clicked, `19:24:56 Received permission response … once`; phone status "clicked Allow once at the PC". |
Both cards showed the whole brief, the session title and a PC screenshot on the Pi API (`input_found`, `has_shot` true). The gate left the phone when the card closed. Archive of the throwaway sessions (A, B and their children) is left to the session that started them.

## Not verified
- The app UI was compiled, not run on a phone (checklist on the to-do list).
- A PC lock during a real answer (hold and click on unlock): the hold logic is unit tested; the lock itself is the phone-test item.
- Cards of tools other than start_session are not answerable yet (`CARD_PHRASE` lists only start_session; others show "answer it at the PC").
