# Stage 4 plan: Claude tab, mc-pc helper, approvals, ideas, usage (draft for Filip, 2026-11-09)

Goal: the Claude tab from the approved mockup (`mockups/dark-claude.png`, style A): approval queue with fingerprint, sessions, usage for Claude / Codex / Gemini / Antigravity, and "send an idea to Claude".
Rule: login tokens of Claude, Codex, Gemini and Antigravity never leave the PC. The Pi only receives numbers, texts and pictures that Filip is asked to approve.

## 1. What I checked today
| AI | Source | Result |
|---|---|---|
| Claude | Claude Code status line gets `rate_limits` (5 h + weekly %, reset time) on every refresh | No status line is set up yet. Needs one line in `~/.claude/settings.json` (your OK). Updates only while Claude Code runs. |
| Codex | The endpoint the Codex CLI's `/status` uses (`chatgpt.com/backend-api/wham/usage`), called with the CLI's own login from `~/.codex/auth.json`, read in place | **Works.** Go plan has one 30-day window: 100% used, resets 2 Dec. Also says 2 "reset usage" credits left. Other plans also have 5 h and weekly windows; the card shows whatever windows come back. |
| Gemini | Gemini CLI quota call | **Not available:** your Google login has no Code Assist plan for the CLI (403), and API keys + the Gemini app have no usage API. Shows the hub's own counters instead: Gemini app jobs today (x / 25), parked keys with "back at" times, daily reset 09:00. |
| Antigravity | The quota call Antigravity itself makes (`fetchAvailableModels`), with agy's login from Windows Credential Manager, read in place, never saved anywhere | **Works.** Per model "remaining" plus the weekly reset (now: 100% left, resets 16 Nov). Shows the weekly bar (Gemini models and Claude models separately). No session window comes back. |

Each usage card shows "updated HH:MM". Mockup bars: Codex Session/Weekly/Monthly (only the windows that exist), Gemini and Antigravity Session/Weekly where they exist, otherwise reset time only.

## 2. mc-pc helper (PC), extends the stage 3 helper
`mission-control/pc/mc-pc.ps1`, same scheduled task. Next to the pc-waker agent, which stays unchanged.
- Every 5 s: asks mc-pi for commands (sleep, as now) **and** for new answers and ideas.
- Every 15 s: sends a report to mc-pi (`POST /api/pc/report`, PC token):
  - last 15 lines of each `D:\ai-hub\status\*.log` (max 4 KB per file)
  - HANDOFF summary: "Current task" + "Status" sections of `D:\ai-hub\HANDOFF.md` (max 4 KB)
  - pending approvals from `D:\ai-hub\approvals\pending\*.json`. Pictures are shrunk to 1280 px JPEG and uploaded once per approval.
  - Codex / Gemini / Antigravity "parked until" from `D:\ai-hub\state\cooldown.json`
- Every 10 min (and after an approval answer): usage. Codex + Antigravity quota calls on the PC, the Claude file written by the status line, Gemini counters. Only numbers go to the Pi.
- Claude sessions list: comes from pc-waker's agent, which already reports them. No double work.

## 3. Approval requests
- File `D:\ai-hub\approvals\pending\<id>.json`:
  `{"id","type":"commit|push|publish|design-pick|question|merge|plan","title","text","options":["Yes","No"],"pictures":["D:\\...png"],"session":"<title>","created"}`
- Made with a new hub script so nobody writes JSON by hand:
  `D:\ai-hub\bin\approval.ps1 -Type commit -Title "..." -Text "..." [-Options a,b] [-Pictures p1,p2]`
