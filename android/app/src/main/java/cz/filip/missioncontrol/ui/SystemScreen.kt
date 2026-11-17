package cz.filip.missioncontrol.ui

import android.graphics.BitmapFactory
import android.widget.Toast
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.LifecycleResumeEffect
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SystemScreen(onSettings: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var resumed by remember { mutableStateOf(false) }
    var shot by remember { mutableStateOf<ImageBitmap?>(null) }
    var shotAt by remember { mutableStateOf(0.0) }
    var waitingShot by remember { mutableStateOf(false) }
    var full by remember { mutableStateOf(false) }
    var moreTimeline by remember { mutableStateOf(false) }

    suspend fun loadShot() {
        shot = withContext(Dispatchers.IO) {
            runCatching { Api.bytes(ctx, "/api/system/screenshot.jpg").let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() } }.getOrNull()
        }
    }

    suspend fun load() {
        try {
            val d = withContext(Dispatchers.IO) { Api.get(ctx, "/api/system") }
            data = d
            error = null
            val at = d.optJSONObject("shot")?.optDouble("at")?.takeIf { !it.isNaN() } ?: 0.0
            if (at > 0 && (at != shotAt || shot == null)) {
                shotAt = at
                loadShot()
                waitingShot = false
            }
        } catch (e: ApiError) {
            if (e.code == 401) onLoggedOut() else error = e.message
        }
    }

    LifecycleResumeEffect(Unit) { resumed = true; onPauseOrDispose { resumed = false } }
    LaunchedEffect(resumed) { while (resumed) { load(); delay(if (waitingShot) 2000 else 10_000) } }
    LaunchedEffect(waitingShot) { if (waitingShot) { delay(40_000); waitingShot = false } }

    fun requestShot() {
        if (waitingShot) return
        waitingShot = true      // "Taking…" at once; undone below if the Pi refuses
        scope.launch {
            try {
                withContext(Dispatchers.IO) { Api.post(ctx, "/api/system/screenshot") }
            } catch (e: ApiError) {
                waitingShot = false
                Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
            }
        }
    }

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } },
        modifier = modifier.fillMaxSize(),
    ) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 22.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            val d = data
            Row(verticalAlignment = Alignment.Bottom) {
                Box(Modifier.weight(1f)) { Header("System") }
                if (d != null) {
                    val problems = d.optJSONArray("problems")?.length() ?: 0
                    val ok = problems == 0
                    Text(
                        if (ok) "All OK" else "$problems problem${if (problems > 1) "s" else ""}",
                        color = if (ok) Mc.Good else Mc.Bad, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(bottom = 8.dp).clip(RoundedCornerShape(50))
                            .background(if (ok) Mc.GoodBg else Color(0xFF2A1215)).padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
                IconButton(onClick = onSettings, modifier = Modifier.padding(bottom = 2.dp)) {
                    Icon(Icons.Filled.Settings, contentDescription = "Settings", tint = Mc.Muted)
                }
            }
            error?.let { McCard { Text(it, color = Mc.Bad, fontSize = 14.sp) } }
            if (d == null) {
                if (error == null) Text("Loading…", color = Mc.Muted)
                return@Column
            }
            PcCard(d, shot, shotAt, waitingShot, onShot = ::requestShot, onOpen = { full = true })
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                PiTile(d.optJSONObject("pi"), Modifier.weight(1f))
                MiniTile(d.optJSONObject("mini_pc"), Modifier.weight(1f))
            }
            Label("Services")
            Column {
                val rows = mutableListOf<Triple<String, Boolean, String>>()
                d.optJSONObject("vault")?.let { rows += Triple(it.optString("name"), it.optBoolean("ok"), it.optString("detail")) }
                val tunnel = d.optJSONObject("tunnel")
                val svcs = d.optJSONArray("services") ?: JSONArray()
                for (i in 0 until svcs.length()) {
                    val s = svcs.getJSONObject(i)
                    if (s.optString("id") == "cloudflared" && tunnel != null) rows += Triple(s.optString("name"), tunnel.optBoolean("ok"), tunnel.optString("detail"))
                    else rows += Triple(s.optString("name"), s.optBoolean("ok"), s.optString("detail"))
                }
                rows.forEachIndexed { i, (name, ok, detail) ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(12.dp).clip(CircleShape).background(if (ok) Mc.Good else Mc.Bad))
                        Spacer(Modifier.width(14.dp))
                        Text(name, color = Mc.Text, fontSize = 16.sp, modifier = Modifier.weight(1f))
                        Text(detail, color = if (ok) Mc.Good else Mc.Bad, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                    }
                    if (i < rows.size - 1) HorizontalDivider(color = Mc.Border)
                }
            }
            SlimeCard(d.optJSONObject("roblox"))
            Timeline(d.optJSONArray("timeline"), moreTimeline) { moreTimeline = !moreTimeline }
        }
    }

    if (full && shot != null) FullScreenShot(shot!!) { full = false }
}

