package cz.filip.missioncontrol.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.animation.core.animateFloat
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.compose.LifecycleResumeEffect
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import cz.filip.missioncontrol.data.Signer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

private val MicIconS: androidx.compose.ui.graphics.vector.ImageVector = androidx.compose.ui.graphics.vector.ImageVector.Builder("mic", 24.dp, 24.dp, 24f, 24f).addPath(
    pathData = androidx.compose.ui.graphics.vector.addPathNodes("M12,14c1.66,0 3,-1.34 3,-3V5c0,-1.66 -1.34,-3 -3,-3S9,3.34 9,5v6c0,1.66 1.34,3 3,3zM17.3,11c0,3 -2.54,5.1 -5.3,5.1S6.7,14 6.7,11H5c0,3.41 2.72,6.23 6,6.72V21h2v-3.28c3.28,-0.48 6,-3.3 6,-6.72h-1.7z"),
    fill = androidx.compose.ui.graphics.SolidColor(Color.Black),
).build()

private fun JSONArray?.objs(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }

/**
 * Fingerprint, sign "[msg]|ts", then POST [body] + ts + sig to [path]. Registers the signing key first if
 * mc-pi has none. Calls [done] on the main thread with null (ok) or an error text.
 */
fun signedPost(ctx: Context, title: String, msg: String, path: String, body: JSONObject, hasKey0: Boolean, done: (String?) -> Unit) =
    signedPostEx(ctx, title, msg, path, body, hasKey0, {}, done)

/** Like [signedPost], but calls [onSigned] (main thread) the moment the fingerprint succeeds, before the Pi has answered: update the UI there. */
fun signedPostEx(ctx: Context, title: String, msg: String, path: String, body: JSONObject, hasKey0: Boolean, onSigned: () -> Unit, done: (String?) -> Unit) {
    val hasKey = hasKey0 && !Signer.needsRegister(ctx)
    val act = ctx as? FragmentActivity ?: return done("no activity")
    val scope = kotlinx.coroutines.MainScope()
    val ts = System.currentTimeMillis() / 1000
    scope.launch {
        if (!hasKey) {
            try { withContext(Dispatchers.IO) { Signer.register(ctx) } } catch (e: Exception) {
                done(if ("biometric" in (e.message ?: "").lowercase() || e is IllegalStateException) "Set up a fingerprint on this phone first."
                     else "Could not register the fingerprint key: ${e.message}"); return@launch
            }
        }
        Signer.sign(act, title, "$msg|$ts") { sig, err ->
            if (sig == null) { done(err ?: "cancelled"); return@sign }
            onSigned()
            scope.launch {
                try {
                    withContext(Dispatchers.IO) { Api.post(ctx, path, body.put("ts", ts).put("sig", sig)) }
                    done(null)
                } catch (e: ApiError) {
                    if (e.code == 403 && e.message?.contains("key") == true) runCatching { withContext(Dispatchers.IO) { Signer.register(ctx) } }
                    done(e.message ?: "error")
                }
            }
        }
    }
}

/** Unix seconds -> "now", "5 min ago", "3 h ago", else the clock. */
fun sinceText(t: Double): String {
    val s = System.currentTimeMillis() / 1000 - t.toLong()
    return when { s < 60 -> "now"; s < 3600 -> "${s / 60} min ago"; s < 6 * 3600 -> "${s / 3600} h ago"; else -> clock(t) }
}

fun stateChip(state: String): Pair<String, Color> = when (state) {
    "waiting" -> "Needs you" to Mc.Warn
    "working" -> "Working" to Mc.Accent
    else -> "Idle" to Mc.Idle
}

