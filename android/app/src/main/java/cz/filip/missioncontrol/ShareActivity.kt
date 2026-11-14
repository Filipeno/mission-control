package cz.filip.missioncontrol

import android.content.Intent
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
        val shared = listOfNotNull(intent.getStringExtra(Intent.EXTRA_SUBJECT), intent.getStringExtra(Intent.EXTRA_TEXT)).joinToString("\n")
        if (Store.token(this) == null) { Toast.makeText(this, "Log in to Mission Control first", Toast.LENGTH_LONG).show(); return finish() }
        setContent { McTheme { Screen(shared) } }
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
                        onSigned = { Toast.makeText(app, "Sent to the PC", Toast.LENGTH_SHORT).show(); finish() }) { err ->
                        if (err != null) { busy = false; Toast.makeText(app, "Not sent: $err", Toast.LENGTH_LONG).show() }
                    }
                }.padding(14.dp)) {
                    Text(s.optString("title"), color = Mc.Text, fontSize = 15.sp, maxLines = 1)
                }
            }
            TextButton(onClick = { finish() }) { Text("Cancel") }
        }
    }
}
