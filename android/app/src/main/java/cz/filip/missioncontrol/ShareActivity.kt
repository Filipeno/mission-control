package cz.filip.missioncontrol

import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import android.os.Bundle
import android.widget.Toast
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.fragment.app.FragmentActivity
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.Store
import cz.filip.missioncontrol.ui.Mc
import cz.filip.missioncontrol.ui.McTheme
import cz.filip.missioncontrol.ui.signedPostEx
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** "Share" target: text or a link from any app goes to Claude's idea inbox or into a Desktop session (fingerprint). */
class ShareActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val uris: List<Uri> = when (intent.action) {
            Intent.ACTION_SEND -> listOfNotNull(intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java))
            Intent.ACTION_SEND_MULTIPLE -> intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
            else -> emptyList()
        }
        val shared = listOfNotNull(intent.getStringExtra(Intent.EXTRA_SUBJECT), intent.getStringExtra(Intent.EXTRA_TEXT)).joinToString("\n")
        if (Store.token(this) == null) { Toast.makeText(this, "Log in to Mission Control first", Toast.LENGTH_LONG).show(); return finish() }
        setContent { McTheme { if (uris.isNotEmpty()) FileScreen(uris.take(6)) else Screen(shared) } }
    }

    @androidx.compose.runtime.Composable
    private fun Screen(initial: String) {
        val scope = rememberCoroutineScope()
        var text by remember { mutableStateOf(initial) }
        var busy by remember { mutableStateOf(false) }
        val data by produceState<JSONObject?>(null) { value = withContext(Dispatchers.IO) { runCatching { Api.get(this@ShareActivity, "/api/sessions") }.getOrNull() } }
        val sessions = data?.optJSONArray("sessions")?.let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
            ?.filter { it.optString("kind") == "desktop" && it.optString("state") != "idle" || it.optString("kind") == "desktop" }.orEmpty()
        fun done(ok: String): (String?) -> Unit = { err ->
            busy = false
            Toast.makeText(this, err ?: ok, Toast.LENGTH_SHORT).show()
            if (err == null) finish()
        }
        Column(Modifier.fillMaxSize().background(Mc.Bg).statusBarsPadding().navigationBarsPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("SHARE TO CLAUDE", color = Mc.Accent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            OutlinedTextField(value = text, onValueChange = { text = it }, minLines = 3, maxLines = 10, modifier = Modifier.fillMaxWidth())
            Button(enabled = !busy && text.isNotBlank(), modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C)), onClick = {
                    // Close at once; the idea is posted in the background and a toast reports a failure.
                    val app = applicationContext
                    val idea = text.trim()
                    Toast.makeText(app, "Sent to Claude's inbox", Toast.LENGTH_SHORT).show()
                    kotlin.concurrent.thread {
                        try { Api.post(app, "/api/ideas", JSONObject().put("text", idea)) }
                        catch (e: Exception) {
                            android.os.Handler(android.os.Looper.getMainLooper()).post {
                                Toast.makeText(app, "Idea not sent: ${e.message ?: "failed"}", Toast.LENGTH_LONG).show()
                            }
                        }
                    }
                    finish()
                }) { Text("Send to Claude's inbox", fontSize = 16.sp, fontWeight = FontWeight.SemiBold) }
            Text("…or type it into a session (fingerprint):", color = Mc.Muted, fontSize = 13.sp)
            if (data == null) Text("Loading sessions…", color = Mc.Muted, fontSize = 13.sp)
            sessions.take(8).forEach { s ->
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Mc.Card).clickable(enabled = !busy && text.isNotBlank()) {
                    busy = true
                    val t = text.trim(); val sid = s.optString("id")
                    val app = applicationContext
                    signedPostEx(this@ShareActivity, "Send to ${s.optString("title").take(40)}", "msg|$sid|$t", "/api/sessions/$sid/message",
                        JSONObject().put("text", t), data?.optBoolean("has_key") == true,
                        onSigned = { Toast.makeText(app, "Sent to the PC", Toast.LENGTH_SHORT).show(); finish() }, tier = "M") { err ->
                        if (err != null) { busy = false; Toast.makeText(app, "Not sent: $err", Toast.LENGTH_LONG).show() }
                    }
                }.padding(14.dp)) {
                    Text(s.optString("title"), color = Mc.Text, fontSize = 15.sp, maxLines = 1)
                }
            }
            TextButton(onClick = { finish() }) { Text("Cancel") }
        }
    }

    private fun nameOf(u: Uri, mime: String?): String {
        var n = runCatching {
            contentResolver.query(u, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) it.getString(0) else null }
        }.getOrNull() ?: "shared"
        if (!n.contains('.')) n += when (mime ?: contentResolver.getType(u)) { "image/png" -> ".png"; "image/webp" -> ".webp"; "image/heic" -> ".heic"; "application/pdf" -> ".pdf"; else -> ".jpg" }
        return n
    }

    private fun readUri(u: Uri): ByteArray {
        val max = 25 * 1024 * 1024
        val out = java.io.ByteArrayOutputStream()
        contentResolver.openInputStream(u)?.use { ins ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = ins.read(buf); if (n < 0) break
                out.write(buf, 0, n)
                if (out.size() > max) throw IllegalStateException("A file is over 25 MB")
            }
        } ?: throw IllegalStateException("Cannot read the shared file")
        return out.toByteArray()
    }

    /** A photo or PDF of an assignment: pick the subject, upload, fingerprint; mc-pc saves it in D:\Skola and a Czech session starts. */
    @androidx.compose.runtime.Composable
    private fun FileScreen(uris: List<Uri>) {
        val scope = rememberCoroutineScope()
        var busy by remember { mutableStateOf(false) }
        var subject by remember { mutableStateOf("") }
        var note by remember { mutableStateOf("") }
        val data by produceState<JSONObject?>(null) { value = withContext(Dispatchers.IO) { runCatching { Api.get(this@ShareActivity, "/api/folders") }.getOrNull() } }
        val subjects = data?.optJSONArray("skola")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
        val names = remember { uris.map { nameOf(it, null) } }
        Column(Modifier.fillMaxSize().background(Mc.Bg).statusBarsPadding().navigationBarsPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("SCHOOL TASK FROM A PHOTO", color = Mc.Accent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            Text(names.joinToString("\n"), color = Mc.Text, fontSize = 14.sp)
            Text("Subject", color = Mc.Muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            if (data == null) Text("Loading subjects\u2026", color = Mc.Muted, fontSize = 13.sp)
            subjects.forEach { sj ->
                val sel = sj == subject
                Text(sj, color = if (sel) Color(0xFF04121C) else Mc.Text, fontSize = 15.sp, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                    .background(if (sel) Mc.Accent else Mc.Card).clickable(enabled = !busy) { subject = sj }.padding(14.dp))
            }
            OutlinedTextField(value = note, onValueChange = { if (it.length <= 400) note = it }, label = { Text("Note (optional)") }, minLines = 2, modifier = Modifier.fillMaxWidth())
            Text("Your main session starts a Czech homework session in that subject folder. The PC must be awake and unlocked.", color = Mc.Muted, fontSize = 13.sp)
            Button(enabled = !busy && subject.isNotBlank(), modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C)), onClick = {
                    busy = true
                    val n = note.trim(); val sj = subject
                    scope.launch {
                        val ids = try {
                            withContext(Dispatchers.IO) {
                                uris.mapIndexed { i, u ->
                                    val bytes = readUri(u)
                                    val r = Api.bytes(this@ShareActivity, "/api/launch/upload?name=" + java.net.URLEncoder.encode(names[i], "UTF-8"), bytes,
                                        contentResolver.getType(u) ?: "application/octet-stream")
                                    JSONObject(String(r)).getString("id")
                                }
                            }
                        } catch (e: Exception) {
                            busy = false; Toast.makeText(this@ShareActivity, "Upload failed: ${e.message ?: "error"}", Toast.LENGTH_LONG).show(); return@launch
                        }
                        signedPostEx(this@ShareActivity, "School task: $sj".take(60), "skola|$sj|${ids.joinToString(",")}|$n", "/api/launch/skola",
                            JSONObject().put("subject", sj).put("files", org.json.JSONArray(ids)).put("note", n), data?.optBoolean("has_key") == true, onSigned = {}, tier = "M") { err ->
                            busy = false
                            if (err != null) Toast.makeText(this@ShareActivity, "Not sent: $err", Toast.LENGTH_LONG).show()
                            else { Toast.makeText(this@ShareActivity, "Sent: the PC saves it and your main session starts the task", Toast.LENGTH_LONG).show(); finish() }
                        }
                    }
                }) { Text(if (busy) "Working\u2026" else "Send (fingerprint)", fontSize = 16.sp, fontWeight = FontWeight.SemiBold) }
            TextButton(enabled = !busy, onClick = { finish() }) { Text("Cancel") }
        }
    }
}
