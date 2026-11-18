# Test Mission Control 0.16.0 (starting work from the phone)

Install 0.16.0 (Settings > Check for updates). mc-pi and mc-pc were updated with the release. Keep your main Claude Desktop session open in D:\projekty (or D:\ai-hub) and the PC unlocked.

New session sheet:
- [ ] Claude tab: a "+" button next to the settings cog. It opens a sheet with Area, Folder, Model, Effort, Permission mode and a prompt box. Defaults are Sonnet, Low, Default.
- [ ] D:\projekty lists your project folders, D:\Skola lists the subject folders (same as on the PC).
- [ ] Pick "Bypass": a red warning line appears.
- [ ] Pick a folder, type a short harmless prompt ("say hello and stop"), tap Start, use the fingerprint: the toast says it asked your main session. On the PC the main session starts a new session in that folder with your prompt (an approval card for start_session may show; it reaches the phone as usual).
- [ ] Reopen the sheet: the same folder is selected again with the model, effort and mode you used last time. Another folder keeps its own settings.
- [ ] Try Opus, High or Auto once: the new session may start lower first; then your main session raises it and a card asks you. Tell Claude what happened.

School task from a photo:
- [ ] In the gallery open a photo of an assignment (or a PDF in Files), Share > "Claude (Mission Control)": a screen "School task from a photo" with the file name and the subject list.
- [ ] Pick a subject, optional note, Send, fingerprint. Within a minute: folder `D:\Skola\<subject>\Nova uloha <date>...\podklady\` holds the photo/PDF, and your main session starts a Czech session in `D:\Skola\<subject>` that reads it and asks "Domaci ukol" cards in Czech.
- [ ] A notification "School task: <subject>" says it started (or says where the files are saved if the main session was not open).
- [ ] Share two photos at once: both end up in podklady.
- [ ] Text sharing still works as before (idea inbox / type into a session).
