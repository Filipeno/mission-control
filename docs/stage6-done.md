# Stage 6: System tab, Slime Keepers card, timeline, widget (2026-11-10)

App 0.7.0 (`dist/mission-control-0.7.0.apk`, git-ignored). Plan: `stage6-plan.md` (approved; mini PC option B, LibreHardwareMonitor yes, Pi deploy yes).

## Built
- **mc-pi** (`pi/system_hub.py` + routes in `mcpi.py`, deployed): `GET /api/system` (Pi, mini PC, services, Vaultwarden backup age, tunnel, Slime Keepers, timeline, screenshot info), `POST /api/system/screenshot`, `GET /api/system/screenshot.jpg`, `GET /api/widget`, CLI `mcpi.py roblox-key` / `ha-token` (hidden prompt). Standard library only, no new packages. `ntfy` removed from the Pi health list (retired in stage 3; it made Home say "Problem").
- **mc-pc**: GPU temp/load, CPU load, RAM, CPU temp (needs LibreHardwareMonitor) in the 15 s report; on request takes a screenshot through `pc/mc-shot.py` (Python + Pillow). Windows' antivirus (AMSI) blocks a PowerShell script that captures the screen, so the capture lives in a small separate Python script; I did not try to get around the antivirus.
- **App**: System tab, full-screen pinch-zoom screenshot, Slime Keepers card, timeline (24 h / 7 days), Glance widget (small 2x2 and large), widget refresh on every app event, after Wake and by the 30-minute system refresh.

## Verified (by Claude)
- Pi endpoints return real data (services, vault 8 h, HA answers, Roblox public 0 playing / 10 visits / 1 favorite).
- Screenshot end to end: app button -> mc-pi -> mc-pc -> mc-shot.py -> app shows it (emulator).
- PC stats arrive (GPU 36 °C, loads, RAM).
- Emulator: System tab renders; widget added at both sizes; widget Sleep opens the app's "Put the PC to sleep?" dialog (cancelled, PC not slept).

## Not verified / still open
- **CPU temperature**: done 2026-11-13 (LibreHardwareMonitor via logon task, mc-pc reads its localhost:8085 JSON).
- **Mini PC temp/disk/uptime**: needs the HA token (steps below); until then "Home Assistant answers".
- **Earnings + daily players**: need the Roblox key; the Open Cloud Analytics API is beta and the metric names (`DailyActiveUsers`, `DailyRevenue`) and response format are from docs only, never called with a key.
- Widget **Wake** (needs the PC asleep), widget on the phone's own launcher, 30-minute refresh, "as of" stale display.
- Timeline "Show more (7 days)".

## Steps for Filip
**Roblox key**: see `stage6-plan.md` section 3, then on the PC: `ssh -t pi "cd ~/mission-control && .venv/bin/python mcpi.py roblox-key"` and `ssh pi sudo systemctl restart mission-control`.

**Mini PC (Home Assistant) token**: in HA Settings > People > Users create a non-admin user `mission-control`; add the **System Monitor** integration (processor temperature, disk usage, last boot) if missing; log in as that user, Profile > Security > Long-lived access tokens > Create; then `ssh -t pi "cd ~/mission-control && .venv/bin/python mcpi.py ha-token"`, paste, restart mission-control. If the sensor names differ, edit `HA_TEMP`, `HA_DISK`, `HA_UPTIME` in `~/mission-control/mc-pi.env`.

**CPU temp**: run `winget install LibreHardwareMonitor.LibreHardwareMonitor` and accept the UAC prompt, then start LibreHardwareMonitor once as administrator and tick Options > Run On Windows Startup (and Start Minimized).

## Phone test (2026-11-10)
Filip: "Works" (System tab, Slime card, widget on his phone). Not individually confirmed: widget Wake, CPU temp, earnings.
New request from Filip (not part of stage 6): Claude tab should let him tap a session to see what it is doing, type to it, and answer AskUserQuestion prompts from the phone.