/** Claude sessions block of the Claude tab: requests on top, then the live sessions. */
@Composable
fun SessionList(s: JSONObject, onOpen: (String) -> Unit, onConfig: () -> Unit) {
    val sessions = s.optJSONArray("sessions").objs()
    val gates = s.optJSONArray("gates").objs()
    val props = s.optJSONArray("proposals").objs()
    val needs = gates.map { it.optString("session_id") }.toSet() + props.map { it.optString("session_id") }.toSet()
    if (!s.optBoolean("fresh")) Text("The PC is not reporting sessions right now (asleep or helper off).", color = Mc.Warn, fontSize = 13.sp)
    if (gates.isNotEmpty() || props.isNotEmpty()) {
        Label("Asks you · ${gates.size + props.size}", Mc.Warn)
        gates.forEach { g ->
            // An app card whose PC session is not in the live list opens on its own (the Pi serves it by its gate id).
            McCard(onClick = { onOpen(g.optString("session_id").ifBlank { g.optString("id") }) }) {
                Label(when (g.optString("kind")) { "question" -> "Question"; "plan" -> "Plan"; "appcard" -> "Claude app card · ${toolShort(g.optString("tool"))}"
                    else -> "Permission · ${g.optString("tool")}" }, Mc.Warn)
                Text(g.optString("summary"), color = Mc.Text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, maxLines = 3,
                    overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 4.dp))
                Text(g.optString("session"), color = Mc.Muted, fontSize = 13.sp)
            }
        }
        props.forEach { p ->
            McCard(onClick = { onOpen(p.optString("session_id")) }) {
                Label("New session", Mc.Warn)
                Text(p.optString("title"), color = Mc.Text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp))
                Text(p.optString("session"), color = Mc.Muted, fontSize = 13.sp)
            }
        }
    }
    Label("Claude sessions · ${sessions.size}")
    if (sessions.isEmpty()) Text("No Claude session is running.", color = Mc.Muted, fontSize = 14.sp)
    val sorted = sessions.sortedWith(compareBy<JSONObject>({ if (it.optString("id") in needs) 0 else when (it.optString("state")) { "waiting" -> 1; "working" -> 2; else -> 3 } },
        { -it.optDouble("updated", 0.0) }))
    var all by remember { mutableStateOf(false) }
    val active = sorted.count { it.optString("id") in needs || it.optString("state") != "idle" }
    val shown = if (all) sorted else sorted.take(maxOf(active + 3, 5))
    Column {
        shown.forEachIndexed { i, x ->
            val (chip, color) = if (x.optString("id") in needs) "Asks you" to Mc.Warn else stateChip(x.optString("state"))
            Row(Modifier.fillMaxWidth().clickable { onOpen(x.optString("id")) }.padding(vertical = 10.dp), verticalAlignment = Alignment.Top) {
                Box(Modifier.padding(top = 6.dp).size(10.dp).clip(CircleShape).background(color))
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(x.optString("title"), color = Mc.Text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, maxLines = 1,
                            overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                        Text(chip, color = if (color == Mc.Idle) Mc.Muted else color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.clip(RoundedCornerShape(50)).background(Mc.ButtonDark).padding(horizontal = 10.dp, vertical = 4.dp))
                    }
                    x.optString("last").takeIf { it.isNotBlank() }?.let { Text(it, color = Mc.Muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis) }
                    Text(x.optString("cwd").substringAfterLast('\\') + (x.optDouble("updated", 0.0).takeIf { it > 0 }?.let { " · ${sinceText(it)}" } ?: ""),
                        color = Mc.Idle, fontSize = 12.sp)
                }
            }
            if (i < shown.size - 1) HorizontalDivider(color = Mc.Border)
        }
        if (sorted.size > shown.size || all) Text(if (all) "Show fewer" else "Show ${sorted.size - shown.size} more idle sessions",
            color = Mc.Accent, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.fillMaxWidth().clickable { all = !all }.padding(vertical = 12.dp))
    }
    val cfg = s.optJSONObject("gate_config") ?: JSONObject()
    Text("Auto-approve without fingerprint: " + (if (cfg.optString("auto") == "readonly") "read-only tools" else "nothing") + " · change",
        color = Mc.Accent, fontSize = 13.sp, modifier = Modifier.clickable(onClick = onConfig).padding(vertical = 6.dp))
}

