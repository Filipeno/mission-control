---
name: release-mc
description: Build and publish a verified Mission Control Android release.
disable-model-invocation: true
---

# Release Mission Control

Run this skill only when a Mission Control release is requested.

1. Read `android/app/build.gradle.kts` and record `versionCode` and `versionName`.
2. Bump both version fields in that file according to the requested release version.
3. From `android/`, build the public APK with the repository command:

   ```powershell
   .\gradlew.bat assembleDebug -PpublicBuild -q
   ```

4. Run the repository release command from the repository root:

   ```powershell
   pwsh -NoProfile -File .\tools\release.ps1 -Notes "<release notes>"
   ```

   This command rebuilds the public APK, writes `dist/mission-control.json`, commits
   pending changes, tags and pushes `v<versionName>`, then creates the GitHub release
   with `dist/mission-control.apk` and `dist/mission-control.json`.
5. Verify the endpoint used by `Updater.kt`, not only the tagged assets. Download
   `mission-control.json` and `mission-control.apk` from
   `https://github.com/Filipeno/mission-control/releases/latest/download/`.
   Confirm the JSON `versionCode` and `versionName` equal the bumped fields, and
   confirm its `sha256` equals the SHA-256 of the downloaded APK. This proves the
   self-update JSON for the latest release describes the new APK.
