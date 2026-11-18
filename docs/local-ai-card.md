# PC mode switch + "Local AI" card (Mission Control 0.15.0, 2026-11-18)

## What it does
- **PC mode switch** (System tab, inside the Gaming PC card): Normal / AI / Gaming, current mode + "since", "Gaming (auto)" when the game watcher switched it (`auto` in `D:\ai-hub\state\pc-mode.json`). Tap -> `POST /api/system/pc-mode {mode, model}` -> PC inbox item `pc-mode` -> mc-pc starts `D:\ai-hub\bin\pc-mode.ps1 -Mode .. [-Model qwen|gptoss] -Quiet` **hidden and without waiting** (it takes ~60 s for AI and may wait up to 240 s for its mutex), ack at once, and the main loop polls the process (`Check-ModeJob`); when it exits mc-pc sends a fresh snapshot (real mode) and then `/api/pc/result` (`key mode-<ts>`, ok = exit code 0). The card shows "Switching to AI (qwen)... 23 s of about 60 s" with a bar. Leaving AI asks for a confirmation (the model server stops). Model chips: Qwen3-Coder 30B / gpt-oss 20B (tapping the other one while AI is on restarts with it). Only the fixed values `normal|ai|gaming` and `''|qwen|gptoss` are accepted (Pi and PC both check); a second request while one runs is refused (409); a switch the PC never reports back is dropped after 5 min.
- **Local AI card** (System tab, under the PC card), refreshes every 5 s while on screen: mode, server state (down / loading / idle / generating) + model, generation speed, slots busy/total, ctx, GPU util + temp, VRAM used/total, CPU %, RAM used/total, current job (loop agent status or "No loop running", newest trial log with last line), button "Open trials report" (only if `D:\ai-hub\files\local-agent-trials\report.md` exists).
- **Live data flow.** The app's GET `/api/system/localai` marks the card "watched" for 20 s; the Pi then adds `ai_watch: true` to `/api/pc/command`, and mc-pc posts `pc/mc_localai.py`'s snapshot to `POST /api/pc/localai` about every 5 s (loop sleeps 1 s while watched). Not watched = no extra work on the PC. The PC mode itself also rides in the normal 15 s report (`pcmode`). Everything is only added to the existing API, so an older app keeps working.
- **Report button.** Tap -> `POST /api/system/localai/report` -> PC item `localai-report` -> mc-pc uploads `report.md` as the doc `local-agent-trials-report` (one stable slug, so a changed file is a new version of the same doc, an unchanged one is no change/no notification) -> app opens it with the Docs viewer.

## Server speed (llama.cpp b12489)
`/health` and `/slots` are on by default; `/metrics` needs `--metrics` and `start-llm.ps1` does not pass it. mc_localai therefore reads `/metrics` if present (`predicted_tokens_seconds`) and otherwise derives tokens/s from the decoded-token count of the busy slot between two samples (`next_token[0].n_decoded`, same `id_task`; field name checked against a live b12489 server on 2026-11-18), and keeps the last value 30 s after generation ends. Suggestion (not done: `start-llm.ps1` is not ours): add `--metrics` for exact numbers incl. prompt speed.

## Loop-agent status file (schema)
`D:\ai-hub\state\local-agent\status.json`, written by the (future) loop agent, e.g. with `python -c "import mc_localai as m; m.write_status('task', 'step', 2, {'cmd':'pytest -q','ok':False,'at':'2026-11-18T05:10:00'})"` from `D:\projekty\mission-control\pc` (atomic write), or by hand:

```json
{"task": "fix the tests in X", "step": "3/6 edit config.py", "iteration": 3,
 "last_check": {"cmd": "pytest -q", "ok": false, "at": "2026-11-18T05:10:00"},
 "started": "2026-11-18T05:00:00", "eta": "2026-11-18T05:30:00", "state": "running"}
```
`task` required; `step` string or number; `iteration` int; `last_check.at`, `started`, `eta` ISO time (local if no zone) or unix seconds; `eta` and `state` (running | done | failed) optional. The card says "No loop running" when the file is absent, unreadable, has no `task`, is `done`/`failed`, or was not touched for 15 min (`AGENT_STALE_S`): the loop should rewrite it at every step. Validation: `mc_localai.parse_status` (PC) and `localai_hub.clean_snapshot` (Pi).

## Files
`pc/mc_localai.py` (snapshot, validator, writer), `pc/mc-pc.ps1` (mode job, snapshot sender, report upload, `-TestLocalAi`), `pi/localai_hub.py` + `pi/mcpi.py` (endpoints), `pi/deploy.sh`, `ui/LocalAiCard.kt` (`PcModeSwitch`, `LocalAiCard`), `ui/SystemScreen.kt`.

## Tests
- `python -m unittest pc/test_mc_localai.py pi/test_localai_hub.py` (+ the older suites: 107 tests OK).
- Pi API (scripted with FastAPI TestClient and test tokens, not in the repo): 24 checks (401s, 409 helper offline / while switching, 400 bad mode or model, one inbox item with the model dropped outside AI, result -> done + new mode, `ai_watch`, report item, old fields intact).
- mc-pc: `-TestLocalAi` against the live PC; a harness with a stub `pc-mode.ps1` checked the non-blocking start, bad-input refusal, the "already running" refusal and exit code 0/2 reporting.
- App on the emulator against a local mc-pi with a simulated PC: screenshots in `D:\ai-hub\files\app-test\0.15.0\`.
