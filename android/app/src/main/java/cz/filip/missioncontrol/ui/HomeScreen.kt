package cz.filip.missioncontrol.ui

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

private fun netLabel(c: Context, reachable: Boolean): Pair<String, Boolean> {
    if (!reachable) return "Offline" to false
    val cm = c.getSystemService(ConnectivityManager::class.java)
    val caps = cm.getNetworkCapabilities(cm.activeNetwork)
    return when {
        caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true -> "VPN" to true
        caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true -> "Home Wi-Fi" to true
        else -> "Connected" to true
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(onSettings: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier,
               sleepAsk: Boolean = false, onSleepAsked: () -> Unit = {}, onOpenTodos: () -> Unit = {}) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var resumed by remember { mutableStateOf(false) }
    var inflight by remember { mutableStateOf(0) }        // taps whose call to the Pi has not finished
    val busy = inflight > 0
    var pcPending by remember { mutableStateOf<String?>(null) }   // "wake" / "sleep" shown at once, until the PC confirms
    var pcPendingAt by remember { mutableStateOf(0L) }
    var sleepDialog by remember { mutableStateOf(false) }

    suspend fun load(force: Boolean = false) {
        try {
            val d = withContext(Dispatchers.IO) { Api.get(ctx, "/api/home") }
            // While one of our own taps is in flight the poll must not undo the instant change.
            if (inflight == 0 || force) {
                data = d
                d.optJSONObject("todos")?.let { TodoCount.open = it.optInt("open") }
                val online = d.optJSONObject("pc")?.optBoolean("online") == true
                val p = pcPending
                if (p != null && ((p == "wake" && online) || (p == "sleep" && !online) || System.currentTimeMillis() - pcPendingAt > 90_000)) pcPending = null
            }
            error = null
        } catch (e: ApiError) {
            if (e.code == 401) onLoggedOut() else error = e.message
        }
    }

    /** Changes the screen at once ([patch] edits a copy of the home data), then calls the Pi; on failure reloads the truth and says why. */
    fun act(path: String, body: JSONObject = JSONObject(), ok: String? = null, pending: String? = null, patch: ((JSONObject) -> Unit)? = null) {
        if (patch != null) data?.let { cur -> data = JSONObject(cur.toString()).also(patch) }
        if (pending != null) { pcPending = pending; pcPendingAt = System.currentTimeMillis() }
        ok?.let { Toast.makeText(ctx, it, Toast.LENGTH_SHORT).show() }
        inflight++
        scope.launch {
            var failed = false
            try {
                withContext(Dispatchers.IO) { Api.post(ctx, path, body) }
                cz.filip.missioncontrol.widget.McWidget.refresh(ctx)
                delay(600)
            } catch (e: ApiError) {
                failed = true
                if (pending != null) pcPending = null
                Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
            } finally {
                inflight--
            }
            load(force = failed)
        }
    }

    LaunchedEffect(sleepAsk) { if (sleepAsk) { sleepDialog = true; onSleepAsked() } }
    LifecycleResumeEffect(Unit) {
        resumed = true
        onPauseOrDispose { resumed = false }
    }
    LaunchedEffect(resumed) {
        while (resumed) {
            load()
            delay(5000)
        }
    }

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } },
        modifier = modifier.fillMaxSize(),
    ) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 22.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.Bottom) {
                Box(Modifier.weight(1f)) { Header("Home") }
                val (net, good) = netLabel(ctx, error == null && data != null)
                Text(
                    net, color = if (good) Mc.Good else Mc.Bad, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(bottom = 8.dp).clip(RoundedCornerShape(50))
                        .background(if (good) Mc.GoodBg else Color(0xFF2A1215)).padding(horizontal = 12.dp, vertical = 6.dp),
                )
                IconButton(onClick = onSettings, modifier = Modifier.padding(bottom = 2.dp)) {
                    Icon(Icons.Filled.Settings, contentDescription = "Settings", tint = Mc.Muted)
                }
            }
            error?.let {
                McCard { Text(it, color = Mc.Bad, fontSize = 14.sp) }
            }
            val d = data
            if (d == null) {
                if (error == null) Text("Loading…", color = Mc.Muted)
                return@Column
            }
            PcCard(d, busy || pcPending != null, pcPending, onWake = { act("/api/pc/wake", ok = "Wake sent", pending = "wake") }, onSleep = { sleepDialog = true })
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                RoomTile(d.getJSONObject("room"), Modifier.weight(1f))
                LightsTile(d.getJSONObject("lights"), Modifier.weight(1f)) { on ->
                    if (!busy) act("/api/lights", JSONObject().put("on", on)) { h ->
                        h.getJSONObject("lights").put("applied", if (on) "on" else "off").put("want", if (on) "on" else "off")
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                AutoSleepTile(d.getJSONObject("autosleep"), Modifier.weight(1f)) { path, body ->
                    act(path, body) { h ->
                        val a = h.getJSONObject("autosleep")
                        if (body.has("enabled")) a.put("enabled", body.getBoolean("enabled"))
                        if (body.has("idle_min")) a.put("idle_min", body.getInt("idle_min"))
                        if (body.has("minutes")) a.put("keep_awake_until", System.currentTimeMillis() / 1000.0 + body.getInt("minutes") * 60)
                    }
                }
                PiTile(d.getJSONObject("pi"), Modifier.weight(1f))
            }
            WaitingCard(d.getJSONObject("claude"))
            TodoCard(TodoCount.open, onOpenTodos)
            Recent(d.optJSONArray("recent"))
        }
    }

    if (sleepDialog) {
        AlertDialog(
            onDismissRequest = { sleepDialog = false },
            title = { Text("Put the PC to sleep?") },
            text = { Text("It sleeps right away, even if something is running.") },
            confirmButton = { TextButton(onClick = { sleepDialog = false; act("/api/pc/sleep", ok = "Sleep sent", pending = "sleep") }) { Text("Sleep") } },
            dismissButton = { TextButton(onClick = { sleepDialog = false }) { Text("Cancel") } },
            containerColor = Mc.Card,
        )
    }
}

