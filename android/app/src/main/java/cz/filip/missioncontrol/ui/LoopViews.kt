package cz.filip.missioncontrol.ui

import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/** One answer of a loop-view route: envelope state, its detail, the data, or the HTTP error text. */
private class Env(val state: String, val detail: String, val data: JSONObject?, val err: String?, val at: Long = System.currentTimeMillis())

private fun JSONArray?.objs(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }

private fun JSONObject.dbl(k: String): Double? = optDouble(k).takeIf { !it.isNaN() }

private suspend fun fetchEnv(ctx: android.content.Context, path: String, prev: Env?, onLoggedOut: () -> Unit): Env =
    try {
        val j = withContext(Dispatchers.IO) { Api.get(ctx, path) }
        val st = j.optString("state")
        Env(st, j.optString("detail"), j.optJSONObject("data") ?: if (st == "loading") prev?.data else null, null)
    } catch (e: CancellationException) {
        throw e
    } catch (e: ApiError) {
        if (e.code == 401) onLoggedOut()
        Env("error", "", prev?.data, e.message ?: "Request failed")
    }

@Composable
private fun rememberResumed(): Boolean {
    var resumed by remember { mutableStateOf(false) }
    LifecycleResumeEffect(Unit) { resumed = true; onPauseOrDispose { resumed = false } }
    return resumed
}

/** Polls an envelope route while the screen is on screen: 1.5 s while loading, [idleMs] otherwise. */
@Composable
private fun rememberEnvelope(path: String, onLoggedOut: () -> Unit, idleMs: (Env) -> Long): Env? {
    val ctx = LocalContext.current
    val resumed = rememberResumed()
    var env by remember(path) { mutableStateOf<Env?>(null) }
    LaunchedEffect(path, resumed) {
        while (resumed) {
            val e = fetchEnv(ctx, path, env, onLoggedOut)
            env = e
            delay(if (e.state == "loading") 1500 else idleMs(e))
        }
    }
    return env
}

@Composable
private fun StatusChip(status: String) {
    val c = when (status) { "running" -> Mc.Accent; "done" -> Mc.Good; "failed" -> Mc.Bad; else -> Mc.Warn }
    Text(status, color = c, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(Mc.ButtonDark).padding(horizontal = 10.dp, vertical = 4.dp))
}

@Composable
private fun ScreenHeader(title: String, onBack: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp, top = 12.dp, end = 16.dp)) {
        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Mc.Text) }
        Text(title, color = Mc.Text, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f))
    }
}

/** Why there is nothing to show: an HTTP error or the envelope's "error" detail. Null when there is data or it is still loading. */
private fun envProblem(e: Env?): String? = when {
    e == null -> null
    e.err != null -> e.err
    e.state == "error" -> e.detail.ifBlank { "The PC could not answer" }
    else -> null
}

// ------------------------------------------------------------------ task list

@Composable
fun LoopTasksScreen(onBack: () -> Unit, onOpen: (String) -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    BackHandler(onBack = onBack)
    val env = rememberEnvelope("/api/system/loop/tasks", onLoggedOut) { 10_000 }
    val tasks = env?.data?.optJSONArray("tasks").objs()
    Column(modifier.fillMaxSize()) {
        ScreenHeader("How it thinks", onBack)
        val problem = envProblem(env)
        LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (problem != null) item { McCard { Text(problem, color = Mc.Bad, fontSize = 14.sp) } }
            if (env == null || (env.state == "loading" && env.data == null)) item {
                Text("Asking the PC…", color = Mc.Muted, fontSize = 14.sp)
            }
            if (env != null && env.state == "ok" && tasks.isEmpty()) item { Text("No tasks yet.", color = Mc.Muted, fontSize = 14.sp) }
            items(tasks, key = { it.optString("id") }) { t ->
                McCard(onClick = { onOpen(t.optString("id")) }) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(t.optString("id"), color = Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.weight(1f))
                        StatusChip(t.optString("status"))
                    }
                    val rounds = t.optInt("rounds")
                    Text(listOfNotNull(t.optString("repo").takeIf { it.isNotBlank() }, "$rounds rounds").joinToString(" · "),
                        color = Mc.Text, fontSize = 13.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 6.dp))
                    Text(t.optString("goal"), color = Mc.Text, fontSize = 15.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(top = 4.dp))
                    t.optString("reason").takeIf { it.isNotBlank() }?.let {
                        Text(it, color = Mc.Muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
                    }
                }
            }
        }
    }
}

