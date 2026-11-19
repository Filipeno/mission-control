package cz.filip.missioncontrol.ui

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import cz.filip.missioncontrol.data.Api
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

private fun JSONArray?.objsD(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }

/** One line about who owns a doc and whether that session runs: where "Send to session" will go. */
@Composable
internal fun OwnerLine(owner: JSONObject?) {
    val title = owner?.optString("title").orEmpty().ifBlank { "a Claude session" }
    val (text, color) = when (owner?.optString("state")) {
        "running" -> {
            val busy = owner.optString("busy")
            ("Owner: $title · " + when (busy) { "working" -> "working"; "waiting" -> "needs you"; else -> "idle" } +
                if (owner.optBoolean("by_folder")) " (found by folder)" else "") to Mc.Good
        }
        "unknown" -> "Owner: $title · the PC is not reporting right now" to Mc.Muted
        "ended" -> "Owner: $title · that session has ended" to Mc.Warn
        else -> "No Claude session owns this file" to Mc.Warn
    }
    Text(text, color = color, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
}

/** Can comments go to the owner directly (it runs, or the PC just is not reporting)? Otherwise the phone offers to start a session. */
internal fun ownerReachable(owner: JSONObject?): Boolean = owner?.optString("state") in setOf("running", "unknown")

private fun oneLine(s: String) = s.replace(Regex("\\s+"), " ").trim()

/** Comments not resolved and not sent yet, in document order: (text, ids). Same format the Pi uses: Line 12 ("quoted line"): comment. */
internal fun unsentFeedback(doc: JSONObject): Pair<String, List<String>> {
    val lines = doc.optString("text").lines()
    val open = doc.optJSONArray("comments").objsD().filter { !it.optBoolean("resolved") && it.optDouble("sent", 0.0) == 0.0 }
        .sortedWith(compareBy({ if (it.has("line")) it.optInt("line") else Int.MAX_VALUE }, { it.optDouble("at", 0.0) }))
    val out = open.map { c ->
        if (c.has("line")) {
            val i = c.optInt("line")
            val q = if (i in lines.indices) oneLine(lines[i]).take(90) else ""
            "Line ${i + 1}" + (if (q.isNotEmpty()) " (\"$q\")" else "") + ": ${c.optString("text")}"
        } else if (c.has("item")) "Item ${c.optInt("item") + 1}: ${c.optString("text")}" else "General: ${c.optString("text")}"
    }
    return out.joinToString("\n") to open.map { it.optString("id") }
}

/** The bottom bar of a plan: Approve / Reject (fingerprint, through the gate answer path), or a hint when nothing waits for him. */
@Composable
internal fun PlanBar(slug: String, doc: JSONObject, modifier: Modifier = Modifier, onChanged: () -> Unit) {
    val ctx = LocalContext.current
    val gate = doc.optJSONObject("gate")
    val gid = gate?.optString("id").orEmpty()
    var answered by remember(gid) { mutableStateOf(false) }          // tapped here: the bar goes away at once
    var busy by remember(gid) { mutableStateOf(false) }
    var askApprove by remember(gid) { mutableStateOf(false) }
    var reject by remember(gid) { mutableStateOf<String?>(null) }
    val (feedback, ids) = remember(doc.toString()) { unsentFeedback(doc) }
    val title = doc.optString("title")

    fun send(decision: String, payload: String, label: String, markSent: List<String>) {
        busy = true
        signedPostEx(ctx, label, "gate|$gid|$decision|$payload", "/api/gate/$gid/answer",
            JSONObject().put("decision", decision).put("payload", payload), true, tier = gateTier(gate, decision, payload),
            onSigned = {
                busy = false; answered = true
                Toast.makeText(ctx, if (decision == "allow") "Plan approved: sent to the PC" else "Changes sent to the PC", Toast.LENGTH_SHORT).show()
                if (markSent.isNotEmpty()) kotlin.concurrent.thread {
                    runCatching { Api.post(ctx, "/api/docs/$slug/sent", JSONObject().put("ids", JSONArray(markSent))) }
                }
            }) { err ->
            busy = false
            if (err != null) { answered = false; Toast.makeText(ctx, "Not sent: $err", Toast.LENGTH_LONG).show() }
            onChanged()
        }
    }
    fun rejectWith(note: String) {
        val head = "Filip wants changes to the plan. Revise the plan file and call ExitPlanMode again."
        val body = listOf(note.trim(), feedback).filter { it.isNotBlank() }.joinToString("\n\n")
        send("deny", (head + "\n\n" + body).take(5500), "Reject plan: $title".take(60), ids)
    }

    Column(modifier.fillMaxWidth().background(Mc.Nav).border(1.dp, Mc.Border).padding(horizontal = 14.dp, vertical = 10.dp)) {
        if (gate == null || answered) {
            Text(if (answered) "Answer sent. It reaches the session in a moment." else "Claude is not asking for approval of this plan right now.",
                color = Mc.Muted, fontSize = 13.sp)
            return@Column
        }
        Text(if (ids.isEmpty()) "Waiting for your decision" else "Waiting for your decision · ${ids.size} open comment${if (ids.size > 1) "s" else ""}",
            color = Mc.Warn, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(bottom = 8.dp))
        if (busy) Text("Waiting for fingerprint…", color = Mc.Muted, fontSize = 14.sp)
        else Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton("Approve", Modifier.weight(1.4f)) {
                if (ids.isNotEmpty()) askApprove = true else send("allow", "", "Approve plan: $title".take(60), emptyList())
            }
            DarkBtn("Reject", Modifier.weight(1f), outlined = true) { reject = "" }
        }
    }
    if (askApprove) AlertDialog(onDismissRequest = { askApprove = false }, containerColor = Mc.Card,
        title = { Text("Send the comments as changes instead?") },
        text = { Text("You have ${ids.size} open comment${if (ids.size > 1) "s" else ""} on this plan. Approving takes the plan as it is and the comments are not sent.") },
        confirmButton = { TextButton(onClick = { askApprove = false; rejectWith("") }) { Text("Send as changes") } },
        dismissButton = {
            Row {
                TextButton(onClick = { askApprove = false; send("allow", "", "Approve plan: $title".take(60), emptyList()) }) { Text("Approve anyway") }
                TextButton(onClick = { askApprove = false }) { Text("Cancel") }
            }
        })
    reject?.let { note ->
        AlertDialog(onDismissRequest = { reject = null }, containerColor = Mc.Card, title = { Text("Reject the plan") },
            text = {
                Column {
                    Text(if (ids.isEmpty()) "Tell Claude what to change." else "Your ${ids.size} open comment${if (ids.size > 1) "s" else ""} go with it as the changes. You can add a note.",
                        color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(bottom = 8.dp))
                    OutlinedTextField(value = note, onValueChange = { reject = it }, minLines = 3, modifier = Modifier.fillMaxWidth())
                }
            },
            confirmButton = { TextButton(enabled = note.isNotBlank() || ids.isNotEmpty(), onClick = { reject = null; rejectWith(note) }) { Text("Reject") } },
            dismissButton = { TextButton(onClick = { reject = null }) { Text("Cancel") } })
    }
}

