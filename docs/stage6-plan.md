# Stage 6 plan: System tab, Slime Keepers card, timeline, widget (draft for Filip, 2026-11-10)

Goal: the System tab from the approved mockup (`mockups/dark-system.png`, style A) and the home-screen
widget (`mockups/dark-widget.png`). Read-only: no Home Assistant controls, no heating/LOGO! card.

## 1. What I found (checked today)
- **Roblox public API** works without a key: Slime Factory Tycoon (Live universe from `Places.luau`) shows playing 0, visits 10, favorites 1.
- **Roblox Open Cloud Analytics API** (beta): `POST apis.roblox.com/analytics-query-api/v1/universes/{id}/metrics`, scope `universe.analytics:read`, metrics include `DailyActiveUsers` and (most likely) `DailyRevenue`. Answers are a long-running operation that mc-pi polls. The revenue metric name is not confirmed yet; I test it once the key exists, and if revenue is not available the card says so.
- **PC temps:** the GTX 1660 SUPER reports its temperature through `nvidia-smi` (no admin needed). Windows gives **no CPU temperature** without an admin driver (LibreHardwareMonitor). See question 3.
- **Vaultwarden backups:** encrypted files in `/srv/vaultwarden-backups` on the Pi; the PC pull task writes its last run to `/var/lib/vaultwarden-backup/`. Last backup today 03:38, PC copy 07:12.
- **Mini PC (Home Assistant OS):** reachable on the LAN; HAOS has no SSH-free read-only health API. See question 2.

## 2. System tab (as the mockup)
- Header "System", chip **All OK** / **N problems**.
- **Gaming PC:** **New screenshot** button → the last screenshot (tap = full screen, pinch zoom). Under it: GPU temp + GPU load + CPU load + RAM when the PC is awake ("Asleep, no live temps" otherwise).
  - How: the phone asks mc-pi → mc-pi queues `screenshot` → mc-pc takes it within 5 s (all monitors, shrunk to 1600 px JPEG) → uploads → the app shows it. Only the **last** screenshot is kept on the Pi (overwritten, never sent to the PC hub or anywhere else).
  - Temps: mc-pc adds them to its 15 s report.
- **Raspberry Pi:** temp, disk used %, uptime, RAM.
- **Mini PC:** "Healthy / Down", Home Assistant up/down, plus temp, disk and uptime if you choose option B in question 2.
- **Services:** Vaultwarden backup (age of the newest backup + of the PC copy; red after 48 h / 72 h, same limits as the pull task), Cloudflare tunnel (Pi connector up + the public ntfy address answers), bp-gateway, pc-waker, mission-control, ntfy.
- **Slime Keepers card** (section 3).
- **Timeline:** last 24 h, newest first: PC woke / slept, Claude sessions finished or waiting (from pc-waker), approvals answered, checklists finished, docs sent, Vaultwarden backup saved + pulled, screenshots taken, a service going down or coming back. Tap "Show more" for 7 days.

## 3. Slime Keepers card
- Title "ROBLOX · SLIME FACTORY TYCOON", chip "Live".
- Always: **Playing now**, **Visits** (total, + today's change), **Favorites** (public API, mc-pi reads every 5 min).
- With the key: **Daily players** (yesterday, 7-day sparkline) and **Earnings** (Robux yesterday + last 7 days). mc-pi asks once an hour (the data is daily).
- Without the key: "Earnings: key not set".
- Later, when Slime Keepers 2.0 goes live, the universe id is one line in `mc-pi.env` (`ROBLOX_UNIVERSE`).

### Creating the Roblox key (you do this; it is never shown in chat)
1. Open <https://create.roblox.com/dashboard/credentials> (logged in as Filipeno696) → **API Keys** → **Create API Key**.
2. Name: `mission-control-analytics`.
3. **Access Permissions** → *Select API System*: **universe.analytics** (Analytics) → add the experience **Slime Factory Tycoon** → operation **read** only. Add nothing else (no write, no assets, no places).
4. **Security** → Accepted IP addresses: your home public IP (shown on the page as a suggestion), or `0.0.0.0/0` if your IP changes. Expiration: none or 1 year.
5. **Save & Generate key** → **Copy Key to Clipboard**.
6. On the PC run `ssh pi`, then: `cd ~/mission-control && .venv/bin/python mcpi.py roblox-key` and paste at the hidden prompt. It is written to `mc-pi.env` (mode 600, git-ignored) and checked at once ("key OK, earnings available" or the exact Roblox error).

## 4. Widget (Jetpack Glance 1.2)
- One resizable widget, as the mockup's big card: **PC Asleep/Awake + Wake** (or **Sleep** when awake), **Claude** ("2 working · 3 need you"), **Approvals** count (orange when > 0), **Checklist** progress of the newest open checklist ("12/20 · 2 failed"), Home/VPN/Offline chip. Small size (2×2) shows PC + Wake and Approvals, like the mockup's lower row.
- Tap a box → opens the matching tab. **Wake** works from the widget directly. **Sleep** opens the app's "Put the PC to sleep?" confirm (no accidental sleeps).
- Refresh: whenever the app receives an event (the notification listener already runs), after Wake/Sleep, and the 30-minute system refresh. Data comes from a small `GET /api/widget` on mc-pi (home Wi-Fi or VPN). Outside home it keeps the last values and shows "as of 07:52".

## 5. Pieces to build
- **mc-pi:** `system_hub.py` (Pi/mini PC/services/vault checks, Roblox public + analytics, timeline store), routes `/api/system`, `/api/pc/screenshot` (+ queue), `/api/widget`, CLI `roblox-key`. Python standard library only: **no new packages on the Pi**.
- **mc-pc:** handle the `screenshot` command, temps/loads in the report. Scheduled task unchanged.
- **App 0.7.0:** System tab, screenshot viewer, Glance widget (new libraries: `androidx.glance:glance-appwidget` + `glance-material3` 1.2). Home tab unchanged.
- pc-waker: unchanged. Tunnel: unchanged.

## 6. Test plan
1. Emulator: System tab numbers match `ssh pi` readings; New screenshot shows the PC screen within ~10 s; widget shows the same counts as the app and Wake works from it.
2. Phone (you): the same, plus the widget after a Claude event and after 30 min.
3. Roblox: public numbers match the Creator Dashboard; earnings after you set the key.

## Your OK needed
1. This plan (System tab, card, widget as above).
2. Mini PC health: **A** ping + Home Assistant answering (no login), or **B** also temp/disk/uptime via a Home Assistant long-lived token from a new non-admin HA user you create (HA tokens can't be made read-only; mc-pi would only read 3 sensors).
3. PC CPU temperature: **skip it** (GPU temp + loads only), or install **LibreHardwareMonitor** (admin driver, runs at logon).
4. Deploying to the Pi (new files in `~/mission-control`, restart of `mission-control`; no new packages, no new ports).
