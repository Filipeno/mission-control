# Stage 7 done: PC Waker Android app retired (2026-11-14)

Mission Control replaced the old PC Waker Android app. The pc-waker **server** on the Pi (port 8765) and its PC agent
keep running, because mc-pi uses them.

## What mc-pi uses on pc-waker (127.0.0.1:8765), untouched
- `GET /api/events` (long-poll, notifications)
- `GET /api/status?room_s=N`
- `POST /api/wake`
- `POST /api/pc-lights`
- `POST /api/autosleep`
- `POST /api/stay-awake`
- `POST /api/room-settings`

## What existed only for the Android app
| Item | What I did |
|---|---|
| `pc-waker/android/` (source, `build.ps1`, APK, signing key) | Moved to `D:\projekty\_archive\pc-waker-android\` (nothing deleted). Includes `release.keystore` and `keystore.pass`, so keep that folder safe. |
| "Get the Android app" link on the page (`index.html`, `app.js`, `app.css`) | Removed. The notification hint now says notifications come from Mission Control. |
| `GET /app/PC-Waker.apk`, `GET /app/version.json` in `pi/server.py` | Removed (now 404). |
| README "Android app" section | Replaced by a "retired 2026-11, use Mission Control" note. |
| `~/pc-waker/downloads/` on the Pi (old APK + json, 70 KB) | Left on disk but no longer served. Safe to delete later with Filip's OK. |

Left alone on purpose (the smallest safe change): the login/cookie system and `/api/events` + `/api/test-notification`, which the
page and mc-pi still use. There were no app-only tokens or sessions.

## Deploy and checks
Deployed as the README says (scp `server.py`, `notify.py`, `static/` to `~/pc-waker`, then restart). The Pi files matched the repo before the change, so nothing from another session was overwritten.
- `systemctl is-active pc-waker mission-control`: both active.
- Page: `/app.css` 200, `/` redirects to login (expected without a cookie), `/app/PC-Waker.apk` and `/app/version.json` 404.
- mc-pi `/api/home` returns the PC state (online, agent and helper connected); `/api/events` through mc-pi answers 200.
- One `events: pc-waker unreachable` line in mc-pi's log at the moment of the restart, then it recovered.

## For Filip
1. Uninstall the PC Waker app from the phone (and remove the WireGuard app's "allow remote control" setting only if nothing else needs it).
2. GitHub (not touched here, needs your OK): the `Filipeno/pc-waker` releases `v1.x` hold `PC-Waker.apk` and `PC-Waker.json`. Old installed copies read `PC-Waker.json` from the latest release for auto-update. Options: delete the releases, or leave them and mark the last one as a pre-release. Nothing else in the repo points at them.
3. Optional: delete `~/pc-waker/downloads/` on the Pi, and later the archive folder once you are sure.
