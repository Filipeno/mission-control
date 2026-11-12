package cz.filip.missioncontrol.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
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
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File

private fun JSONArray?.objs(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).map { getJSONObject(it) }

/** Markdown marks that would show raw: **bold**, `code`. */
private fun plain(s: String) = s.replace("**", "").replace("`", "")

private fun ago(t: Double): String {
    val s = (System.currentTimeMillis() / 1000 - t).toLong()
    return when { s < 90 -> "just now"; s < 3600 -> "${s / 60} min ago"; s < 86400 -> "${s / 3600} h ago"; else -> "${s / 86400} d ago" }
}

@Composable
fun DocsScreen(onSettings: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    var list by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }

    LaunchedEffect(reload, open) {
        if (open != null) return@LaunchedEffect
        try { list = withContext(Dispatchers.IO) { Api.get(ctx, "/api/docs") }; error = null }
        catch (e: ApiError) { if (e.code == 401) onLoggedOut() else error = e.message }
    }
    BackHandler(enabled = open != null) { open = null; reload++ }

    open?.let { slug ->
        DocDetail(slug, onBack = { open = null; reload++ }, modifier = modifier)
        return
    }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 22.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            Box(Modifier.weight(1f)) { Header("Docs") }
            Text("On the Pi", color = Mc.Good, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(bottom = 8.dp).clip(RoundedCornerShape(50)).background(Mc.GoodBg).padding(horizontal = 12.dp, vertical = 6.dp))
            IconButton(onClick = onSettings, modifier = Modifier.padding(bottom = 2.dp)) { Icon(Icons.Filled.Settings, "Settings", tint = Mc.Muted) }
        }
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).border(1.dp, Mc.Border, RoundedCornerShape(16.dp)).background(Mc.Card).padding(5.dp)) {
            listOf("Checklists", "Docs").forEachIndexed { i, t ->
                Box(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).background(if (tab == i) Mc.ButtonDark else Color.Transparent)
                    .clickable { tab = i }.padding(vertical = 12.dp), contentAlignment = Alignment.Center) {
                    Text(t, color = if (tab == i) Mc.Text else Mc.Muted, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                }
            }
        }
        error?.let { McCard { Text(it, color = Mc.Bad) } }
        val l = list ?: return@Column
        if (tab == 0) {
            val cl = l.optJSONArray("checklists").objs()
            if (cl.isEmpty()) Text("No checklists yet. Claude sends them through D:\\ai-hub\\to-phone\\checklists.", color = Mc.Muted, fontSize = 14.sp)
            cl.forEach { c ->
                McCard(onClick = { open = c.getString("slug") }) {
                    Label(c.optString("title"))
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
                        Text("${c.optInt("done")} of ${c.optInt("total")} done", color = Mc.Text, fontSize = 24.sp,
                            fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        if (c.optInt("failed") > 0) Text("${c.optInt("failed")} failed", color = Mc.Warn, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.clip(RoundedCornerShape(50)).background(Color(0xFF2A2210)).padding(horizontal = 10.dp, vertical = 5.dp))
                        else if (!c.isNull("finished_at")) Text("finished", color = Mc.Good, fontSize = 13.sp)
                    }
                    Progress(c.optInt("done"), c.optInt("total"))
                }
            }
        } else {
            val docs = l.optJSONArray("docs").objs()
            if (docs.isEmpty()) Text("No docs yet. Claude sends them through D:\\ai-hub\\to-phone\\docs.", color = Mc.Muted, fontSize = 14.sp)
            docs.forEachIndexed { i, d ->
                Row(Modifier.fillMaxWidth().clickable { open = d.getString("slug") }.padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.List, null, tint = Mc.Text, modifier = Modifier.size(26.dp))
                    Spacer(Modifier.width(16.dp))
                    Column {
                        Text(d.optString("title"), color = Mc.Text, fontSize = 17.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        val oc = d.optInt("open_comments")
                        Text(if (oc > 0) "$oc open comment${if (oc > 1) "s" else ""}" else "Edited by ${d.optString("by")} · ${ago(d.optDouble("updated"))}",
                            color = Mc.Muted, fontSize = 14.sp)
                    }
                }
                if (i < docs.size - 1) HorizontalDivider(color = Mc.Border)
            }
        }
    }
}

