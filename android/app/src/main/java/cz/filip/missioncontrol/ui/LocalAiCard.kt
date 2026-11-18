package cz.filip.missioncontrol.ui

import android.widget.Toast
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

private fun JSONObject.num(k: String): Double? = optDouble(k).takeIf { !it.isNaN() }

private val AI_SWITCH_SECONDS = 60

/** "Normal" / "AI (qwen)" / "Gaming (auto)" for the current PC mode (from /api/system pc_mode). */
fun pcModeLabel(m: JSONObject?): String {
    val mode = m?.optString("mode").orEmpty()
    return when (mode) {
        "normal" -> "Normal"
        "ai" -> "AI" + m?.optString("model").orEmpty().takeIf { it.isNotBlank() }?.let { " ($it)" }.orEmpty()
        "gaming" -> if (m?.optBoolean("auto") == true) "Gaming (auto)" else "Gaming"
        else -> "unknown"
    }
}

/**
 * The 3-way PC mode switch (inside the PC card). [onSwitch] (mode, model) posts the request; the card shows the
 * progress from the Pi's `switch` state (requested -> done / failed).
 */
@Composable
fun PcModeSwitch(pc: JSONObject?, onSwitch: (String, String) -> Unit) {
    if (pc == null) return
    val sw = pc.optJSONObject("switch") ?: JSONObject()
    val switching = sw.optString("state") == "requested"
    val current = pc.optString("mode")
    var model by remember { mutableStateOf("qwen") }
    var confirm by remember { mutableStateOf<Pair<String, String>?>(null) }
    var now by remember { mutableStateOf(System.currentTimeMillis() / 1000.0) }
    LaunchedEffect(switching) { while (switching) { now = System.currentTimeMillis() / 1000.0; delay(1000) } }
    LaunchedEffect(pc.optString("model")) { pc.optString("model").takeIf { it == "qwen" || it == "gptoss" }?.let { model = it } }

    fun pick(mode: String, m: String) {
        if (switching) return
        if (current == "ai" && (mode != "ai" || m != pc.optString("model"))) confirm = mode to m      // stops the model server
        else onSwitch(mode, m)
    }

    Spacer(Modifier.height(12.dp))
    HorizontalSeparator()
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 12.dp)) {
        Box(Modifier.weight(1f)) { Label("PC mode") }
        val label = pcModeLabel(pc)
        Text(if (pc.optBoolean("known")) label else "$label · stale", color = if (pc.optBoolean("known")) Mc.Text else Mc.Muted,
            fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
    Row(Modifier.fillMaxWidth().padding(top = 8.dp).clip(RoundedCornerShape(14.dp)).background(Mc.Bg)
        .border(1.dp, Mc.Border, RoundedCornerShape(14.dp))) {
        listOf("normal" to "Normal", "ai" to "AI", "gaming" to "Gaming").forEach { (mode, text) ->
            val selected = current == mode
            val target = sw.optString("target") == mode && switching
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(14.dp))
                    .background(if (selected) Mc.NavSelected else Color.Transparent)
                    .clickable(enabled = !switching && !selected) { pick(mode, if (mode == "ai") model else "") }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (selected && mode == "gaming" && pc.optBoolean("auto")) "Gaming (auto)" else text,
                    color = if (selected) Mc.Accent else if (target) Mc.Warn else if (switching) Mc.Idle else Mc.Text,
                    fontSize = 14.sp, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
                )
            }
        }
    }
    Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("AI model", color = Mc.Muted, fontSize = 13.sp)
        listOf("qwen" to "Qwen3-Coder 30B", "gptoss" to "gpt-oss 20B").forEach { (id, text) ->
            val on = model == id
            Text(
                text, color = if (on) Mc.Accent else Mc.Muted, fontSize = 12.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                modifier = Modifier.clip(RoundedCornerShape(50)).background(if (on) Mc.NavSelected else Mc.ButtonDark)
                    .clickable(enabled = !switching) { model = id; if (current == "ai" && pc.optString("model") != id) pick("ai", id) }
                    .padding(horizontal = 10.dp, vertical = 5.dp),
            )
        }
    }
    if (current == "gaming" && pc.optBoolean("auto")) {
        Text("The game watcher switched to Gaming by itself and will switch back when the game closes.", color = Mc.Muted, fontSize = 13.sp,
            modifier = Modifier.padding(top = 6.dp))
    }
    pc.num("since")?.let { if (!switching) Text("since ${clock(it)}", color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp)) }
    if (switching) {
        val target = sw.optString("target")
        val elapsed = (now - (sw.num("at") ?: now)).coerceAtLeast(0.0)
        val tText = pcModeLabel(JSONObject().put("mode", target).put("model", sw.optString("model")))
        val ai = target == "ai"
        Text(
            "Switching to $tText… ${elapsed.toInt()} s" + if (ai) " of about $AI_SWITCH_SECONDS s" else "",
            color = Mc.Warn, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp),
        )
        if (ai) LinearProgressIndicator(progress = { (elapsed / AI_SWITCH_SECONDS).toFloat().coerceIn(0.02f, 0.98f) }, color = Mc.Warn, trackColor = Mc.ButtonDark,
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(6.dp).clip(RoundedCornerShape(3.dp)))
        else LinearProgressIndicator(color = Mc.Warn, trackColor = Mc.ButtonDark, modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(6.dp).clip(RoundedCornerShape(3.dp)))
    } else if (sw.optString("state") == "failed") {
        Text("Switch to ${sw.optString("target")} failed: ${sw.optString("detail").ifBlank { "no answer" }}", color = Mc.Bad, fontSize = 13.sp,
            modifier = Modifier.padding(top = 8.dp))
    }
    confirm?.let { (mode, m) ->
        AlertDialog(
            onDismissRequest = { confirm = null }, containerColor = Mc.Card,
            title = { Text("Stop the local AI?") },
            text = { Text("The model server stops and its running jobs end. Switch to ${pcModeLabel(JSONObject().put("mode", mode).put("model", m))}?", color = Mc.Muted) },
            confirmButton = { TextButton(onClick = { confirm = null; onSwitch(mode, m) }) { Text("Switch") } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun HorizontalSeparator() = Box(Modifier.fillMaxWidth().height(1.dp).background(Mc.Border))

@Composable
private fun Meter(label: String, value: String, pct: Double?, color: Color = Mc.Accent) {
    Row(Modifier.padding(top = 8.dp)) {
        Text(label, color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.weight(1f))
        Text(value, color = Mc.Text, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
    }
    LinearProgressIndicator(progress = { ((pct ?: 0.0) / 100).toFloat().coerceIn(0f, 1f) }, color = color, trackColor = Mc.ButtonDark,
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp).height(5.dp).clip(RoundedCornerShape(3.dp)))
}

private fun pctColor(p: Double?) = when { (p ?: 0.0) >= 95 -> Mc.Bad; (p ?: 0.0) >= 85 -> Mc.Warn; else -> Mc.Accent }

private fun ago(unixS: Double): String {
    val s = (System.currentTimeMillis() / 1000.0 - unixS).toLong().coerceAtLeast(0)
    return when { s < 90 -> "${s} s ago"; s < 5400 -> "${s / 60} min ago"; else -> "${s / 3600} h ago" }
}

/** Live "Local AI" card. Refreshes every 5 s while it is on screen (the Pi then tells mc-pc to report faster). */
@Composable
fun LocalAiCard(active: Boolean, onOpenReport: (String) -> Unit, onLoggedOut: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var d by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var wantReport by remember { mutableStateOf(0.0) }          // unix time of the tap, 0 = not waiting

    LaunchedEffect(active) {
        while (active) {
            try {
                val v = withContext(Dispatchers.IO) { Api.get(ctx, "/api/system/localai") }
                d = v; error = null
                val rep = v.optJSONObject("report")
                if (wantReport > 0 && rep != null) {
                    val reqAt = rep.num("requested_at") ?: 0.0
                    when {
                        rep.optString("state") == "done" && reqAt >= wantReport - 5 -> { wantReport = 0.0; onOpenReport(rep.optString("slug")) }
                        rep.optString("state") == "failed" && reqAt >= wantReport - 5 -> {
                            wantReport = 0.0; Toast.makeText(ctx, rep.optString("detail").ifBlank { "Could not get the report" }, Toast.LENGTH_LONG).show()
                        }
                        System.currentTimeMillis() / 1000.0 - wantReport > 45 -> { wantReport = 0.0; Toast.makeText(ctx, "The PC did not answer", Toast.LENGTH_LONG).show() }
                    }
                }
            } catch (e: ApiError) {
                if (e.code == 401) onLoggedOut() else error = e.message
            }
            delay(5000)
        }
    }

    McCard {
        val live = d?.optBoolean("live") == true
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) { Label("Local AI") }
            Box(Modifier.size(9.dp).clip(CircleShape).background(if (live) Mc.Good else Mc.Idle))
            Spacer(Modifier.width(6.dp))
            Text(if (live) "live" else "no live data", color = if (live) Mc.Good else Mc.Muted, fontSize = 12.sp)
        }
        val v = d
        if (v == null) {
            Text(error ?: "Loading…", color = if (error != null) Mc.Bad else Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp))
            return@McCard
        }
        error?.let { Text(it, color = Mc.Bad, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp)) }
        val mode = v.optJSONObject("mode")
        Text(pcModeLabel(mode), color = Mc.Text, fontSize = 22.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 6.dp))
        if (!live) {
            Text(if (v.optBoolean("pc_online")) "Waiting for the PC's first report…" else "The PC is off or its helper is not connected.",
                color = Mc.Muted, fontSize = 13.sp)
            return@McCard
        }
        // ---- model server
        val srv = v.optJSONObject("server") ?: JSONObject()
        val state = srv.optString("state", "down")
        val (stateText, stateColor) = when (state) {
            "busy" -> "Generating" to Mc.Accent
            "idle" -> "Idle, ready" to Mc.Good
            "loading" -> "Loading the model…" to Mc.Warn
            else -> "Server not running" to Mc.Muted
        }
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
            Box(Modifier.size(10.dp).clip(CircleShape).background(stateColor))
            Spacer(Modifier.width(8.dp))
            Text(stateText, color = stateColor, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
            srv.optString("model").takeIf { it.isNotBlank() && it != "null" }?.let { Text("  ·  $it", color = Mc.Text, fontSize = 14.sp) }
        }
        if (state == "busy" || state == "idle") {
            val speed = srv.num("tok_s")?.let { "%.1f tok/s".format(it) } ?: "— tok/s"
            val slots = "${srv.optInt("busy")}/${srv.optInt("slots")} slots busy"
            val ctxText = srv.num("ctx")?.let { " · ctx ${(it / 1024).toInt()}k" } ?: ""
            Text("$speed · $slots$ctxText", color = Mc.Muted, fontSize = 13.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.padding(top = 4.dp))
            srv.num("prompt_tok_s")?.let { Text("prompt %.0f tok/s".format(it), color = Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace) }
        }
        // ---- hardware
        val gpu = v.optJSONObject("gpu")
        if (gpu != null) {
            val util = gpu.num("util"); val used = gpu.num("mem_used_mb"); val total = gpu.num("mem_total_mb"); val temp = gpu.num("temp")
            Meter("GPU", (util?.let { "${it.toInt()}%" } ?: "—") + (temp?.let { " · ${it.toInt()} °C" } ?: ""), util, pctColor(util))
            val vp = if (used != null && total != null && total > 0) used / total * 100 else null
            Meter("VRAM", if (used != null && total != null) "%.1f / %.1f GB".format(used / 1024, total / 1024) else "—", vp, pctColor(vp))
        }
        v.num("cpu_pct")?.let { Meter("CPU", "${it.toInt()}%", it, pctColor(it)) }
        v.optJSONObject("ram")?.let { r ->
            val p = r.num("pct")
            Meter("RAM", if (r.num("used_gb") != null && r.num("total_gb") != null) "%.1f / %.1f GB".format(r.num("used_gb"), r.num("total_gb")) else "—", p, pctColor(p))
        }
        // ---- current job
        Spacer(Modifier.height(14.dp))
        HorizontalSeparator()
        Label("Current job")
        val job = v.optJSONObject("job")
        val agent = job?.optJSONObject("agent")
        if (agent == null) {
            Text("No loop running", color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp))
        } else {
            Text(agent.optString("task"), color = Mc.Text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, maxLines = 2,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 8.dp))
            val bits = listOfNotNull(agent.optString("step").takeIf { it.isNotBlank() }?.let { "step $it" },
                "iteration ${agent.optInt("iteration")}", agent.num("started")?.let { "started ${clock(it)}" },
                agent.num("eta")?.let { "ETA ${clock(it)}" })
            Text(bits.joinToString(" · "), color = Mc.Muted, fontSize = 13.sp)
            agent.optJSONObject("last_check")?.let { lc ->
                val ok = lc.optBoolean("ok")
                Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.Top) {
                    Text(if (ok) "✓" else "✗", color = if (ok) Mc.Good else Mc.Bad, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.width(8.dp))
                    Column {
                        Text(lc.optString("cmd"), color = Mc.Text, fontSize = 13.sp, fontFamily = FontFamily.Monospace, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        lc.num("at")?.let { Text("last check ${ago(it)}", color = Mc.Muted, fontSize = 13.sp) }
                    }
                }
            }
        }
        val log = job?.optJSONObject("log")
        if (log != null) {
            Text("Newest trial log", color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 10.dp))
            Text(log.optString("name") + (log.num("at")?.let { " · ${ago(it)}" } ?: ""), color = Mc.Text, fontSize = 13.sp, fontFamily = FontFamily.Monospace,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            log.optString("line").takeIf { it.isNotBlank() }?.let {
                Text(it, color = Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
        val rep = v.optJSONObject("report")
        if (rep?.optBoolean("exists") == true) {
            val waiting = wantReport > 0
            Button(
                onClick = {
                    wantReport = System.currentTimeMillis() / 1000.0
                    scope.launch {
                        try { withContext(Dispatchers.IO) { Api.post(ctx, "/api/system/localai/report") } }
                        catch (e: ApiError) { wantReport = 0.0; Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show() }
                    }
                },
                enabled = !waiting, modifier = Modifier.padding(top = 12.dp), shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Accent, disabledContainerColor = Mc.ButtonDark, disabledContentColor = Mc.Muted),
                border = BorderStroke(1.dp, Mc.Border),
            ) { Text(if (waiting) "Fetching report…" else "Open trials report", fontSize = 14.sp, fontWeight = FontWeight.SemiBold) }
        }
    }
}