/** Dialog to change what the phone gate auto-approves (needs the fingerprint). */
@Composable
fun GateConfigDialog(current: String, hasKey: Boolean, onClose: () -> Unit) {
    val ctx = LocalContext.current
    AlertDialog(onDismissRequest = onClose, containerColor = Mc.Card,
        title = { Text("Auto-approve") },
        text = { Text("Which permission requests may be allowed without your fingerprint? Questions are never answered automatically.\n\nNow: " +
            if (current == "readonly") "read-only tools (Read, Glob, Grep, LS)" else "nothing") },
        confirmButton = {
            val next = if (current == "readonly") "none" else "readonly"
            TextButton(onClick = {
                signedPostEx(ctx, "Auto-approve: $next", "gate-config|$next|1", "/api/gate/config", JSONObject().put("auto", next).put("enabled", true), hasKey,
                    onSigned = { Toast.makeText(ctx, "Saved", Toast.LENGTH_SHORT).show(); onClose() }) { err ->
                    if (err != null) { Toast.makeText(ctx, "Not saved: $err", Toast.LENGTH_LONG).show(); onClose() }
                }
            }) { Text(if (current == "readonly") "Ask for everything" else "Allow read-only tools") }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Close") } })
}

@Composable
fun SessionView(sid: String, hasKey: Boolean, onBack: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var resumed by remember { mutableStateOf(false) }
    var text by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }               // waiting for the fingerprint
    var gone by remember { mutableStateOf(setOf<String>()) }     // gates / proposals answered here: hidden at once
    val sending = remember { mutableStateListOf<String>() }      // messages typed here that the Pi has not confirmed yet
    val scroll = rememberScrollState()
    BackHandler(onBack = onBack)

    suspend fun load() {
        try { data = withContext(Dispatchers.IO) { Api.get(ctx, "/api/sessions/$sid") }; error = null }
        catch (e: ApiError) { if (e.code == 401) onLoggedOut() else error = e.message }
    }
    LifecycleResumeEffect(Unit) { resumed = true; onPauseOrDispose { resumed = false } }
    LaunchedEffect(resumed) { while (resumed) { load(); delay(1500) } }
    val speech = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.StartActivityForResult()) { r ->
        r.data?.getStringArrayListExtra(android.speech.RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { text = if (text.isBlank()) it else "$text $it" }
    }
    val haptic = androidx.compose.ui.platform.LocalHapticFeedback.current
    val rows = data?.optJSONArray("rows").objs()
    // Follow new activity only while the user is at the bottom; reading older rows must not jump.
    var stick by remember { mutableStateOf(true) }
    LaunchedEffect(scroll) {
        androidx.compose.runtime.snapshotFlow { scroll.isScrollInProgress }.collect { moving ->
            if (!moving) stick = scroll.maxValue - scroll.value < 300
        }
    }
    LaunchedEffect(rows.size, data?.optJSONArray("gates")?.length()) { if (stick) scroll.animateScrollTo(scroll.maxValue) }

    val s = data?.optJSONObject("session")
    Column(modifier.fillMaxSize().imePadding()) {
        // Header: back, title (2 lines), then folder · state · Claude app link
        Row(Modifier.fillMaxWidth().padding(start = 4.dp, end = 16.dp, top = 10.dp), verticalAlignment = Alignment.Top) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Mc.Accent) }
            Column(Modifier.weight(1f).padding(top = 8.dp)) {
                Text(s?.optString("title") ?: "Session", color = Mc.Text, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, maxLines = 2,
                    overflow = TextOverflow.Ellipsis, lineHeight = 22.sp)
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
                    s?.let { val (chip, color) = stateChip(it.optString("state"))
                        Text(chip, color = if (color == Mc.Idle) Mc.Muted else color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.clip(RoundedCornerShape(50)).background(Mc.ButtonDark).padding(horizontal = 10.dp, vertical = 3.dp))
                        Text(it.optString("cwd").substringAfterLast('\\'), color = Mc.Muted, fontSize = 12.sp, maxLines = 1,
                            overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f).padding(horizontal = 8.dp))
                        val rc = it.optString("rc_id")
                        if (rc.isNotBlank()) Text("Claude app ↗", color = Mc.Accent, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable {
                                runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://claude.ai/code/$rc"))) }
                            }.padding(horizontal = 6.dp, vertical = 4.dp))
                    }
                }
            }
        }
        HorizontalDivider(color = Mc.Border, modifier = Modifier.padding(top = 8.dp))
        Column(Modifier.weight(1f).verticalScroll(scroll).padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            error?.let { Text(it, color = Mc.Bad, fontSize = 14.sp) }
            val d = data ?: run { if (error == null) Text("Loading…", color = Mc.Muted); null }
            if (d != null) {
                if (s == null) Text(if (d.optJSONArray("gates").objs().isEmpty()) "This session is not running any more."
                    else "A background Claude session (not in the list) asks you:", color = Mc.Warn, fontSize = 14.sp)
                if (!d.optBoolean("fresh", true)) Text("The PC is not reporting right now (asleep or helper off). This may be old.", color = Mc.Warn, fontSize = 13.sp)
                if (rows.isEmpty() && s != null) Text("Loading activity from the PC…", color = Mc.Muted, fontSize = 14.sp)
                groupRows(rows).forEach { g -> if (g.size == 1 && g[0].optString("role") != "tool") ActivityRow(g[0]) else ToolGroup(g) }
                if (s?.optString("state") == "working") {
                    val a by androidx.compose.animation.core.rememberInfiniteTransition(label = "w").animateFloat(0.35f, 1f,
                        androidx.compose.animation.core.infiniteRepeatable(androidx.compose.animation.core.tween(900), androidx.compose.animation.core.RepeatMode.Reverse), label = "a")
                    Text("● Claude is working…", color = Mc.Accent.copy(alpha = a), fontSize = 13.sp, modifier = Modifier.padding(start = 4.dp))
                }
                d.optJSONArray("gates").objs().filter { it.optString("kind") == "appcard" }.forEach { g ->
                    // App card: Allow needs the fingerprint, Deny is one tap. It stays on screen to show what the PC did.
                    val gid = g.optString("id")
                    val label = "Claude app card · ${toolShort(g.optString("tool"))}"
                    AppCardGate(g, busy, onAllow = {
                        busy = true
                        signedPostEx(ctx, "Allow once: $label", "gate|$gid|allow|", "/api/gate/$gid/answer",
                            JSONObject().put("decision", "allow").put("payload", ""), hasKey,
                            onSigned = { busy = false; Toast.makeText(ctx, "Sent to the PC", Toast.LENGTH_SHORT).show() }) { err ->
                            busy = false
                            if (err != null) Toast.makeText(ctx, "Not sent: $err", Toast.LENGTH_LONG).show()
                            scope.launch { load() }
                        }
                    }, onDeny = {
                        scope.launch {
                            try {
                                withContext(Dispatchers.IO) { Api.post(ctx, "/api/gate/$gid/answer", JSONObject().put("decision", "deny").put("payload", "")) }
                                Toast.makeText(ctx, "Deny sent to the PC", Toast.LENGTH_SHORT).show()
                            } catch (e: Exception) { Toast.makeText(ctx, "Not sent: ${e.message}", Toast.LENGTH_LONG).show() }
                            load()
                        }
                    })
                }
                d.optJSONArray("gates").objs().filter { it.optString("kind") != "appcard" && "gate:" + it.optString("id") !in gone }.forEach { g -> GateCard(g, busy) { decision, payload, label ->
                    val key = "gate:" + g.optString("id")
                    busy = true
                    signedPostEx(ctx, label, "gate|${g.optString("id")}|$decision|$payload", "/api/gate/${g.optString("id")}/answer",
                        JSONObject().put("decision", decision).put("payload", payload), hasKey,
                        onSigned = { busy = false; gone = gone + key; Toast.makeText(ctx, "Sent to the PC", Toast.LENGTH_SHORT).show() }) { err ->
                        busy = false
                        if (err != null) { gone = gone - key; Toast.makeText(ctx, "Not sent: $err", Toast.LENGTH_LONG).show() }
                        scope.launch { load() }
                    }
                } }
                d.optJSONArray("proposals").objs().filter { "prop:" + it.optString("key") !in gone }.forEach { p -> ProposalCard(p, busy,
                    onStart = {
                        val key = "prop:" + p.optString("key")
                        busy = true
                        signedPostEx(ctx, "Start: ${p.optString("title")}", "start|${p.optString("key")}", "/api/proposals/${p.optString("key")}/start",
                            JSONObject(), hasKey,
                            onSigned = { busy = false; gone = gone + key; Toast.makeText(ctx, "Start sent to the session", Toast.LENGTH_SHORT).show() }) { err ->
                            busy = false
                            if (err != null) { gone = gone - key; Toast.makeText(ctx, "Not sent: $err", Toast.LENGTH_LONG).show() }
                            scope.launch { load() }
                        }
                    },
                    onHide = {
                        val key = "prop:" + p.optString("key")
                        gone = gone + key
                        scope.launch {
                            try { withContext(Dispatchers.IO) { Api.post(ctx, "/api/proposals/${p.optString("key")}/hide") } }
                            catch (e: ApiError) { gone = gone - key; Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show() }
                            load()
                        }
                    }) }
                sending.forEach { t ->
                    Box(Modifier.fillMaxWidth().padding(start = 40.dp)) {
                        Text(t + "  · sending…", color = Mc.Muted, fontSize = 15.sp, lineHeight = 21.sp, modifier = Modifier.align(Alignment.CenterEnd)
                            .clip(RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp)).background(Color(0xFF16384D)).padding(horizontal = 12.dp, vertical = 9.dp))
                    }
                }
                d.optJSONArray("outbox").objs().takeIf { it.isNotEmpty() }?.let { out ->
                    Label("Sent from the phone")
                    out.forEach { o ->
                        val ok = if (o.isNull("ok")) null else o.optBoolean("ok")
                        Text("${clock(o.optDouble("at"))} · ${o.optString("text").take(80)} → ${o.optString("detail")}",
                            color = when (ok) { true -> Mc.Good; false -> Mc.Bad; null -> Mc.Muted }, fontSize = 12.sp)
                    }
                }
            }
        }
        if (s != null) {
            val desktop = s.optString("kind") == "desktop"
            HorizontalDivider(color = Mc.Border)
            if (!desktop) Text("Messages from the phone work only for Claude Desktop sessions. Use the Claude app link above.",
                color = Mc.Muted, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp))
            if (desktop) Row(Modifier.fillMaxWidth().background(Mc.Bg).padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(value = text, onValueChange = { text = it }, placeholder = { Text("Message Claude…", maxLines = 1) },
                    maxLines = 5, shape = RoundedCornerShape(14.dp), textStyle = androidx.compose.ui.text.TextStyle(fontSize = 15.sp),
                    modifier = Modifier.weight(1f))
                IconButton(onClick = {
                    runCatching { speech.launch(Intent(android.speech.RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                        .putExtra(android.speech.RecognizerIntent.EXTRA_LANGUAGE_MODEL, android.speech.RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)) }
                        .onFailure { Toast.makeText(ctx, "No speech recognition on this phone", Toast.LENGTH_LONG).show() }
                }, modifier = Modifier.padding(bottom = 3.dp).size(50.dp).clip(RoundedCornerShape(14.dp)).background(Mc.ButtonDark)) {
                    Icon(MicIconS, contentDescription = "Speak", tint = Mc.Text)
                }
                IconButton(enabled = !busy && text.isNotBlank(), onClick = {
                    haptic.performHapticFeedback(androidx.compose.ui.hapticfeedback.HapticFeedbackType.LongPress)
                    val t = text.trim(); busy = true
                    signedPostEx(ctx, "Send to ${s.optString("title").take(40)}", "msg|$sid|$t", "/api/sessions/$sid/message",
                        JSONObject().put("text", t), hasKey,
                        onSigned = { busy = false; if (text.trim() == t) text = ""; sending.add(t) }) { err ->
                        busy = false
                        if (err != null) {
                            sending.remove(t)
                            if (text.isBlank()) text = t
                            Toast.makeText(ctx, if (err == "cancelled") err else "Not sent: $err", Toast.LENGTH_LONG).show()
                        }
                        scope.launch { load(); sending.remove(t) }
                    }
                }, modifier = Modifier.padding(bottom = 3.dp).size(50.dp).clip(RoundedCornerShape(14.dp))
                    .background(if (!busy && text.isNotBlank()) Mc.Accent else Mc.ButtonDark)) {
                    Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send",
                        tint = if (!busy && text.isNotBlank()) Color(0xFF04121C) else Mc.Muted)
                }
            }
        }
    }
}

