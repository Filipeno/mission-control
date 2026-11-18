# Test Mission Control 0.15.0 (PC modes + Local AI card)

Install 0.15.0 (Settings > Check for updates). mc-pi and mc-pc were updated on the Pi / PC with the release.

- [ ] System tab > Gaming PC card: under the temperatures there is a "PC mode" row with Normal / AI / Gaming and the current mode ("since" time).
- [ ] Tap Gaming (or Normal): if AI was on, a dialog "Stop the local AI?" appears; confirm. The bar shows "Switching to ..." and within about 10 s the mode changes. The PC really switches (model server stops, apps come back).
- [ ] Tap AI with "Qwen3-Coder 30B" selected: "Switching to AI (qwen)... N s of about 60 s", then the mode shows AI and the Local AI card says the server is idle. Try "gpt-oss 20B" the same way.
- [ ] While AI mode is on, start a game: the watcher switches to Gaming and the card says "Gaming (auto)".
- [ ] Local AI card (right below the PC card): numbers move about every 5 s (GPU %, VRAM, CPU, RAM, temperature). Send a prompt to the local model: state "Generating" and a tok/s number appear (tok/s is derived from two samples, so it shows after about 5-10 s of generating).
- [ ] "Current job": "No loop running" when no loop agent is active; the newest trial log name + last line shows.
- [ ] If `D:\ai-hub\files\local-agent-trials\report.md` exists: "Open trials report" opens it in the Docs viewer (back arrow returns).
- [ ] Leave the System tab: the PC stops sending the fast snapshots (no load on the PC).