@Composable
private fun PcCard(d: JSONObject, shot: ImageBitmap?, shotAt: Double, waiting: Boolean, onShot: () -> Unit, onOpen: () -> Unit) {
    val pc = d.optJSONObject("pc") ?: JSONObject()
    McCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) { Label("Gaming PC") }
            Button(
                onClick = onShot, enabled = !waiting,
                colors = ButtonDefaults.buttonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Text,
                    disabledContainerColor = Mc.ButtonDark, disabledContentColor = Mc.Muted),
                shape = RoundedCornerShape(14.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, Mc.Border),
            ) { Text(if (waiting) "Taking…" else "New screenshot", fontSize = 15.sp, fontWeight = FontWeight.SemiBold) }
        }
        Spacer(Modifier.height(12.dp))
        Box(
            Modifier.fillMaxWidth().height(190.dp).clip(RoundedCornerShape(12.dp)).background(Mc.Bg)
                .then(if (shot != null) Modifier.clickable { onOpen() } else Modifier),
            contentAlignment = Alignment.Center,
        ) {
            if (shot != null) Image(shot, "PC screenshot", Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
            else Text("No screenshot yet", color = Mc.Muted, fontSize = 14.sp)
        }
        Text(if (shotAt > 0) "Last screenshot · ${clock(shotAt)}" else "Needs the PC awake", color = Mc.Muted, fontSize = 12.sp,
            modifier = Modifier.padding(top = 6.dp))
        Spacer(Modifier.height(6.dp))
        val fresh = pc.optBoolean("fresh")
        fun t(k: String) = pc.optDouble(k).takeIf { !it.isNaN() }
        val temps = if (fresh) listOf(
            t("cpu_temp")?.let { "CPU ${it.toInt()} °C" } ?: "CPU —",
            t("gpu_temp")?.let { "GPU ${it.toInt()} °C" } ?: "GPU —",
        ).joinToString(" · ") else "CPU — · GPU —"
        Text(temps, color = Mc.Text, fontSize = 15.sp, fontFamily = FontFamily.Monospace)
        Text(
            if (fresh) listOfNotNull(t("cpu_load")?.let { "CPU ${it.toInt()}%" }, t("gpu_load")?.let { "GPU ${it.toInt()}%" },
                t("ram_pct")?.let { "RAM ${it.toInt()}%" }).joinToString(" · ") + " load" else "Asleep, no live temps",
            color = Mc.Muted, fontSize = 13.sp,
        )
    }
}

@Composable
private fun PiTile(pi: JSONObject?, modifier: Modifier) {
    McCard(modifier) {
        Label("Raspberry Pi")
        if (pi == null) { Text("…", color = Mc.Muted); return@McCard }
        val t = pi.optDouble("temp_c").takeIf { !it.isNaN() }
        Text(if (t != null) "${t.toInt()} °C" else "—", color = if (pi.optBoolean("healthy")) Mc.Text else Mc.Bad, fontSize = 28.sp,
            fontWeight = FontWeight.SemiBold, fontFamily = FontFamily.Monospace, modifier = Modifier.padding(top = 4.dp))
        val free = pi.optDouble("disk_free_gb").takeIf { !it.isNaN() }?.let { "${it.toInt()} GB free" }
        val up = pi.optLong("uptime_s").takeIf { it > 0 }?.let { "up ${duration(it)}" }
        Text(listOfNotNull(free, up).joinToString(" · "), color = Mc.Muted, fontSize = 14.sp)
        pi.optInt("mem_used_pct", -1).takeIf { it >= 0 }?.let { Text("RAM $it%", color = Mc.Muted, fontSize = 14.sp) }
    }
}

@Composable
private fun MiniTile(m: JSONObject?, modifier: Modifier) {
    McCard(modifier) {
        Label("Mini PC")
        if (m == null || !m.optBoolean("configured")) {
            Text("Not set up", color = Mc.Muted, fontSize = 18.sp, modifier = Modifier.padding(top = 4.dp))
            return@McCard
        }
        val ok = m.optBoolean("ok")
        Text(if (ok) "Healthy" else if (!m.optBoolean("up")) "Down" else "HA not answering", color = if (ok) Mc.Good else Mc.Bad,
            fontSize = 24.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp))
        val temp = m.optDouble("temp").takeIf { !it.isNaN() }?.let { "${it.toInt()} °C" }
        val disk = m.optDouble("disk_pct").takeIf { !it.isNaN() }?.let { "disk ${it.toInt()}%" }
        val up = m.optLong("uptime").takeIf { it > 0 }?.let { "up ${duration(it)}" }
        val line = listOfNotNull(temp, disk, up).joinToString(" · ")
        Text(if (line.isNotBlank()) line else if (ok) "Home Assistant answers" else "", color = Mc.Muted, fontSize = 14.sp)
    }
}

