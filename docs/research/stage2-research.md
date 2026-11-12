# Stage 2 research (2026-11-09)

Sources: Gemini app (Flash) web research, then checked by Claude. **Checked** = Claude confirmed it directly (Maven metadata, a live API call, the Pi, or the local Claude Code build). Everything else is a lead, not a fact.

## Decisions so far
- Style **A · Dark dashboard** (picked 2026-11-09). Mockups: `../mockups/`.
- Roblox card shows **Slime Keepers**.

## 1. Android toolchain (Windows, no Android Studio needed)
| Piece | Version | Status |
|---|---|---|
| Android Gradle Plugin | 9.5.1 | Checked (Google Maven) |
| Gradle | 9.9.0 | Checked (services.gradle.org) |
| Kotlin | 2.4.21 | Checked (Maven Central) |
| Compose BOM | 2026.09.00 | Checked (Google Maven) |
| Material 3 | 1.4.0 | Checked (Gemini said 1.3.0: outdated) |
| Glance app widget | 1.2.0 | Checked |
| androidx.biometric | 1.1.0 stable | Checked |
| JDK | 17 | Already installed (Adoptium 17.0.7) |
| Android SDK | platforms;android-35 + build-tools 35.0.1 installed; Compose BOM 2026.09 likely wants compileSdk 36 | Needs install: platforms;android-36, build-tools;36.x, platform-tools |

- pc-waker builds its APK with no Gradle (aapt2 → javac → d8). That will not work for Kotlin + Compose (needs the Kotlin compiler plugin), so Mission Control uses the **Gradle wrapper** (`gradlew`): it downloads Gradle and the libraries itself (about 1-2 GB of caches in `~/.gradle`).
- Sideloaded apps have no targetSdk rule at install time; Play rules do not apply.

## 2. Widget (Glance)
- Only a small set of layouts (Row, Column, Box, Text, Image, Button, LazyColumn): fine for the mockup widget.
- Automatic refresh at most every 30 min; the app pushes updates itself (`GlanceAppWidget.update`) when a notification arrives, so the widget can still be fresh.

## 3. Fingerprint for approvals
- `BiometricPrompt` with `BIOMETRIC_STRONG`.
- Best practice: a KeyStore key that needs the fingerprint for every use (`setUserAuthenticationRequired(true)`), passed as a `CryptoObject`; the app signs each approval and the Pi checks the signature. A stolen session password then still cannot approve anything.

## 4. Notifications without Firebase
| Option | Notes |
|---|---|
| Keep pc-waker's way: one long-poll on the Pi (`/api/events`) in a service | Already works on Filip's phone today. Android 14+ needs a foreground-service type; `dataSync` is capped at 6 h a day on Android 15+, so it needs a different type or a different approach. Lead, not checked. |
| ntfy (self-hosted on the Pi) + UnifiedPush | One shared connection, best battery. Needs the ntfy app on the phone. Lead. |
| WorkManager polling | At least 15 min apart and delayed by Doze: too slow for approvals. |

## 5. Slime Keepers stats (Roblox)
- `GET https://games.roblox.com/v1/games?universeIds=<id>` works **without login**. Checked live today: the Live universe (10770523394, still named "Slime Factory Tycoon" on Roblox) returned playing 0, visits 10, favorites 1. The Test universe is private and returns nothing.
- Open Cloud has analytics (DAU, revenue) with an API key: lead, not checked.

## 6. Pi service on 32-bit ARM
- The Pi is armv7l, Python 3.10, 8 GB RAM, 12 GB free.
- **Checked**: pydantic-core has armv7l wheels (pip downloaded `pydantic_core-2.50.4-...armv7l.whl` on the Pi), so FastAPI installs fine.
- pc-waker itself uses only the Python standard library (`http.server`).

## 7. AI usage and limits
| AI | What we can show | Status |
|---|---|---|
| Claude | **% used + reset time** for the 5-hour and weekly limits. Claude Code passes `rate_limits` (five_hour / seven_day, used % and reset time) to a status-line script; a tiny script saves it to a file and the PC agent sends it to the Pi. Only updates while Claude Code is in use. | Checked (fields exist in Claude Code 2.1.306; docs page code.claude.com/docs/en/statusline per Gemini) |
| Codex (Go plan) | Reset time only, when a limit is hit. Its session logs on this PC have no % on the Go plan. | Checked locally |
| Gemini | No usage API. Show the daily reset and whether the hub has parked a helper (`D:\ai-hub\state\cooldown.json`). | Partly checked |

## 8. How the Pi learns about Claude
- The Pi cannot read `D:\ai-hub`. pc-waker's PC agent (`pc/pc-agent.ps1`) already pushes Claude session state to the Pi every 15 s.
- Plan: a Mission Control PC helper (or an extended agent) pushes the hub status logs, HANDOFF, usage and pending approvals to the Pi, and pulls Filip's answers and ideas back into `D:\ai-hub\inbox\claude\`.
- When the PC sleeps, the Claude tab shows the last known state; answers wait on the Pi.
- Open risk: how an answer reaches a Claude session that is waiting. To work out in PLAN.md.
