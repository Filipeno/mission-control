package cz.filip.missioncontrol.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cz.filip.missioncontrol.data.Api
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Short name of a tool for labels: "mcp__ccd_session__start_session" -> "start_session". */
fun toolShort(tool: String) = tool.replace(Regex("^mcp__.+?__"), "")

/**
 * One of the Claude desktop app's own approval cards (stage 11a-1): tool, session, the full input (scrollable),
 * the PC screenshot taken when the card appeared, and Allow (fingerprint) / Deny (one tap). Never "Always allow".
 * Once answered, it shows what the PC did: sent, waiting for unlock, clicked, or refused with the reason.
 */
@Composable
internal fun AppCardGate(g: JSONObject, busy: Boolean, onAllow: () -> Unit, onDeny: () -> Unit) {
    val ctx = LocalContext.current
    val inp = g.optJSONObject("input") ?: JSONObject()
    val tool = g.optString("tool")
    val gid = g.optString("id")
    McCard(modifier = Modifier.border(1.dp, Color(0xFF5A4115), RoundedCornerShape(18.dp))) {
        Label("Claude app card · ${toolShort(tool)}", Mc.Warn)
        Text(g.optString("card_title").ifBlank { g.optString("session") }, color = Mc.Muted, fontSize = 13.sp)
        if (tool == "mcp__ccd_session__start_session") {
            Text("Start a new session: “${inp.optString("title")}”", color = Mc.Text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(top = 6.dp))
            val meta = listOf(inp.optString("cwd").ifBlank { inp.optString("folder") }, inp.optString("model"), inp.optString("effort"),
                inp.optString("context"), inp.optString("initiation")).filter { it.isNotBlank() }
            if (meta.isNotEmpty()) Text(meta.joinToString(" · "), color = Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
            CodeBox(inp.optString("prompt").ifBlank { inp.toString(2) })
        } else if (inp.length() > 0) CodeBox(inp.toString(2))
        if (!g.optBoolean("input_found", true)) Text("The request's details were not found in the session's transcript: check the screenshot or the PC.",
            color = Mc.Warn, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        if (g.optBoolean("truncated")) Text("Too long to show fully here: check it at the PC before allowing.", color = Mc.Warn, fontSize = 13.sp)

        // The PC screenshot from when the card appeared (tap to zoom).
        var shot by remember(gid) { mutableStateOf<ImageBitmap?>(null) }
        var full by remember { mutableStateOf(false) }
        val hasShot = g.optBoolean("has_shot")
        LaunchedEffect(gid, hasShot) {
            if (hasShot && shot == null) shot = withContext(Dispatchers.IO) {
                runCatching { Api.bytes(ctx, "/api/appcard/$gid/shot").let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() } }.getOrNull()
            }
        }
        shot?.let { img ->
            Image(img, "PC screenshot", Modifier.fillMaxWidth().padding(top = 8.dp).heightIn(max = 220.dp).clip(RoundedCornerShape(10.dp))
                .clickable { full = true }, contentScale = ContentScale.Fit)
            Text("PC screen when the card appeared · tap to zoom", color = Mc.Muted, fontSize = 12.sp)
            if (full) FullScreenShot(img) { full = false }
        } ?: Text(if (hasShot) "Loading the PC screenshot…" else "No PC screenshot yet.", color = Mc.Muted, fontSize = 12.sp,
            modifier = Modifier.padding(top = 6.dp))
        Spacer(Modifier.height(10.dp))

        val ans = g.optJSONObject("answer")
        val ok = ans?.opt("ok")
        if (ans != null && ok != false) {
            // Sent (ok null: on its way or waiting for unlock) or clicked (ok true).
            val what = if (ans.optString("decision") == "allow") "Allow once" else "Deny"
            Text(if (ok == true) "✓ ${ans.optString("detail")}" else "$what sent · ${ans.optString("detail")}",
                color = if (ok == true) Mc.Good else Mc.Accent, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
            return@McCard
        }
        if (ans != null) Text(ans.optString("detail").ifBlank { "Refused at the PC" } + " · you can try again.", color = Mc.Bad, fontSize = 14.sp,
            modifier = Modifier.padding(bottom = 8.dp))
        if (!g.optBoolean("answerable", true)) {
            Text("Mission Control does not know this kind of card yet: answer it at the PC.", color = Mc.Warn, fontSize = 14.sp)
            return@McCard
        }
        if (busy) Text("Waiting for fingerprint…", color = Mc.Muted, fontSize = 14.sp)
        else Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton("Allow once", Modifier.weight(1.5f), onClick = onAllow)
            DarkBtn("Deny", Modifier.weight(1f), Mc.Bad, onClick = onDeny)
        }
        Text("The PC clicks the card for you. If it is locked, the answer waits for unlock (up to 8 h).", color = Mc.Muted, fontSize = 12.sp,
            modifier = Modifier.padding(top = 6.dp))
    }
}
