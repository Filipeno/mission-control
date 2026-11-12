# Claude tab upgrade: research + plan (draft for Filip, 2026-11-10)

Goal (Filip, 2026-11-10): from the phone (1) open a Claude session and see what it is doing, (2) type to it,
(3) answer its questions (multiple choice + free text), (4) allow what it asks for (tool permissions and
"start a new session" cards) with the fingerprint.
Mockup: `mockups/claude-tab-v2.png` (style A).

## 1. Research: what is possible

Checked on this PC (Claude Desktop 4.23118, Claude Code 2.1.321) and in the Claude Code docs. Nothing in
Filip's running sessions was touched; transcripts were only read.

| Need | How | Works? |
|---|---|---|
| **List sessions + live status** | `~/.claude/sessions/<pid>.json` per live session: id, title, cwd, `status` (busy/idle), `waitingFor` ("input needed", "dialog open"), desktop/CLI kind. pc-waker already reads it. | **Yes**, reliable, no usage cost. |
| **Readable activity** | The transcript `~/.claude/projects/<folder>/<id>.jsonl`: user and assistant text, tool calls (name + input) and results. mc-pc reads only new bytes, like pc-waker. | **Yes**, no usage cost. Tool calls shown collapsed ("Bash: npm test", "Edit: Api.kt"). |
| **See a pending question / permission** | Last `tool_use` in the transcript with no result yet + `waitingFor` set. AskUserQuestion carries its questions and options; a permission prompt carries the exact tool input (command, file, diff). | **Yes**, read-only. |
| **Answer a question / permission** | Official **PermissionRequest hook** (in `~/.claude/settings.json`, runs in Desktop sessions too). The hook gets the exact tool input and can return allow / deny; for AskUserQuestion it returns the chosen answers (`updatedInput.answers`), which is the documented way. Docs: with the Desktop app the hook and the on-screen dialog run side by side and **whichever answers first wins**, so you can still answer at the PC. | **Yes** (documented). The "side by side" part must be tested on this build before I rely on it (test in a throwaway session, not yours). If the dialog instead waits for the hook, the hook only waits when the PC has been idle 2+ min. |
| **Type a message into a running session** | (a) **Remote Control** is already **on** for your Desktop sessions: the official Claude Android app can open them, type, answer questions and permissions. Mission Control can open the exact session there with one tap. (b) Desktop **session messaging** (what sessions use to talk to each other): undocumented local pipe, and the message arrives labelled "from another session", so Claude treats it as information, **not as your words** (it will not approve or start things on it). (c) **Typing into the Claude Desktop window** by mc-pc (UI automation): arrives as your own words, but only works while the PC is unlocked, briefly takes focus, and may break after app updates. (d) `claude --resume <id> -p`: undocumented for a session open in the Desktop app; risks two processes writing one session. **Not used.** | (a) **Yes**, reliable, free. (c) **Possible, experimental.** (b) and (d) not good enough. |
| **Start a proposed new session** (the cards with a Start button) | The card is Desktop app UI, not a permission prompt, so no hook can press Start. Starting it needs your words in that session ("start it"), so it uses the same route as typing: (a) open in the Claude app, or (c) mc-pc types "Start the proposed session: <title>" into the session. Also found: `claude://code/new?q=<brief>&folder=<path>` opens a **new** Desktop session with the brief filled in (not linked to the parent session; whether it sends by itself is untested). | **Partly.** Mission Control shows the card with the full brief; Start goes through (a) or (c). |
| **Usage cost** | Reading sessions, transcripts and answering through the hook cost **no** Claude usage. A typed message costs one normal turn of that session. Nothing runs a hidden extra Claude. | |

Note: most of your sessions run in **auto** or **bypass** permission mode, so tool permission prompts are rare;
AskUserQuestion questions (which your rules use for every decision) are the common case.

## 2. Design

### mc-pc (PC helper, extends `pc/mc-pc.ps1`)
- Every 5 s: live sessions from `~/.claude/sessions` (title, status, waiting, folder, kind, Remote Control id
  for the "Open in Claude app" link), plus a pending item per session if one exists.
- For the session open on the phone only: the last ~60 activity rows from its transcript (text cut to 1500
  chars, tool calls collapsed, tool results reduced to one line). mc-pi tells mc-pc which session is open.
- Pending gate requests from the hook (below) are sent with the exact command / file / diff / brief.
- Transcripts stay on the PC; the Pi only keeps the last rows of the open session in memory (not on disk).

### Phone gate hook (new, `D:\ai-hub\bin\phone-gate.py`, PermissionRequest hook for all tools)
- Writes `D:\ai-hub\gate\pending\<id>.json` (session, tool, exact input), then waits for
  `gate\answered\<id>.json` (written by mc-pc after a fingerprint-signed answer) and returns allow / deny /
  answers. Stops waiting quietly if the question is answered at the PC first (transcript shows a result).
- Timeout 1 hour, then it gives up silently (the normal dialog stays).
- **Auto-approve** (Settings, default **nothing**): you can pick categories that mc-pc answers "allow"
  without asking: read-only tools; file edits inside the session's own folder; Bash commands from a list you
  write. Questions (AskUserQuestion) are never auto-answered.
- Needs one hook entry in `~/.claude/settings.json` (your OK).

