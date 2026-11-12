package cz.filip.missioncontrol.push

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.Color
import cz.filip.missioncontrol.MainActivity
import cz.filip.missioncontrol.R
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.Store
import org.json.JSONObject
import kotlin.concurrent.thread

private const val TAG = "mc-push"

/** Notification channels and how a message from mc-pi becomes a notification. */
object Notifs {
    private val channels = listOf(
        Triple("claude", "Claude", NotificationManager.IMPORTANCE_HIGH),
        Triple("sleep", "PC & sleep", NotificationManager.IMPORTANCE_HIGH),
        Triple("room", "Room", NotificationManager.IMPORTANCE_DEFAULT),
        Triple("system", "System", NotificationManager.IMPORTANCE_DEFAULT),
        Triple("quiet", "Quiet hours (silent)", NotificationManager.IMPORTANCE_LOW),
    )

    fun createChannels(c: Context) {
        val nm = c.getSystemService(NotificationManager::class.java)
        for ((id, name, imp) in channels) {
            nm.createNotificationChannel(NotificationChannel(id, name, imp).apply {
                enableLights(true); lightColor = Color.CYAN
            })
        }
    }

    private fun idFor(group: String) = group.hashCode() and 0x7fffffff

    fun show(c: Context, m: JSONObject) {
        createChannels(c)
        val nm = c.getSystemService(NotificationManager::class.java)
        val group = m.optString("group").ifBlank { m.optString("id") }
        if (m.optString("kind") == "cancel") {
            nm.cancel(idFor(group)); return
        }
        val channel = if (m.optBoolean("quiet")) "quiet" else when (m.optString("cat")) {
            "claude", "sleep", "room" -> m.optString("cat")
            else -> "system"
        }
        val sid = m.optString("sid")
        val open = PendingIntent.getActivity(
            c, idFor(group) and 0xffff, Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .apply { if (sid.isNotBlank()) putExtra(MainActivity.EXTRA_SESSION, sid) },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val body = m.optString("body")
        val b = android.app.Notification.Builder(c, channel)
            .setSmallIcon(R.drawable.ic_stat_mc)
            .setColor(0xFF4CC2FF.toInt())
            .setContentTitle(m.optString("title"))
            .setContentText(body.lineSequence().firstOrNull() ?: "")
            .setStyle(android.app.Notification.BigTextStyle().bigText(body))
            .setContentIntent(open)
            .setAutoCancel(true)
        val actions = m.optJSONArray("actions")
        for (i in 0 until (actions?.length() ?: 0)) {
            val a = actions!!.getJSONObject(i)
            val intent = Intent(c, ActionReceiver::class.java)
                .putExtra("post", a.optString("post"))
                .putExtra("body", a.optJSONObject("body")?.toString() ?: "{}")
                .putExtra("notif", idFor(group))
            val pi = PendingIntent.getBroadcast(
                c, idFor(group) * 4 + i, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            b.addAction(android.app.Notification.Action.Builder(null, a.optString("label"), pi).build())
        }
        // A permission request: Allow / Deny right in the notification (fingerprint, strong face or PIN asked first).
        if (m.optString("kind") == "claude-gate" && m.optString("gkind") != "question" && m.optString("gate").isNotBlank()) {
            for ((i, d) in listOf("allow" to "Allow", "deny" to "Deny").withIndex()) {
                val pi = PendingIntent.getActivity(c, (idFor(group) and 0xfff) * 8 + 4 + i,
                    Intent(c, GateAnswerActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_HISTORY)
                        .putExtra("gate", m.optString("gate")).putExtra("decision", d.first)
                        .putExtra("summary", m.optString("summary")).putExtra("notif", idFor(group)),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
                b.addAction(android.app.Notification.Action.Builder(null, d.second, pi).build())
            }
        }
        runCatching { nm.notify(idFor(group), b.build()) }   // fails only without notification permission
    }
}

/** A button in a notification: mc-pi forwards it to pc-waker (only allow-listed calls). */
class ActionReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, intent: Intent) {
        val done = goAsync()
        val app = c.applicationContext
        thread {
            try {
                Api.post(app, "/api/action", JSONObject()
                    .put("post", intent.getStringExtra("post"))
                    .put("body", JSONObject(intent.getStringExtra("body") ?: "{}")))
                app.getSystemService(NotificationManager::class.java).cancel(intent.getIntExtra("notif", 0))
            } catch (e: Exception) {
                android.util.Log.w(TAG, "action failed: ${e.message}")
            } finally {
                done.finish()
            }
        }
    }
}