@Composable
private fun Progress(done: Int, total: Int) =
    LinearProgressIndicator(progress = { if (total == 0) 0f else done.toFloat() / total }, color = Mc.Accent, trackColor = Mc.ButtonDark,
        modifier = Modifier.fillMaxWidth().padding(top = 10.dp).height(8.dp).clip(RoundedCornerShape(4.dp)))

@Composable
private fun DocDetail(slug: String, onBack: () -> Unit, modifier: Modifier) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var d by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var tick by remember { mutableIntStateOf(0) }
    LaunchedEffect(tick) {
        try { d = withContext(Dispatchers.IO) { Api.get(ctx, "/api/docs/$slug") }; error = null } catch (e: ApiError) { error = e.message }
    }
    fun post(path: String, body: JSONObject = JSONObject(), ok: String? = null) = scope.launch {
        try {
            withContext(Dispatchers.IO) { Api.post(ctx, "/api/docs/$slug$path", body) }
            ok?.let { Toast.makeText(ctx, it, Toast.LENGTH_SHORT).show() }
            tick++
        } catch (e: ApiError) { Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show() }
    }

    Column(modifier.fillMaxSize().imePadding()) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp, top = 12.dp, end = 16.dp)) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Mc.Text) }
            Text(d?.optString("title") ?: "…", color = Mc.Text, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, maxLines = 2,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        }
        error?.let { Text(it, color = Mc.Bad, modifier = Modifier.padding(16.dp)) }
        val doc = d ?: return@Column
        if (doc.optString("kind") == "checklist") Checklist(slug, doc, ::post) { tick++ }
        else DocText(slug, doc, ::post)
    }
}

private fun shrinkJpeg(ctx: Context, uri: Uri): ByteArray {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    ctx.contentResolver.openInputStream(uri).use { BitmapFactory.decodeStream(it, null, bounds) }
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= 1600) sample *= 2
    val bmp = ctx.contentResolver.openInputStream(uri).use { BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample }) }
        ?: throw IllegalArgumentException("Not a picture")
    val scale = minOf(1f, 1600f / maxOf(bmp.width, bmp.height))
    val out = if (scale < 1f) Bitmap.createScaledBitmap(bmp, (bmp.width * scale).toInt(), (bmp.height * scale).toInt(), true) else bmp
    return ByteArrayOutputStream().also { out.compress(Bitmap.CompressFormat.JPEG, 85, it) }.toByteArray()
}

@Composable
private fun Checklist(slug: String, doc: JSONObject, post: (String, JSONObject, String?) -> Any, refresh: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val blocks = doc.optJSONArray("blocks").objs()
    val items = doc.optJSONObject("items") ?: JSONObject()
    val comments = doc.optJSONArray("comments").objs()
    val total = blocks.count { it.optString("t") == "item" }
    val done = blocks.count { it.optString("t") == "item" && items.optJSONObject(it.optInt("id").toString())?.optString("status") in setOf("pass", "fail", "skip") }
    val failed = blocks.count { it.optString("t") == "item" && items.optJSONObject(it.optInt("id").toString())?.optString("status") == "fail" }
    var shotFor by remember { mutableStateOf<Int?>(null) }
    var commentsFor by remember { mutableStateOf<Int?>(null) }
    var viewShots by remember { mutableStateOf<List<String>?>(null) }
    val camFile = remember { File(ctx.cacheDir, "shot.jpg") }

    fun upload(uri: Uri) {
        val id = shotFor ?: return
        scope.launch {
            try {
                withContext(Dispatchers.IO) { Api.bytes(ctx, "/api/docs/$slug/item/$id/shot", shrinkJpeg(ctx, uri), "image/jpeg") }
                Toast.makeText(ctx, "Screenshot added", Toast.LENGTH_SHORT).show(); refresh()
            } catch (e: Exception) { Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show() }
        }
    }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { it?.let(::upload) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        if (ok) upload(FileProvider.getUriForFile(ctx, ctx.packageName + ".files", camFile))
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        McCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("$done of $total done", color = Mc.Text, fontSize = 26.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                if (failed > 0) Text("$failed failed", color = Mc.Warn, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }
            Progress(done, total)
        }
        blocks.forEach { b ->
            when (b.optString("t")) {
                "h" -> Text(plain(b.optString("text")), color = Mc.Text, fontSize = if (b.optInt("level") <= 2) 19.sp else 16.sp,
                    fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 10.dp))
                "p" -> Text(plain(b.optString("text")), color = Mc.Muted, fontSize = 14.sp)
                else -> {
                    val id = b.optInt("id")
                    val it = items.optJSONObject(id.toString()) ?: JSONObject()
                    ItemRow(id, plain(b.optString("text")), it, comments.count { c -> c.optInt("item", -1) == id },
                        setStatus = { s -> post("/item/$id", JSONObject().put("status", if (s == it.optString("status")) "" else s), null) },
                        saveNote = { n -> post("/item/$id", JSONObject().put("note", n), null) },
                        onShot = { shotFor = id }, onShots = { viewShots = it.optJSONArray("shots")?.let { a -> (0 until a.length()).map(a::getString) } },
                        onComments = { commentsFor = id })
                }
            }
        }
        Button(onClick = { post("/finish", JSONObject(), "Sent to Claude") }, shape = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C)),
            modifier = Modifier.fillMaxWidth().padding(vertical = 14.dp).height(52.dp)) { Text("Finish and send to Claude", fontSize = 16.sp) }
    }

    shotFor?.let {
        AlertDialog(onDismissRequest = { shotFor = null }, containerColor = Mc.Card, title = { Text("Add a screenshot") },
            confirmButton = {
                TextButton(onClick = { camera.launch(FileProvider.getUriForFile(ctx, ctx.packageName + ".files", camFile)) }) { Text("Camera") }
            },
            dismissButton = {
                TextButton(onClick = { gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }) { Text("Gallery") }
            })
    }
    viewShots?.let { files ->
        AlertDialog(onDismissRequest = { viewShots = null }, containerColor = Mc.Card,
            confirmButton = { TextButton(onClick = { viewShots = null }) { Text("Close") } },
            text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                files.forEach { f -> ShotImage(slug, f) } } })
    }
    commentsFor?.let { id ->
        CommentsDialog(comments.filter { it.optInt("item", -1) == id }, onDismiss = { commentsFor = null },
            onAdd = { t -> post("/comment", JSONObject().put("text", t).put("item", id), null) },
            onResolve = { c -> post("/comment/$c/resolve", JSONObject(), null) })
    }
}