/** Consecutive tool rows become one group; text rows stay single. */
private fun groupRows(rows: List<JSONObject>): List<List<JSONObject>> {
    val out = mutableListOf<MutableList<JSONObject>>()
    rows.forEach { r ->
        val tool = r.optString("role") == "tool"
        if (tool && out.isNotEmpty() && out.last()[0].optString("role") == "tool") out.last() += r
        else out += mutableListOf(r)
    }
    return out
}

/** Light Markdown for Claude's text: **bold**, `code`, # headings, bullet dashes. */
private fun md(t: String) = buildAnnotatedString {
    t.lines().forEachIndexed { i, raw ->
        if (i > 0) append("\n")
        var line = raw
        val heading = line.startsWith("#")
        if (heading) line = line.trimStart('#').trim()
        if (line.startsWith("- ") || line.startsWith("* ")) line = "• " + line.drop(2)
        val start = length
        var j = 0
        while (j < line.length) {
            when {
                line.startsWith("**", j) && line.indexOf("**", j + 2) > j -> {
                    val e = line.indexOf("**", j + 2)
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(line.substring(j + 2, e)) }; j = e + 2
                }
                line[j] == '`' && line.indexOf('`', j + 1) > j -> {
                    val e = line.indexOf('`', j + 1)
                    withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = Mc.ButtonDark, fontSize = 13.sp)) { append(line.substring(j + 1, e)) }; j = e + 1
                }
                else -> { append(line[j]); j++ }
            }
        }
        if (heading) addStyle(SpanStyle(fontWeight = FontWeight.Bold), start, length)
    }
}