// ------------------------------------------------------------------ one task

@Composable
fun LoopTaskScreen(id: String, onBack: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    BackHandler(onBack = onBack)
    val ctx = LocalContext.current
    val resumed = rememberResumed()
    val env = rememberEnvelope("/api/system/loop/tasks/$id", onLoggedOut) { if (it.data?.optBoolean("running") == true) 5_000 else 30_000 }
    val d = env?.data
    val rounds = d?.optJSONArray("rounds").objs()
    val expanded = remember(id) { mutableStateListOf<Int>() }
    val roundEnv = remember(id) { mutableStateMapOf<Int, Env>() }
    var opened by remember(id) { mutableStateOf(false) }
    LaunchedEffect(rounds.size) {
        if (!opened && rounds.isNotEmpty()) { opened = true; expanded += rounds.last().optInt("n") }
    }
    val key = expanded.toList()
    LaunchedEffect(id, resumed, key) {
        while (resumed) {
            for (n in key) {
                val cur = roundEnv[n]
                val age = System.currentTimeMillis() - (cur?.at ?: 0L)
                val due = when {
                    cur == null -> true
                    cur.state == "loading" -> age >= 1500
                    cur.err != null || cur.state == "error" -> age >= 10_000
                    cur.data?.optBoolean("running") == true -> age >= 5_000
                    else -> false
                }
                if (due) roundEnv[n] = fetchEnv(ctx, "/api/system/loop/tasks/$id/round/$n", cur, onLoggedOut)
            }
            delay(700)
        }
    }

    Column(modifier.fillMaxSize()) {
        ScreenHeader("Task $id", onBack)
        val problem = envProblem(env)
        LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (problem != null) item { McCard { Text(problem, color = Mc.Bad, fontSize = 14.sp) } }
            if (d == null && problem == null) item { Text("Asking the PC…", color = Mc.Muted, fontSize = 14.sp) }
            if (d != null) {
                item {
                    McCard {
                        Row(verticalAlignment = Alignment.Top) {
                            Text(d.optString("goal"), color = Mc.Text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                            Spacer(Modifier.width(8.dp))
                            StatusChip(d.optString("status"))
                        }
                        val meta = listOfNotNull(d.optString("model").takeIf { it.isNotBlank() }, d.optString("repo").takeIf { it.isNotBlank() },
                            d.dbl("total_seconds")?.let { "${it.toInt()} s" })
                        if (meta.isNotEmpty()) Text(meta.joinToString(" · "), color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
                        d.optString("check").takeIf { it.isNotBlank() }?.let {
                            Text("check: $it", color = Mc.Text, fontSize = 12.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.padding(top = 6.dp))
                        }
                        d.optString("reason").takeIf { it.isNotBlank() }?.let {
                            Text(it, color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
                        }
                    }
                }
                for (r in rounds) {
                    val n = r.optInt("n")
                    val open = n in expanded
                    item(key = "h$n") {
                        val ok = r.optInt("check_exit", -1) == 0
                        Row(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Mc.Card).border(1.dp, Mc.Border, RoundedCornerShape(14.dp))
                                .clickable { if (open) expanded.remove(n) else expanded.add(n) }.padding(horizontal = 14.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(Modifier.size(10.dp).clip(CircleShape).background(if (ok) Mc.Good else Mc.Bad))
                            Spacer(Modifier.width(10.dp))
                            val exit = if (r.has("check_exit") && !r.isNull("check_exit")) r.optInt("check_exit").toString() else "?"
                            Text("Round $n · ${r.optInt("turns")} turns · ${r.dbl("seconds")?.toInt() ?: 0} s · check exit $exit" +
                                (if (r.optBoolean("timed_out")) " (timed out)" else ""),
                                color = Mc.Text, fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                            Text(if (open) "▲" else "▼", color = Mc.Muted, fontSize = 12.sp)
                        }
                    }
                    if (open) roundBody(n, roundEnv[n])
                }
                item {
                    d.optString("check_output_tail").takeIf { it.isNotBlank() }?.let { tail ->
                        Column(Modifier.padding(top = 8.dp)) {
                            Label("Check output")
                            Spacer(Modifier.size(6.dp))
                            ResultCard(tail, error = false, full = -1)
                        }
                    }
                }
                val reviews = d.optJSONArray("reviews").objs()
                if (reviews.isNotEmpty()) item {
                    McCard {
                        Label("Reviews")
                        for (rv in reviews) {
                            Text("Review ${rv.optInt("n")} · ${rv.optString("verdict")}", color = Mc.Text, fontSize = 14.sp,
                                fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp))
                            val notes = rv.optJSONArray("notes")
                            if (notes != null) for (i in 0 until notes.length()) {
                                Text("• ${notes.optString(i)}", color = Mc.Muted, fontSize = 13.sp)
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.roundBody(n: Int, e: Env?) {
    val problem = envProblem(e)
    if (problem != null) item(key = "p$n") { Text(problem, color = Mc.Bad, fontSize = 13.sp, modifier = Modifier.padding(start = 8.dp)) }
    val data = e?.data
    if (data == null) {
        if (problem == null) item(key = "l$n") { Text("Loading round $n…", color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.padding(start = 8.dp)) }
        return
    }
    val skipped = data.optInt("skipped")
    if (skipped > 0) item(key = "s$n") { Text("$skipped earlier steps not shown", color = Mc.Muted, fontSize = 12.sp, modifier = Modifier.padding(start = 8.dp)) }
    val list = data.optJSONArray("items").objs()
    items(list.size, key = { "i$n-$it" }) { idx ->
        Box(Modifier.padding(start = 8.dp)) { TimelineItem(list[idx]) }
    }
}

@Composable
private fun TimelineItem(it: JSONObject) {
    val t = it.optString("t")
    when (it.optString("k")) {
        "text" -> Text(t, color = Mc.Text, fontSize = 14.sp, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(Mc.ButtonDark).padding(12.dp))
        "tool" -> Text("${it.optString("n")}: $t", color = Mc.Accent, fontSize = 12.sp, fontFamily = FontFamily.Monospace,
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Color(0xFF13202C))
                .border(1.dp, Mc.Accent.copy(alpha = 0.3f), RoundedCornerShape(12.dp)).padding(12.dp))
        "result" -> ResultCard(t, it.optBoolean("e"), if (it.has("full")) it.optInt("full", -1) else -1)
        "end" -> Text(t, color = Mc.Muted, fontSize = 12.sp, modifier = Modifier.padding(vertical = 2.dp))
        else -> Text(t, color = Mc.Muted, fontSize = 12.sp)
    }
}

@Composable
private fun ResultCard(t: String, error: Boolean, full: Int) {
    var more by remember { mutableStateOf(false) }
    val long = t.length > 600
    val shape = RoundedCornerShape(12.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(Color(0xFF0B0E14))
        .border(1.dp, if (error) Mc.Bad.copy(alpha = 0.5f) else Mc.Border, shape).padding(12.dp)) {
        Text(if (long && !more) t.take(600) + "…" else t, color = if (error) Mc.Bad else Mc.Muted, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
        if (long) TextButton(onClick = { more = !more }) { Text(if (more) "show less" else "show more", color = Mc.Accent, fontSize = 13.sp) }
        if (more && full > t.length) Text("cut at ${t.length} of $full chars", color = Mc.Muted, fontSize = 12.sp)
    }
}

// ------------------------------------------------------------------ chat

private class Msg(val role: String, val text: String, val error: Boolean = false, val pending: Boolean = false)

private const val CHAT_KEEP_MSGS = 200          // the Pi accepts this many; the PC trims further to the running model's context

/** The conversation lives only on the phone (private prefs) until Clear; the Pi keeps nothing between requests. */
private object ChatStore {
    private fun sp(c: android.content.Context) = c.getSharedPreferences("mc-localchat", android.content.Context.MODE_PRIVATE)

    fun load(c: android.content.Context): List<Msg> = try {
        val a = JSONArray(sp(c).getString("msgs", "[]"))
        (0 until a.length()).mapNotNull { i ->
            val o = a.optJSONObject(i) ?: return@mapNotNull null
            val role = o.optString("role")
            if (role != "user" && role != "assistant") null else Msg(role, o.optString("text"), error = o.optBoolean("error"))
        }
    } catch (e: Exception) { emptyList() }

    fun save(c: android.content.Context, msgs: List<Msg>) {
        val a = JSONArray()
        for (m in msgs.filter { !it.pending }.takeLast(CHAT_KEEP_MSGS))
            a.put(JSONObject().put("role", m.role).put("text", m.text).put("error", m.error))
        sp(c).edit().putString("msgs", a.toString()).apply()
    }
}

/** What goes to the Pi: the whole kept conversation (errors and empty bubbles left out), newest [CHAT_KEEP_MSGS]. */
private fun chatBody(messages: List<Msg>, newText: String): JSONArray {
    val body = JSONArray()
    for (m in messages.filter { !it.error && it.text.isNotBlank() }.takeLast(CHAT_KEEP_MSGS - 1))
        body.put(JSONObject().put("role", m.role).put("content", m.text))
    return body.put(JSONObject().put("role", "user").put("content", newText))
}

@Composable
fun LoopChatScreen(onBack: () -> Unit, onLoggedOut: () -> Unit, modifier: Modifier = Modifier) {
    BackHandler(onBack = onBack)
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val resumed = rememberResumed()
    var available by remember { mutableStateOf(false) }
    var reason by remember { mutableStateOf("Checking the PC…") }
    var model by remember { mutableStateOf("") }
    val messages = remember { mutableStateListOf<Msg>().also { it.addAll(ChatStore.load(ctx)) } }
    var input by remember { mutableStateOf("") }
    var answering by remember { mutableStateOf(false) }
    var rid by remember { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()

    LaunchedEffect(resumed) {
        while (resumed) {
            try {
                val v = withContext(Dispatchers.IO) { Api.get(ctx, "/api/system/localai") }
                val c = v.optJSONObject("chat")
                available = c?.optBoolean("available") == true
                reason = c?.optString("reason").orEmpty().ifBlank { "Chat is not available" }
                model = v.optJSONObject("server")?.optString("model").orEmpty().takeIf { it != "null" }.orEmpty()
            } catch (e: ApiError) {
                if (e.code == 401) onLoggedOut() else { available = false; reason = e.message ?: "Request failed" }
            }
            delay(10_000)
        }
    }
    LaunchedEffect(messages.size, messages.lastOrNull()?.text?.length) {
        if (messages.isNotEmpty()) listState.scrollToItem(messages.lastIndex)
    }

    fun send() {
        val text = input.trim()
        if (text.isEmpty() || answering || !available) return
        val body = chatBody(messages, text)
        messages += Msg("user", text, pending = true)
        val userIdx = messages.lastIndex
        input = ""
        answering = true
        scope.launch {
            try {
                val r = withContext(Dispatchers.IO) { Api.post(ctx, "/api/system/localai/chat", JSONObject().put("messages", body)) }
                val id = r.optString("rid")
                rid = id
                messages[userIdx] = Msg("user", text)
                messages += Msg("assistant", "")
                val ai = messages.lastIndex
                while (true) {
                    delay(700)
                    val s = withContext(Dispatchers.IO) { Api.get(ctx, "/api/system/localai/chat/$id") }
                    val st = s.optString("state")
                    val partial = s.optString("text")
                    messages[ai] = Msg("assistant", partial)
                    if (s.optString("model").isNotBlank() && model.isBlank()) model = s.optString("model")
                    if (st == "done" || st == "stopped") break
                    if (st == "error") {
                        messages += Msg("assistant", s.optString("error").ifBlank { "The model failed" }, error = true)
                        break
                    }
                }
                if (messages[ai].text.isBlank()) messages.removeAt(ai)
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiError) {
                if (userIdx < messages.size && messages[userIdx].pending) messages[userIdx] = Msg("user", text)
                if (e.code == 401) onLoggedOut() else Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
            } finally {
                answering = false
                rid = null
                ChatStore.save(ctx, messages.filter { it.text.isNotBlank() })
            }
        }
    }

    fun stop() {
        val id = rid ?: return
        scope.launch {
            try { withContext(Dispatchers.IO) { Api.post(ctx, "/api/system/localai/chat/$id/stop") } }
            catch (e: ApiError) { Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show() }
        }
    }

    Column(modifier.fillMaxSize().imePadding()) {
        ScreenHeader("Chat", onBack)
        Text("Local model, LAN/VPN only", color = Mc.Muted, fontSize = 12.sp,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Mc.Card)
                .padding(horizontal = 12.dp, vertical = 8.dp))
        if (model.isNotBlank()) Text(model, color = Mc.Accent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp).clip(RoundedCornerShape(50)).background(Mc.NavSelected)
                .padding(horizontal = 10.dp, vertical = 5.dp))
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState, contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (messages.isEmpty()) item { Text("Ask the local model something.", color = Mc.Muted, fontSize = 14.sp) }
            items(messages.size) { i ->
                val m = messages[i]
                val user = m.role == "user"
                Row(Modifier.fillMaxWidth(), horizontalArrangement = if (user) Arrangement.End else Arrangement.Start) {
                    Column(horizontalAlignment = if (user) Alignment.End else Alignment.Start, modifier = Modifier.fillMaxWidth(0.88f)) {
                        Text(if (m.text.isEmpty() && !m.error) "…" else m.text, color = if (m.error) Mc.Bad else Mc.Text, fontSize = 14.sp,
                            modifier = Modifier.clip(RoundedCornerShape(14.dp)).background(if (user) Mc.NavSelected else Mc.Card)
                                .border(1.dp, Mc.Border, RoundedCornerShape(14.dp)).padding(horizontal = 12.dp, vertical = 9.dp))
                        if (m.pending) Text("sending…", color = Mc.Muted, fontSize = 11.sp)
                    }
                }
            }
        }
        Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
            if (!available) {
                Text(reason, color = Mc.Muted, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                    .background(Mc.Card).padding(12.dp))
            } else {
                FieldLabel("Message")
                OutlinedTextField(value = input, onValueChange = { if (it.length <= 4000) input = it }, maxLines = 4,
                    placeholder = { Text("e.g. explain this error") }, modifier = Modifier.fillMaxWidth())
            }
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val colors = ButtonDefaults.buttonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Accent,
                    disabledContainerColor = Mc.ButtonDark, disabledContentColor = Mc.Muted)
                Button(onClick = ::send, enabled = input.isNotBlank() && available && !answering, shape = RoundedCornerShape(14.dp),
                    colors = colors, border = BorderStroke(1.dp, Mc.Border)) { Text("Send", fontSize = 14.sp, fontWeight = FontWeight.SemiBold) }
                if (answering) Button(onClick = ::stop, shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Mc.ButtonDark, contentColor = Mc.Warn), border = BorderStroke(1.dp, Mc.Border)) { Text("Stop", fontSize = 14.sp, fontWeight = FontWeight.SemiBold) }
                Button(onClick = { messages.clear(); ChatStore.save(ctx, messages) }, enabled = !answering && messages.isNotEmpty(), shape = RoundedCornerShape(14.dp),
                    colors = colors, border = BorderStroke(1.dp, Mc.Border)) { Text("Clear", fontSize = 14.sp, fontWeight = FontWeight.SemiBold) }
            }
        }
    }
}
