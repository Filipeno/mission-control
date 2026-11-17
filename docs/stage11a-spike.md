# Stage 11a-1 spike: answering the desktop app's own approval cards

Date 2026-11-17. Claude desktop app 5.11492.5, Windows 11. Files: `pc/mc-appcard.ps1` (UIA side), `pc/mc_appcard.py` (log parser and checks), `pc/test_mc_appcard.py` (28 tests).

## What the script does
`mc-appcard.ps1 -List | -Answer <requestId> -Decision allow|deny [-ExpectTitle T] [-Tool T] [-DumpTree file] | -WaitNext ...`

1. Log check (`mc_appcard.py check`): the card is in `%LOCALAPPDATA%\Claude\Logs\main.log` since the last app start, still pending (an `Emitted tool permission request` line, no `Received permission response` or `aborted` line), not an AskUserQuestion card, tool equals `-Tool`, session title equals `-ExpectTitle`, the title is used by only one non-archived session, and it is the only Allow/Deny card pending in that session. Records the log offset.
2. Opens the session with `claude://claude.ai/epitaxy/<local_id>` and binds to it: exactly one `RootWebArea` whose UIA Value (its URL) is `https://claude.ai/epitaxy/<local_id>`, its name must be `<title> - Claude Code`, and no second document may carry that name.
3. Brings the window to the front, finds exactly one `Allow once` button and its smallest ancestor holding exactly one `Deny`; that group must be named `Permission request…`.
4. Re-check right before the click: same card name, same session URL, button name unchanged and enabled, and `check --since <offset> --card-name <name>` again: still the only pending card, no new card emitted for that session since the offset, and the card name must fit the tool (`CARD_PHRASE`: start_session → `Permission request: start the session`; any tool not in that table is refused).
5. `InvokePattern.Invoke()` on the button. If no log confirmation in 4 s, a real mouse click, only when the element under the button centre is that button (and after one more log re-check).
6. Done only when main.log shows `Received permission response for <id>: once|deny`. Never touches "Always allow".

Exit codes: 0 done, 2 bad args, 3 PC locked, 4 refused by log check, 6 no window, 7 wrong session, 8 card not found/ambiguous/changed, 9 not confirmed, 10 no new card.

## Live proof (2026-11-17)
| What | Result |
|---|---|
| Deny, real card `486fcb05…` (start_session in test chat "MC card test 3 (asks to start one)", default mode) | exit 0, method `invoke`, confirmed by `18:53:09 Received permission response for 486fcb05…: deny`. Card emitted 18:53:02, answered 7 s later. |
| Wrong title on that pending card (`-ExpectTitle 'Some other chat'`) | exit 4, `title mismatch` |
| Same, from a waiter that expected this chat's own title | exit 4, `title mismatch` (nothing clicked) |
| Wrong tool (`-Tool …delete_session`) | exit 4, `tool mismatch` |
| Unknown id `00000000-1111-…` | exit 4, `unknown request id (not in the log since the last app start)` |
| Two cards pending in one session | unit tests only (`test_two_pending_same_session`, `test_check_two_pending`); one chat can't raise two cards at once live |
| Allow once | **not proven in this run** (see below). The earlier WIP run noted live that Invoke on "Allow once" of a background window was ignored while Deny worked, hence the bring-to-front step. |

### UIA facts seen live (app 5.11492.5)
- Card = `Group` with class `epitaxy-approval-card …`, name `Permission request: start the session “<new title>”`. Children: Text runs ("Allow Claude to ", "start the session", "“<title>”", "?", model line, reason line, the brief), a `Button` "Background, 1 line" (ExpandCollapse), `Button` "Deny" (Invoke), `Button` "Allow once" (Invoke). No AutomationIds on any of them.
- Just above the card there is a `StatusBar` (sr-only) with one Text that spells the whole card: "Permission requested: start the session. <brief>. Background, 1 line, “<title>”. Works in this folder, Haiku 5.5, Low effort. Claude wants to start another session. Claude is continuing on its own, without a new message from you." Good source for the phone text.
- "Always allow" was not offered on this card (`alwaysAllowOffered: false`).
- The session document is a `RootWebArea` named `<title> - Claude Code`; its ValuePattern value is the `claude.ai/epitaxy/<local_id>` URL, so the click is bound to the session id, not only the title.
- A Deny on the card ends that chat's turn ("stopped before its turn finished"); the model does not get to retry.

### When cards appear (matters for the integration)
- A bypass-mode orchestrator calling start_session got **no card**, both on its first task turn and on a continued (side-session-event) turn: the app auto-allows it. On the side-session-event turn the app refused the start outright ("Start sessions only on the user's own words…").
- A session in `default` permission mode did raise the card on its first (task) turn.
- So the cards Filip sees come from sessions in default/acceptEdits/plan mode or from the cases the research lists (unattended turns, 10-start cap); bypass sessions mostly don't produce them.

## Limits
- Needs the PC unlocked (LogonUI check), the Claude window present, and the window brought to the front (it steals focus for ~1 s).
- Card phrases and button names are app-version specific; `CARD_PHRASE` must be extended per tool after its card has been seen once. Unknown tools are refused.
- The log has no tool input; the phone must read it from the session transcript (`tool_use` without `tool_result`) or from the StatusBar text above.
- Titles must be unique among non-archived sessions, or the card is refused.

## What the integration (11a-1 step 2) needs
- mc-pc tails main.log (`mc_appcard.py wait/list`), builds the phone item with tool, title, the StatusBar text / transcript input and a screenshot.
- On the phone answer, call `mc-appcard.ps1 -Answer <id> -Decision … -ExpectTitle <title shown on the phone> -Tool <tool shown>`; any non-zero exit goes back to the phone as "refused: <reason>".
- Drop the phone item when list shows the card answered or aborted at the PC.
- Hold answers while LogonUI runs; expire after 8 h.
- Before shipping: one live Allow once on a real card (still open from this spike).