@Composable
private fun ToolGroup(g: List<JSONObject>) {
    var open by remember { mutableStateOf(false) }
    val errors = g.count { it.optBoolean("error") }
    val last = g.last()
    Column(Modifier.fillMaxWidth().padding(horizontal = 4.dp).clip(RoundedCornerShape(10.dp)).clickable { open = !open }
        .padding(horizontal = 8.dp, vertical = 4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (open) "▾" else "▸", color = Mc.Idle, fontSize = 13.sp, modifier = Modifier.width(14.dp))
            Text(if (g.size == 1) "1 step" else "${g.size} steps", color = Mc.Idle, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Mc.ButtonDark).padding(horizontal = 6.dp, vertical = 2.dp))
            if (errors > 0) Text(" $errors failed", color = Mc.Bad, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            if (!open) Text(last.optString("text"), color = Mc.Muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(start = 8.dp).weight(1f))
        }
        if (!open) return@Column
        g.forEach { r ->
            Column(Modifier.padding(start = 16.dp, top = 8.dp)) {
                Text((if (r.optBoolean("error")) "✗ " else "") + r.optString("text"), color = if (r.optBoolean("error")) Mc.Bad else Mc.Text,
                    fontSize = 13.sp, lineHeight = 18.sp)
                r.optString("detail").takeIf { it.isNotBlank() }?.let {
                    Text(it, color = Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace, lineHeight = 16.sp, maxLines = 4, overflow = TextOverflow.Ellipsis)
                }
                r.optString("result").takeIf { it.isNotBlank() }?.let {
                    Text("→ $it", color = Mc.Idle, fontSize = 12.sp, lineHeight = 16.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

@Composable
private fun ActivityRow(r: JSONObject) {
    val role = r.optString("role")
    val t = r.optString("text")
    when (role) {
        "user" -> Box(Modifier.fillMaxWidth().padding(start = 40.dp)) {
            Text(t, color = Mc.Text, fontSize = 15.sp, lineHeight = 21.sp, modifier = Modifier.align(Alignment.CenterEnd)
                .clip(RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp)).background(Color(0xFF16384D)).padding(horizontal = 12.dp, vertical = 9.dp))
        }
        "claude" -> {
            var open by remember { mutableStateOf(false) }
            val long = t.length > 700
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp)).background(Mc.Card)
                .border(1.dp, Mc.Border, RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp)).clickable(enabled = long) { open = !open }
                .padding(horizontal = 12.dp, vertical = 10.dp)) {
                Text(md(if (open || !long) t else t.take(700).substringBeforeLast(' ') + " …"), color = Mc.Text, fontSize = 15.sp, lineHeight = 21.sp)
                if (long) Text(if (open) "Show less" else "Show more", color = Mc.Accent, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(top = 6.dp))
            }
        }
        "tool" -> {
            var open by remember { mutableStateOf(false) }
            Column(Modifier.clip(RoundedCornerShape(10.dp)).border(1.dp, Mc.Border, RoundedCornerShape(10.dp)).clickable { open = !open }
                .padding(horizontal = 10.dp, vertical = 6.dp)) {
                Text((if (r.optBoolean("error")) "✗ " else "▸ ") + t, color = if (r.optBoolean("error")) Mc.Bad else Mc.Muted, fontSize = 12.5.sp,
                    fontFamily = FontFamily.Monospace, maxLines = if (open) 20 else 1, overflow = TextOverflow.Ellipsis)
                if (open) r.optString("result").takeIf { it.isNotBlank() }?.let { Text(it, color = Mc.Idle, fontSize = 12.sp, fontFamily = FontFamily.Monospace) }
            }
        }
        else -> Text(t, color = Mc.Idle, fontSize = 12.sp)
    }
}

