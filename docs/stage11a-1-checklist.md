# Test Mission Control 0.12.0 (Claude app cards)

Install 0.12.0 (Settings > Check for updates). A "Claude app card" is an Allow/Deny card in the Claude desktop app itself (not the phone-gate prompts). It appears when a chat in default permission mode asks to start a session.

- [ ] Ask the orchestrator for a test: it starts a chat in default mode that asks to start a session. A push "<chat>: app card waiting" arrives.
- [ ] The Claude tab shows it under "Asks you" as "Claude app card · start_session". Opening it shows the chat name, the whole brief (scrollable), and a PC screenshot (tap to zoom).
- [ ] The notification has only a Deny button (no Allow).
- [ ] Tap Allow once: the fingerprint prompt appears. After it, the card shows "sent", then "clicked Allow once at the PC", and the new session starts on the PC.
- [ ] Repeat with another test card and tap Deny: no fingerprint, one tap. The PC click happens and the chat says it was denied.
- [ ] There is no "Always allow" anywhere.
- [ ] Lock the PC (Win+L), raise another test card, tap Deny: the card says "waiting for unlock (expires HH:MM)". Unlock the PC: it gets clicked within about a minute.
- [ ] Raise a card and answer it at the PC first: the card disappears from the phone.
