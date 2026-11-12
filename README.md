# Mission Control

A native Android control panel (Kotlin + Jetpack Compose) for a home setup: wake and sleep a PC, watch and steer
Claude Code sessions, answer their questions and permission requests with a fingerprint, docs and checklists,
and a system overview.

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

## Updates
The app checks the latest GitHub release (`mission-control.json` + `mission-control.apk`), shows the installed version in
Settings, and installs a newer one after Android's own confirmation. To publish: bump `versionCode` and `versionName`
in `android/app/build.gradle.kts`, then run `tools/release.ps1 -Notes "what changed"`.

Release APKs are signed with a debug key, so only updates built on the same machine install over each other.