@Composable
internal fun CodeBox(text: String) {
    Text(text, color = Mc.Text, fontSize = 12.5.sp, fontFamily = FontFamily.Monospace,
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp).heightIn(max = 420.dp).clip(RoundedCornerShape(10.dp)).background(Mc.Bg)
            .border(1.dp, Mc.Border, RoundedCornerShape(10.dp)).verticalScroll(rememberScrollState()).padding(10.dp))
}

@Composable
private fun DiffBox(old: String, new: String) {
    val s = buildAnnotatedString {
        old.lines().forEach { withStyle(SpanStyle(color = Mc.Bad)) { append("- $it\n") } }
        new.lines().forEach { withStyle(SpanStyle(color = Mc.Good)) { append("+ $it\n") } }
    }
    Text(s, fontSize = 12.5.sp, fontFamily = FontFamily.Monospace,
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp).heightIn(max = 420.dp).clip(RoundedCornerShape(10.dp)).background(Mc.Bg)
            .border(1.dp, Mc.Border, RoundedCornerShape(10.dp)).verticalScroll(rememberScrollState()).padding(10.dp))
}

@Composable
internal fun PrimaryButton(text: String, modifier: Modifier = Modifier, enabled: Boolean = true, onClick: () -> Unit) =
    Button(onClick = onClick, enabled = enabled, shape = RoundedCornerShape(14.dp), modifier = modifier.height(50.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C))) {
        Text(text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
    }

@Composable
internal fun DarkBtn(text: String, modifier: Modifier = Modifier, color: Color = Mc.Text, onClick: () -> Unit) =
    OutlinedButton(onClick = onClick, modifier = modifier.height(50.dp), shape = RoundedCornerShape(14.dp),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = Mc.ButtonDark, contentColor = color), border = BorderStroke(1.dp, Mc.Border)) {
        Text(text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }

/** A phone-gate request: a question (options + own text) or a permission (exact input, Allow / Deny). */
@Composable
private fun GateCard(g: JSONObject, busy: Boolean, send: (decision: String, payload: String, label: String) -> Unit) {
    val ctx = LocalContext.current
    val inp = g.optJSONObject("input") ?: JSONObject()
    val kind = g.optString("kind")
    val tool = g.optString("tool")
    McCard(modifier = Modifier.border(1.dp, Color(0xFF5A4115), RoundedCornerShape(18.dp))) {
        if (kind == "question") {
            val qs = inp.optJSONArray("questions").objs()
            val picked = remember(g.optString("id")) { mutableStateMapOf<String, Set<String>>() }
            val other = remember(g.optString("id")) { mutableStateMapOf<String, String>() }
            qs.forEach { q ->
                val qt = q.optString("question")
                val multi = q.optBoolean("multiSelect")
                Label("Question · ${q.optString("header")}" + if (multi) " · pick any" else "", Mc.Warn)
                Text(qt, color = Mc.Text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp, bottom = 4.dp))
                q.optJSONArray("options").objs().forEach { o ->
                    val label = o.optString("label")
                    val sel = label in (picked[qt] ?: emptySet())
                    Column(Modifier.fillMaxWidth().padding(top = 6.dp).clip(RoundedCornerShape(12.dp))
                        .background(if (sel) Color(0xFF0F2A3B) else Color.Transparent)
                        .border(1.dp, if (sel) Mc.Accent else Mc.Border, RoundedCornerShape(12.dp))
                        .clickable {
                            val cur = picked[qt] ?: emptySet()
                            picked[qt] = if (multi) (if (sel) cur - label else cur + label) else setOf(label)
                            if (!multi) other.remove(qt)
                        }.padding(10.dp)) {
                        Text(label, color = Mc.Text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                        o.optString("description").takeIf { it.isNotBlank() }?.let { Text(it, color = Mc.Muted, fontSize = 13.sp) }
                    }
                }
                OutlinedTextField(value = other[qt] ?: "", onValueChange = { other[qt] = it; if (!multi && it.isNotBlank()) picked.remove(qt) },
                    placeholder = { Text("Other… (your own answer)") }, maxLines = 4, shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 10.dp))
            }
            fun answerOf(q: JSONObject): String {
                val qt = q.optString("question")
                val parts = (picked[qt] ?: emptySet()).toList() + listOfNotNull(other[qt]?.trim()?.takeIf { it.isNotBlank() })
                return parts.joinToString(", ")
            }
            val ready = qs.isNotEmpty() && qs.all { answerOf(it).isNotBlank() }
            if (busy) Text("Waiting for fingerprint…", color = Mc.Muted, fontSize = 14.sp)
            else PrimaryButton("Send answer", Modifier.fillMaxWidth(), enabled = ready) {
                val a = JSONObject(); qs.forEach { a.put(it.optString("question"), answerOf(it)) }
                send("answer", a.toString(), "Answer: ${qs.firstOrNull()?.optString("question")?.take(60)}")
            }
            return@McCard
        }
        Label(if (kind == "plan") "Plan · approve to start" else "Wants to run · $tool", Mc.Warn)
        val planDoc = if (kind == "plan") g.optString("doc") else ""
        when {
            kind == "plan" && inp.optString("plan").isBlank() -> Text(
                if (planDoc.isNotBlank()) "Claude's plan is ready. Open it to read it, comment on lines and approve or reject it."
                else "Claude's plan is ready, but this phone cannot find the plan file. Read it at the PC.", color = Mc.Text, fontSize = 15.sp,
                modifier = Modifier.padding(top = 6.dp))
            tool == "Bash" || tool == "PowerShell" -> {
                CodeBox(inp.optString("command"))
                inp.optString("description").takeIf { it.isNotBlank() }?.let { Text(it, color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp)) }
            }
            tool == "Edit" -> { Text(inp.optString("file_path"), color = Mc.Text, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                DiffBox(inp.optString("old_string"), inp.optString("new_string"))
                if (inp.optBoolean("replace_all")) Text("Replaces every match", color = Mc.Warn, fontSize = 13.sp) }
            tool == "Write" -> { Text(inp.optString("file_path"), color = Mc.Text, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                CodeBox(inp.optString("content")) }
            kind == "plan" -> CodeBox(inp.optString("plan"))
            else -> CodeBox(inp.toString(2))
        }
        Text("Folder: ${g.optString("cwd")}" + (g.optString("agent").takeIf { it.isNotBlank() }?.let { " · subagent $it" } ?: ""),
            color = Mc.Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
        if (g.optBoolean("truncated")) Text("Too long to show fully here: check it at the PC before allowing.", color = Mc.Warn, fontSize = 13.sp)
        Spacer(Modifier.height(10.dp))
        var note by remember { mutableStateOf<String?>(null) }
        var askComments by remember { mutableStateOf(false) }
        val openComments = g.optInt("doc_open_comments")
        if (planDoc.isNotBlank() && !busy) {
            PrimaryButton(if (openComments > 0) "Open plan · $openComments comment${if (openComments > 1) "s" else ""}" else "Open plan to review", Modifier.fillMaxWidth()) {
                cz.filip.missioncontrol.MainActivity.wantDoc.value = planDoc; cz.filip.missioncontrol.MainActivity.wantTab.intValue = 2
            }
            Spacer(Modifier.height(8.dp))
        }
        if (busy) Text("Waiting for fingerprint…", color = Mc.Muted, fontSize = 14.sp)
        else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (kind == "plan") {
                    DarkBtn("Approve", Modifier.weight(1.5f)) { if (openComments > 0) askComments = true else send("allow", "", "Approve plan") }
                    DarkBtn("Reject", Modifier.weight(1f), Mc.Bad) {
                        if (openComments > 0 && planDoc.isNotBlank()) {      // the comments are the feedback: reject in the plan, where they are listed
                            Toast.makeText(ctx, "Reject it in the plan: your comments go with it", Toast.LENGTH_LONG).show()
                            cz.filip.missioncontrol.MainActivity.wantDoc.value = planDoc; cz.filip.missioncontrol.MainActivity.wantTab.intValue = 2
                        } else note = ""
                    }
                } else {
                    PrimaryButton("Allow", Modifier.weight(1.5f)) { send("allow", "", "Allow $tool") }
                    DarkBtn("Deny", Modifier.weight(1f), Mc.Bad) { send("deny", "", "Deny $tool") }
                }
            }
            if (kind != "plan") Text("Deny and tell Claude why…", color = Mc.Accent, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable { note = "" }.padding(vertical = 10.dp, horizontal = 4.dp))
        }
        note?.let { n ->
            AlertDialog(onDismissRequest = { note = null }, containerColor = Mc.Card, title = { Text(if (kind == "plan") "Reject the plan" else "Deny with a note") },
                text = { OutlinedTextField(value = n, onValueChange = { note = it }, minLines = 3, modifier = Modifier.fillMaxWidth()) },
                confirmButton = { TextButton(enabled = n.isNotBlank(), onClick = { note = null; send("deny", n.trim(), if (kind == "plan") "Reject plan" else "Deny $tool") }) { Text("Send") } },
                dismissButton = { TextButton(onClick = { note = null }) { Text("Cancel") } })
        }
        if (askComments) AlertDialog(onDismissRequest = { askComments = false }, containerColor = Mc.Card,
            title = { Text("Send the comments as changes instead?") },
            text = { Text("This plan has $openComments open comment${if (openComments > 1) "s" else ""}. Approving takes the plan as it is. Open the plan to reject it with the comments as the changes.") },
            confirmButton = { TextButton(onClick = {
                askComments = false
                cz.filip.missioncontrol.MainActivity.wantDoc.value = planDoc; cz.filip.missioncontrol.MainActivity.wantTab.intValue = 2
            }) { Text("Open the plan") } },
            dismissButton = { Row {
                TextButton(onClick = { askComments = false; send("allow", "", "Approve plan") }) { Text("Approve anyway") }
                TextButton(onClick = { askComments = false }) { Text("Cancel") }
            } })
    }
}

@Composable
private fun ProposalCard(p: JSONObject, busy: Boolean, onStart: () -> Unit, onHide: () -> Unit) {
    McCard(modifier = Modifier.border(1.dp, Color(0xFF5A4115), RoundedCornerShape(18.dp))) {
        Label("New session", Mc.Warn)
        Text(p.optString("title"), color = Mc.Text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp))
        Text(listOf(p.optString("folder"), p.optString("context"), p.optString("model")).filter { it.isNotBlank() }.joinToString(" · "),
            color = Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
        CodeBox(p.optString("prompt"))
        Spacer(Modifier.height(10.dp))
        if (p.optBoolean("offer")) { Text("This card waits in Claude Desktop: answer it there or in the Claude app.", color = Mc.Muted, fontSize = 13.sp); return@McCard }
        if (busy) Text("Waiting for fingerprint…", color = Mc.Muted, fontSize = 14.sp)
        else Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton("Start", Modifier.weight(1.3f), onClick = onStart)
            DarkBtn("Hide", Modifier.weight(1f), onClick = onHide)
        }
        Text("Start is typed into the session as your words (PC must be unlocked and unused for 2 min).", color = Mc.Muted, fontSize = 12.sp,
            modifier = Modifier.padding(top = 6.dp))
    }
}
