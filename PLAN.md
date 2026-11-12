# Mission Control: plan (draft for Filip, 2026-11-09)

Native Android control panel that replaces the PC Waker app. Look: **A · Dark dashboard** (`docs/mockups/A-dark-dashboard.png`). Research: `docs/research/stage2-research.md`.

## 1. Parts

| Part | Where | What it does |
|---|---|---|
| **Android app** | phone | Kotlin 2.4 + Jetpack Compose (BOM 2026.09, Material 3 1.4), Glance 1.2 widget, androidx.biometric. Built with Android Studio + Gradle wrapper. minSdk 26, targetSdk 36, compileSdk 37.2 (core-ktx 1.19 needs it). |
| **mc-pi service** | Raspberry Pi | New **separate** Python service (FastAPI, systemd unit `mission-control`, own port). Stores approvals, checklists, docs, screenshots, timeline in SQLite + files under `/var/lib/mission-control`. Talks to pc-waker through its API (wake, sleep, lights, room, auto-sleep); pc-waker itself is unchanged. |
| **ntfy** | Raspberry Pi | Self-hosted push server. The phone runs the ntfy app; Mission Control receives pushes via UnifiedPush. Reachable outside home through the existing **Cloudflare tunnel**, locked with an access token. Any other app or script can use it too (`curl -d "text" <ntfy>/<topic>`). |
| **mc-pc helper** | PC | PowerShell or Python task next to the pc-waker agent. Every few seconds pushes to mc-pi: `D:\ai-hub\status\*.log` tails, HANDOFF summary, pending approvals, AI usage. Pulls Filip's answers and ideas back into `D:\ai-hub\inbox\claude\`. Tokens never leave the PC. |

## 2. Data flows
- **Approvals:** a Claude session writes an approval request file (`D:\ai-hub\approvals\pending\<id>.json`: type, title, text, options, picture paths). mc-pc sends it to mc-pi → ntfy push → phone. Filip answers; Approve needs the fingerprint, and the phone signs the answer with a KeyStore key that only unlocks with the fingerprint; mc-pi checks the signature. mc-pc writes the answer to `D:\ai-hub\approvals\answered\<id>.json` and the inbox. How a waiting Claude session picks the answer up (hook, inbox check or the desktop app's session messaging) is worked out and tested at the start of stage 4.
- **PC asleep:** answers wait on the Pi. Setting **"Wake PC when I approve"** (off by default) wakes it.
- **Ideas:** text, or voice through the phone's speech-to-text (default). Setting: **send audio instead**, transcribed by Whisper on the PC when it is awake.
- **AI usage** (read on the PC, sent as numbers only):
  - Claude: a status-line script saves `rate_limits` (5-hour + weekly %, resets).
  - Codex: the usage endpoint the Codex CLI uses for `/status` (session, weekly, monthly %), with its own login.
  - Gemini + Antigravity: their quota endpoints with their own logins (session + weekly %).
  - Each card shows "last updated", like Filip's limits app. Exact endpoints are tested in stage 4; any that fail fall back to reset time only.
- **Slime Keepers card:** public Roblox API (playing, visits, favorites) for the Live universe now; earnings + daily players via an Open Cloud API key Filip creates in stage 6 (stored only on the Pi).

## 3. Security and privacy
- Same access as pc-waker: home Wi-Fi or WireGuard, password once. ntfy is the only part reachable through the tunnel, and only with its token.
- Fingerprint (BIOMETRIC_STRONG + signed answers) before every approval.
- Public repo: no MACs, home IP, email, tokens or personal data. Config lives in `*.env` / `agent.json` (git-ignored); `*.env.example` files hold placeholders.

## 4. Stages (Filip OKs each before it starts)
1. ~~Mockups~~ done, style A picked.
2. **This plan + toolchain**: Android Studio installed, an empty app that builds and installs on the phone (dark theme, 4 tabs, no data).
3. **mc-pi service + ntfy + Home tab + notifications**: wake/sleep/lights/room/auto-sleep through pc-waker; the PC Waker app's Claude notifications move here.
4. **Claude tab**: mc-pc helper, sessions, approval queue with fingerprint, ideas, usage card for Claude, Codex, Gemini, Antigravity.
5. **Docs & Checklists**: files on the Pi, Pass/Fail/Skip + note, screenshot attach, line comments, edit on the phone, results readable by Claude.
6. **System tab + widget**: PC screenshot and temps, Pi and mini PC health, Vaultwarden backup age, tunnel, bp-gateway, Slime Keepers (with earnings), timeline, Glance widget.
7. **Retire the PC Waker app** after a week of Mission Control working.

## 5. Settings screen (collected so far)
- Wake PC when I approve (off)
- Ideas: speech-to-text / send audio
- Notifications: quiet hours, mute, which events (moved from pc-waker)

## 6. Still to decide later
- Where approval request files come from: Claude sessions need a short rule in `D:\ai-hub\README.md` (stage 4).
- Pi 64-bit reinstall: mc-pi and ntfy must be redeployed afterwards (deploy script from day one).
