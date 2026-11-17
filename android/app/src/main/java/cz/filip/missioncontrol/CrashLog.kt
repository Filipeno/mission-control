package cz.filip.missioncontrol

import android.content.Context
import android.os.Build
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.Store
import org.json.JSONObject
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Writes uncaught exceptions to files/crash and sends them to mc-pi on the next start. */
object CrashLog {
    private fun dir(c: Context) = File(c.filesDir, "crash")

    /** Call once, as early as possible. The previous default handler still runs afterwards, so the app crashes as usual. */
    fun install(c: Context) {
        val app = c.applicationContext
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            runCatching { write(app, thread, error) }
            previous?.uncaughtException(thread, error)
        }
    }

    private fun write(c: Context, thread: Thread, error: Throwable) {
        val now = Date()
        val stack = StringWriter().also { error.printStackTrace(PrintWriter(it)) }.toString()
        val version = runCatching { c.packageManager.getPackageInfo(c.packageName, 0).versionName }.getOrNull() ?: "?"
        val text = "Time: ${SimpleDateFormat("yyyy-MM-dd HH:mm:ss Z", Locale.US).format(now)}\n" +
            "App: $version\n" +
            "Android: ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})\n" +
            "Device: ${Build.MANUFACTURER} ${Build.MODEL}\n" +
            "Thread: ${thread.name}\n\n" + stack
        val d = dir(c).also { it.mkdirs() }
        File(d, "crash-${now.time}.txt").writeText(text)
        // keep at most 5 unsent files
        d.listFiles()?.sortedBy { it.name }?.dropLast(5)?.forEach { it.delete() }
    }

    /** Background upload of saved crashes; a file is deleted only after a 2xx answer. Silent on any failure (retried next start). */
    fun sendPending(c: Context) {
        val app = c.applicationContext
        val files = dir(app).listFiles { f -> f.name.startsWith("crash-") && f.name.endsWith(".txt") } ?: return
        if (files.isEmpty() || Store.token(app) == null) return
        kotlin.concurrent.thread(name = "crash-upload", isDaemon = true) {
            for (f in files.sortedBy { it.name }) {
                try {
                    val body = JSONObject().put("name", f.name).put("text", f.readText())
                    Api.call(app, "POST", "/api/app/crash", body, timeoutMs = 15000)   // throws on non-2xx
                    f.delete()
                } catch (_: Throwable) {
                    return@thread
                }
            }
        }
    }
}
