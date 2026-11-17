# Test Mission Control 0.13.0 (health + hub)

Install 0.13.0 (Settings > Check for updates). mc-pc was restarted on the PC with the release, so the System tab should fill in within a minute.

- [ ] System tab shows a "Claude app" card: green "Running", the number of chats with Remote Control on / off, and "Watchdog last ran HH:MM" (should be within the last couple of minutes).
- [ ] "Remote Control is off" card lists chats whose Remote Control is off. Tap "Turn on" on one: the row changes to "Queued - turns on at the next Claude turn". (Do not expect it to switch at once: it waits for the next Claude turn in any chat.)
- [ ] "Hub self-test" card shows one row per helper with a green or red dot and the last run time. A red row shows the reason.
- [ ] Claude tab, under Usage: a "Helpers today" card with Gemini app jobs left, Perplexity jobs left, Codex % used and reset date, and parked helpers if any.
- [ ] Tap "Restart Claude app" (only when no chat is mid-task): the Claude app closes and comes back on the PC within about 30 s, the card says "Restarting..." then "restarted".
- [ ] Optional: close the Claude app on the PC and leave it closed: the watchdog restarts it. If it cannot, a "Claude app is down" notification arrives after 5 minutes.
