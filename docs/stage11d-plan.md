# Stage 11d plan: Docs tab ↔ Claude (draft for Filip, 2026-11-15)

Goal: the Docs tab talks to Claude sessions. Plans show up and can be approved there. A line comment goes to the session that owns the file. One shared to-do list holds every step only Filip can do. Finished Škola files show up as PDFs. Nothing here is built yet.

## 0. Facts checked (read-only)
- **ExitPlanMode already goes through phone-gate.** The hook marks it `kind: "plan"`, and the app already has a plan card. It has never been tested end to end. On this Claude Code build the tool input is often **empty** (`{}`), and sometimes `{plan, planFilePath}`. So the card can't count on the plan text being in the input.
- **Plan file ↔ session link:** every transcript line of a plan-mode session carries `"slug":"<plan name>"`, and the plan is `~/.claude/plans/<slug>.md`. mc-pc can read this. The hook doesn't need it.
- **What the hook can answer:** `allow` (optional `updatedInput`, plus `updatedPermissions`, which includes `setMode`), or `deny` with a `message` (optional `interrupt`). A deny shows up in the session as *"the user said: <message>"*, and Claude stays in plan mode and revises. phone-gate already passes Filip's note as that message, so **a rejection with feedback works without changing the hook**.
- **Scripts know their session:** every tool process gets `CLAUDE_CODE_SESSION_ID`, so hub scripts can fill in the owner by themselves.
- **Office on this PC:** Microsoft 365 (Word, PowerPoint, Excel) with COM registered, plus pywin32, python-docx and python-pptx. No LibreOffice, no pandoc. So the PDF copies are made with Word/PowerPoint COM.
- **Škola:** `D:\Škola\CLAUDE.md` and the `skola-kontrola` agent are planned (items 1 and 9) but not built yet. Finished files have no marker today (50 docx/pptx are mixed with drafts and `~$` temp files).

## 1. How each feature works