- **How a waiting Claude session gets the answer:** the script writes the file, then **waits** until `approvals\answered\<id>.json` appears and prints the answer (`Approved`, `Rejected`, the picked option, or the reply text). Sessions run it with `run_in_background`, so Claude Code wakes the session when it finishes. No hooks needed. If the session is stopped or you answer at the PC, closing the script removes the pending file. Every answer also goes into `inbox\claude\` as a normal hub message (for a session that was not waiting).
- A short rule goes into `D:\ai-hub\README.md` + the global CLAUDE.md: "when Filip must approve something and he may be away from the PC, also file it with approval.ps1". **This changes your global CLAUDE.md: your OK needed.**
- PC asleep: answers wait on the Pi. Setting **Wake PC when I approve** (off by default): mc-pi wakes the PC through pc-waker when you answer.

## 4. Fingerprint-signed answers
- After login, the app creates a KeyStore EC P-256 key that needs a fingerprint for **every** use (`BIOMETRIC_STRONG`, no timeout). It sends the public key to mc-pi once (tied to the app's login token).
- Approve / Reject / option / reply: BiometricPrompt, then the app signs `id|decision|text|time` with that key. mc-pi checks the signature (Python `cryptography`; armv7 wheel confirmed) and refuses unsigned or old (>5 min) answers. A stolen app token alone can't approve anything.
- Questions (type `question`) need the fingerprint too: same path for everything, simple.

## 5. Ideas
- Text field at the bottom of the tab + mic button using the phone's speech-to-text (default).
- mc-pi queues it, mc-pc writes `D:\ai-hub\inbox\claude\YYYY-MM-DD-HHMM-from-filip-idea.md` (hub message format).
- Settings option **Send audio instead**: records audio; mc-pc saves the file next to the inbox message. Transcribing with Whisper on the PC needs an install (not there now). **Later, with your OK.** Until then the message says "audio, not transcribed".

## 6. Claude tab (as the mockup)
- Header "Claude" + chip "N working".
- **Approvals · N**: one card per request. Type label, title, session, files/picture line, picture thumbnails (tap = full screen). Buttons by type: Approve / Reject / Reply (commit, push, publish, merge, plan), option buttons (design-pick with pictures, question) + Reply.
- **Sessions**: Claude sessions from pc-waker (Working / Needs you / Idle), plus rows for Codex, Gemini, Antigravity (Idle, or "Limit · back <date>").
- **Usage**: card with bars as in section 1, each with "updated HH:MM".
- **Status**: collapsible list of the hub status logs (last lines) and the HANDOFF summary.
- Bottom: idea field, mic, send.

## 7. mc-pi additions
`POST /api/pc/report`, `GET /api/pc/inbox` (answers + ideas for mc-pc, acknowledged after writing), `GET /api/claude` (whole tab), `POST /api/approvals/<id>/answer` (signed), `POST /api/keys` (public key), `POST /api/ideas`, picture upload/serve. Pictures and approvals live in `/var/lib/mission-control`, approvals kept 30 days. A notification "Claude needs your approval: <title>" when a new request arrives.

## 8. Also in this stage
- Test the two stage 3 leftovers: **Wake** from the app while the PC sleeps, and **Sleep** from the app (I ask before the PC is put to sleep).

## Your OKs needed
1. This plan.
2. Status line in `~/.claude/settings.json` (writes usage numbers to `D:\ai-hub\state\usage-claude.json`).
3. The approval rule in `D:\ai-hub\README.md` and your global CLAUDE.md.
4. Reading the Codex and Antigravity logins in place on the PC for their usage numbers.

## Outcome (2026-11-10)
- Built: `pc/mc-pc.ps1` (report, usage, answers/ideas → D:\ai-hub), `pi/claude_hub.py` + `pi/p256.py` (pure-Python ECDSA P-256 check; the `cryptography` package needs `cffi`, which has no armv7 wheel), app 0.5.0 Claude tab (fingerprint-signed answers, pictures, sessions, usage, hub status, ideas), `D:\ai-hub\bin\approval.ps1`, `D:\ai-hub\bin\statusline-usage.py` + statusLine in Claude Code settings, approval rule in the hub README and global CLAUDE.md.
- Verified with Filip: Claude tab, fingerprint approvals (commit + design pick with pictures) reached the PC; a background `approval.ps1` woke with `ANSWER: approve`; Sleep from the app slept the PC and Wake from the app woke it (stage 3 leftovers done).
- Not verified: ideas (text, speech, audio): Filip doesn't plan to use speech. Claude usage numbers: wait for the status line to run. Antigravity token refresh while agy is not running (code path untested). "Wake PC when I approve" with the PC asleep.
- Antigravity built a parallel Claude-tab scaffold; Filip had it rolled back (see `CHANGES_BY_GEMINI.md`); its `org.gradle.java.home` line stays because the build works with it.
