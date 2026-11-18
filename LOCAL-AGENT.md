# LOCAL-AGENT notes (Mission Control)

## Layout
- `android/` Kotlin + Jetpack Compose app (minSdk 26). Version: `versionCode` / `versionName` in `android/app/build.gradle.kts`.
- `pi/` `mc-pi` FastAPI service for the Raspberry Pi (`mcpi.py`, `*_hub.py`).
- `pc/` `mc-pc` Windows helper (PowerShell + Python). Tests are `pc/test_*.py`.
- `tools/release.ps1` builds the public APK and publishes a GitHub release.

## Commands (run from repo root, PowerShell or Git Bash)
- Pi tests: `python -m unittest discover -s pi -p "test_*.py"`
- PC tests: `python -m unittest discover -s pc -p "test_*.py"` (each file also runs with `python pc/test_x.py`)
- Android debug build: `android\gradlew.bat assembleDebug` (no unit-test sources were found in the repo)
- Public build used for release: `android\gradlew.bat assembleDebug -PpublicBuild`
- Release: bump `versionCode` and `versionName` first, then `.\tools\release.ps1 -Notes "one line"` (needs `gh auth login` and remote `origin`)
- Pi deploy: `pi/deploy.sh` (needs `ssh pi` and sudo on the Pi)

## Pitfalls
- Secrets stay out of git: `mc-pc.json`, `mc-pi.env`, `mc.local.properties`, `*.keystore`, `*.pass`, `secrets/`, `state/`. They are in `.gitignore`; keep it that way.
- Public APK must have empty `PI_URL` and `REMOTE_URL`. `release.ps1` refuses to publish otherwise. Do not build the release with `mc.local.properties` addresses.
- Release APKs are signed with a debug key, so updates only install over builds from the same machine.
- `pi/deploy.sh` copies an explicit file list (`tar -cf - ...`). A new Pi module must be added there, or it will not reach the Pi.
- `deploy.sh` must never touch `pc-waker`; it only reads `pc-waker.env` on the Pi.
- `release.ps1` runs `git add -A` and commits pending changes. Check `git status` first.
- `build/`, `dist/`, `*.apk` and `__pycache__/` are generated. Do not commit them.
- The CLI build folder `build-cli` has been locked by sync tools before. Rename it and rebuild if so (WORKLOG 2026-11-14).
- Keep `README.md` and `WORKLOG.md` as the source of project history; the repo has no CLAUDE.md or AGENTS.md.
