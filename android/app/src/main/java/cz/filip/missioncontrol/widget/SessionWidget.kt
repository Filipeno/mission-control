package cz.filip.missioncontrol.widget

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.ImageProvider
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.action.actionStartActivity
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
import cz.filip.missioncontrol.push.GateAnswerActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
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
private val cGood = ColorProvider(Color(0xFF4ADE9A))
private val cOnAccent = ColorProvider(Color(0xFF04121C))

/** Home-screen widget (stage 11e): one Claude session (the pinned one, else the one that asks, else the latest): title,
 *  last line, working / waiting, and Allow (fingerprint) + Deny (one tap) when it waits for a permission. */
class SessionWidget : GlanceAppWidget() {
    companion object {
        private fun sp(c: Context) = c.getSharedPreferences("widget", Context.MODE_PRIVATE)
        fun pin(c: Context): String = sp(c).getString("pin", "") ?: ""
        fun setPin(c: Context, id: String) { sp(c).edit().putString("pin", id).apply(); refresh(c) }

        /** Redraw all session widgets now (the app got an event, the user answered, or the 15 s tick). */
        fun refresh(c: Context) {
            val app = c.applicationContext
            CoroutineScope(Dispatchers.Default).launch { runCatching { SessionWidget().updateAll(app) } }
        }

        fun active(c: Context): Boolean = runCatching {
            AppWidgetManager.getInstance(c).getAppWidgetIds(ComponentName(c, SessionWidgetReceiver::class.java)).isNotEmpty()
        }.getOrDefault(false)

        /** The session JSON from /api/widget (cached when the Pi is out of reach); the second value says it is live. */
        suspend fun load(c: Context): Triple<JSONObject?, Boolean, Long> {
            if (Store.token(c) == null) return Triple(null, false, 0)
            val got = withContext(Dispatchers.IO) { runCatching { Api.get(c, "/api/widget?pin=" + pin(c)) }.getOrNull() }
            if (got != null) {
                val s = got.optJSONObject("session")
                sp(c).edit().putString("sjson", s?.toString() ?: "").putLong("sat", System.currentTimeMillis()).apply()
                return Triple(s, true, System.currentTimeMillis())
            }
            val cached = sp(c).getString("sjson", "")?.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() }
            return Triple(cached, false, sp(c).getLong("sat", 0))
        }
    }

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val loggedIn = Store.token(context) != null
        val (s, live, at) = load(context)
        provideContent { Content(context, loggedIn, s, live, at) }
    }

    private fun open(c: Context, sid: String) = actionStartActivity(
        Intent(c, MainActivity::class.java).setAction("mc.session.$sid")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra(McWidget.EXTRA_TAB, 1).putExtra(MainActivity.EXTRA_SESSION, sid),
    )

    /** The Allow / Deny taps go to the same invisible screen as the notification buttons (Allow: fingerprint). */
    private fun answer(c: Context, gate: JSONObject, decision: String) = actionStartActivity(
        Intent(c, GateAnswerActivity::class.java).setAction("mc.widget.${gate.optString("id")}.$decision")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra("gate", gate.optString("id")).putExtra("decision", decision).putExtra("summary", gate.optString("summary"))
            .putExtra("gkind", gate.optString("kind")).putExtra("tap", true).putExtra("notif", 0),
    )

    @Composable
    private fun Content(c: Context, loggedIn: Boolean, s: JSONObject?, live: Boolean, at: Long) {
        Column(GlanceModifier.fillMaxSize().background(ImageProvider(R.drawable.w_card)).padding(14.dp)) {
            if (!loggedIn || s == null) {
                Text("CLAUDE SESSION", style = TextStyle(color = cAccent, fontSize = 11.sp, fontWeight = FontWeight.Bold))
                Text(
                    if (!loggedIn) "Open the app and log in" else if (live) "No Claude session is running" else "Pi not reachable",
                    style = TextStyle(color = cMuted, fontSize = 14.sp),
                    modifier = GlanceModifier.padding(top = 6.dp).clickable(open(c, "")),
                )
                return@Column
            }
            val state = s.optString("state")
            val gate = s.optJSONObject("gate")
            val asks = s.optJSONObject("asks")
            val (label, color) = when {
                state == "waiting" -> "Needs you" to cWarn
                state == "working" -> "Working" to cAccent
                else -> "Idle" to cMuted
            }
            val stale = !live && at > 0
            Row(GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    (if (s.optBoolean("pinned")) "PINNED · " else "LATEST · ") + label.uppercase(),
                    style = TextStyle(color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold),
                    modifier = GlanceModifier.defaultWeight(),
                )
                if (stale) Text("as of " + SimpleDateFormat("HH:mm", Locale.ROOT).format(Date(at)), style = TextStyle(color = cWarn, fontSize = 11.sp))
            }
            Column(GlanceModifier.fillMaxWidth().padding(top = 4.dp).clickable(open(c, s.optString("id")))) {
                Text(s.optString("title"), maxLines = 1, style = TextStyle(color = cText, fontSize = 17.sp, fontWeight = FontWeight.Bold))
                val last = s.optString("last")
                if (last.isNotBlank()) Text(last, maxLines = 2, style = TextStyle(color = cMuted, fontSize = 12.sp))
            }
            if (gate != null) {
                Spacer(GlanceModifier.height(6.dp))
                Text(gate.optString("summary"), maxLines = 2, style = TextStyle(color = cText, fontSize = 12.sp))
                Spacer(GlanceModifier.height(6.dp))
                Row(GlanceModifier.fillMaxWidth()) {
                    Box(
                        GlanceModifier.defaultWeight().background(ImageProvider(R.drawable.w_btn_accent)).padding(vertical = 9.dp)
                            .clickable(answer(c, gate, "allow")), contentAlignment = Alignment.Center,
                    ) { Text("Allow", style = TextStyle(color = cOnAccent, fontSize = 14.sp, fontWeight = FontWeight.Bold)) }
                    Spacer(GlanceModifier.width(8.dp))
                    Box(
                        GlanceModifier.defaultWeight().background(ImageProvider(R.drawable.w_btn_dark)).padding(vertical = 9.dp)
                            .clickable(answer(c, gate, "deny")), contentAlignment = Alignment.Center,
                    ) { Text("Deny", style = TextStyle(color = cText, fontSize = 14.sp, fontWeight = FontWeight.Bold)) }
                }
            } else if (asks != null) {
                Spacer(GlanceModifier.height(6.dp))
                Text(
                    (if (asks.optString("kind") == "question") "Asks a question" else "Plan ready") + ": " + asks.optString("summary"),
                    maxLines = 2, style = TextStyle(color = cWarn, fontSize = 12.sp),
                    modifier = GlanceModifier.clickable(open(c, s.optString("id"))),
                )
            }
        }
    }
}

class SessionWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = SessionWidget()
}
