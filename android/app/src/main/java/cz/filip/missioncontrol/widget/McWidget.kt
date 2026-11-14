package cz.filip.missioncontrol.widget

import android.content.Context
import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.ImageProvider
import androidx.glance.LocalSize
import androidx.glance.action.ActionParameters
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import cz.filip.missioncontrol.MainActivity
import cz.filip.missioncontrol.R
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.Store
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val cText = ColorProvider(Color(0xFFE6EAF2))
private val cMuted = ColorProvider(Color(0xFF9AA4B5))
private val cAccent = ColorProvider(Color(0xFF4CC2FF))
private val cWarn = ColorProvider(Color(0xFFFFB547))
private val cBad = ColorProvider(Color(0xFFFF6B6B))
private val cGood = ColorProvider(Color(0xFF4ADE9A))
private val cOnAccent = ColorProvider(Color(0xFF04121C))

/** What the widget shows; cached on the phone so it still has numbers when the Pi is out of reach. */
data class WidgetState(val json: JSONObject?, val fetchedAt: Long, val fresh: Boolean, val loggedIn: Boolean, val waking: Boolean = false)

object WidgetData {
    private fun sp(c: Context) = c.getSharedPreferences("widget", Context.MODE_PRIVATE)

    /** A tap on Wake shows "Waking…" at once; this remembers it until the PC is up, the call failed, or 90 s passed. */
    fun setWaking(c: Context, on: Boolean) = sp(c).edit().putLong("waking_at", if (on) System.currentTimeMillis() else 0L).apply()
    private fun waking(c: Context) = System.currentTimeMillis() - sp(c).getLong("waking_at", 0L) < 90_000

    suspend fun load(c: Context): WidgetState {
        if (Store.token(c) == null) return WidgetState(null, 0, false, false)
        // Right after a Wake tap draw from the cache without waiting for the Pi.
        val instant = System.currentTimeMillis() - sp(c).getLong("waking_at", 0L) < 1_500
        val got = if (instant) null else withContext(Dispatchers.IO) { runCatching { Api.get(c, "/api/widget") }.getOrNull() }
        if (got != null) {
            val now = System.currentTimeMillis()
            sp(c).edit().putString("json", got.toString()).putLong("at", now).apply()
            val online = got.optJSONObject("pc")?.optBoolean("online") == true
            if (online) setWaking(c, false)
            return WidgetState(got, now, true, true, waking(c) && !online)
        }
        val cached = sp(c).getString("json", null)?.let { runCatching { JSONObject(it) }.getOrNull() }
        return WidgetState(cached, sp(c).getLong("at", 0), instant, true, waking(c))
    }
}

class McWidget : GlanceAppWidget() {
    companion object {
        const val EXTRA_TAB = "mc_tab"
        const val EXTRA_SLEEP = "mc_sleep"
        private val SMALL = DpSize(110.dp, 110.dp)
        private val LARGE = DpSize(250.dp, 180.dp)

        /** Called when the app gets an event or the user acts: redraw all widgets now. */
        fun refresh(c: Context) {
            val app = c.applicationContext
            CoroutineScope(Dispatchers.Default).launch { runCatching { McWidget().updateAll(app) } }
        }
    }

