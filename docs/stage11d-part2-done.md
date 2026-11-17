# Stage 11d, part 2 done: plans in Docs, line comments to the owner session, Skola outputs (2026-11-17)

Built per `stage11d-plan.md` and Filip's answers 3 to 6. Part 1 (mailbox, `mc-wait.ps1`, mc-pc delivery, typing fallback) is reused as it is.
Nothing is committed, pushed, released or version-bumped (app still 0.10.0 in the source). The new debug APK is
`android/build-cli/app/outputs/apk/debug/app-debug.apk`. `phone-gate.py` is NOT changed (`WAIT_S` stays 28700).

## What works

**1. Plans in Docs + approve**
- Every `~/.claude/plans/*.md` is a Doc of kind `plan` (Docs tab, group "Plans"), read-only on the phone. `mc_sessions.py` finds the owner session:
  a live session whose transcript lines carry `"slug":"<plan name>"`, else a one-time transcript search (cached in `%TEMP%\mc-plans-cache.json`,
  resumable, 4 s budget per run, a miss is retried after 10 min). mc-pc (`Sync-Plans`, every loop) uploads a plan when its file changed.
- A plan request from phone-gate (`kind: plan`) gets a `doc` link: from `planFilePath` in the tool input, else the session's current plan name,
  else the newest plan that session owns. This covers the empty `{}` input.
- Push "<session>: plan ready" (muted / quiet hours respected). Tapping it opens the plan Doc. No Allow/Deny buttons in that notification
  (comments must be seen first).
- Plan Doc bottom bar: **Approve** / **Reject** with the open comment count, both with fingerprint through the existing `POST /api/gate/{id}/answer`.
  Approve with open comments asks "Send the comments as changes instead?" (Send as changes / Approve anyway / Cancel).
  Reject sends "Filip wants changes... " + his note + every open comment as `Line N ("quoted line"): comment` as the deny message
  (Pi cap for the note raised from 2000 to 6000 characters), then marks those comments "sent". The bar disappears when the request is gone (answered at the PC) (the Doc is re-read every 4 s).
- The plan card in the session view: "Open plan" button, Approve / Reject there too (Approve asks first when comments are open; Reject with open comments opens the plan so they go with it).

**2. Line comments to the session**
- Owner of a Doc: the session that published it (`mc-doc.ps1` uses `CLAUDE_CODE_SESSION_ID`), for plans the slug, otherwise the newest live session whose folder contains the file
  (deepest folder first). A Doc shows "Owner: <session> · running / working / idle / ended / none".