/** "No session owns it": hands the comments to the boss session, which starts a session for them. Fingerprint. */
@Composable
internal fun StartSessionDialog(slug: String, doc: JSONObject, onClose: (started: Boolean) -> Unit) {
    val ctx = LocalContext.current
    val owner = doc.optJSONObject("owner")
    var folder by remember { mutableStateOf(owner?.optString("cwd").orEmpty().ifBlank { "D:\\projekty" }) }
    var busy by remember { mutableStateOf(false) }
    val n = doc.optInt("unsent")
    AlertDialog(onDismissRequest = { if (!busy) onClose(false) }, containerColor = Mc.Card, title = { Text("Start a session for this file") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("No running Claude session owns this file. Your main Claude session is asked (typed into it, as you) to start one with " +
                    "your $n comment${if (n != 1) "s" else ""} as the brief. The PC must be unlocked.", color = Mc.Muted, fontSize = 14.sp)
                OutlinedTextField(value = folder, onValueChange = { folder = it }, label = { Text("Folder for the new session") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            TextButton(enabled = !busy && n > 0 && folder.isNotBlank(), onClick = {
                busy = true
                signedPostEx(ctx, "Start a session: ${doc.optString("title")}".take(60), "docstart|$slug", "/api/docs/$slug/start-session",
                    JSONObject().put("folder", folder.trim()), true, onSigned = {}, tier = "M") { err ->
                    busy = false
                    if (err != null) Toast.makeText(ctx, "Not sent: $err", Toast.LENGTH_LONG).show()
                    else { Toast.makeText(ctx, "Asked your main session to start it", Toast.LENGTH_LONG).show(); onClose(true) }
                }
            }) { Text(if (busy) "Waiting…" else "Start (fingerprint)") }
        },
        dismissButton = { TextButton(enabled = !busy, onClick = { onClose(false) }) { Text("Cancel") } })
}

/** A school output's PDF, drawn with Android's own PdfRenderer (no library), plus "open in another app". */
@Composable
internal fun PdfViewer(slug: String, title: String, onBack: () -> Unit) {
    val ctx = LocalContext.current
    var file by remember { mutableStateOf<File?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(slug) {
        try {
            file = withContext(Dispatchers.IO) { File(ctx.cacheDir, "doc-$slug.pdf").also { it.writeBytes(Api.bytes(ctx, "/api/docs/$slug/pdf")) } }
        } catch (e: Exception) { error = e.message ?: "Could not load the PDF" }
    }
    BackHandler(onBack = onBack)
    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp, top = 12.dp, end = 8.dp)) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Mc.Text) }
            Text(title, color = Mc.Text, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f))
            file?.let { f ->
                TextButton(onClick = {
                    runCatching {
                        ctx.startActivity(Intent.createChooser(Intent(Intent.ACTION_VIEW)
                            .setDataAndType(FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f), "application/pdf")
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), "Open PDF"))
                    }.onFailure { Toast.makeText(ctx, "No app for PDFs on this phone", Toast.LENGTH_LONG).show() }
                }) { Text("Open in…") }
            }
        }
        when {
            error != null -> Text(error!!, color = Mc.Bad, modifier = Modifier.padding(16.dp))
            file == null -> Text("Loading the PDF…", color = Mc.Muted, modifier = Modifier.padding(16.dp))
            else -> PdfPages(file!!)
        }
    }
}

