package cz.filip.missioncontrol.ui

import android.graphics.BitmapFactory
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Settings
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.LifecycleResumeEffect
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Open to-dos, shown as a badge on the tab and on Home. Updated by Home's poll and by this screen. */
object TodoCount {
    var open by mutableIntStateOf(0)
}

private fun JSONArray?.objs(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).map { getJSONObject(it) }

private fun kindLabel(k: String) = when (k) {
    "test" -> "Test"; "bios" -> "BIOS"; "signin" -> "Sign-in"; "hardware" -> "Hardware"; "uninstall" -> "Uninstall"; else -> "Other"
}

private fun plainT(s: String) = s.replace("**", "").replace("`", "")

private fun agoT(t: Double): String {
    val s = (System.currentTimeMillis() / 1000 - t).toLong()
    return when { s < 90 -> "just now"; s < 3600 -> "${s / 60} min ago"; s < 86400 -> "${s / 3600} h ago"; else -> "${s / 86400} d ago" }
}

/** Where the answer got to, in words. null = nothing to say yet. */
private fun deliveryText(item: JSONObject): String? {
    val d = item.optJSONObject("delivery")
    if (item.optString("status") == "open") return null
    if (d == null) return "Sending to the PC…"
    return when (d.optString("state")) {
        "waiter" -> "Claude got it"
        "typed" -> "Typed into the Claude session"
        "inbox" -> "Saved to the Claude inbox (session not running)"
        "queued" -> "Sent to the PC"
        "mailbox" -> "In the session's mailbox"
        else -> d.optString("detail").ifBlank { "Waiting for the PC" }
    }
}