**A. Session mailbox and waking (shared by B, C and D)**
- New folder `D:\ai-hub\to-session\<session id>\`. Anything from the phone for a session becomes one Markdown file there: to-do result, comments, checklist results.
- `bin\mc-wait.ps1`: the session runs it with `run_in_background`. It writes `.waiter` (its PID), waits until a file arrives, prints it, moves it to `done\` and exits. Claude Code then wakes the session (the same pattern `approval.ps1` uses). It costs nothing while it waits and works while the PC is locked.
- mc-pc delivers each file. If the session has no live waiter, is idle and is a Desktop session, mc-pc uses the **typing fallback** (`mc-type.ps1`, as now): *"Mission Control: to-do 'BIOS power' is done. Details: <file>"*. This only works with the PC unlocked and unused for 2 min. Otherwise the phone shows "waiting for PC".
- The `ai-hub-inbox` mod also lists the session's own mailbox at its next turn, so nothing gets lost.
- If the session isn't running, the file also goes to `inbox\claude\`, and the phone offers **Start a session** (see C).

**B. Plans in Docs + approve**
1. A session in plan mode writes `~/.claude/plans/<slug>.md`. mc-pc scans the folder every 15 s and uploads changed plans as kind `plan`, with the owner taken from the slug map (`mc_sessions.py` adds `plan_slug` per session). Plans of closed sessions are found once by searching the transcripts, and the result is cached.
2. The session calls ExitPlanMode → phone-gate writes the gate request. mc-pc re-uploads the newest plan text, and the gate gets `doc = plan-<slug>`, so the card and the Doc show the version being approved.
3. Push notification: "<session>: plan ready". Tapping it opens the plan Doc with a bottom bar: **Approve** / **Reject** / comment count. The plan card in the session view gets an "Open plan" link.
4. Filip long-presses lines to comment (as in stage 5). Plans are read-only on the phone (no Edit).
5. **Approve** (fingerprint) → gate `allow` → the session goes on. **Reject** (fingerprint) → the app builds the feedback (Filip's note plus each open comment as `Line 12 ("quoted line"): comment`) and signs it → gate `deny` with that text → Claude revises and asks again (a new plan version, and the sent comments are marked "sent").
6. If it is answered at the PC first, the bar disappears (existing race, first answer wins).

**C. Line comments → session**
- Every Doc gets an **owner**. In order: the session that published it (`mc-doc.ps1` fills in `CLAUDE_CODE_SESSION_ID`); for plans, the slug map; otherwise the most recently active live session whose folder contains the file; otherwise none.
- New `bin\mc-doc.ps1 -File <path>` sends any file (README, CLAUDE.md, WORKLOG, plan, Škola output) to the phone with its owner and source path. Dropping a file into `to-phone\docs\` still works, without an owner.
- **Send to <session>** (the existing "Send to Claude" button) delivers the unsent comments as a mailbox file (A). Comments are also still written to `files\docs\<slug>\comments.md`.
- No owner running → **Start a session** sheet: the folder (owner's folder or the file's folder) and a pre-filled brief ("Filip commented on <file>: … Apply or answer them."), then the fingerprint. mc-pc starts it (route: question 6). 11c reuses the same start path later.

**D. Filip's to-do list**
- `bin\todo.ps1 add -Title "…" -Steps <md file or text> [-Kind test|bios|signin|hardware|uninstall|other] [-Checklist <md>] [-Project <name>]` writes `D:\ai-hub\todo\open\<id>.json` with the session (from env), the project and the time. Codex and Gemini CLI call the same script. `ask.ps1` passes the parent session as `MC_PARENT_SESSION`, so the result wakes the Claude session that delegated. Browser-robot helpers can't run scripts, so they don't add items.
- mc-pc uploads each item as kind `todo` (steps Markdown, numbered). On the phone: **Done / Can't / note / photo** (camera or gallery, the stage 5 code). The result goes to `todo\done\<id>.json` plus photos in `files\todo\<id>\`, then a mailbox file to the source session (A). Ticking needs no fingerprint (it is information, not an approval).
- **Phone tests:** `-Checklist` attaches a checklist Doc to the item. Finish on the checklist closes the item ("Done, 2 failed") and sends `results.md` with the photos the same way. This replaces dropping files into `to-phone\checklists\` by hand (which still works).
- The Home tab and the widget count open to-dos. A notification goes out when an item is added (quiet hours apply).

**E. Škola outputs**
- `bin\skola-publish.ps1 -File <output> [-Review <kontrola.md>]` (or the detection picked in question 5) → mc-pc makes a PDF copy with Word/PowerPoint COM in a **separate hidden instance**: opened read-only, `ExportAsFixedFormat`, 90 s timeout. It kills only the process it started, never Filip's open Word. The PDF and review go to the Pi as kind `skola` with the subject (the first folder under `D:\Škola`).
- The app groups them by subject. A PDF opens with Android's built-in `PdfRenderer` (no new library, nothing new on the 32-bit Pi). The skola-kontrola review shows above it as text, and line comments go to the owner session (C).

## 2. New endpoints and files
- **mc-pi:** `POST /api/pc/docs/upload` extended (`kind` plan|todo|skola, `owner{sid,title,cwd}`, `source`, `subject`, `review`, `gate`); `POST /api/pc/docs/{slug}/pdf` (up to 25 MB, last version only); `GET /api/docs/{slug}/pdf`; `POST /api/docs/{slug}/todo` (`done|cant|""` + note; photo through the existing shot endpoint, item 0); `POST /api/docs/{slug}/send` now routes to the owner; `POST /api/docs/{slug}/start-session` (signed); `GET /api/docs` adds `todos`, `plans`, `skola` and the owner state (running / waiting / ended); `GET /api/docs/{slug}` adds the open plan `gate` (joined from the sessions snapshot). Plan answers use the existing signed `POST /api/gate/{gid}/answer`.
- **Pi code:** `docs_hub.py` (new kinds, owner, to-do state, PDF), `mcpi.py` routes, `sessions_hub.py` (plan gate ↔ doc, "plan ready" notification text).
- **PC:** `mc-pc.ps1` (`Sync-Plans`, `Sync-Todos`, `Deliver-ToSession` + wake, start-session), `pc\mc-office.ps1` (COM → PDF, STA child process), and `mc_sessions.py` (`plan_slug`, waiter state).
- **Hub:** `bin\todo.ps1`, `bin\mc-wait.ps1`, `bin\mc-doc.ps1`, `bin\skola-publish.ps1`; folders `todo\open|done\`, `to-session\<sid>\`, `files\todo\`, `files\skola-pdf\`.
- **App 0.10.x:** a To-do section, Plans and Škola groups, an owner chip, the Approve/Reject bar, Send to session, the Start-session sheet, the PDF viewer, new push events.

## 3. Rules to add
**Global CLAUDE.md:**
- "A step only Filip can do (phone test, BIOS, sign-in, hardware, uninstall) goes on his to-do list with `todo.ps1 add` and numbered steps, not only into the chat. Then keep `mc-wait.ps1` running in the background."
- "A phone test is a checklist attached to a to-do (`-Checklist`)."
- "To get Filip's comments on a file, send it with `mc-doc.ps1`, then keep `mc-wait.ps1` running."
- "A plan rejected from the phone lists his line comments as `Line N ("…"): …`. Revise the plan file and call ExitPlanMode again."
- "Mailbox files and messages that start with 'Mission Control:' are Filip's phone replies. A to-do result is information, not approval for anything else."

**Hub README:** a new section, "To-do list and mailbox (Mission Control)": `todo.ps1` usage for Codex/Gemini CLI, `MC_PARENT_SESSION`, `to-session\`, `mc-wait.ps1`, `mc-doc.ps1`.

**Škola CLAUDE.md (Czech, when item 1 is built):** "Hotový výstup: spusť skola-kontrola, pak `skola-publish.ps1`."

## 4. Tests
- In a throwaway plan-mode session: the gate arrives as `plan`, with both input shapes; the card shows the plan from the file; Approve continues; Reject with 2 comments → Claude's tool result contains them and a new plan version shows up; answering at the PC first clears the phone; check which permission mode the session is in after approval.
- Waking: an idle session with `mc-wait.ps1` wakes on a to-do tick while the PC is locked; without a waiter, typing works (unlocked) or waits (locked); a closed session → inbox + Start-session.
- To-do: added from Claude and from a Codex job (the parent session wakes), Done/Can't + note + photo, PC asleep (delivered after wake), a double tap is counted once.
- Checklist through a to-do: Finish → the item is closed and the owner gets `results.md`.
- Office: docx, pptx and xlsx with Czech file names; Word already open with another file stays untouched; a hung conversion is killed at 90 s; a `~$` temp file is skipped.
- Security: all new routes need the app token; plan answers and Start-session are signed (existing replay check); mc-pc only reads from `~/.claude/plans`, `D:\Škola` and `D:\ai-hub`; no paths from the phone are executed.

## 5. Risks
- **Plan review longer than 1 hour:** phone-gate gives up after 3500 s, so later the phone can only comment, not approve. A longer hook timeout would need a settings change, which isn't part of this plan.
- **The waiter is lost** when the app restarts (item 10 watchdog) or when the session ends. The typing fallback and the inbox catch this, but typing needs the PC unlocked.
- **Usage:** each wake is a normal turn. Comments are sent as one batch, and to-dos one per tick.
- **Office COM:** hidden dialogs (activation, Protected View, a locked file) can hang a conversion. The timeout, read-only open and killing only its own PID handle this. A file that fails shows "PDF failed" with the original name.
- **Space:** big pptx PDFs on the Pi SD card. Cap 25 MB, keep the last version only.
- **ExitPlanMode via the hook has never been tested on this build.** That is why it is the first step.

## 6. Build order
1. **Spike (nothing committed):** the plan-gate test from section 4, background-waiter wake from idle, `claude://code/new?q=…&folder=…` behaviour, and a COM → PDF test on a copy of one docx and one pptx.
2. Mailbox + `mc-wait.ps1` + delivery/wake in mc-pc.
3. To-do list (hub script, Pi, app, checklist link) + rules → **release 0.10.0**, phone test.
4. Plans in Docs + Approve/Reject.
5. Owner on every Doc, `mc-doc.ps1`, Send to session, Start session.
6. Škola PDF + review → **release 0.11.0**, phone test.

