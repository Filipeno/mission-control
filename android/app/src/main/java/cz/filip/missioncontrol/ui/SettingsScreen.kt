package cz.filip.missioncontrol.ui

import android.app.TimePickerDialog
import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import cz.filip.missioncontrol.data.Store
import cz.filip.missioncontrol.data.Updater
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

@Composable
fun SettingsScreen(onBack: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var s by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var tick by remember { mutableIntStateOf(0) }   // bump to re-read local push status

    suspend fun load() {
        try {
            s = withContext(Dispatchers.IO) { Api.get(ctx, "/api/settings") }.getJSONObject("settings"); error = null
        } catch (e: ApiError) {
            if (e.code == 401) onLoggedOut() else error = e.message
        }
    }

    fun save(change: JSONObject) {
        scope.launch {
            try {
                s = withContext(Dispatchers.IO) { Api.post(ctx, "/api/settings", change) }.getJSONObject("settings")
            } catch (e: ApiError) {
                Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
            }
        }
    }

    fun pickTime(key: String, current: String) {
        val (h, m) = current.split(":").map { it.toInt() }
        TimePickerDialog(ctx, { _, hh, mm -> save(JSONObject().put(key, "%02d:%02d".format(hh, mm))) }, h, m, true).show()
    }

    LaunchedEffect(Unit) { load() }

    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 22.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Mc.Text) }
            Header("Settings")
        }
        error?.let { McCard { Text(it, color = Mc.Bad) } }
        val st = s
        if (st != null) {
            McCard {
                Label("Notifications")
                ToggleRow("Mute everything", st.optBoolean("muted")) { save(JSONObject().put("muted", it)) }
                ToggleRow("Quiet hours (silent)", st.optBoolean("quiet_on")) { save(JSONObject().put("quiet_on", it)) }
                if (st.optBoolean("quiet_on")) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("From", color = Mc.Muted, modifier = Modifier.weight(1f))
                        TextButton(onClick = { pickTime("quiet_from", st.getString("quiet_from")) }) {
                            Text(st.getString("quiet_from"), fontFamily = FontFamily.Monospace, color = Mc.Accent)
                        }
                        Text("to", color = Mc.Muted)
                        TextButton(onClick = { pickTime("quiet_to", st.getString("quiet_to")) }) {
                            Text(st.getString("quiet_to"), fontFamily = FontFamily.Monospace, color = Mc.Accent)
                        }
                    }
                }
                Text("Which notifications", color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 10.dp))
                val kinds = st.getJSONObject("kinds")
                for ((key, label) in listOf("claude" to "Claude (finished, waiting, errors)", "sleep" to "PC sleep warnings",
                    "room" to "Room sensor", "system" to "System (backups, other)")) {
                    ToggleRow(label, kinds.optBoolean(key, true)) { save(JSONObject().put("kinds", JSONObject().put(key, it))) }
                }
            }
            McCard {
                Label("Approvals")
                ToggleRow("Wake PC when I approve", st.optBoolean("wake_on_approve")) { save(JSONObject().put("wake_on_approve", it)) }
                Text("When you answer an approval while the PC sleeps, the Pi wakes it.", color = Mc.Muted, fontSize = 13.sp)
            }
            McCard {
                Label("Ideas")
                ToggleRow("Send audio instead of speech-to-text", st.optBoolean("ideas_audio")) { save(JSONObject().put("ideas_audio", it)) }
                Text("Audio is saved next to the inbox message; Whisper transcription is not set up yet.", color = Mc.Muted, fontSize = 13.sp)
            }
        }
        McCard {
            Label("Notifications connection")
            tick.let { }
            Text("Status: ${Store.pushStatus(ctx)}", color = Mc.Text, fontSize = 15.sp, modifier = Modifier.padding(top = 6.dp))
            Text("Outside home: ${Store.remoteUrl(ctx).ifBlank { "not set" }}", color = Mc.Muted, fontSize = 13.sp)
            val last = Store.lastPushAt(ctx)
            if (last > 0) Text("Last notification: ${clock(last / 1000.0)}", color = Mc.Muted, fontSize = 14.sp)
            TextButton(onClick = {
                scope.launch {
                    try {
                        withContext(Dispatchers.IO) { Api.post(ctx, "/api/push/test") }
                        Toast.makeText(ctx, "Test sent", Toast.LENGTH_SHORT).show()
                    } catch (e: ApiError) {
                        Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
                    }
                    tick++
                }
            }) { Text("Send test notification", color = Mc.Accent) }
        }
        McCard {
            Label("About & updates")
            Text("Mission Control ${Updater.installedName}", color = Mc.Text, fontSize = 18.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
                modifier = Modifier.padding(top = 6.dp))
            Text("Build ${Updater.installedCode}", color = Mc.Muted, fontSize = 13.sp)
            if (Updater.status.isNotBlank()) Text(Updater.status, color = if (Updater.updateAvailable) Mc.Warn else Mc.Muted, fontSize = 14.sp,
                modifier = Modifier.padding(top = 6.dp))
            Updater.latest?.takeIf { Updater.updateAvailable && it.notes.isNotBlank() }?.let { Text(it.notes, color = Mc.Text, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp)) }
            Row {
                TextButton(enabled = !Updater.busy, onClick = { kotlin.concurrent.thread { Updater.check(ctx.applicationContext, force = true) } }) {
                    Text("Check for updates", color = Mc.Accent)
                }
                if (Updater.updateAvailable) TextButton(enabled = !Updater.busy, onClick = {
                    kotlin.concurrent.thread {
                        val err = Updater.downloadAndInstall(ctx.applicationContext)
                        if (err != null) android.os.Handler(android.os.Looper.getMainLooper()).post { Toast.makeText(ctx, err, Toast.LENGTH_LONG).show() }
                    }
                }) { Text("Install ${Updater.latest?.name}", color = Mc.Warn) }
            }
        }
        McCard {
            Label("Account")
            Text("Pi: ${Store.baseUrl(ctx)}", color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp))
            TextButton(onClick = {
                scope.launch {
                    runCatching { withContext(Dispatchers.IO) { Api.post(ctx, "/api/logout") } }
                    Store.setToken(ctx, null)
                    onLoggedOut()
                }
            }) { Text("Log out", color = Mc.Bad) }
        }
    }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = Mc.Text, fontSize = 15.sp, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange, colors = SwitchDefaults.colors(checkedTrackColor = Mc.Accent))
    }
}