@Composable
private fun ShotImage(slug: String, file: String) {
    val ctx = LocalContext.current
    val img by produceState<ImageBitmap?>(null, file) {
        value = withContext(Dispatchers.IO) { runCatching { Api.bytes(ctx, "/api/docs/$slug/shot/$file").let { BitmapFactory.decodeByteArray(it, 0, it.size).asImageBitmap() } }.getOrNull() }
    }
    img?.let { Image(it, null, contentScale = ContentScale.FillWidth, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))) }
        ?: Text("Loading…", color = Mc.Muted)
}

@Composable
private fun ItemRow(id: Int, text: String, it: JSONObject, nComments: Int, setStatus: (String) -> Unit, saveNote: (String) -> Unit,
                    onShot: () -> Unit, onShots: () -> Unit, onComments: () -> Unit) {
    val status = it.optString("status").takeIf { s -> s != "null" } ?: ""
    var note by remember(id, it.optString("note")) { mutableStateOf(it.optString("note")) }
    var noteOpen by remember(id) { mutableStateOf(false) }
    LaunchedEffect(note) {
        if (note != it.optString("note")) { delay(900); saveNote(note) }
    }
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row {
            Text("${id + 1}", color = Mc.Muted, fontSize = 15.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.width(34.dp))
            Text(text, color = Mc.Text, fontSize = 16.sp, modifier = Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
            for ((s, label, fg, bg) in listOf(Quad("pass", "Pass", Mc.Good, Color(0xFF0F2A1F)), Quad("fail", "Fail", Mc.Bad, Color(0xFF2A1215)),
                Quad("skip", "Skip", Mc.Text, Color(0xFF232B38)))) {
                val on = status == s
                OutlinedButton(onClick = { setStatus(s); if (s == "fail" && !on) noteOpen = true }, modifier = Modifier.weight(1f).height(46.dp),
                    shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, if (on) fg else Mc.Border),
                    colors = ButtonDefaults.outlinedButtonColors(containerColor = if (on) bg else Mc.ButtonDark, contentColor = if (on) fg else Mc.Text)) {
                    Text(label, fontWeight = FontWeight.SemiBold)
                }
            }
        }
        if (noteOpen || note.isNotBlank() || status == "fail") {
            OutlinedTextField(value = note, onValueChange = { v -> note = v }, placeholder = { Text("Note (what went wrong?)") },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp), minLines = 1, maxLines = 5)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
            val nShots = it.optJSONArray("shots")?.length() ?: 0
            SmallButton(if (nShots > 0) "$nShots screenshot${if (nShots > 1) "s" else ""}" else "+ Screenshot") { if (nShots > 0) onShots() else onShot() }
            if (nShots > 0) SmallButton("+") { onShot() }
            SmallButton(if (nComments > 0) "$nComments comment${if (nComments > 1) "s" else ""}" else "Comment", onComments)
            if (!noteOpen && note.isBlank() && status != "fail") SmallButton("Note") { noteOpen = true }
        }
        HorizontalDivider(color = Mc.Border, modifier = Modifier.padding(top = 10.dp))
    }
}