@Composable
private fun PcCard(d: JSONObject, busy: Boolean, pending: String?, onWake: () -> Unit, onSleep: () -> Unit) {
    val pc = d.getJSONObject("pc")
    val auto = d.getJSONObject("autosleep")
    val online = pc.optBoolean("online")
    McCard {
        Label("Gaming PC")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (pending == "wake" && !online) "Waking…" else if (pending == "sleep" && online) "Sleeping…" else if (online) "Awake" else "Asleep", color = Mc.Text, fontSize = 40.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f))
            Box(Modifier.size(14.dp).clip(CircleShape).background(if (online) Mc.Good else Mc.Idle))
        }
        val since = pc.optDouble("since").takeIf { !it.isNaN() }?.let { "Since ${clock(it)}" }
        val autoLine = if (auto.optBoolean("enabled")) "auto-sleep after ${auto.optInt("idle_min")} min idle" else "auto-sleep off"
        val sleeping = if (pc.optBoolean("sleep_pending") || (pending == "sleep" && online)) "going to sleep…" else null
        Text(listOfNotNull(since, sleeping ?: autoLine).joinToString(" · "), color = Mc.Muted, fontSize = 15.sp)
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(
                onClick = onWake, enabled = !busy && !online,
                colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C),
                    disabledContainerColor = Mc.ButtonDark, disabledContentColor = Mc.Muted),
                shape = RoundedCornerShape(14.dp), modifier = Modifier.weight(1f).height(52.dp),
            ) {
                Icon(PowerIcon, contentDescription = null, modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(10.dp))
                Text(if (online) "PC is on" else "Wake PC", fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            }
            OutlinedButton(
                onClick = onSleep, enabled = !busy && online && pc.optBoolean("helper"),
                colors = ButtonDefaults.outlinedButtonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Text),
                border = androidx.compose.foundation.BorderStroke(1.dp, Mc.Border),
                shape = RoundedCornerShape(14.dp), modifier = Modifier.height(52.dp),
            ) { Text("Sleep", fontSize = 17.sp, fontWeight = FontWeight.SemiBold) }
        }
        if (online && !pc.optBoolean("helper")) {
            Text("Sleep needs the PC helper (mc-pc), which is not reporting.", color = Mc.Muted, fontSize = 12.sp,
                modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@Composable
private fun Tile(label: String, value: String, sub: String, modifier: Modifier, valueColor: Color = Mc.Text,
                 onClick: (() -> Unit)? = null) {
    McCard(modifier = modifier, onClick = onClick) {
        Label(label)
        Text(value, color = valueColor, fontSize = 24.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp))
        Text(sub, color = Mc.Muted, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun RoomTile(r: JSONObject, modifier: Modifier) {
    val fresh = r.optBoolean("fresh")
    val value = if (!fresh) "Offline" else if (r.optBoolean("present")) "Someone here" else "Empty"
    val last = r.optDouble("last_motion").takeIf { !it.isNaN() }
    val sub = if (!fresh) "Presence sensor not reporting" else last?.let { "Last motion ${clock(it)}" } ?: "Presence sensor"
    Tile("Room", value, sub, modifier, if (!fresh) Mc.Muted else Mc.Text)
}

@Composable
private fun LightsTile(l: JSONObject, modifier: Modifier, set: (Boolean) -> Unit) {
    val on = (l.optString("applied").ifBlank { l.optString("want") }) == "on"
    val pending = l.optString("want").isNotBlank() && l.optString("applied").isNotBlank() && l.optString("want") != l.optString("applied")
    Tile("Lights", if (on) "On" else "Off", if (pending) "Switching…" else "Tap to turn ${if (on) "off" else "on"}",
        modifier, onClick = { set(!on) })
}

@Composable
private fun AutoSleepTile(a: JSONObject, modifier: Modifier, call: (String, JSONObject) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val enabled = a.optBoolean("enabled")
    val min = a.optInt("idle_min", 30)
    val keep = a.optDouble("keep_awake_until", 0.0)
    val blockers = a.optJSONArray("blockers")
    val sub = when {
        a.optBoolean("warning") -> "Sleeping soon"
        keep * 1000 > System.currentTimeMillis() -> "Awake until ${clock(keep)}"
        enabled && blockers != null && blockers.length() > 0 -> blockers.getString(0)
        else -> "$min min idle"
    }
    Tile("Auto-sleep", if (enabled) "On" else "Off", sub, modifier, onClick = { open = true })
    if (open) {
        AlertDialog(
            onDismissRequest = { open = false },
            containerColor = Mc.Card,
            title = { Text("Auto-sleep") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("On", modifier = Modifier.weight(1f))
                        Switch(checked = enabled, onCheckedChange = { call("/api/autosleep", JSONObject().put("enabled", it)) },
                            colors = SwitchDefaults.colors(checkedTrackColor = Mc.Accent))
                    }
                    Text("Sleep after idle", color = Mc.Muted, fontSize = 13.sp)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for (m in listOf(15, 30, 60, 90)) {
                            FilterChip(selected = m == min, onClick = { call("/api/autosleep", JSONObject().put("idle_min", m)) },
                                label = { Text("$m min") },
                                colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Mc.NavSelected, selectedLabelColor = Mc.Accent))
                        }
                    }
                    if (blockers != null && blockers.length() > 0) {
                        Text("Not sleeping now because: " + (0 until blockers.length()).joinToString(", ") { blockers.getString(it) },
                            color = Mc.Muted, fontSize = 13.sp)
                    }
                }
            },
            confirmButton = { TextButton(onClick = { open = false; call("/api/stay-awake", JSONObject().put("minutes", 60)) }) { Text("Stay awake 1 h") } },
            dismissButton = { TextButton(onClick = { open = false }) { Text("Close") } },
        )
    }
}

