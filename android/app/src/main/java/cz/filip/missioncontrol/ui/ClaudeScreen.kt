package cz.filip.missioncontrol.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.media.MediaRecorder
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.compose.LifecycleResumeEffect
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import cz.filip.missioncontrol.data.Signer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val MicIcon: ImageVector = ImageVector.Builder("mic", 24.dp, 24.dp, 24f, 24f).addPath(
    pathData = addPathNodes("M12,14c1.66,0 3,-1.34 3,-3V5c0,-1.66 -1.34,-3 -3,-3S9,3.34 9,5v6c0,1.66 1.34,3 3,3zM17.3,11c0,3 -2.54,5.1 -5.3,5.1S6.7,14 6.7,11H5c0,3.41 2.72,6.23 6,6.72V21h2v-3.28c3.28,-0.48 6,-3.3 6,-6.72h-1.7z"),
    fill = SolidColor(Color.Black),
).build()

private fun JSONArray?.strings(): List<String> = if (this == null) emptyList() else (0 until length()).map { getString(it) }
private fun JSONArray?.objects(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).map { getJSONObject(it) }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ClaudeScreen(onSettings: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var resumed by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf<String?>(null) }          // approval id being answered
    var replyFor by remember { mutableStateOf<JSONObject?>(null) }
    var bigPicture by remember { mutableStateOf<Pair<String, Int>?>(null) }
    var live by remember { mutableStateOf<JSONObject?>(null) }       // /api/sessions
    var openSid by remember { mutableStateOf<String?>(null) }
    var gateConfig by remember { mutableStateOf(false) }
    var answered by remember { mutableStateOf(setOf<String>()) }     // approvals answered on this phone, hidden at once

    suspend fun load() {
        try {
            kotlinx.coroutines.coroutineScope {
                val l = async(Dispatchers.IO) { runCatching { Api.get(ctx, "/api/sessions") }.getOrNull() }
                val d = async(Dispatchers.IO) { Api.get(ctx, "/api/claude") }
                data = d.await(); error = null
                live = l.await()
            }
        } catch (e: ApiError) {
            if (e.code == 401) onLoggedOut() else error = e.message
        }
    }

    val wantS = cz.filip.missioncontrol.MainActivity.wantSession.value
    LaunchedEffect(wantS) { if (wantS.isNotBlank()) { openSid = wantS; cz.filip.missioncontrol.MainActivity.wantSession.value = "" } }
    openSid?.let { sid ->
        SessionView(sid, hasKey = live?.optBoolean("has_key") == true || data?.optBoolean("has_key") == true,
            onBack = { openSid = null; scope.launch { load() } }, onLoggedOut = onLoggedOut, modifier = modifier)
        return
    }

    fun answer(a: JSONObject, decision: String, option: String = "", text: String = "") {
        val act = ctx as? FragmentActivity ?: return
        val id = a.getString("id")
        val ts = System.currentTimeMillis() / 1000
        val msg = "$id|$decision|$option|$text|$ts"
        busy = id
        scope.launch {
            try {
                if (data?.optBoolean("has_key") != true || Signer.needsRegister(ctx)) withContext(Dispatchers.IO) { Signer.register(ctx) }
            } catch (e: Exception) {
                Toast.makeText(ctx, "Could not register the fingerprint key: ${e.message}", Toast.LENGTH_LONG).show()
                busy = null; return@launch
            }
            Signer.sign(act, a.optString("title"), msg) { sig, err ->
                if (sig == null) { busy = null; err?.let { Toast.makeText(ctx, it, Toast.LENGTH_SHORT).show() }; return@sign }
                // Fingerprint done: the card disappears now, the answer travels in the background.
                busy = null
                answered = answered + id
                Toast.makeText(ctx, "Sent", Toast.LENGTH_SHORT).show()
                scope.launch {
                    try {
                        val r = withContext(Dispatchers.IO) {
                            Api.post(ctx, "/api/approvals/$id/answer", JSONObject().put("decision", decision)
                                .put("option", option).put("text", text).put("ts", ts).put("sig", sig))
                        }
                        if (r.optBoolean("woke_pc")) Toast.makeText(ctx, "Waking the PC…", Toast.LENGTH_SHORT).show()
                    } catch (e: ApiError) {
                        answered = answered - id      // not delivered: the card comes back
                        if (e.code == 403 && e.message?.contains("key") == true) runCatching { withContext(Dispatchers.IO) { Signer.register(ctx) } }
                        Toast.makeText(ctx, "Not sent: ${e.message}", Toast.LENGTH_LONG).show()
                    } finally {
                        load()
                    }
                }
            }
        }
    }

    LifecycleResumeEffect(Unit) { resumed = true; onPauseOrDispose { resumed = false } }
    LaunchedEffect(resumed) { while (resumed) { load(); delay(4000) } }

    Column(modifier.fillMaxSize().imePadding()) {
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } },
            modifier = Modifier.weight(1f)) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 22.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                val d = data
                val sessions = d?.optJSONArray("sessions").objects()
                Row(verticalAlignment = Alignment.Bottom) {
                    Box(Modifier.weight(1f)) { Header("Claude") }
                    val working = live?.optJSONArray("sessions").objects().count { it.optString("state") == "working" }
                    Chip("$working working", Mc.Accent, Mc.NavSelected, Modifier.padding(bottom = 8.dp))
                    IconButton(onClick = onSettings, modifier = Modifier.padding(bottom = 2.dp)) {
                        Icon(Icons.Filled.Settings, contentDescription = "Settings", tint = Mc.Muted)
                    }
                }
                error?.let { McCard { Text(it, color = Mc.Bad, fontSize = 14.sp) } }
                if (d == null) { if (error == null) Text("Loading…", color = Mc.Muted); return@Column }
                if (d.optBoolean("helper") == false && d.optBoolean("pc_online")) {
                    Text("The PC helper is not reporting, so this may be old.", color = Mc.Warn, fontSize = 13.sp)
                }

                val approvals = d.optJSONArray("approvals").objects().filter { it.optString("id") !in answered }
                if (approvals.isNotEmpty()) Label("Approvals · ${approvals.size}", Mc.Warn)
                val asks = (live?.optJSONArray("gates")?.length() ?: 0) + (live?.optJSONArray("proposals")?.length() ?: 0)
                if (approvals.isEmpty() && asks == 0) Text("Nothing is waiting for you.", color = Mc.Muted, fontSize = 14.sp)
                approvals.forEach { a ->
                    ApprovalCard(a, busy == a.optString("id"),
                        onAnswer = { dec, opt -> answer(a, dec, opt) },
                        onReply = { replyFor = a },
                        onPicture = { n -> bigPicture = a.getString("id") to n })
                }

                val l = live
                if (l != null) SessionList(l, onOpen = { openSid = it }, onConfig = { gateConfig = true })
                Label(if (l != null) "Other AIs" else "Sessions")
                Sessions(if (l != null) emptyList() else sessions, d.optJSONObject("parked") ?: JSONObject(), d.optJSONObject("usage") ?: JSONObject())

                Label("Usage")
                UsageCard(d.optJSONObject("usage") ?: JSONObject(), d.optJSONObject("parked") ?: JSONObject())

                HubStatus(d.optJSONObject("logs") ?: JSONObject(), d.optString("handoff"))
            }
        }
        IdeaDock(audioMode = data?.optBoolean("ideas_audio") == true)
    }

    replyFor?.let { a ->
        var text by remember(a) { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { replyFor = null }, containerColor = Mc.Card,
            title = { Text("Reply: ${a.optString("title")}") },
            text = { OutlinedTextField(value = text, onValueChange = { text = it }, minLines = 3, modifier = Modifier.fillMaxWidth()) },
            confirmButton = { TextButton(enabled = text.isNotBlank(), onClick = { replyFor = null; answer(a, "reply", text = text.trim()) }) { Text("Send") } },
            dismissButton = { TextButton(onClick = { replyFor = null }) { Text("Cancel") } },
        )
    }
    if (gateConfig) GateConfigDialog(live?.optJSONObject("gate_config")?.optString("auto") ?: "none",
        live?.optBoolean("has_key") == true) { gateConfig = false; scope.launch { load() } }
    bigPicture?.let { (id, n) ->
        Dialog(onDismissRequest = { bigPicture = null }) {
            val img = rememberPicture(id, n)
            Box(Modifier.fillMaxWidth().clickable { bigPicture = null }) {
                if (img != null) Image(img, null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth())
                else Text("Loading…", color = Mc.Muted)
            }
        }
    }
}

