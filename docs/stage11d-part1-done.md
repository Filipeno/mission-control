# Stage 11d, part 1 done: session mailbox, waiter, to-do list (2026-11-15)

Built per `stage11d-plan.md` (Filip's answers: own 5th tab, background waiter with typing fallback). Part 2 (plans in Docs,
line comments, Skola) is not touched. Nothing is committed, pushed, released or version-bumped (app is still 0.9.5; the
new debug APK is `android/build-cli/app/outputs/apk/debug/app-debug.apk`).

## What works
**Session mailbox + waiter**
- `D:\ai-hub\to-session\<session id>\` holds one Markdown file per phone reply. `D:\ai-hub\bin\mc-wait.ps1` (run in the
  background) writes `.waiter` (PID + start time), waits, prints the files, moves them to `done\`, exits. Only one waiter per
  session; a stale `.waiter` is detected by PID + start time.
- mc-pc (`Process-Mailboxes`, every 15 s) delivers files nobody waits for:
  1. waiter alive: leave it (the waiter reads it at once);
  2. session not running: copy to `inbox\claude\`;
  3. Desktop session, idle: type "Mission Control: ... Details: <path>" through `mc-type.ps1`, with no idle wait
     (see "Extra change" below); PC locked or draft in the prompt box: wait and retry (locked: every 15 s, other failures: 60 s);
  4. session busy / not a Desktop session: stays in the mailbox (the waiter or the next turn picks it up).
- The Pi remembers the delivery state per item (waiter / typed / inbox / waiting) and the app shows it under done items.

**To-do list, end to end**
- `D:\ai-hub\bin\todo.ps1 add|list|show` (`-Title -Steps [-Kind] [-Checklist] [-Project] [-Session] [-Source]`). Unnumbered step
  lines are numbered. Session comes from `MC_PARENT_SESSION` (ask.ps1 now sets it to the delegating Claude session), else
  `CLAUDE_CODE_SESSION_ID`. Items live in `D:\ai-hub\todo\open|done\`.
- mc-pi: new `pi/todo_hub.py` and routes `/api/todos...` (list, one, note, photo, photo file, result, reopen) and `/api/pc/todos/...`
  (upload, changes, ack, delivery, photo). All need the app or PC token. A closed item ignores later results (double tap counts once),
  and results wait on the Pi while the PC sleeps. `docs_hub.py` marks a checklist as belonging to an item; finishing it closes
  the item with "Done, N failed". `/api/home` and `/api/widget` carry the open count. A push "New to-do for you" goes out when an item
  is added (respects mute, the Claude category and quiet hours); tapping it opens the To-do tab.
- mc-pc: `Sync-Todos` uploads items, downloads photos to `D:\ai-hub\files\todo\<id>\`, writes `result.md`, puts the message in the
  source session's mailbox and moves the item to `todo\done\`. Checklist results are named in the message
  (`files\checklists\todo-<id>\results.md`).
- App (`ui/TodoScreen.kt`): 5th tab "To-do" with a count badge; Home has a "Your to-do list" card with the count (tap opens the tab).
  Open items list, detail with numbered steps, note, photos (camera or gallery), "Open the checklist" if one is attached,
  Done / Can't do it. Taps are instant (the item moves to "Done recently" at once, the call runs queued behind it, and a failure
  shows a toast and reloads); an Undo is offered until the PC has taken the result.
- Rules added: global `C:\Users\filip\.claude\CLAUDE.md` (2 lines), `D:\ai-hub\README.md` new section "To-do list and mailbox".

**Extra change from Filip (during the build):** messages typed into Claude Desktop from the phone no longer wait for the PC to be
idle. Removed the 2-minute idle check in `mc-pc.ps1` `Send-Typed` and in `mc-type.ps1` (`-IdleSec` and exit code 4 are gone).
The "PC is locked" wait and the draft-in-prompt-box check (code 5) stay. The mailbox typing fallback also types at once.

**Bug fixed on the way:** mc-pc read Pi replies with `Invoke-RestMethod`, which in Windows PowerShell 5.1 decodes JSON without a
charset as Latin-1, so Czech text came out garbled (it also affected Docs text and comments). `Api` now decodes UTF-8.

## What I verified, and how
- Python: `TodoHub` unit-run locally (upload idempotent, photo, double result, reopen, checklist close, ack, reopen blocked after ack).
- Deployed with `pi/deploy.sh`; after it and after the final cleanup restart `systemctl is-active mission-control pc-waker` = active, active;
  `/api/home` works (has `todos.open`); new routes return 401 without a token.
- Real flow on this PC with three test items (all removed afterwards, also from the Pi):
  1. `todo.ps1 add` with a checklist, mc-pc uploaded it, the Pi created the checklist doc and the item; a "phone" tick via the API
     (photo + Czech note + a second tap) delivered once, photo downloaded, `result.md` written, file moved to `todo\done\`, delivery "waiter".
  2. A background `mc-wait.ps1` woke this session when the result arrived (task notification), printed the file and exited;
     a second waiter refused to start; the `.waiter` file was cleaned.
  3. Checklist finish via the API closed the item with "Done, 1 failed" and delivered it; the message named the results file;
     with no waiter and the session busy the state stayed "waiting" (mailbox kept the file).
  4. An item for a session that is not running went to `inbox\claude\`, with the state "inbox".
  Czech text survived end to end after the encoding fix.
- Android: `gradlew.bat -PcliBuild assembleDebug` succeeds (warnings only; `build-cli` was locked, so it was renamed, rebuilt and the
  renamed folder deleted; no stray folders, `git status` shows only intended files).

## Not verified / deviations from the plan
- **Spike on a real idle Desktop session was not possible.** `start_session` was refused for this sub-agent (permission not granted), so I
  could not create a throwaway session. I proved that a background `mc-wait.ps1` completing wakes the session that runs it (harness
  notification, repeated twice), which is the same mechanism `approval.ps1` already relies on. Still untested: waking a session that is
  truly idle (turn ended), and the **typing fallback** for the mailbox (`mc-type.ps1` was only parse-checked; typing into one of Filip's
  real sessions was not safe to try). Please test both on the phone checklist below.
- The `ai-hub-inbox` mod does not yet list the session's own mailbox at its next turn (plan section A). I left the mod alone: it runs in
  every session, I cannot test it here, and the waiter + typing + inbox paths already cover delivery. Small follow-up if wanted.
- The app was compiled but not run on a phone or emulator (no device here). The widget JSON carries `todos`, but the widget does not show it yet.
- `mc-type.ps1` and the app notification `tab` extra (opens the To-do tab) are untested beyond compiling.

## Filip's phone test (after the boss installs the new build)
1. Open the app: there is a 5th tab "To-do" (badge with the count when something is open) and a "Your to-do list" card on Home; the card opens the tab.
2. The boss adds a test item with `todo.ps1 add` (with `-Checklist`). Within about 20 s a notification "New to-do for you" arrives; tap it: the To-do tab opens.
3. Open the item: numbered steps are readable, "Open the checklist" opens the attached checklist.
4. Add a photo (camera and gallery) and type a note, then tap **Done**: the item jumps to "Done recently" immediately, and its line later says where the answer went.
5. Tap Done twice quickly on a second item: Claude must get only one message.
6. On a third item finish the checklist (with one Fail): the item closes with "Done, 1 failed" by itself.
7. Tap **Can't do it** on another item and check the note arrives; try Undo right after a tap.
8. Waking: with a session idle and `mc-wait.ps1` running in the background, tick an item; the session should wake within about 20 s, also with the PC locked.
9. Without a waiter, tick an item for an idle Desktop session while the PC is unlocked and untouched: a "Mission Control: to-do ..." line should be typed into the session (this is the untested typing fallback).
10. Tick an item for a closed session: the answer shows "Saved to the Claude inbox".