    override val sizeMode = SizeMode.Responsive(setOf(SMALL, LARGE))

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val state = WidgetData.load(context)
        provideContent { Content(context, state) }
    }

    private fun open(c: Context, tab: Int, sleep: Boolean = false) = actionStartActivity(
        Intent(c, MainActivity::class.java).setAction("mc.open.$tab.$sleep")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra(EXTRA_TAB, tab).putExtra(EXTRA_SLEEP, sleep),
    )

    @Composable
    private fun Content(c: Context, st: WidgetState) {
        val large = LocalSize.current.width >= LARGE.width
        val d = st.json
        val online = d?.optJSONObject("pc")?.optBoolean("online") == true
        val cl = d?.optJSONObject("claude")
        val approvals = d?.optInt("approvals") ?: 0
        val check = d?.optJSONObject("checklist")
        val stale = !st.fresh && st.fetchedAt > 0
        val asOf = if (stale) "as of " + SimpleDateFormat("HH:mm", Locale.ROOT).format(Date(st.fetchedAt)) else null

        Column(GlanceModifier.fillMaxSize().background(ImageProvider(R.drawable.w_card)).padding(14.dp)) {
            if (!st.loggedIn || d == null) {
                Text("MISSION CONTROL", style = TextStyle(color = cAccent, fontSize = 11.sp, fontWeight = FontWeight.Bold))
                Text(
                    if (!st.loggedIn) "Open the app and log in" else "Pi not reachable",
                    style = TextStyle(color = cMuted, fontSize = 14.sp),
                    modifier = GlanceModifier.padding(top = 6.dp).clickable(open(c, 0)),
                )
                return@Column
            }
            if (large) {
                Row(GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "MISSION CONTROL", style = TextStyle(color = cAccent, fontSize = 11.sp, fontWeight = FontWeight.Bold),
                        modifier = GlanceModifier.defaultWeight(),
                    )
                    Text(asOf ?: "live", style = TextStyle(color = if (stale) cWarn else cGood, fontSize = 11.sp))
                }
                Spacer(GlanceModifier.height(6.dp))
            }
            Row(GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(GlanceModifier.defaultWeight().clickable(open(c, 0))) {
                    Text("PC", style = TextStyle(color = cMuted, fontSize = 11.sp, fontWeight = FontWeight.Bold))
                    Text(
                        if (online) "Awake" else if (st.waking) "Waking…" else "Asleep",
                        style = TextStyle(color = cText, fontSize = if (large) 24.sp else 20.sp, fontWeight = FontWeight.Bold),
                    )
                }
                Box(
                    GlanceModifier.background(ImageProvider(if (online) R.drawable.w_btn_dark else R.drawable.w_btn_accent))
                        .padding(horizontal = if (large) 16.dp else 12.dp, vertical = 10.dp)
                        .clickable(if (online) open(c, 0, sleep = true) else actionRunCallback<WakeAction>()),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        if (online) "Sleep" else "Wake",
                        style = TextStyle(color = if (online) cText else cOnAccent, fontSize = 15.sp, fontWeight = FontWeight.Bold),
                    )
                }
            }
            Spacer(GlanceModifier.height(8.dp))
            if (large) {
                Row(GlanceModifier.fillMaxWidth()) {
                    Tile(
                        c, "CLAUDE", "${cl?.optInt("working") ?: 0} working", "${cl?.optInt("waiting") ?: 0} need you",
                        cText, tab = 1, mod = GlanceModifier.defaultWeight(),
                    )
                    Spacer(GlanceModifier.width(8.dp))
                    Tile(
                        c, "APPROVALS", "$approvals", if (approvals > 0) "tap to answer" else "none waiting",
                        if (approvals > 0) cWarn else cMuted, tab = 1, mod = GlanceModifier.defaultWeight(),
                    )
                    Spacer(GlanceModifier.width(8.dp))
                    val sub = check?.let {
                        if (it.optInt("failed") > 0) "${it.optInt("failed")} failed"
                        else if (it.optBoolean("finished")) "finished" else it.optString("title").take(14)
                    }
                        ?: "no open list"
                    Tile(
                        c, "CHECKLIST", check?.let { "${it.optInt("done")}/${it.optInt("total")}" } ?: "-", sub,
                        if (check != null && check.optInt("failed") > 0) cBad else cText, tab = 2, mod = GlanceModifier.defaultWeight(),
                    )
                }
            } else {
                Tile(
                    c, "APPROVALS", "$approvals", if (approvals > 0) "Open Claude tab" else "none waiting",
                    if (approvals > 0) cWarn else cMuted, tab = 1, mod = GlanceModifier.fillMaxWidth(),
                )
            }
        }
    }

    @Composable
    private fun Tile(
        c: Context, label: String, value: String, sub: String, color: ColorProvider, tab: Int,
        mod: GlanceModifier = GlanceModifier,
    ) {
        Column(mod.background(ImageProvider(R.drawable.w_tile)).padding(10.dp).clickable(open(c, tab))) {
            Text(label, style = TextStyle(color = cMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold))
            Text(value, style = TextStyle(color = color, fontSize = 20.sp, fontWeight = FontWeight.Bold))
            Text(sub, style = TextStyle(color = cMuted, fontSize = 11.sp), maxLines = 1)
        }
    }
}

class WakeAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        // Show "Waking…" now, send in the background of this callback, and undo it if the Pi says no.
        WidgetData.setWaking(context, true)
        McWidget().updateAll(context)
        val ok = withContext(Dispatchers.IO) { runCatching { Api.post(context, "/api/pc/wake") }.isSuccess }
        if (!ok) WidgetData.setWaking(context, false)
        delay(1500)
        McWidget().updateAll(context)
    }
}

class McWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = McWidget()
}