@Composable
private fun Chip(text: String, fg: Color, bg: Color, modifier: Modifier = Modifier) =
    Text(text, color = fg, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
        modifier = modifier.clip(RoundedCornerShape(50)).background(bg).padding(horizontal = 12.dp, vertical = 6.dp))

@Composable
private fun rememberPicture(id: String, n: Int): ImageBitmap? {
    val ctx = LocalContext.current
    val img by produceState<ImageBitmap?>(null, id, n) {
        value = withContext(Dispatchers.IO) {
            runCatching { Api.bytes(ctx, "/api/pictures/$id/$n").let { BitmapFactory.decodeByteArray(it, 0, it.size).asImageBitmap() } }.getOrNull()
        }
    }
    return img
}

@Composable
private fun ApprovalCard(a: JSONObject, busy: Boolean, onAnswer: (String, String) -> Unit, onReply: () -> Unit, onPicture: (Int) -> Unit) {
    val type = a.optString("type")
    val options = a.optJSONArray("options").strings()
    val pics = a.optInt("pictures")
    McCard {
        Label(type.replace('-', ' '), Mc.Accent)
        Text(a.optString("title"), color = Mc.Text, fontSize = 21.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp))
        val sub = listOfNotNull(a.optString("session").ifBlank { null }, if (pics > 0) "$pics picture${if (pics > 1) "s" else ""}" else null)
        if (sub.isNotEmpty()) Text(sub.joinToString(" · "), color = Mc.Muted, fontSize = 14.sp)
        a.optString("text").takeIf { it.isNotBlank() }?.let { Text(it, color = Mc.Text, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp)) }
        if (pics > 0) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 10.dp)) {
                for (n in 0 until pics) {
                    val img = rememberPicture(a.getString("id"), n)
                    Box(Modifier.weight(1f).aspectRatio(1.4f).clip(RoundedCornerShape(12.dp)).background(Mc.ButtonDark).clickable { onPicture(n) }) {
                        if (img != null) Image(img, null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                        if (type == "design-pick" && n < options.size) {
                            Text(options[n], color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.align(Alignment.BottomStart).background(Color(0x99000000)).padding(6.dp))
                        }
                    }
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        if (busy) { Text("Waiting for fingerprint…", color = Mc.Muted, fontSize = 14.sp); return@McCard }
        if (options.isNotEmpty()) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                options.take(3).forEach { o -> DarkButton(o, Modifier.weight(1f)) { onAnswer("option", o) } }
                DarkButton("Reply", Modifier.weight(1f), onClick = onReply)
            }
            if (options.size > 3) Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
                options.drop(3).forEach { o -> DarkButton(o, Modifier.weight(1f)) { onAnswer("option", o) } }
            }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onAnswer("approve", "") }, shape = RoundedCornerShape(14.dp), modifier = Modifier.weight(1.6f).height(50.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C))) {
                    Text("Approve", fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
                }
                DarkButton("Reject", Modifier.weight(1f), color = Mc.Bad) { onAnswer("reject", "") }
                DarkButton("Reply", Modifier.weight(1f), onClick = onReply)
            }
        }
    }
}

