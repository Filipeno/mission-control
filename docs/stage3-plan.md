# Stage 3 plan: mc-pi, ntfy, Home tab, notifications (draft for Filip, 2026-11-09)

Goal: the Home tab works on the phone (wake/sleep, room, lights, auto-sleep, Pi health, recent events),
and the PC Waker app's notifications arrive in Mission Control through ntfy. pc-waker stays unchanged.

## 1. What I found (checked today)
- Pi: armv7l, Python 3.10.12, `python3-venv` + `pip` installed, 12 GB free, 7.4 GB RAM free. Ports in use: 22, 80, 443, 6052, 8765 (pc-waker), 8770 (bp-gateway, localhost), 9000/9001, 18443, 20241 (cloudflared metrics).
- pc-waker API (cookie login, `X-Requested-With: pc-waker` on POSTs): `/login`, `/api/status`, `/api/events` (long-poll), `/api/wake`, `/api/pc-lights`, `/api/autosleep`, `/api/stay-awake`, `/api/room-settings`, `/api/notify-settings`, `/api/test-notification`.
- **pc-waker has no "sleep now" call.** The PC only sleeps when auto-sleep decides it (reply to the PC agent). So the Sleep button needs something on the PC (see 4).
- The Cloudflare tunnel is remotely managed in the Cloudflare dashboard and has **two connectors**: the mini PC's Cloudflared add-on and `cloudflared.service` on the Pi (redundant). Both reach <pi-ip>, so a new public hostname works through either.
- ntfy latest is **v2.37.2**, with an official `linux_armv7.deb`.
- UnifiedPush Android connector latest is **org.unifiedpush.android:connector 3.3.5** (Maven Central).

## 2. mc-pi (Pi service)
- Python 3.10 + FastAPI + uvicorn in a venv at `/home/filip/mission-control/.venv` (pydantic-core armv7l wheel was already confirmed in stage 2; I re-check every wheel with `pip download --only-binary` before installing).
- systemd unit `mission-control.service`, user filip, `StateDirectory=mission-control` (`/var/lib/mission-control`), same hardening as pc-waker. Port **8780**, LAN/WireGuard only (not in the tunnel).
- Config in `/home/filip/mission-control/mc-pi.env` (0600, git-ignored); `mc-pi.env.example` in the repo with placeholders.
- Talks to pc-waker on `http://127.0.0.1:8765` with its own pc-waker login (password kept in `mc-pi.env`, so it can log in again when the 30-day cookie runs out).

| Endpoint | Does |
|---|---|
| `POST /api/login` | Phone sends the password once. mc-pi checks it by logging in to pc-waker (same password as pc-waker) and returns a long-lived app token (stored hashed, revocable with `mc-pi revoke`). Same lockout as pc-waker: 5 wrong tries / 15 min. |
| `GET /api/home` | One call for the whole Home tab: PC on/off + since, auto-sleep (on, idle min, blockers, warning), room (present, last motion, sensor fresh), lights, Claude sessions waiting (count), Pi health, last 10 events. Built from pc-waker `/api/status` + own Pi readings. |
| `POST /api/pc/wake` | → pc-waker `/api/wake` |
| `POST /api/pc/sleep` | Queues a sleep command for the PC helper (see 4). Answers 409 "PC helper not connected" if the helper hasn't checked in for 30 s. |
| `POST /api/lights` `{on}` | → pc-waker `/api/pc-lights` |
| `POST /api/autosleep` `{enabled, idle_min}` / `POST /api/stay-awake` `{minutes}` | → pc-waker |
| `POST /api/room-settings` | → pc-waker (only `wake_on_enter`, `block_sleep` from the app) |
| `GET/POST /api/settings` | Mission Control's own notification settings: mute, quiet hours (from/to), which kinds (Claude done / waiting / error / stuck, sleep warnings, room, vault), "Wake PC when I approve" (stored, used in stage 4). |
| `POST /api/push/register` `{endpoint}` | The app sends its UnifiedPush endpoint (a ntfy topic URL). |
| `POST /api/push/test` | Sends a test push. |
| `GET /api/pc/command` (PC token) | The PC helper polls this every 5 s: `{"cmd": "sleep"}` or nothing. |

