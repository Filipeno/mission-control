# Stage 4: done (2026-11-10)

## Verified on Filip's phone
- Claude tab (app 0.5.0): approvals, sessions, usage, hub status.
- Fingerprint-signed answers: a commit approval and a design pick with 2 pictures reached the PC (`D:\ai-hub\approvals\answered\`, message in `inbox\claude\`). A bad signature is refused by mc-pi.
- `D:\ai-hub\bin\approval.ps1` waiting in the background woke up with `ANSWER: approve`.
- Sleep from the app put the PC to sleep; Wake PC from the app woke it (stage 3 leftovers).
- Usage readable: Codex (`wham/usage`, Go plan monthly window), Antigravity (`fetchAvailableModels`, weekly per model family), Gemini hub counters.

## Still to test
- [ ] Ideas: text, speech-to-text, and "send audio instead".
- [ ] Claude usage bars (need the new status line to run in a Claude Code session).
- [ ] "Wake PC when I approve" while the PC sleeps.
- [ ] Antigravity usage after its saved login expires (~1 h after agy last ran): the in-memory token refresh in `mc-pc.ps1` has not run yet.