@Composable
private fun DarkButton(text: String, modifier: Modifier = Modifier, color: Color = Mc.Text, onClick: () -> Unit) =
    OutlinedButton(onClick = onClick, modifier = modifier.height(50.dp), shape = RoundedCornerShape(14.dp),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = Mc.ButtonDark, contentColor = color),
        border = androidx.compose.foundation.BorderStroke(1.dp, Mc.Border)) {
        Text(text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }

private val day = SimpleDateFormat("d MMM", Locale.ENGLISH)
private fun backAt(t: Double): String = if (t * 1000 - System.currentTimeMillis() > 20 * 3600_000L) day.format(Date((t * 1000).toLong())) else clock(t)

@Composable
private fun Sessions(sessions: List<JSONObject>, parked: JSONObject, usage: JSONObject) {
    Column {
        val rows = mutableListOf<Triple<String, String, Color>>()   // name, chip, color
        sessions.sortedBy { when (it.optString("status")) { "waiting" -> 0; "busy" -> 1; else -> 2 } }.forEach { s ->
            when (s.optString("status")) {
                "waiting" -> rows += Triple(s.optString("title"), "Needs you", Mc.Warn)
                "busy" -> rows += Triple(s.optString("title"), "Working", Mc.Accent)
                else -> rows += Triple(s.optString("title"), "Idle", Mc.Idle)
            }
        }
        fun parkedUntil(prefix: String) = parked.keys().asSequence().filter { it == prefix || it.startsWith("$prefix#") }
            .map { parked.getDouble(it) }.maxOrNull()
        val codexUsage = usage.optJSONObject("codex")
        val codexBack = parkedUntil("codex") ?: if (codexUsage?.optBoolean("limit_reached") == true)
            codexUsage.optJSONArray("windows").objects().mapNotNull { it.optDouble("resets_at").takeIf { r -> !r.isNaN() } }.maxOrNull() else null
        rows += Triple("Codex", codexBack?.let { "Limit · back ${backAt(it)}" } ?: "Idle", if (codexBack != null) Mc.Bad else Mc.Idle)
        val gem = parkedUntil("gemini")
        rows += Triple("Gemini", gem?.let { "Key parked · back ${backAt(it)}" } ?: "Idle", if (gem != null) Mc.Warn else Mc.Idle)
        val agy = parkedUntil("agy")
        rows += Triple("Antigravity", agy?.let { "Limit · back ${backAt(it)}" } ?: "Idle", if (agy != null) Mc.Bad else Mc.Idle)
        rows.forEachIndexed { i, (name, chip, color) ->
            Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).clip(CircleShape).background(color))
                Spacer(Modifier.width(14.dp))
                Text(name, color = Mc.Text, fontSize = 16.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Chip(chip, if (color == Mc.Idle) Mc.Muted else color, Mc.ButtonDark)
            }
            if (i < rows.size - 1) HorizontalDivider(color = Mc.Border)
        }
    }
}