private data class Quad(val a: String, val b: String, val c: Color, val d: Color)

@Composable
private fun SmallButton(text: String, onClick: () -> Unit) =
    OutlinedButton(onClick = onClick, shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Mc.Border),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Text)) { Text(text, fontSize = 14.sp) }

@Composable
private fun CommentsDialog(list: List<JSONObject>, onDismiss: () -> Unit, onAdd: (String) -> Unit, onResolve: (String) -> Unit, title: String = "Comments") {
    var text by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss, containerColor = Mc.Card, title = { Text(title) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                list.forEach { c ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(c.optString("text"), color = if (c.optBoolean("resolved")) Mc.Muted else Mc.Text, fontSize = 14.sp, modifier = Modifier.weight(1f))
                        if (!c.optBoolean("resolved")) TextButton(onClick = { onResolve(c.optString("id")) }) { Text("Done") }
                    }
                }
                OutlinedTextField(value = text, onValueChange = { text = it }, placeholder = { Text("Add a comment") }, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = { TextButton(enabled = text.isNotBlank(), onClick = { onAdd(text.trim()); text = "" }) { Text("Add") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Close") } })
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun DocText(slug: String, doc: JSONObject, post: (String, JSONObject, String?) -> Any) {
    val text = doc.optString("text")
    val lines = text.lines()
    val comments = doc.optJSONArray("comments").objs()
    var editing by remember { mutableStateOf(false) }
    var draft by remember(text) { mutableStateOf(text) }
    var lineFor by remember { mutableStateOf<Int?>(null) }

    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
        if (editing) {
            SmallButton("Save") { post("/text", JSONObject().put("text", draft), "Saved"); editing = false }
            SmallButton("Cancel") { draft = text; editing = false }
        } else {
            SmallButton("Edit") { editing = true }
            SmallButton("Send to Claude") { post("/send", JSONObject(), "Sent to Claude") }
        }
    }
    if (editing) {
        OutlinedTextField(value = draft, onValueChange = { draft = it }, textStyle = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.Monospace, fontSize = 13.sp, color = Mc.Text),
            modifier = Modifier.fillMaxSize().padding(16.dp))
        return
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text("Long-press a line to comment on it.", color = Mc.Muted, fontSize = 12.sp, modifier = Modifier.padding(bottom = 8.dp))
        lines.forEachIndexed { i, l ->
            val h = Regex("^(#{1,6})\\s+(.*)").find(l)
            val shown = h?.groupValues?.get(2) ?: l.replace(Regex("^\\s*[-*] "), "•  ").replace("**", "")
            Text(shown.ifEmpty { " " }, color = Mc.Text,
                fontSize = when (h?.groupValues?.get(1)?.length) { 1 -> 22.sp; 2 -> 19.sp; null -> 15.sp; else -> 16.sp },
                fontWeight = if (h != null) FontWeight.SemiBold else FontWeight.Normal,
                modifier = Modifier.fillMaxWidth().combinedClickable(onClick = {}, onLongClick = { lineFor = i }).padding(vertical = 2.dp))
            comments.filter { it.optInt("line", -1) == i && !it.optBoolean("resolved") }.forEach { c ->
                Text("💬 ${c.optString("text")}", color = Mc.Warn, fontSize = 13.sp,
                    modifier = Modifier.padding(start = 12.dp, bottom = 4.dp).clickable { lineFor = i })
            }
        }
    }
    lineFor?.let { i ->
        CommentsDialog(comments.filter { it.optInt("line", -1) == i }, onDismiss = { lineFor = null }, title = "Line ${i + 1}",
            onAdd = { t -> post("/comment", JSONObject().put("text", t).put("line", i), null) },
            onResolve = { c -> post("/comment/$c/resolve", JSONObject(), null) })
    }
}
