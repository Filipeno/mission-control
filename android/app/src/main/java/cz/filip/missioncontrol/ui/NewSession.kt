package cz.filip.missioncontrol.ui

import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cz.filip.missioncontrol.data.Api
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Stage 11c: what the new-session sheet remembers per folder. Cheap defaults (Sonnet, low, default permission mode). */
internal data class NewPrefs(val model: String = "sonnet", val effort: String = "low", val perm: String = "default")

private fun prefs(c: Context) = c.getSharedPreferences("mc-newsession", Context.MODE_PRIVATE)
internal fun loadNewPrefs(c: Context, area: String, name: String): NewPrefs {
    val raw = prefs(c).getString("$area|$name", null) ?: return NewPrefs()
    val p = raw.split("|")
    return if (p.size == 3) NewPrefs(p[0], p[1], p[2]) else NewPrefs()
}
internal fun saveNewPrefs(c: Context, area: String, name: String, v: NewPrefs) =
    prefs(c).edit().putString("$area|$name", "${v.model}|${v.effort}|${v.perm}").putString("last", "$area|$name").apply()
internal fun lastNewFolder(c: Context): Pair<String, String>? =
    prefs(c).getString("last", null)?.split("|", limit = 2)?.takeIf { it.size == 2 }?.let { it[0] to it[1] }

private val MODELS = listOf("sonnet" to "Sonnet", "haiku" to "Haiku", "opus" to "Opus")
private val EFFORTS = listOf("low" to "Low", "medium" to "Medium", "high" to "High")
private val PERMS = listOf("default" to "Default", "acceptEdits" to "Accept edits", "auto" to "Auto", "bypassPermissions" to "Bypass")
internal const val MAX_PROMPT = 2500

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun Choice(label: String, options: List<Pair<String, String>>, value: String, onPick: (String) -> Unit) {
    Text(label, color = Mc.Muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { (id, text) ->
            val sel = id == value
            Text(text, color = if (sel) Color(0xFF04121C) else Mc.Text, fontSize = 14.sp,
                modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(if (sel) Mc.Accent else Mc.Card).clickable { onPick(id) }
                    .padding(horizontal = 12.dp, vertical = 8.dp))
        }
    }
}

/** "New session" bottom sheet in the Claude tab. Fingerprint-signed start; the main session starts it on the PC. */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun NewSessionSheet(onClose: () -> Unit) {
    val ctx = LocalContext.current
    val data by produceState<JSONObject?>(null) { value = withContext(Dispatchers.IO) { runCatching { Api.get(ctx, "/api/folders") }.getOrNull() } }
    var area by remember { mutableStateOf(lastNewFolder(ctx)?.first ?: "projects") }
    var name by remember { mutableStateOf(lastNewFolder(ctx)?.second ?: "") }
    var p by remember { mutableStateOf(NewPrefs()) }
    var prompt by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val names = data?.optJSONArray(area)?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
    fun pick(a: String, n: String) { area = a; name = n; p = loadNewPrefs(ctx, a, n) }
    // Restore the remembered choices of the last-used folder once the list is here.
    androidx.compose.runtime.LaunchedEffect(data) { if (name.isNotBlank()) p = loadNewPrefs(ctx, area, name) }
    ModalBottomSheet(onDismissRequest = { if (!busy) onClose() }, containerColor = Mc.Bg) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).navigationBarsPadding().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("NEW CLAUDE SESSION", color = Mc.Accent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            if (data == null) Text("Loading folders…", color = Mc.Muted, fontSize = 13.sp)
            else if (!data!!.optBoolean("fresh")) Text("The PC has not listed its folders lately. Is it awake?", color = Mc.Warn, fontSize = 13.sp)
            Choice("Area", listOf("projects" to "D:\\projekty", "skola" to "D:\\\u0160kola"), area) { a -> area = a; name = ""; }
            Text("Folder", color = Mc.Muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                names.forEach { n ->
                    val sel = n == name
                    Text(n, color = if (sel) Color(0xFF04121C) else Mc.Text, fontSize = 14.sp, maxLines = 1,
                        modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(if (sel) Mc.Accent else Mc.Card).clickable { pick(area, n) }
                            .padding(horizontal = 12.dp, vertical = 8.dp))
                }
            }
            Choice("Model", MODELS, p.model) { p = p.copy(model = it) }
            Choice("Effort", EFFORTS, p.effort) { p = p.copy(effort = it) }
            Choice("Permission mode", PERMS, p.perm) { p = p.copy(perm = it) }
            if (p.perm == "bypassPermissions") Text("Bypass: the session runs every tool without asking you. Use it only for work you trust.", color = Mc.Bad, fontSize = 13.sp)
            Text("Your main session starts it, so it may cap model, effort and mode at its own level; then it raises them and asks you with a card.",
                color = Mc.Muted, fontSize = 13.sp)
            OutlinedTextField(value = prompt, onValueChange = { if (it.length <= MAX_PROMPT) prompt = it }, label = { Text("First prompt") },
                minLines = 4, maxLines = 10, modifier = Modifier.fillMaxWidth())
            Button(enabled = !busy && name.isNotBlank() && prompt.isNotBlank(), modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C)), onClick = {
                    busy = true
                    val body = JSONObject().put("area", area).put("name", name).put("model", p.model).put("effort", p.effort)
                        .put("permission", p.perm).put("prompt", prompt.trim())
                    signedPostEx(ctx, "New session in $name".take(60), "newsess|$area|$name|${p.model}|${p.effort}|${p.perm}|${prompt.trim()}",
                        "/api/sessions/new", body, data?.optBoolean("has_key") == true, onSigned = {},
                        tier = if (p.perm == "default") "M" else "H") { err ->
                        busy = false
                        if (err != null) Toast.makeText(ctx, "Not started: $err", Toast.LENGTH_LONG).show()
                        else { saveNewPrefs(ctx, area, name, p); Toast.makeText(ctx, "Asked your main session to start it", Toast.LENGTH_LONG).show(); onClose() }
                    }
                }) { Text(if (busy) "Waiting…" else "Start (fingerprint)", fontSize = 16.sp, fontWeight = FontWeight.SemiBold) }
            TextButton(enabled = !busy, onClick = onClose) { Text("Cancel") }
        }
    }
}
