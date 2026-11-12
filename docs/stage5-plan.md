# Stage 5 plan: Docs & Checklists (draft for Filip, 2026-11-10)

Goal: the Docs tab from the approved mockup (`mockups/dark-docs.png`, style A). Run checklists on the phone (Pass / Fail / Skip + note + screenshot + comments), read and comment on docs, edit text, and Claude gets every result back on the PC. Text-first and simple.

## 1. Where things live
- **On the Pi** (`/var/lib/mission-control/docs/`): checklists and docs as Markdown, plus results, comments and screenshots. Nothing goes into the repo.
- **Claude → phone:** Claude drops a Markdown file into `D:\ai-hub\to-phone\checklists\` or `D:\ai-hub\to-phone\docs\`. mc-pc uploads it within 15 s and moves it to `to-phone\sent\`. A checklist is any Markdown file: every `- [ ]` line is an item, `#` headings become sections, other lines show as notes. Same file name again = a new version (the old run's results are kept).
- **Phone → Claude:** mc-pc writes `D:\ai-hub\files\checklists\<name>\results.md` (every item: ✅ / ❌ / ⏭ / open, note, comments, screenshot file names) plus the screenshots next to it, updated a few seconds after each change. When Filip taps **Finish**, a message goes to `inbox\claude\` ("12 of 20 done, 2 failed: …"). Docs: edits and comments go to `D:\ai-hub\files\docs\<name>\` (the edited text + `comments.md`), and **Send to Claude** puts a message in the inbox.
- A short rule in `D:\ai-hub\README.md` tells Claude sessions about the two folders.

## 2. Import
- `roblox-game/docs/proposals/teleport-checklist.md` (28 items) is the only phone-test checklist found. It gets **copied** to the phone once (the original is not touched). `PLAN-v1-tycoon.md` also has checkboxes but is an old plan, so it is skipped.

## 3. Docs tab (as the mockup)
- Header "Docs", chip "On the Pi", switch **Checklists | Docs**.
- **Checklists:** list with progress ("12 of 20 done", "2 failed"). Opening one shows sections and items, each with **Pass / Fail / Skip** (tap again to clear). Fail opens a note field (a note is optional for the others). **Screenshot** (camera or gallery; shrunk to 1600 px on the phone before upload), **Comments** (short thread per item). **Finish** at the bottom.
- **Docs:** list (name, "edited by Claude/Filip · 2 h ago", open comments). Opening one shows the text with simple formatting (headings, bullets, bold). Long-press a line → comment on that line. **Edit** → plain text editor, Save keeps the previous version on the Pi. **Send to Claude**.
- Works offline? No: it needs home Wi-Fi or VPN like the rest (only notifications go through the tunnel).

## 4. Pieces to build
- mc-pi: `docs_hub.py` (files, results, comments, screenshots, versions) + API routes.
- mc-pc: upload `to-phone\`, pull changed results/docs back, inbox messages.
- App: Docs tab (two lists, checklist screen, doc screen, editor, comments sheet, photo picker).
- Hub README rule (section 1).

## Your OK needed
1. This plan.
2. The hub folders `D:\ai-hub\to-phone\` and `D:\ai-hub\files\checklists|docs\` + the README rule.
3. Copying the teleport checklist to the phone.

## Outcome (2026-11-10)
- Built: `pi/docs_hub.py` + routes, mc-pc `Sync-Docs` (to-phone upload, results/comments/screenshots back, inbox messages), app 0.6.0 Docs tab, hub README rule. Teleport checklist copied to the phone (original untouched).
- Tested by Claude on the Android emulator (text-only adb driving, `mcpi.py token-add emulator` + `mctoken:` login): Pass/Fail/Skip, note, item comment, Finish → `D:\ai-hub\files\checklists\teleport-checklist\results.md` + inbox message; doc line comment + Send → `files\docs\stage5-plan\comments.md` + inbox message. Fixed: wrong "failed" count, raw `**`/backticks, wrapped lines shown as separate paragraphs. Test marks were undone.
- Filip's text idea ("Test") reached the inbox: ideas (text) verified.
- Not tested: screenshot upload (camera/gallery), doc Edit + Save.
- Login now also accepts `mctoken:<app token>` (for test devices; a valid token is needed, same access as the password).