@Composable
private fun PdfPages(file: File) {
    val ctx = LocalContext.current
    val opened = remember(file) {
        runCatching { PdfRenderer(ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)) }
    }
    val renderer = opened.getOrNull()
    if (renderer == null) { Text("This PDF cannot be shown here: ${opened.exceptionOrNull()?.message}. Try \"Open in…\".", color = Mc.Warn, modifier = Modifier.padding(16.dp)); return }
    DisposableEffect(renderer) { onDispose { runCatching { renderer.close() } } }
    val lock = remember { Mutex() }                                        // PdfRenderer shows one page at a time
    val widthPx = ctx.resources.displayMetrics.widthPixels
    LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items((0 until renderer.pageCount).toList()) { i -> PdfPage(renderer, lock, i, widthPx) }
    }
}

@Composable
private fun PdfPage(renderer: PdfRenderer, lock: Mutex, index: Int, widthPx: Int) {
    val bmp by produceState<ImageBitmap?>(null, index) {
        value = withContext(Dispatchers.IO) {
            lock.withLock {
                runCatching {
                    renderer.openPage(index).use { page ->
                        val h = (widthPx.toFloat() / page.width * page.height).toInt().coerceAtLeast(1)
                        val b = Bitmap.createBitmap(widthPx, h, Bitmap.Config.ARGB_8888)
                        b.eraseColor(android.graphics.Color.WHITE)
                        page.render(b, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                        b.asImageBitmap()
                    }
                }.getOrNull()
            }
        }
    }
    val img = bmp
    if (img != null) Image(img, "Page ${index + 1}", contentScale = ContentScale.FillWidth, modifier = Modifier.fillMaxWidth())
    else Box(Modifier.fillMaxWidth().height(420.dp).clip(RoundedCornerShape(4.dp)).background(Mc.Card), contentAlignment = Alignment.Center) {
        Text("Page ${index + 1}…", color = Mc.Muted)
    }
}