- **Pi health** (own readings): CPU temp (`/sys/class/thermal`), uptime, load, RAM, disk, and `systemctl is-active` of pc-waker, mission-control, ntfy, cloudflared, bp-gateway.
- **Notifications:** a background thread long-polls pc-waker `/api/events` (same as the PC Waker app does today), applies Mission Control's mute / quiet hours / kinds, and POSTs each event to the phone's UnifiedPush endpoint on ntfy (localhost, with mc-pi's ntfy token). Quiet hours = delivered silently. Action buttons (e.g. "Stay awake 60 min") are passed along; the app sends them back to mc-pi, which forwards to pc-waker.
- Note: pc-waker's own mute must stay off, otherwise pc-waker holds the events back from mc-pi too. During the changeover week, turn off notifications for the **PC Waker app** in Android settings to avoid double notifications.

## 3. ntfy on the Pi
- Install `ntfy_2.37.2_linux_armv7.deb` from GitHub releases (no apt repo), systemd unit `ntfy` from the package.
- `/etc/ntfy/server.yml`: `base-url: https://<ntfy-host>`, `listen-http: :2586`, `behind-proxy: true`, `auth-file: /var/lib/ntfy/user.db`, `auth-default-access: deny-all`, cache + attachments off (not needed), `upstream-base-url` **not** set (no Google/Firebase).
- Users: `filip` (phone, read-write to `up*`) and `mc-pi` (write to `up*`). Each gets an access token (`ntfy token add`); tokens go only into the ntfy app on the phone and into `mc-pi.env`.
- Topics: UnifiedPush makes its own random `up…` topic per app; mc-pi stores it. Extra topic `mc-alerts` for scripts (`curl -H "Authorization: Bearer …" -d "text" https://<ntfy-host>/mc-alerts`), subscribed in the ntfy app.

## 4. Sleep button: tiny PC helper (first piece of stage 4's mc-pc)
- `mission-control/pc/mc-pc.ps1`, a scheduled task at logon (like the pc-waker agent). Every 5 s: `GET /api/pc/command` with a PC token from `mc-pc.json` (git-ignored). On `sleep` it calls the same `SetSuspendState` the pc-waker agent uses.
- Stage 4 extends this same helper (hub status, approvals, usage).

## 5. Phone push path
1. Filip installs **ntfy** from F-Droid or Play, adds server `https://<ntfy-host>`, logs in with the `filip` token. Battery: "unrestricted" for ntfy (its one connection serves all apps).
2. Mission Control uses UnifiedPush connector 3.3.5: on first start it picks ntfy as distributor, gets an endpoint URL, sends it to mc-pi (`/api/push/register`).
3. mc-pi posts events (JSON) to that endpoint; ntfy wakes Mission Control, which shows the notification (channels: Claude, PC & sleep, Room, System; quiet = silent channel). Tap opens the Home tab.
- Works on home Wi-Fi and outside (through the tunnel). Controlling the PC from outside still needs WireGuard, as today.

## 6. Tunnel change (needs your separate OK, shown before I do it)
In the Cloudflare dashboard → Zero Trust → Networks → Tunnels → (the home tunnel) → Public hostnames → add:
`<ntfy-host>` → `http://<pi-ip>:2586`. Nothing else changes (Home Assistant, Portainer, bp-gateway stay as they are). I do it in the browser pane if you sign in there, or you click it yourself.

## 7. App (Home tab + Settings)
- Home follows the approved mockup `mockups/dark-home.png`: PC card (state, since, auto-sleep line, **Wake PC** + **Sleep**), Room, Lights (tap toggles), Auto-sleep (tap: on/off, long-press: idle minutes), Pi (temp, uptime, red if a service is down), **Waiting for you** (count of Claude sessions waiting, from pc-waker; approvals come in stage 4), Recent (last events). Pull to refresh + refresh every 5 s while open. The "Slime Keepers phone test" card waits for stage 5. A "Home Wi-Fi / VPN / Offline" chip at the top.
- Login screen: Pi address (default filled in) + password, once. Token stored with EncryptedSharedPreferences / KeyStore.
- Settings (gear icon on Home): mute, quiet hours from/to, kinds of notifications, "Wake PC when I approve" (off, says "used from stage 4"), push status (distributor, last push), "Send test push", log out.
- New libraries: OkHttp 5, kotlinx-serialization, lifecycle-viewmodel-compose, UnifiedPush connector 3.3.5. No Firebase.

## 8. Deploy
- `mission-control/pi/deploy.sh` (run from the PC, Git Bash): rsync/scp `pi/` to `/home/filip/mission-control`, make the venv, `pip install -r requirements.txt`, install/refresh the systemd unit, restart, and check `/api/health`. First run with `--setup`: prompts for the pc-waker password, creates tokens, writes `mc-pi.env`. Re-runnable after the 64-bit reinstall.
- `pi/install-ntfy.sh`: downloads the .deb, writes `server.yml`, creates users + tokens (printed once).

## 9. Test plan
1. mc-pi: `/api/home` matches pc-waker's page; wake from the app wakes the PC; sleep from the app puts it to sleep (helper running).
2. `POST /api/push/test` → notification on the phone, on Wi-Fi and on mobile data.
3. A real pc-waker event (e.g. pc-waker's test notification, or a Claude session finishing) arrives in Mission Control.
4. pc-waker page and PC Waker app still work the same.

## Questions for you
- OK to install ntfy 2.37.2 + mc-pi on the Pi (ports 2586, 8780)?
- Sleep button: OK to add the tiny PC helper now (section 4)?
- Later, separately: the tunnel hostname in section 6.

## Outcome (2026-11-09)
- Built and running: mc-pi (`mission-control.service`, port 8780), PC helper `pc/mc-pc.ps1` (scheduled task "Mission Control PC helper"), app 0.4.0.
- Login: mc-pi checks the password against pc-waker's own hash in pc-waker.env and signs pc-waker cookies itself, so no second copy of the password is stored.
- **Notifications changed during testing:** the ntfy app kept dropping its connection, so Filip chose Mission Control's own connection instead. mc-pi keeps an event list and serves `GET /api/events` (long-poll, max 55 s). The app's foreground service polls the Pi address at home and the tunnel address outside. Tunnel route `mc.<host>` with path `^/api/events$` only → mc-pi. Everything else on that hostname is 404, and no token gives 401. Tested on Wi-Fi and mobile data without VPN.
- ntfy was uninstalled from the Pi (Filip's choice). `install-ntfy.sh` stays in the repo if it is wanted again. The `ntfy.<host>` tunnel route still exists and is unused.
- Verified by Filip on the phone: Home tab (lights and auto-sleep calls seen in pc-waker's log), notifications at home and outside. Not exercised yet: Wake from the app while the PC is asleep, Sleep button on the real PC.