private fun windowLabel(w: JSONObject): String {
    val span = when (w.optInt("seconds")) { 18000 -> "5 hours"; 604800 -> "week"; 2592000 -> "month"; else -> "session" }
    val name = w.optString("name")
    return if (name.endsWith("models")) "$span · ${name.removeSuffix(" models").replaceFirstChar { it.uppercase() }}" else span
}

@Composable
private fun UsageCard(usage: JSONObject, parked: JSONObject) {
    McCard {
        val names = listOf("claude" to "Claude", "codex" to "Codex", "gemini" to "Gemini", "antigravity" to "Antigravity")
        names.forEachIndexed { i, (key, title) ->
            val u = usage.optJSONObject(key)
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = if (i == 0) 0.dp else 14.dp)) {
                Text(title, color = Mc.Text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                u?.optDouble("at")?.takeIf { !it.isNaN() }?.let { Text("updated ${clock(it)}", color = Mc.Muted, fontSize = 12.sp) }
            }
            if (u == null) { Text("no data yet", color = Mc.Muted, fontSize = 13.sp); return@forEachIndexed }
            val wins = u.optJSONArray("windows").objects()
            wins.forEach { w ->
                val pct = w.optDouble("used_pct").takeIf { !it.isNaN() }
                val reset = w.optDouble("resets_at").takeIf { !it.isNaN() }
                val color = when { (pct ?: 0.0) >= 100 -> Mc.Bad; (pct ?: 0.0) >= 80 -> Mc.Warn; else -> Mc.Accent }
                Row(Modifier.padding(top = 8.dp)) {
                    Text(windowLabel(w), color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.weight(1f))
                    Text(listOfNotNull(pct?.let { "${it.toInt()}%" }, reset?.let { "resets ${backAt(it)}" }).joinToString(" · "),
                        color = if (color == Mc.Accent) Mc.Text else color, fontSize = 14.sp, fontFamily = FontFamily.Monospace)
                }
                if (pct != null) LinearProgressIndicator(progress = { (pct / 100).toFloat().coerceIn(0f, 1f) }, color = color,
                    trackColor = Mc.ButtonDark, modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(6.dp).clip(RoundedCornerShape(3.dp)))
            }
            if (key == "gemini") {
                Text("App jobs today ${u.optInt("app_jobs_today")} / ${u.optInt("app_jobs_max", 25)} · daily reset 09:00",
                    color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp))
                val keys = parked.keys().asSequence().filter { it.startsWith("gemini#") }.toList()
                if (keys.isNotEmpty()) Text("${keys.size} key(s) parked", color = Mc.Warn, fontSize = 13.sp)
            }
            if (key == "codex" && u.optInt("reset_credits") > 0) Text("${u.optInt("reset_credits")} usage resets available", color = Mc.Muted, fontSize = 13.sp)
            u.optString("error").takeIf { it.isNotBlank() }?.let { Text(it, color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp)) }
        }
    }
}