- **Send to session** delivers all new comments as ONE Markdown file in `D:\ai-hub\to-session\<owner id>\` (batch format as above, first line "Mission Control: Filip commented on ..."),
  so a waiting `mc-wait.ps1`, the typing fallback or `inbox\claude\` (session ended) takes it. Comments are marked "sent" and are not sent twice.
- No running owner (none / ended): **Start a session** (folder field, fingerprint, signed `docstart|<slug>`). The Pi types a request into the **boss session**
  (through the existing message queue and `mc-type.ps1`); the boss starts the session with `start_session`.
- **Boss session** (defined in `sessions_hub.py`, documented in the hub README): the most recently active main Claude Desktop session (Desktop kind, has a local id) whose folder is exactly
  `D:\projekty` or `D:\ai-hub`. A side session (started by a boss for one task) normally runs in a project folder, so it never counts. There is no marker for "side session" in the session files, so this is a folder rule; it needs a fresh PC report, otherwise the phone says no boss was found and nothing is typed.
- New `D:\ai-hub\bin\mc-doc.ps1 -File <path> [-Name <title>] [-Session <id>]` (text files; copies to `to-phone\docs\` with an owner sidecar). Docs dropped by hand still work, without an owner.

**3. Skola outputs**
- New `D:\ai-hub\bin\skola-publish.ps1 -File <output> [-Review <kontrola.md>] [-Subject] [-TimeoutSec 90]` and `bin\lib\office-pdf.ps1`.
  The file is copied to a temp folder first (the original is never opened, no `~$` files), converted in a child `powershell -STA` with Word / PowerPoint / Excel COM
  in the script's own hidden, read-only instance, 90 s timeout. A PDF is copied as it is. On a timeout only the Office process the script started is killed (pid file plus
  "new process with /Automation or -Embedding"); Office windows Filip opened are never touched.
- Subject = first folder under `D:\Škola` (`-Subject` for files elsewhere). The script leaves PDF + review + owner in `to-phone\skola\<id>\` and **mc-pc uploads it within ~15 s**
  (the PC token stays with mc-pc; the script does not talk to the Pi itself). A failed PDF still sends the review and shows "PDF failed" with the original file name.
- Docs tab "School": grouped by subject; the Doc shows the review (long-press to comment) and **Open PDF**, drawn with Android's own `PdfRenderer` (no library) plus "Open in..." for another viewer app.
- Notification "New school output" when one arrives.

**Rules** added: global `C:\Users\filip\.claude\CLAUDE.md` (3 lines: after a plan, `mc-doc.ps1`, `skola-publish.ps1`) and a README section "Plans, line comments and Škola outputs in Docs".

## Pi and PC changes
- mc-pi: `docs_hub.py` (kinds plan / skola, owner, source, subject, sent flags, batch text, PDF store `docs/pdf/`, delete), `sessions_hub.py` (gate `doc`, plan notification, `boss_session`, `start_from_doc`, deny text cap),
  `mcpi.py` (owner resolver; `GET /api/docs/{slug}/pdf`, `POST /api/docs/{slug}/sent`, `POST /api/docs/{slug}/start-session` (signed), `/send` now routes to the owner;
  PC-only `POST /api/pc/docs/{slug}/pdf` and `/delete`; `GET /api/docs` adds `plans`, `skola`, owners). `GET /api/sessions` gates carry `doc` and `doc_open_comments`.
- mc-pc: `mc_sessions.py` (`plan_slugs`, `plans`, gate `doc`), `mc-pc.ps1` (`Sync-Plans`, `Sync-Skola`, owner sidecar, send events to the mailbox, comments of every doc kind in `files\docs\<slug>\`).
- App: Docs tab has Lists / Docs / Plans / School; plan bar, owner line, Send to session / Start a session, PDF viewer, `MainActivity.wantDoc` (notification tap and plan card open a Doc).

## What I verified, and how
- Python: `DocsHub` run locally (owner, batch, sent, PDF, delete, Czech slug). The whole API run in a local FastAPI test client with a test key: plan notification, gate-to-doc join,
  owner states (running / ended / none / by folder), send / start-session (queued typed message into the newest boss session, a side session is skipped), signed answers, long reject text, PDF upload checks, 401 without token.
- Real stack (deployed to the Pi, mc-pc restarted; a fake plan file, a fake session id and a test token with its own test key): the real, unchanged `phone-gate.py` run twice with an ExitPlanMode request:
  1. plan arrived in Docs with the fake owner, gate linked by `planFilePath`; **Reject with two line comments** came back as the deny message listing `Line N ("..."): ...`; comments marked sent;
  2. a plan edit made a new version; with an empty `{}` input the gate was linked through the newest plan the session owns; **Approve** returned `allow`; a second answer got 409.
  3. Send to session: with `mc-wait.ps1` running for the fake id it printed the batch (path of `comments.md` included); without a waiter the session counted as ended and the file went to `inbox\claude\`.
  4. `mc-doc.ps1` (Czech text kept, sidecar owner) and `skola-publish.ps1` (docx with Czech name + review, PDF 68 KB, PDF downloadable from the Pi as `application/pdf`).
  5. Office: docx, pptx, xlsx convert; **a Word that "Filip" had open with another file stayed alive and untouched**; a forced timeout (1 and 2 s) killed only the Office process the script started (the test Word survived); a failing PDF still sent the review with "PDF failed" and the original name; `~$` temp files and files outside `D:\Škola` without `-Subject` are refused.
- After the run everything was removed: Pi docs, test token and key, fake plan, mailbox folder, inbox file, `files\docs\` folders, `to-phone\sent` entries. `systemctl is-active mission-control pc-waker` = active, active (also after the final deploy); `/api/home`, `/api/todos`, `/api/sessions` still work.
- The three real plans are now in Docs (that is the feature); no other real data was changed.
- Android: `gradlew.bat -PcliBuild assembleDebug` succeeds. The first try failed because `build-cli` was locked; it was renamed, rebuilt and the renamed folder deleted (`git status` shows only source files).
- Notifications: the real phone may have shown test notifications ("plan ready", "New school output") while I tested.

## Not verified
- **The app was compiled but never run** (no device here): plan bar, dialogs, PDF viewer, tabs, notification taps, the instant taps and the fingerprint prompts for the new calls are untested on a phone.
- **A real plan-mode session with ExitPlanMode** (only the hook with a fake request was run). Not checked: which permission mode the session is in after Approve; that Claude shows the deny text and stays in plan mode; how the real tool input looks on this build.
- **Start a session**: the Pi side queues the typed request (tested locally); the typing into the real boss session was NOT run (never type into real sessions). Whether the boss really calls `start_session` from that text is untested.
- The typing fallback for doc comments into an idle Desktop session (same untested part as in part 1) and "owner found by folder" on the real stack (unit-tested only).
- A plan whose session ended long ago is found by searching transcripts; slow disks may need a few runs (4 s each) before its owner appears.
- PowerPoint / Excel were only tried with files made by python-pptx / openpyxl, not with real school files (none were touched).
- The PDF viewer has no pinch zoom (it draws pages at screen width); "Open in..." hands the file to a PDF app.
- The `ai-hub-inbox` mod still does not list the session's own mailbox (as in part 1).

## Filip's phone checklist (after the boss installs the new build; the boss starts the throwaway sessions and files)
- [ ] Docs tab shows four tabs: Lists / Docs / Plans / School. Plans lists the real plan files, each with its session name and "running" or "ended".
- [ ] Open a plan, long-press a line, add a comment: it shows under the line. Leave and reopen: it is still there. A plan has no Edit button.
- [ ] In a throwaway session in plan mode: when Claude asks to approve, a "plan ready" notification arrives. Tapping it opens the plan with Approve / Reject at the bottom.
- [ ] Add a comment, tap Reject (fingerprint): Claude revises the plan and asks again, and its tool result lists your comment as `Line N ("..."): ...`. The comment now shows "sent".
- [ ] On the next plan version add a comment and tap Approve: the dialog "Send the comments as changes instead?" appears. Pick "Approve anyway": the session carries on (check which mode it is in).
- [ ] Answer a plan at the PC while the phone shows it: the Approve / Reject bar disappears within a few seconds.
- [ ] The boss sends a test file with `mc-doc.ps1` (and keeps `mc-wait.ps1` running). Comment on two lines, tap "Send N to <session>": ONE message wakes the session. Tapping again says there is nothing new.
- [ ] A doc with no owner (drop a file into `to-phone\docs`): comment, tap "Start a session", fingerprint: with the PC unlocked, a request is typed into the boss session, which starts a session.
- [ ] School tab: after `skola-publish.ps1` on a COPY of a school file, it shows under its subject. "Open PDF" shows the pages, "Open in..." opens a PDF app, a comment on the review reaches the owner session.
- [ ] With Word open on another file, run `skola-publish.ps1` on a copy: your Word window stays open and untouched.
