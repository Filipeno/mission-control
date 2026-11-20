package cz.filip.missioncontrol.ui

import android.widget.Toast
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject

/**
 * The Laptop host card (0.21): state, power, link, mode, Apollo / stream dots, backup, last seen, and the actions
 * Wake, Open app on the PC, mode switch, Send PC clipboard. Every key is read with opt* so an older or newer Pi never
 * crashes the Home screen. mc-pi checks every tier again.
 */
@Composable
fun HostCard(h: JSONObject, busy: Boolean, onWake: () -> Unit, onChanged: () -> Unit) {
    val ctx = LocalContext.current
    val state = h.optString("state", "unknown")
    val online = state == "online"
    val pending = h.optJSONObject("pending") ?: JSONObject()
    val tiers = h.optJSONObject("tiers") ?: JSONObject()
    val power = h.optJSONObject("power") ?: JSONObject()
    val net = h.optJSONObject("net") ?: JSONObject()
    val apollo = h.optJSONObject("apollo") ?: JSONObject()
    val backup = h.optJSONObject("backup") ?: JSONObject()
    val mode = h.optJSONObject("mode") ?: JSONObject()
    val apps = h.optJSONArray("apps")
    val appList = (0 until (apps?.length() ?: 0)).map { apps!!.optString(it) }.filter { it.isNotEmpty() }
    val warnings = h.optJSONArray("warnings")
    val slow = (0 until (warnings?.length() ?: 0)).any { warnings!!.optString(it) == "slow_link" }
    var sending by remember { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    val jobs = listOf("open", "mode", "clip").mapNotNull { pending.optJSONObject(it) }
    val jobRunning = jobs.any { it.optString("state") == "requested" }
    val canAct = h.optBoolean("pc_helper") && h.optBoolean("pc_laptop_support") && !jobRunning && !sending

    fun send(action: String, arg: String, title: String, body: JSONObject) {
        sending = true
        signedPost(ctx, title, "host|$action|$arg", "/api/hosts/laptop/$action", body, true, tiers.optString(action, "M")) { err ->
            sending = false
            if (err != null) Toast.makeText(ctx, err, Toast.LENGTH_LONG).show()
            onChanged()
        }
    }

    McCard {
        Label("Laptop")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                when (state) { "online" -> "Online"; "waking" -> "Waking…"; "asleep" -> "Asleep or off"; else -> "Unknown" },
                color = Mc.Text, fontSize = 32.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f),
            )
            Box(Modifier.size(14.dp).clip(CircleShape).background(if (online) Mc.Good else if (state == "waking") Mc.Warn else Mc.Idle))
        }
        val wakeNote = pending.optString("wake_note")
        if (wakeNote.isNotEmpty()) Text("$wakeNote (not confirmed)", color = Mc.Warn, fontSize = 14.sp)
        if (state == "waking") Text("Wake sent; waiting for the laptop to answer (up to 2 min).", color = Mc.Muted, fontSize = 14.sp)
        val lastSeen = h.optDouble("last_seen").takeIf { !it.isNaN() && it > 0 }
        Text(if (lastSeen != null) (if (online) "Last report ${clock(lastSeen)}" else "Last seen ${clock(lastSeen)}") else "Never reported", color = Mc.Muted, fontSize = 14.sp)

        if (online) {
            val mains = if (power.has("mains") && !power.isNull("mains")) power.optBoolean("mains") else null
            val pct = if (power.has("battery_pct") && !power.isNull("battery_pct")) "${power.optInt("battery_pct")} %" else null
            Line("Power", listOfNotNull(when (mains) { true -> "mains"; false -> "battery"; null -> null }, pct).joinToString(" · ").ifEmpty { "unknown" },
                if (mains == false && power.optInt("battery_pct", 100) < 20) Mc.Bad else Mc.Text)
            val speed = if (net.has("speed_mbps") && !net.isNull("speed_mbps")) "${net.optInt("speed_mbps")} Mbit/s" else null
            Line("Link", listOfNotNull(net.optString("type").takeIf { it.isNotEmpty() && it != "unknown" }?.replaceFirstChar { it.uppercase() }, speed).joinToString(" · ").ifEmpty { "unknown" },
                if (slow) Mc.Warn else Mc.Text)
            if (slow) Text("Slow link: under 1 Gbit/s, streams may stutter.", color = Mc.Warn, fontSize = 13.sp)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.padding(top = 4.dp)) {
                Dot("Apollo", apollo.optBoolean("service") && apollo.optBoolean("web"))
                Dot("App stream", apollo.optBoolean("stream_active"))
                Dot("Monitor stream", h.optBoolean("monitor_stream"))
            }
            val bs = backup.optString("status", "unknown")
            val bt = backup.optDouble("last_ok").takeIf { !it.isNaN() && it > 0 }?.let { " · last ok ${clock(it)}" } ?: ""
            Line("Backup", when (bs) { "ok" -> "ok"; "failed" -> "failed" + backup.optString("detail").takeIf { it.isNotEmpty() }?.let { " ($it)" }.orEmpty(); else -> "unknown" } + bt,
                if (bs == "failed") Mc.Bad else Mc.Text)
        }
        // mode comes from the PC, so it is shown even while the laptop sleeps (last known)
        val mv = mode.optString("value", "unknown")
        val msince = mode.optDouble("since").takeIf { !it.isNaN() && it > 0 }?.let { " · since ${clock(it)}" } ?: ""
        Line("Mode", if (mode.optBoolean("known")) mv.replaceFirstChar { it.uppercase() } + msince + (if (mode.optBoolean("manual")) " · manual" else " · auto") else "unknown (PC not reporting)")
        for ((k, label) in listOf("open" to "Open", "mode" to "Mode", "clip" to "Clipboard")) {
            val j = pending.optJSONObject(k) ?: continue
            val st = j.optString("state")
            val txt = when (st) { "requested" -> "working…"; "done" -> j.optString("detail").ifEmpty { "done" }; else -> "failed: " + j.optString("detail") }
            Text("$label ${j.optString("arg")}: $txt".replace("  ", " "), color = if (st == "failed") Mc.Bad else Mc.Muted, fontSize = 13.sp)
        }

        Spacer(Modifier.height(12.dp))
        Button(
            onClick = onWake, enabled = !busy && !online && state != "waking" && h.optBoolean("wake_configured", true),
            colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C),
                disabledContainerColor = Mc.ButtonDark, disabledContentColor = Mc.Muted),
            shape = RoundedCornerShape(14.dp), modifier = Modifier.height(48.dp),
        ) {
            Text(if (online) "Laptop is on" else if (h.optBoolean("wake_configured", true)) "Wake laptop" else "Wake not set up", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
        }
        if (!h.optBoolean("pc_laptop_support")) {
            Text("Open app, modes and clipboard need the PC helper updated (mc-pc).", color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        } else if (!h.optBoolean("pc_helper")) {
            Text("PC helper not connected, so the PC actions are off.", color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 10.dp)) {
                Box {
                    ActionButton("Open app", canAct && appList.isNotEmpty()) { menu = true }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }, containerColor = Mc.Card) {
                        for (a in appList) DropdownMenuItem(text = { Text(a, color = Mc.Text) }, onClick = {
                            menu = false; send("open", a, "Open $a on the PC", JSONObject().put("app", a))
                        })
                    }
                }
                ActionButton("Clipboard", canAct && online) { send("clip", "", "Send PC clipboard to the laptop", JSONObject()) }
            }
            if (appList.isEmpty()) Text("The PC has not listed any apps yet.", color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
                for ((m, label) in listOf("monitor" to "Monitor", "app" to "App", "own" to "Own", "auto" to "Auto")) {
                    ActionButton(label, canAct) { send("mode", m, "Laptop mode: $label", JSONObject().put("mode", m)) }
                }
            }
        }
    }
}

@Composable
private fun Line(label: String, value: String, color: Color = Mc.Text) {
    Row(Modifier.padding(top = 4.dp)) {
        Text(label, color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(end = 10.dp))
        Text(value, color = color, fontSize = 14.sp)
    }
}

@Composable
private fun Dot(label: String, on: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).clip(CircleShape).background(if (on) Mc.Good else Mc.Idle))
        Text(" $label", color = Mc.Muted, fontSize = 13.sp)
    }
}

@Composable
private fun ActionButton(label: String, enabled: Boolean, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, enabled = enabled,
        colors = ButtonDefaults.outlinedButtonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Text, disabledContentColor = Mc.Muted),
        border = BorderStroke(1.dp, Mc.Border), shape = RoundedCornerShape(12.dp),
    ) { Text(label, fontSize = 14.sp, fontWeight = FontWeight.SemiBold) }
}
