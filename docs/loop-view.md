# Loop views + local chat (0.20.0)

Stage 4 of the local loop agent in Mission Control. Everything sits under the **Local AI** card on the System tab
(Filip's choice A, 2026-11-19). Plan: `D:\ai-hub\files\briefs\c2\35-mc-stage4-plan-answer.md`.

## Screens
- **Loop live** (inside the Local AI card, "Current job"): task goal, `round i/N`, step, state chip (running / stuck),
  progress bar from `started` -> `eta`, last check (command, green/red dot, "2 min ago", last output line), tok/s.
  Footer buttons: **How it thinks**, **Morning summary**, **Chat**.
- **Morning summary**: `POST /api/system/loop/morning` -> the PC uploads `D:\ai-hub\files\loop-morning.md` as the doc
  `loop-morning` (stable slug: a changed file is a new version, an unchanged one no change) -> the app polls
  `GET /api/system/loop/morning` until `done` and opens the doc in the Docs viewer.
- **How it thinks**: task list (newest first, last 30) -> a task (rounds as collapsible sections) -> each round a timeline
  of cards: model text (grey), tool call (blue, `Bash: pytest -q`), result (dark mono, cut to 600 chars, "show more"),
  round footer (check exit code; the task's check output tail at the end). A running task refreshes every 5 s.
- **Chat**: bubbles, model chip, text field, Send / Stop / Clear, banner "Local model, LAN/VPN only". Disabled with a
  hint when the PC is not in AI mode. Uses whatever model runs (choice A). The app keeps the chat only while the
  screen is open.

## App API (all need the app token; errors are `{"error": "..."}`)
| Route | Answer |
|---|---|
| `GET /api/system/localai` | as before, plus `loop_views` (bool: the PC can serve the views), `chat` `{available, reason, busy}`; `job.agent` gains `id`, `rounds` (planned), `check_line` |
| `GET /api/system/loop/tasks` | `{state, detail, at, pc_online, data, refreshing}`; `data` = `{tasks: [Task]}` |
| `GET /api/system/loop/tasks/{id}` | same envelope; `data` = TaskDetail |
| `GET /api/system/loop/tasks/{id}/round/{n}` | same envelope; `data` = Round |
| `POST /api/system/loop/morning` | `{ok}`; then `GET /api/system/loop/morning` -> `{state: none/requested/done/failed, slug: "loop-morning", detail, requested_at}` |
| `POST /api/system/localai/chat` body `{messages: [{role: user/assistant, content}]}` | `{ok, rid}` |
| `GET /api/system/localai/chat/{rid}` | `{rid, state: queued/running/done/error/stopped, text, model, error}` |
| `POST /api/system/localai/chat/{rid}/stop` | `{ok}` |

Envelope `state`: `loading` (the Pi asked the PC; poll again in ~1.5 s), `ok` (`data` set), `error` (`detail`, e.g.
"task not found"). HTTP 409 = PC helper offline with nothing cached, or an mc-pc that is too old ("Update mc-pc ...");
400 = bad id; 404 = unknown chat id; 429 = chat rate limit.

- **Task** `{id, repo, goal, status, rounds, rounds_max, reason, started, finished, model, running}` (times unix s;
  `status` running / done / failed / stuck / ...; `repo` is the folder name).
- **TaskDetail** `{id, repo, goal, check, status, reason, model, started, finished, total_seconds, running, rounds_max,
  rounds: [{n, turns, seconds, check_exit, timed_out}], check_output_tail, reviews: [{n, verdict, notes: [str]}]}`.
- **Round** `{id, n, running, total, skipped, items: [Item]}`; `skipped` = earlier items left out (a round keeps its
  last 200 items). **Item** `{k, t, n?, e?, full?}`: `k` = `text` (model text), `tool` (`n` = tool name, `t` = short
  input: command / path), `result` (`t` = output, `e` = true if it is an error), `end` (final line of the round).
  `full` = original length when `t` was cut (items are cut to 2000 chars).

## PC API (PC token)
- `/api/pc/command` reply adds `loop_req: [{key, kind: tasks/task/round/morning, id?, n?}]` and `chat_req: [{rid}]`
  (RAM queue on the Pi, handed out once, asked again after 20 s without an answer).
- `POST /api/pc/loop` `{key, ok, data | detail}`.
- `GET /api/pc/chat/{rid}` -> `{rid, messages, max_tokens, timeout_s}` (once: the Pi drops the text when the PC has it).
- `POST /api/pc/chat/{rid}` `{text, done?, error?, model?}` -> `{stop}` (true after Stop in the app).
- `/api/pc/report` adds `caps: ["loop", "chat"]`; without it the app gets the "update mc-pc" message.

## PC side (`pc/mc_loop.py`, `pc/mc-pc.ps1`)
- `python -I mc_loop.py serve` (request in `MC_ITEM`) reads `D:\ai-hub\loop` and POSTs the answer itself (URL + PC
  token from `mc-pc.json`). Tasks: `done/*/result.json` + `task.json`, newest 30; the running task from
  `queue/<id>.json`, `work/<id>/` and `state/local-agent/status.json`.
- Transcript: `round-N.jsonl` (Claude Code stream-json) -> items; drops `system` lines, usage, ids and the duplicate
  `tool_use_result`; a broken last line (still being written) is skipped.
- `python -I mc_loop.py chat <rid>` runs hidden (mc-pc does not wait): GETs the messages, streams
  `http://127.0.0.1:8080/v1/chat/completions` (`Authorization: Bearer <llm_key>` only if `llm_key` is set in
  `mc-pc.json`), POSTs the text about every 0.7 s, stops on `{stop: true}`, 800 tokens, 120 s.
- `mc-pc.ps1 -TestLoop` prints the task list and one parsed round from the live `D:\ai-hub\loop` (nothing is sent).

## Security
- **Redaction on the PC before upload** (`mc_loop.redact`): `sk-...`, `ghp_/gho_/ghs_/github_pat_...`, `Bearer ...`,
  `api_key=` / `token=` / `password=` / `secret=` values, AWS / Google keys, private key blocks, long hex (> 40) and
  long mixed base64-like tokens, `.env`-style `*_KEY=` / `*_TOKEN=` lines. Results of reading secret-looking files
  (`.env*`, `secrets*`, `*.pass`, `*.keystore`, `*.jks`, `*.pem`, `*.key`, `credentials*`, `id_rsa*`, `mc-pc.json`,
  `mc-pi.env`, `api-keys.txt`, `.prod-secrets`) and of env dumps (`env`, `set`, `printenv`, `Get-ChildItem env:`)
  become `[hidden]`; so do Write / Edit contents for such files.
- Task ids must match `^\d{8}-\d{6}-[0-9a-f]{3}$` (Pi and PC) before any path is built; round 1..50.
- Chat: local model only; Pi RAM only (dropped 10 min after the end, the request text as soon as the PC has it);
  one at a time (409), 12 per minute (429), 4000 chars per message, newest 20 messages / 24 000 chars, 800 output
  tokens, 120 s. Same app login as the other `/api/system` routes. No fingerprint: reading and chatting send no
  commands to the PC.

## Tests
`python -m unittest pc/test_mc_loop.py pi/test_loop_hub.py` + the older suites; `mc-pc.ps1 -TestLoop`; emulator
screenshots in `D:\ai-hub\files\app-test\0.20.0\`.