@Composable
private fun PiTile(p: JSONObject, modifier: Modifier) {
    val healthy = p.optBoolean("healthy")
    val down = p.optJSONArray("down")
    val temp = p.optDouble("temp_c").takeIf { !it.isNaN() }?.let { "${it.toInt()} °C" }
    val up = p.optLong("uptime_s").takeIf { it > 0 }?.let { "up ${duration(it)}" }
    val sub = if (!healthy && down != null && down.length() > 0)
        "Down: " + (0 until down.length()).joinToString(", ") { down.getString(it) }
    else listOfNotNull(temp, up).joinToString(" · ")
    McCard(modifier = modifier) {
        Label("Pi")
        Text(if (healthy) "Healthy" else "Problem", color = if (healthy) Mc.Good else Mc.Bad, fontSize = 24.sp,
            fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp))
        Text(sub, color = Mc.Muted, fontSize = 14.sp, fontFamily = if (healthy) FontFamily.Monospace else FontFamily.Default,
            maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun TodoCard(open: Int, onClick: () -> Unit) {
    McCard(onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Label("Your to-do list")
                Text(if (open == 0) "Nothing open." else if (open == 1) "1 step waits for you." else "$open steps wait for you.",
                    color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(top = 4.dp))
            }
            Text("$open", color = if (open > 0) Mc.Accent else Mc.Muted, fontSize = 34.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
        }
    }
}

@Composable
private fun WaitingCard(cl: JSONObject) {
    val n = cl.optInt("waiting")
    val titles = cl.optJSONArray("waiting_titles")
    McCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Label("Waiting for you")
                val sub = if (n == 0) "Nothing. ${cl.optInt("sessions")} Claude sessions open."
                else (0 until (titles?.length() ?: 0)).joinToString(" · ") { titles!!.getString(it) }
                Text(sub, color = Mc.Muted, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 4.dp))
            }
            Text("$n", color = if (n > 0) Mc.Warn else Mc.Muted, fontSize = 34.sp, fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace)
        }
    }
}

private fun kindColor(kind: String): Color = when (kind) {
    "done" -> Mc.Accent
    "waiting", "stuck" -> Mc.Warn
    "error" -> Mc.Bad
    else -> Mc.Idle
}

@Composable
private fun Recent(arr: org.json.JSONArray?) {
    if (arr == null || arr.length() == 0) return
    Label("Recent")
    Column {
        for (i in 0 until arr.length()) {
            val e = arr.getJSONObject(i)
            val first = e.optString("body").lineSequence().firstOrNull().orEmpty()
            val text = if (first.isNotBlank() && e.optString("kind") in setOf("done", "waiting", "error", "stuck"))
                "$first: ${e.optString("title").replaceFirstChar { it.lowercase() }}" else e.optString("title")
            Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).clip(CircleShape).background(kindColor(e.optString("kind"))))
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(text, color = Mc.Text, fontSize = 15.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(clock(e.optDouble("at")), color = Mc.Muted, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                }
            }
            if (i < arr.length() - 1) HorizontalDivider(color = Mc.Border)
        }
    }
}