@Composable
private fun SlimeCard(rb: JSONObject?) {
    val pub = rb?.optJSONObject("public")
    if (pub == null || !pub.has("playing")) return
    val an = rb.optJSONObject("analytics")
    McCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) { Label("Roblox · ${pub.optString("name", "Slime Factory Tycoon")}") }
            Text("Live", color = Mc.Accent, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.clip(RoundedCornerShape(50)).background(Mc.NavSelected).padding(horizontal = 12.dp, vertical = 5.dp))
        }
        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Stat("${pub.optInt("playing")}", "Playing now")
            Stat("${pub.optInt("visits")}", if (pub.optInt("visits_today") > 0) "Visits · +${pub.optInt("visits_today")} today" else "Visits")
            Stat("${pub.optInt("favorites")}", "Favorites")
        }
        Spacer(Modifier.height(12.dp))
        HorizontalDivider(color = Mc.Border)
        Spacer(Modifier.height(10.dp))
        when (an?.optString("state")) {
            "ok" -> {
                val players = an.optJSONArray("players")
                val rev = an.optJSONArray("revenue")
                if (players != null && players.length() > 0) {
                    val ns = (0 until players.length()).map { players.getJSONObject(it).optInt("n") }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("${ns.last()} players yesterday", color = Mc.Text, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                            Text("Last ${ns.size} days: ${ns.sum()}", color = Mc.Muted, fontSize = 13.sp)
                        }
                        Bars(ns)
                    }
                }
                Spacer(Modifier.height(6.dp))
                if (rev != null && rev.length() > 0) {
                    val rs = (0 until rev.length()).map { rev.getJSONObject(it).optInt("robux") }
                    Text("Earnings: ${rs.last()} Robux yesterday · ${rs.sum()} in ${rs.size} days", color = Mc.Text, fontSize = 15.sp)
                } else {
                    Text("Earnings: ${an.optString("revenue_error").ifBlank { "no data yet" }}", color = Mc.Muted, fontSize = 14.sp)
                }
            }
            "error" -> Text("Earnings: ${an.optString("error")}", color = Mc.Warn, fontSize = 14.sp)
            else -> Text("Earnings: key not set", color = Mc.Muted, fontSize = 14.sp)
        }
    }
}

@Composable
private fun Stat(value: String, label: String) {
    Column {
        Text(value, color = Mc.Text, fontSize = 26.sp, fontWeight = FontWeight.SemiBold, fontFamily = FontFamily.Monospace)
        Text(label, color = Mc.Muted, fontSize = 13.sp)
    }
}

@Composable
private fun Bars(values: List<Int>) {
    val max = (values.maxOrNull() ?: 1).coerceAtLeast(1)
    Canvas(Modifier.width(84.dp).height(36.dp)) {
        val w = size.width / (values.size * 1.5f)
        values.forEachIndexed { i, v ->
            val h = (size.height * v / max).coerceAtLeast(3f)
            drawRect(Mc.Accent, Offset(i * w * 1.5f, size.height - h), Size(w, h))
        }
    }
}

@Composable
private fun Timeline(arr: JSONArray?, more: Boolean, toggle: () -> Unit) {
    if (arr == null || arr.length() == 0) return
    Label("Timeline")
    val now = System.currentTimeMillis() / 1000.0
    val items = (0 until arr.length()).map { arr.getJSONObject(it) }.filter { more || now - it.optDouble("at") < 86400 }
    Column {
        if (items.isEmpty()) Text("Nothing in the last 24 h.", color = Mc.Muted, fontSize = 14.sp, modifier = Modifier.padding(vertical = 8.dp))
        items.take(if (more) 120 else 30).forEachIndexed { i, e ->
            Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.Top) {
                Text(clock(e.optDouble("at")), color = Mc.Muted, fontSize = 13.sp, fontFamily = FontFamily.Monospace,
                    modifier = Modifier.width(if (more) 92.dp else 58.dp))
                Text(e.optString("text"), color = Mc.Text, fontSize = 15.sp, modifier = Modifier.weight(1f))
            }
            HorizontalDivider(color = Mc.Border)
        }
        TextButton(onClick = toggle) { Text(if (more) "Show only 24 h" else "Show more (7 days)", color = Mc.Accent) }
    }
}

@Composable
internal fun FullScreenShot(img: ImageBitmap, onClose: () -> Unit) {
    var scale by remember { mutableStateOf(1f) }
    var off by remember { mutableStateOf(Offset.Zero) }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Box(Modifier.fillMaxSize().background(Color.Black).pointerInput(Unit) {
            detectTransformGestures { _, pan, zoom, _ ->
                scale = (scale * zoom).coerceIn(1f, 6f)
                off = if (scale == 1f) Offset.Zero else off + pan
            }
        }) {
            Image(img, "PC screenshot", Modifier.fillMaxSize().graphicsLayer(scaleX = scale, scaleY = scale, translationX = off.x, translationY = off.y),
                contentScale = ContentScale.Fit)
            TextButton(onClick = onClose, modifier = Modifier.align(Alignment.TopEnd).padding(12.dp)) { Text("Close", color = Mc.Text) }
        }
    }
}