@Composable
private fun HubStatus(logs: JSONObject, handoff: String) {
    var open by remember { mutableStateOf(false) }
    McCard(onClick = { open = !open }) {
        Row { Label("Hub status"); Spacer(Modifier.weight(1f)); Text(if (open) "Hide" else "Show", color = Mc.Accent, fontSize = 13.sp) }
        if (!open) return@McCard
        logs.keys().forEach { name ->
            val l = logs.getJSONObject(name)
            Text(name, color = Mc.Text, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 10.dp))
            Text(l.optString("text").lines().takeLast(6).joinToString("\n"), color = Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
        }
        if (handoff.isNotBlank()) {
            Text("HANDOFF", color = Mc.Text, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 10.dp))
            Text(handoff.take(1500), color = Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
        }
    }
}

@Composable
private fun IdeaDock(audioMode: Boolean) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    var recorder by remember { mutableStateOf<MediaRecorder?>(null) }
    val audioFile = remember { File(ctx.cacheDir, "idea.m4a") }

    val speech = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        r.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let {
            text = if (text.isBlank()) it else "$text $it"
        }
    }
    val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (!ok) Toast.makeText(ctx, "Microphone permission is needed for audio ideas", Toast.LENGTH_LONG).show()
    }

    fun send(audio: ByteArray? = null) {
        val sent = text
        sending = true
        text = ""                       // the box empties and the toast shows at once; the text comes back if the Pi refuses
        Toast.makeText(ctx, "Sent to Claude's inbox", Toast.LENGTH_SHORT).show()
        scope.launch {
            try {
                withContext(Dispatchers.IO) {
                    if (audio != null) Api.bytes(ctx, "/api/ideas?text=" + java.net.URLEncoder.encode(sent, "UTF-8"), audio, "audio/mp4")
                    else Api.post(ctx, "/api/ideas", JSONObject().put("text", sent.trim()))
                }
            } catch (e: Exception) {
                if (text.isBlank()) text = sent
                Toast.makeText(ctx, "Not sent: ${e.message}", Toast.LENGTH_LONG).show()
            } finally { sending = false }
        }
    }

    fun mic() {
        if (!audioMode) {
            runCatching {
                speech.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    .putExtra(RecognizerIntent.EXTRA_PROMPT, "Idea for Claude"))
            }.onFailure { Toast.makeText(ctx, "No speech recognition on this phone", Toast.LENGTH_LONG).show() }
            return
        }
        if (ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            askMic.launch(Manifest.permission.RECORD_AUDIO); return
        }
        val r = recorder
        if (r == null) {
            recorder = (if (android.os.Build.VERSION.SDK_INT >= 31) MediaRecorder(ctx) else @Suppress("DEPRECATION") MediaRecorder()).apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioEncodingBitRate(64000)
                setOutputFile(audioFile.absolutePath)
                prepare(); start()
            }
        } else {
            runCatching { r.stop() }; r.release(); recorder = null
            send(audioFile.readBytes())
        }
    }

    Row(Modifier.fillMaxWidth().background(Mc.Bg).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(value = text, onValueChange = { text = it }, placeholder = { Text("Idea for Claude's inbox…") },
            maxLines = 4, shape = RoundedCornerShape(14.dp), modifier = Modifier.weight(1f))
        val recording = recorder != null
        IconButton(onClick = { mic() }, modifier = Modifier.size(50.dp).clip(RoundedCornerShape(14.dp))
            .background(if (recording) Mc.Bad else Mc.ButtonDark)) {
            Icon(MicIcon, contentDescription = if (recording) "Stop and send" else "Speak", tint = Mc.Text)
        }
        IconButton(onClick = { send() }, enabled = !sending && text.isNotBlank() && recorder == null,
            modifier = Modifier.size(50.dp).clip(RoundedCornerShape(14.dp)).background(Mc.Accent)) {
            Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send", tint = Color(0xFF04121C))
        }
    }
}