@Composable
fun TodoScreen(onSettings: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    var list by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var resumed by remember { mutableStateOf(false) }
    var inflight by remember { mutableIntStateOf(0) }       // taps whose call to the Pi has not finished
    val lock = remember { Mutex() }                          // calls go to the Pi in tap order

    LifecycleResumeEffect(Unit) {
        resumed = true
        onPauseOrDispose { resumed = false }
    }
    LaunchedEffect(resumed, reload, open) {
        if (open != null) return@LaunchedEffect
        while (resumed) {
            try {
                val d = withContext(Dispatchers.IO) { Api.get(ctx, "/api/todos") }
                if (inflight == 0) { list = d; TodoCount.open = d.optInt("open_count") }   // a poll must not undo an instant tap
                error = null
            } catch (e: ApiError) { if (e.code == 401) onLoggedOut() else error = e.message }
            delay(8000)
        }
    }
    BackHandler(enabled = open != null) { open = null; reload++ }

    /** Queues a call to the Pi behind earlier taps; on failure says why and reloads the truth. */
    fun send(path: String, body: JSONObject = JSONObject()) {
        inflight++
        scope.launch {
            var failed = false
            try { lock.withLock { withContext(Dispatchers.IO) { Api.post(ctx, path, body) } } }
            catch (e: ApiError) { failed = true; Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show() }
            finally { inflight-- }
            if (failed || inflight == 0) reload++
        }
    }

    /** The item moves to the done list on screen at once. */
    fun markClosed(id: String, status: String) {
        val cur = list ?: return
        val copy = JSONObject(cur.toString())
        val opens = copy.optJSONArray("open").objs()
        val item = opens.firstOrNull { it.optString("id") == id } ?: return
        val newOpen = JSONArray().also { a -> opens.filter { it !== item }.forEach { a.put(it) } }
        item.put("status", status).put("summary", if (status == "done") "Done" else "Can't do it")
            .put("closed_at", System.currentTimeMillis() / 1000.0).put("delivery", JSONObject.NULL)
        val newDone = JSONArray().also { a -> a.put(item); copy.optJSONArray("done").objs().forEach { a.put(it) } }
        copy.put("open", newOpen).put("done", newDone).put("open_count", newOpen.length())
        list = copy
        TodoCount.open = newOpen.length()
    }

    open?.let { id ->
        TodoDetail(id, onBack = { open = null; reload++ }, send = { p, b -> send(p, b) },
            onClosed = { status -> markClosed(id, status); open = null }, modifier = modifier)
        return
    }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 22.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            Box(Modifier.weight(1f)) { Header("To-do") }
            IconButton(onClick = onSettings, modifier = Modifier.padding(bottom = 2.dp)) { Icon(Icons.Filled.Settings, "Settings", tint = Mc.Muted) }
        }
        error?.let { McCard { Text(it, color = Mc.Bad) } }
        val l = list ?: run { if (error == null) Text("Loading…", color = Mc.Muted); return@Column }
        val opens = l.optJSONArray("open").objs()
        val dones = l.optJSONArray("done").objs()
        if (opens.isEmpty()) McCard {
            Label("Nothing to do")
            Text("Claude puts steps only you can do here (phone tests, BIOS, sign-ins, hardware).", color = Mc.Muted, fontSize = 14.sp,
                modifier = Modifier.padding(top = 4.dp))
        }
        opens.forEach { t ->
            McCard(onClick = { open = t.getString("id") }) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Chip(kindLabel(t.optString("kind")), Mc.Accent)
                    if (t.optString("checklist").isNotBlank() && t.optString("checklist") != "null") { Spacer(Modifier.width(6.dp)); Chip("Checklist", Mc.Warn) }
                    Spacer(Modifier.weight(1f))
                    Text(agoT(t.optDouble("created")), color = Mc.Muted, fontSize = 13.sp)
                }
                Text(t.optString("title"), color = Mc.Text, fontSize = 20.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(top = 8.dp), maxLines = 3, overflow = TextOverflow.Ellipsis)
                val from = listOf(t.optString("project"), t.optString("session")).filter { it.isNotBlank() }.joinToString(" · ")
                if (from.isNotBlank()) Text(from, color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(top = 4.dp), maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        if (dones.isNotEmpty()) {
            Label("Done recently")
            dones.forEachIndexed { i, t ->
                Column(Modifier.fillMaxWidth().clickable { open = t.getString("id") }.padding(vertical = 10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(t.optString("title"), color = Mc.Muted, fontSize = 16.sp, modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Spacer(Modifier.width(8.dp))
                        val cant = t.optString("status") == "cant"
                        Text(t.optString("summary").ifBlank { if (cant) "Can't do it" else "Done" }, color = if (cant) Mc.Warn else Mc.Good, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                    }
                    deliveryText(t)?.let { Text(it, color = Mc.Idle, fontSize = 12.sp, modifier = Modifier.padding(top = 2.dp)) }
                }
                if (i < dones.size - 1) HorizontalDivider(color = Mc.Border)
            }
        }
    }
}

@Composable
private fun Chip(text: String, color: Color) =
    Text(text, color = color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(Mc.ButtonDark).padding(horizontal = 10.dp, vertical = 4.dp))

@Composable
private fun TodoDetail(id: String, onBack: () -> Unit, send: (String, JSONObject) -> Unit, onClosed: (String) -> Unit, modifier: Modifier) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var d by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var tick by remember { mutableIntStateOf(0) }
    var checklist by rememberSaveable { mutableStateOf(false) }
    var photoDialog by remember { mutableStateOf(false) }
    var viewPhoto by remember { mutableStateOf<String?>(null) }
    var closing by remember { mutableStateOf(false) }
    var note by rememberSaveable(id) { mutableStateOf<String?>(null) }

    LaunchedEffect(tick) {
        try {
            val r = withContext(Dispatchers.IO) { Api.get(ctx, "/api/todos/$id") }
            d = r; error = null
            if (note == null) note = r.optString("note")
        } catch (e: ApiError) { error = e.message }
    }

    if (checklist) {
        val slug = d?.optString("checklist").orEmpty()
        BackHandler { checklist = false; tick++ }
        DocDetailScreen(slug, onBack = { checklist = false; tick++ }, modifier = modifier)
        return
    }

    val item = d
    val isOpen = item?.optString("status") == "open"
    // Typed notes are kept on the Pi while the item is open (the Done / Can't call carries the final text too).
    LaunchedEffect(note) {
        val n = note ?: return@LaunchedEffect
        if (isOpen && n != item?.optString("note")) { delay(900); send("/api/todos/$id/note", JSONObject().put("note", n)) }
    }

    val camFile = remember { File(ctx.cacheDir, "shot.jpg") }
    fun upload(uri: Uri) {
        photoDialog = false
        Toast.makeText(ctx, "Adding photo…", Toast.LENGTH_SHORT).show()
        scope.launch {
            try { withContext(Dispatchers.IO) { Api.bytes(ctx, "/api/todos/$id/photo", shrinkJpeg(ctx, uri), "image/jpeg") }; tick++ }
            catch (e: Exception) { Toast.makeText(ctx, e.message ?: "Could not add the photo", Toast.LENGTH_LONG).show() }
        }
    }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { it?.let(::upload) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        if (ok) upload(FileProvider.getUriForFile(ctx, ctx.packageName + ".files", camFile))
    }

    Column(modifier.fillMaxSize().imePadding()) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp, top = 12.dp, end = 16.dp)) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Mc.Text) }
            Text(item?.optString("title") ?: "…", color = Mc.Text, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, maxLines = 3,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        }
        error?.let { Text(it, color = Mc.Bad, modifier = Modifier.padding(16.dp)) }
        val t = item ?: return@Column
        val hasChecklist = t.optString("checklist").isNotBlank() && t.optString("checklist") != "null"
        val photos = t.optJSONArray("photos")?.let { a -> (0 until a.length()).map(a::getString) } ?: emptyList()
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Chip(kindLabel(t.optString("kind")), Mc.Accent)
                val from = listOf(t.optString("project"), t.optJSONObject("session")?.optString("title").orEmpty()).filter { it.isNotBlank() }.joinToString(" · ")
                if (from.isNotBlank()) Text(from, color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(start = 10.dp), maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (!isOpen) McCard {
                val cant = t.optString("status") == "cant"
                Text(t.optString("summary").ifBlank { if (cant) "Can't do it" else "Done" }, color = if (cant) Mc.Warn else Mc.Good, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
                deliveryText(t)?.let { Text(it, color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(top = 4.dp)) }
                if (t.isNull("delivery")) SmallBtn("Undo (back to open)") {
                    d = JSONObject(t.toString()).put("status", "open")
                    send("/api/todos/$id/reopen", JSONObject())
                }
            }
            McCard {
                Label("Steps")
                Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    t.optString("steps").lines().filter { it.isNotBlank() }.forEach { l ->
                        val m = Regex("^\\s*(\\d+)[.)]\\s+(.*)").find(l)
                        if (m != null) Row {
                            Text(m.groupValues[1], color = Mc.Accent, fontSize = 16.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.width(30.dp))
                            Text(plainT(m.groupValues[2]), color = Mc.Text, fontSize = 17.sp, modifier = Modifier.weight(1f))
                        } else Text(plainT(l.replace(Regex("^\\s*[-*] "), "•  ")), color = Mc.Muted, fontSize = 15.sp)
                    }
                }
            }
            if (hasChecklist) Button(onClick = { checklist = true }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Text),
                modifier = Modifier.fillMaxWidth().height(50.dp)) { Text("Open the checklist", fontSize = 16.sp) }
            if (photos.isNotEmpty()) Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                photos.forEach { f -> Box(Modifier.size(96.dp).clip(RoundedCornerShape(10.dp)).clickable { viewPhoto = f }) { TodoPhoto(id, f, fill = true) } }
            }
            if (isOpen) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { SmallBtn(if (photos.isEmpty()) "+ Photo" else "+ Another photo") { photoDialog = true } }
                OutlinedTextField(value = note ?: "", onValueChange = { note = it }, placeholder = { Text("Note (what happened?)") },
                    modifier = Modifier.fillMaxWidth(), minLines = 1, maxLines = 6)
            } else if (!t.optString("note").isNullOrBlank()) McCard { Label("Your note"); Text(t.optString("note"), color = Mc.Text, fontSize = 15.sp, modifier = Modifier.padding(top = 4.dp)) }
        }
        if (isOpen) Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(enabled = !closing, onClick = {
                closing = true
                send("/api/todos/$id/result", JSONObject().put("status", "cant").put("note", note ?: ""))
                onClosed("cant")
            }, shape = RoundedCornerShape(14.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Mc.Warn),
                colors = ButtonDefaults.outlinedButtonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Warn),
                modifier = Modifier.weight(1f).height(54.dp)) { Text("Can't do it", fontSize = 16.sp) }
            Button(enabled = !closing, onClick = {
                closing = true
                send("/api/todos/$id/result", JSONObject().put("status", "done").put("note", note ?: ""))
                onClosed("done")
            }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C)),
                modifier = Modifier.weight(1f).height(54.dp)) { Text("Done", fontSize = 17.sp, fontWeight = FontWeight.SemiBold) }
        }
    }

    if (photoDialog) AlertDialog(onDismissRequest = { photoDialog = false }, containerColor = Mc.Card, title = { Text("Add a photo") },
        confirmButton = { TextButton(onClick = { camera.launch(FileProvider.getUriForFile(ctx, ctx.packageName + ".files", camFile)) }) { Text("Camera") } },
        dismissButton = { TextButton(onClick = { gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }) { Text("Gallery") } })
    viewPhoto?.let { f ->
        AlertDialog(onDismissRequest = { viewPhoto = null }, containerColor = Mc.Card,
            confirmButton = { TextButton(onClick = { viewPhoto = null }) { Text("Close") } },
            text = { Column(Modifier.verticalScroll(rememberScrollState())) { TodoPhoto(id, f, fill = false) } })
    }
}

@Composable
private fun TodoPhoto(id: String, file: String, fill: Boolean) {
    val ctx = LocalContext.current
    val img by produceState<ImageBitmap?>(null, file) {
        value = withContext(Dispatchers.IO) { runCatching { Api.bytes(ctx, "/api/todos/$id/photo/$file").let { BitmapFactory.decodeByteArray(it, 0, it.size).asImageBitmap() } }.getOrNull() }
    }
    val m = if (fill) Modifier.fillMaxSize() else Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
    img?.let { Image(it, null, contentScale = if (fill) ContentScale.Crop else ContentScale.FillWidth, modifier = m) }
        ?: Text("…", color = Mc.Muted)
}

@Composable
private fun SmallBtn(text: String, onClick: () -> Unit) =
    OutlinedButton(onClick = onClick, shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Mc.Border),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Text)) { Text(text, fontSize = 14.sp) }
