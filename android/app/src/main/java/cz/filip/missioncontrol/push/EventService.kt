package cz.filip.missioncontrol.push

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.IBinder
import cz.filip.missioncontrol.MainActivity
import cz.filip.missioncontrol.R
import cz.filip.missioncontrol.data.Store
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Keeps one long-poll open to mc-pi's /api/events and shows each event as a notification.
 * At home (Wi-Fi/VPN) it uses the Pi address; otherwise the public tunnel address, which only
 * passes /api/events. No Firebase, no ntfy app.
 */
class EventService : Service() {
    companion object {
        private const val LISTEN_ID = 1
        private const val CH_LISTEN = "listen"
        private const val WAIT_S = 50              // under Cloudflare's 100 s limit
        private const val MAX_BACKOFF_MS = 120_000L

        fun start(c: Context) {
            if (Store.token(c) == null) return
            try {
                c.startForegroundService(Intent(c, EventService::class.java))
            } catch (e: RuntimeException) {
                // Not allowed from the background right now; the next app start retries.
            }
        }

        fun stop(c: Context) = c.stopService(Intent(c, EventService::class.java))
    }

    /** Restarts the listener after a reboot or an app update. */
    class Starter : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) = start(c)
    }

    @Volatile private var running = false
    @Volatile private var current: HttpURLConnection? = null
    private var worker: Thread? = null
    private val wakeUp = Object()
    private var shown = ""
    private lateinit var netCallback: ConnectivityManager.NetworkCallback

    override fun onCreate() {
        super.onCreate()
        Notifs.createChannels(this)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CH_LISTEN, "Listening for the Pi", NotificationManager.IMPORTANCE_MIN))
        val n = listening("Connecting to the Pi…")
        if (Build.VERSION.SDK_INT >= 34) startForeground(LISTEN_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(LISTEN_ID, n)
        // Network changed (Wi-Fi <-> mobile, VPN): drop the old connection and retry at once.
        netCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = kick()
        }
        getSystemService(ConnectivityManager::class.java).registerDefaultNetworkCallback(netCallback)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (worker == null) {
            running = true
            worker = Thread(::loop, "mc-events").apply { start() }
            // The session widget shows working / waiting, which has no push event: redraw it every 15 s while one is on a home screen.
            Thread {
                while (running) {
                    try { Thread.sleep(15_000) } catch (e: InterruptedException) { break }
                    if (running && cz.filip.missioncontrol.widget.SessionWidget.active(this)) cz.filip.missioncontrol.widget.SessionWidget.refresh(this)
                }
            }.apply { isDaemon = true; name = "mc-widget-tick"; start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        kick()
        runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(netCallback) }
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun sp() = getSharedPreferences("events", MODE_PRIVATE)

    private fun loop() {
        var backoff = 5_000L
        var preferRemote = false
        while (running) {
            val token = Store.token(this)
            if (token == null) { status("Log in to get notifications"); pause(60_000); continue }
            val bases = listOf(Store.baseUrl(this), Store.remoteUrl(this)).filter { it.isNotBlank() }.distinct()
                .let { if (preferRemote) it.reversed() else it }
            var ok = false
            for (base in bases) {
                if (!running) break
                val since = sp().getLong("since", -1)
                val q = if (since < 0) "?wait=0" else "?since=$since&wait=$WAIT_S"
                val local = base == Store.baseUrl(this)
                var c: HttpURLConnection? = null
                try {
                    c = URL("$base/api/events$q").openConnection() as HttpURLConnection
                    c.connectTimeout = if (local) 4_000 else 10_000
                    c.readTimeout = (WAIT_S + 20) * 1000
                    c.useCaches = false
                    c.setRequestProperty("Authorization", "Bearer $token")
                    current = c
                    val code = c.responseCode
                    if (code == 401) { status("Logged out: open Mission Control and log in"); pause(300_000); ok = true; break }
                    if (code != 200) throw java.io.IOException("HTTP $code")
                    val body = JSONObject(c.inputStream.bufferedReader().use { it.readText() })
                    val events = body.getJSONArray("events")
                    for (i in 0 until events.length()) {
                        Store.setLastPushAt(this, System.currentTimeMillis())
                        Notifs.show(this, events.getJSONObject(i))
                    }
                    if (events.length() > 0) { cz.filip.missioncontrol.widget.McWidget.refresh(this); cz.filip.missioncontrol.widget.SessionWidget.refresh(this) }
                    sp().edit().putLong("since", body.getLong("last")).apply()
                    status(if (local) "Connected (home)" else "Connected (tunnel)")
                    Store.setPushStatus(this, if (local) "Connected at home" else "Connected through the tunnel")
                    preferRemote = !local
                    ok = true
                    backoff = 5_000
                    break
                } catch (e: Exception) {
                    if (!running) break
                } finally {
                    current = null
                    c?.disconnect()
                }
            }
            if (!ok && running) {
                status("Can't reach the Pi. Retrying…")
                Store.setPushStatus(this, "Can't reach the Pi")
                preferRemote = !preferRemote
                pause(backoff)
                backoff = (backoff * 2).coerceAtMost(MAX_BACKOFF_MS)
            }
        }
    }

    private fun kick() {
        current?.let { c -> Thread { c.disconnect() }.start() }
        synchronized(wakeUp) { wakeUp.notifyAll() }
    }

    private fun pause(ms: Long) = synchronized(wakeUp) { runCatching { wakeUp.wait(ms) } }

    private fun status(s: String) {
        if (s == shown) return
        shown = s
        getSystemService(NotificationManager::class.java).notify(LISTEN_ID, listening(s))
    }

    private fun listening(text: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Builder(this, CH_LISTEN)
            .setSmallIcon(R.drawable.ic_stat_mc)
            .setContentTitle("Mission Control")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }
}
