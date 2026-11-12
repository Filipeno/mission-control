1. Android Build Toolchain on Windows (Without Android Studio)

Android Gradle Plugin (AGP): AGP 8.8.0 / 9.1.1 (latest stable versions requirement: JDK 17, Gradle 8.11+). https://developer.android.com/build/releases/agp-9-1-0-release-notes

Gradle: Gradle 8.11 or higher. https://abinantony.io/blog/android-gradle-plugin-920-april-2026

Kotlin: Kotlin 2.0.20+ or 2.1.0+. https://abinantony.io/blog/android-gradle-plugin-920-april-2026

JDK: JDK 17 (minimum required runtime for modern AGP versions) or JDK 21. https://developer.sumup.com/changelog/

Android SDK Command-Line Tool Package Names: cmdline-tools;latest, platform-tools, build-tools;36.0.0 (or 35.0.0), platforms;android-36 (or android-35). https://developer.android.com/tools/sdkmanager

compileSdk / targetSdk for Sideloaded Apps: compileSdk 36 (Android 16) or 35 (Android 15). Sideloaded apps on Android 14+ require minSdkVersion 23+ to install, but do not enforce a targetSdk block during installation; Google Play requires targetSdk 36. https://dev.to/dainyjose/google-play-requires-android-16-by-august-31-2026-react-native-migration-guide-1d51

2. Jetpack Compose BOM, Material 3 & Jetpack Glance

Jetpack Compose BOM Version: 2026.04.01 (or 2026.08.00). https://doveletter.dev/release-notes/compose-april-2026

Material 3 Version: androidx.compose.material3:material3:1.3.0. https://developer.android.com/jetpack/androidx/releases/compose-material3

Jetpack Glance Stable Version: androidx.glance:glance:1.2.0. https://developer.android.com/jetpack/androidx/releases/glance

Glance Limits (Update Frequency): System restricts periodic background updates to a 30-minute minimum interval via AppWidgetProviderInfo.updatePeriodMillis, though manual triggers via GlanceAppWidget.update() or WorkManager can bypass the periodic timer. https://developer.android.com/jetpack/androidx/releases/glance

Glance Limits (Allowed Composables): Supports only a restricted subset of layouts (Text, Image, Button, Column, Row, Box, LazyColumn) that compile down to standard Android RemoteViews; arbitrary Compose canvas drawing, custom layout math, and standard Compose UI animation primitives are unsupported. https://developer.android.com/jetpack/androidx/releases/glance

3. androidx.biometric & Authentication Safeguards

androidx.biometric Version: Stable release androidx.biometric:biometric:1.1.0 (with pre-release 1.4.0-beta01). https://developer.android.com/jetpack/androidx/releases/biometric

Fingerprint Enforcement: Configure BiometricPrompt.PromptInfo.Builder.setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG) to strictly require Class 3 (strong) biometrics such as hardware fingerprint sensors or 3D face unlock. https://developer.android.com/jetpack/androidx/releases/biometric

CryptoObject Recommendation: Strongly recommended. Passing a BiometricPrompt.CryptoObject wrapping a Signature or Cipher backed by Android KeyStore (setUserAuthenticationRequired(true)) ensures hardware-bound cryptographic signing of server requests that cannot be forged by memory tampering. https://developer.android.com/jetpack/androidx/releases/biometric

4. Self-Hosted Push Notifications (Without Firebase/FCM)

ntfy (Self-Hosted) + UnifiedPush: Highly battery-efficient because one shared background connection handles notification delivery for all registered applications. https://back.unifiedpush.org/users/distributors/ntfy/

Foreground Service (WebSocket/SSE): High battery usage due to holding persistent sockets and wake locks open. Under Android 14/15/16 rules, long-running services require explicit service types in AndroidManifest.xml (e.g. remoteMessaging or dataSync); Android 15/16 caps dataSync FGS runtime to 6 aggregate hours in a 24-hour window. https://developer.android.com/develop/background-work/services/fgs/service-types

WorkManager Polling: Moderate battery usage with zero foreground notification requirement. Subject to Doze mode deferrals and a strict 15-minute minimum execution interval. https://developer.android.com/develop/background-work/services/fgs/service-types

5. Roblox Public Web APIs & Open Cloud Analytics

Live Stats API: GET [https://games.roblox.com/v1/games?universeIds=](https://games.roblox.com/v1/games?universeIds=){universeId} returns live metrics including playing, visits, and favoritedCount. https://create.roblox.com/docs/cloud/reference/features/universes

Get universeId from placeId: GET [https://apis.roblox.com/universes/v1/places/](https://apis.roblox.com/universes/v1/places/){placeId}/universe (or [https://games.roblox.com/v1/games/multiget-place-details?placeIds=](https://games.roblox.com/v1/games/multiget-place-details?placeIds=){placeId}) returns { "universeId": <id> }. https://github.com/QuasarRBX/RobloxAPI

Public API Rate Limits: Standard IP-based rate limiting enforces ~120 to 500 requests per minute per IP depending on the endpoint. https://create.roblox.com/docs/cloud-services/http-service

Open Cloud Daily Analytics API Key Support: Roblox Open Cloud provides an Analytics Query API ([https://apis.roblox.com/analytics-query-api/v1/universes/](https://apis.roblox.com/analytics-query-api/v1/universes/){universeId}/operations/metrics/) to query metrics via API key, alongside Creator Hub Analytics dashboards. https://create.roblox.com/docs/cloud/reference/domains/apis

6. Python Web Frameworks on 32-bit ARM (armv7l) Linux

pydantic-core / FastAPI Wheel Support: pydantic-core publishes pre-compiled armv7l binary wheels (manylinux2014_armv7l and musllinux_1_1_armv7l) on PyPI and piwheels, allowing FastAPI and Pydantic v2 to install on armv7l without a local Rust toolchain. https://pypi.org/project/pydantic_core/

Flask: Pure Python framework with zero binary dependencies; installs instantly on armv7l. https://pypi.org/project/Flask/

aiohttp: Ships C-extension ARM wheels or falls back to pure-Python execution smoothly. https://pypi.org/project/aiohttp/

Starlette (without Pydantic): Lightweight ASGI framework with zero compiled binary requirements. https://pypi.org/project/starlette/

Litestar: Installs cleanly on armv7l with optional speedup libraries (fast-query-parsers) providing native armv7l PyPI wheels. https://pypi.org/project/fast-query-parsers/

Go Binary Alternative: Statically compiles to a single native ARM binary (GOARCH=arm GOARM=7), offering sub-10 MB idle RAM usage without Python dependencies. https://go.dev/doc/install

7. Programmatic Usage Limit Monitoring for LLM Services

Claude (claude.ai Pro / Claude Code): No public external REST API exists for claude.ai Pro usage limits. However, Claude Code CLI passes standard JSON session data to statusLine scripts containing a rate_limits object with five_hour and seven_day limits (used_percentage and resets_at epoch timestamp); limits can also be checked interactively with /usage. https://code.claude.com/docs/en/statusline

OpenAI Codex CLI (ChatGPT Plans): Subscription rate-limit status on ChatGPT plans can be checked directly in the terminal via codex /status or online at [chatgpt.com/codex/settings/usage](https://chatgpt.com/codex/settings/usage). https://sessionwatcher.com/guides/codex-usage-dashboard

Google Gemini App & Gemini API Free Tier: No API exists for checking consumer Gemini web app usage. For the Gemini API free tier, quota status (e.g. 15 RPM / 500 RPD limits) is visible in Google AI Studio / Google Cloud Console, or parsed from x-ratelimit-remaining-* HTTP response headers. https://aistudio.google.com/docs/pricing
