# Publishes a new Mission Control version on GitHub Releases; the app updates itself from there.
#   .\tools\release.ps1 -Notes "What changed, one line"
# Steps: read the version from android/app/build.gradle.kts -> build a PUBLIC APK (no Pi address inside) ->
# write mission-control.json (version, sha256, notes) -> commit pending changes -> tag -> push -> GitHub release.
# Bump versionCode + versionName in build.gradle.kts first. Needs `gh auth login` (done once) and a git remote "origin".
param([Parameter(Mandatory)][string]$Notes, [switch]$NoCommit)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$gradle = Get-Content android\app\build.gradle.kts -Raw
$code = [int][regex]::Match($gradle, 'versionCode\s*=\s*(\d+)').Groups[1].Value
$name = [regex]::Match($gradle, 'versionName\s*=\s*"([^"]+)"').Groups[1].Value
if (-not $code -or -not $name) { throw 'Could not read the version from build.gradle.kts' }
$tag = "v$name"
if (git tag --list $tag) { throw "Tag $tag exists: bump the version first." }
$last = (gh release view --json tagName -q .tagName 2>$null)
Write-Host "Releasing $name (build $code); latest on GitHub: $(if ($last) { $last } else { 'none' })"

# Public build: nothing machine-specific inside the APK.
Remove-Item android\app\build -Recurse -Force -ErrorAction SilentlyContinue
Push-Location android
.\gradlew.bat assembleDebug -PpublicBuild -q
if ($LASTEXITCODE) { throw 'Build failed' }
Pop-Location
$cfg = Get-Content (Get-ChildItem android\app\build -Recurse -Filter BuildConfig.java | Select-Object -First 1).FullName -Raw
if ($cfg -notmatch 'PI_URL = ""' -or $cfg -notmatch 'REMOTE_URL = ""') { throw 'The APK still contains addresses: refusing to publish' }

New-Item -ItemType Directory -Force dist | Out-Null
Copy-Item android\app\build\outputs\apk\debug\app-debug.apk dist\mission-control.apk -Force
$sha = (Get-FileHash dist\mission-control.apk -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$root\dist\mission-control.json",
    (@{ versionCode = $code; versionName = $name; sha256 = $sha; notes = $Notes } | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))

if (-not $NoCommit) {
    git add -A
    if (git status --porcelain) { git commit -m "Release $name`: $Notes" }
}
git tag $tag
if ($LASTEXITCODE) { throw 'git tag failed' }
git push origin HEAD --tags
if ($LASTEXITCODE) { throw "git push failed (exit $LASTEXITCODE): nothing was released" }
gh release create $tag dist\mission-control.apk dist\mission-control.json --title "Mission Control $name" --notes $Notes
if ($LASTEXITCODE) { throw "gh release create failed (exit $LASTEXITCODE): the tag may already be pushed" }
Write-Host "Done: $tag is live. The app finds it within 12 h (or Settings > Check for updates)."