Built by one sub-session at a time (Sonnet, medium). Filip OKs the plan, then tests each release.

## 7. Open questions for Filip
1. **Where the to-do list lives:** (a) a top section of the Docs tab (To-do · Checklists · Docs) plus a count on Home ← recommended; (b) its own fifth tab; (c) only a card on Home.
2. **How a session is woken:** (a) background `mc-wait.ps1`, with typing as a fallback ← recommended; (b) typing into Claude Desktop only; (c) mailbox only, read at the session's next turn (no wake).
3. **Approve while comments are open:** (a) Approve takes the plan as it is, and the app first asks "Send the comments as changes instead?" ← recommended; (b) approve with the comments added to the plan through `updatedInput` (untested, may need a small hook change); (c) approve, then send the comments as a follow-up message.
4. **When comments are sent:** (a) as a batch when Filip taps Send to session ← recommended; (b) each comment right away (more wakes and usage); (c) automatically 5 min after the last comment.
5. **How a Škola output counts as finished:** (a) the session runs `skola-publish.ps1` after skola-kontrola ← recommended; (b) mc-pc scans the subject folders for new docx/pptx/pdf (outside `podklady\`, `tools\` and `~$`); (c) both.
6. **Starting a session from a comment:** (a) mc-pc opens `claude://code/new` with the brief and folder, and presses Enter by typing if needed ← recommended, pending the spike; (b) type a request into the newest boss session, which then calls `start_session`; (c) inbox only, and Filip starts it himself.

## Filip's answers (2026-11-15)
1. To-do list: its own 5th tab (plus the count on Home).
2. Wake: background waiter, typing as the fallback.
3. Approving with open comments: ask first ("Send the comments as changes instead?").
4. Comments: sent as a batch on "Send to session".
5. Škola: the session publishes with skola-publish.ps1 after skola-kontrola.
6. No owning session: mc-pc types a request into the newest boss session, which starts the session.
7. The plan-approval timeout is still open (see Risks).