### Typing (route picked by you, see the question)
- (a) **Open in Claude app** button on every session (Remote Control link). Always there.
- (c) **Send from Mission Control** (experimental, off by default): text + fingerprint → mc-pi → mc-pc puts
  it into that session's input box in Claude Desktop and presses Enter, only when the PC is unlocked and you
  have not touched it for 2 min; otherwise it waits and the phone shows "waiting for PC".

### mc-pi
New endpoints: `GET /api/sessions` (list + pending), `GET /api/sessions/<id>` (activity, marks it "open"),
`POST /api/sessions/<id>/message` (signed), `POST /api/gate/<id>/answer` (signed, same P-256 check as
approvals), `GET/POST /api/gate/auto` (auto-approve settings). Push notification: "<session> asks: <question>"
or "<session> wants to run: <command>".

### App screens (style A, see mockup)
1. **Session list** (Claude tab, replaces the plain Sessions block): dot + title + folder + status chip
   (Working / Needs you / Idle), last activity line; "Needs you" sessions on top.
2. **Session view**: header with status, scrolling activity (your messages, Claude's replies, collapsed tool
   rows, tap to expand), message box at the bottom + "Open in Claude app".
3. **Question card** (inside the session view and as a notification): question, option buttons (multi-select
   when asked), "Other…" free text; Send needs the fingerprint.
4. **Permission card**: tool, exact command / file + diff (scrollable, nothing hidden), Allow (fingerprint) /
   Deny / Deny with a note.
5. **New session card**: title, folder, full brief, Start (fingerprint) / Dismiss.

## 3. Steps after your OK
1. Test the hook race in a throwaway session (I start a scratch `claude` in a temp folder; your sessions are untouched).
2. mc-pc + hook + mc-pi + app 0.8.0; deploy to the Pi; APK sent to you.
3. Test on the phone together: open a session, read activity, answer a question from a test session, allow a
   test permission, start a test proposal.

## Your OKs needed
1. This plan and the mockup.
2. Which typing route: (a) Claude app link only, or (a) + (c) experimental typing into Claude Desktop.
3. The hook entry in `~/.claude/settings.json`.

## Outcome (2026-11-10)
Filip approved the plan and mockup, picked typing route (a) + (c), approved the hook, and chose auto-approve = read-only tools.

Built:
- `D:\ai-hub\bin\phone-gate.py`: PermissionRequest hook (all tools, timeout 3600 s) in `~/.claude/settings.json`
  (backup: `settings.json.bak-before-phone-gate`). Gate files are in `D:\ai-hub\gate\` (`pending`, `answered`, `config.json`).
- `pc/mc_sessions.py`: sessions snapshot (list, activity of the open session, gate requests, proposals). mc-pc runs it every 5 s.
- `pc/mc-type.ps1`: experimental typing into Claude Desktop. It opens the session with `claude://claude.ai/epitaxy/<local id>`,
  checks the open session's title and that the prompt box is empty, then pastes and presses Enter. It only runs
  when the PC is unlocked and idle for 2 min or more.
- `pc/mc-pc.ps1`: new inbox kinds `gate`, `gate-config`, `message`; sends `POST /api/pc/sessions` and `/api/pc/result`.
- `pi/sessions_hub.py` + routes in `mcpi.py`: `/api/sessions`, `/api/sessions/<id>`, `/api/sessions/<id>/message`,
  `/api/gate/<id>/answer`, `/api/proposals/<key>/start|hide`, `/api/gate/config`. Everything Filip sends is signed with the fingerprint.
  Activity rows stay in memory only. Deployed.
- App 0.8.0: `ui/SessionScreen.kt` (session list, session view, question / permission / plan / new-session cards,
  message box, "Open in Claude app"), plus changes to `ClaudeScreen.kt`.

Verified on 2026-11-10:
- Throwaway SDK-mode test: the hook and the host dialog race, and the first answer wins. A late answer from the phone is ignored.
- On Filip's phone: the session list and activity work. A question from a test session was answered from the phone ("Apple").
  A Bash permission was allowed from the phone (the command ran). A message typed on the phone ("Hello") arrived in a
  Claude Desktop session as a normal user message.

Not verified / limits:
- Start on a new-session card: it uses the same typing path as messages, but the end-to-end test is not done yet.
- "Offer" cards (where Claude waits for New session / Do it here) can only be answered in Claude Desktop or the Claude app.
- The "Open in Claude app" link (`https://claude.ai/code/<bridge session id>`) is not tested yet.
- Typing needs the PC unlocked and unused for 2 min. Otherwise it waits up to 30 min, then gives up.
  App updates of Claude Desktop may break it (it relies on the prompt box being named "Prompt").
- Plan approval (ExitPlanMode) goes through the same hook, but it has not been tested.

## Update 2026-11-10 (app 0.9.0)
- Layout rework after Filip's phone screenshot: grouped tool steps, wrapped commands and diffs, short session list (idle ones folded), compact header with folder and Claude app link, mic in the message box, 1.5 s refresh while a session is open (mc-pc polls every 1 s then).
- Signing key v2: fingerprint, strong face scan, or phone PIN (Filip chose this; Huawei face unlock only counts if the phone rates it Class 3). The key is re-registered automatically.
- Notification Allow / Deny for permission requests (prompt first), tap opens the session; Share target for text and links (inbox or Desktop session).
- Verified on the emulator with sample cards; real biometric and Huawei behaviour untested.
