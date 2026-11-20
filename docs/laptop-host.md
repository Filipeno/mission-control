# Laptop as a second host (0.21.0)

A "Laptop" tile on the Home screen next to the PC card. The laptop reports itself to `mc-pi`; the PC carries out
everything the phone asks for. The laptop never receives a command and no free text goes from the phone to it.

## What the tile shows
State (online / asleep / waking / offline / unknown), power (mains or battery %), link, current mode
(monitor / app / own / auto, with a "manual" tag when set by hand), Apollo and stream dots, backup status, app list.

## Actions
| Action | Tier | How |
|---|---|---|
| Wake | 0 (no fingerprint) | `mc-pi` sends the magic packet itself. Not confirmed until the laptop reports; after 120 s the tile says "Wake sent, laptop did not answer" |
| Open app on PC | M (5-minute window) | Phone -> Pi -> mc-pc runs a fixed script on the PC |
| Mode switch (monitor, app, own, auto) | M | same relay |
| Send PC clipboard | M | same relay; the tile only says "sent", never shows the text |

Tiers live in one dict, `HOST_TIERS` in `pi/host_hub.py`. Needs `laptop` in the PC helper's `caps`; the Pi answers 409
for open / mode / clip while the PC helper has not advertised it.

## Notifications (category `host`, own mute toggle in Settings)
Battery low, backup failed, stream died, slow link, wake did not answer, open app done / failed.

## Deploy order
1. Update the repo on the PC and restart the mc-pc task (`Mission Control PC helper`). An old mc-pc silently acks new job kinds.
2. Add the keys below to the real `mc-pi.env` on the Pi (it is git-ignored), then run `pi/deploy.sh`.
3. Create the host token on the Pi: `.venv/bin/python mcpi.py host-token-add laptop` (printed once). Pipe it straight into
   the laptop installer with `-TokenFromStdin`; never store it in a file. Revoke with `host-token-revoke laptop`.
4. Install the app update (Settings > Check for updates).

## `mc-pi.env` keys (values stay on the Pi)
- `HOST_ALLOW_NETS`: comma-separated CIDRs allowed to call `/api/host/*` (home LAN, VPN). Empty = nobody. Loopback is
  always refused, because a tunnel connector shows up as 127.0.0.1.
- `HOST_LAPTOP_MAC`: laptop NIC for Wake-on-LAN. `HOST_LAPTOP_BCAST` and `HOST_LAPTOP_SOURCE_IP` are optional.
- `HOST_LAPTOP_IP`: address for the "is it asleep" probe.

## Host API (host token, LAN / VPN only)
`POST /api/host/report` (every 15 s on mains, 60 s on battery; `next_in_s` in the body; stale = 3 x that) and
`POST /api/host/event`. The app side is `GET /api/home` (`hosts.laptop`) and `POST /api/hosts/laptop/{wake|open|mode|clip}`.
