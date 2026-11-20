# Mission Control

A native Android control panel (Kotlin + Jetpack Compose) for a home setup: wake and sleep a PC, watch and steer
Claude Code sessions, answer their questions and permission requests with a fingerprint, docs and checklists,
and a system overview. A second host, the laptop, has its own tile (wake, open an app on the PC, mode,
clipboard, notifications): see `docs/laptop-host.md`.

| Folder | What it is |
|---|---|
| `android/` | The phone app (Gradle project, minSdk 26) |
| `pi/` | `mc-pi`, a small FastAPI service for a Raspberry Pi (`deploy.sh` installs it) |
| `pc/` | `mc-pc`, the Windows helper (PowerShell + Python) that reads Claude sessions and talks to the Pi |
| `docs/` | Plans, research and mockups per stage |
| `tools/release.ps1` | Builds a public APK and publishes a GitHub release |

## Setup (short)
1. Pi: copy `pi/mc-pi.env.example` to `mc-pi.env`, then run `pi/deploy.sh`.
2. PC: copy `pc/mc-pc.json.example` to `pc/mc-pc.json`, fill it in, run `pc/install-mc-pc.ps1`.
3. Phone: build with `android/gradlew assembleDebug`, or install a release APK and enter the Pi address at login.
   Machine-specific addresses go in `android/mc.local.properties` (git-ignored).

No addresses, tokens or keys are stored in this repository.

## Fingerprint tiers
Everything the phone sends to Claude is signed with a key in the Android KeyStore; `mc-pi` checks the signature and
decides how strong it must be (`pi/tiers.py`):
- **0, no fingerprint:** any Deny without a note, picking an offered option in a question.
- **M, 5-minute window:** routine Allow, plan approval, free-text answers, messages, starting a session in the default
  mode. One fingerprint (or PIN) opens a 5-minute window; a second KeyStore key signs without a prompt inside it.
- **H, every time:** changing auto-approve, a new session in any other permission mode, "Allow once" on a Claude app
  card, key changes, and Bash / PowerShell commands that look destructive (rm/del -r, git push or force,
  deploy / publish / release, `curl | sh`, registry, money, ssh). Unknown tools and unreadable commands are H as well.

The window key is only accepted after the every-time key vouched for it. A login's first key is taken as is; a different
key later (new fingerprints enrolled) needs a new login, so a stolen token cannot plant its own key. Deploy the Pi before
installing an app that uses the window.

## Open Bitwarden on PC
System screen, "Open Bitwarden on PC": the PC helper starts Bitwarden desktop, or brings its window to the front, and the
phone gets a notification: choose "Log in with device" there, then approve in the Bitwarden app on the phone.
Mission Control never calls Bitwarden or Vaultwarden APIs and never touches vault data or secrets; it only opens the app.
For "Log in with device" to appear, set the desktop app's vault timeout action to "Log out" (a locked vault asks for the
master password instead). Always compare the fingerprint phrase on the PC with the one in the phone's approval request.
Check without opening anything: `pc\mc-pc.ps1 -TestBitwarden`.

## Updates
The app checks the latest GitHub release (`mission-control.json` + `mission-control.apk`), shows the installed version in
Settings, and installs a newer one after Android's own confirmation. To publish: bump `versionCode` and `versionName`
in `android/app/build.gradle.kts`, then run `tools/release.ps1 -Notes "what changed"`.

Release APKs are signed with a debug key, so only updates built on the same machine install over each other.
