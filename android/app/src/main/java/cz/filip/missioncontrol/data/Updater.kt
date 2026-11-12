package cz.filip.missioncontrol.data

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.FileProvider
import cz.filip.missioncontrol.BuildConfig
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Self-update from GitHub Releases (public repo, no login). Each release carries two files:
 *   mission-control.json  {"versionCode":10,"versionName":"0.9.0","sha256":"...","notes":"..."}
 *   mission-control.apk
 * The app compares versionCode, downloads the APK, checks its SHA-256 and hands it to Android's installer.
 * Android asks for confirmation (and "install from this source" once); updates keep data because the APK is
 * signed with the same key as the installed app.
 */
object Updater {
    private const val BASE = "https://github.com/Filipeno/mission-control/releases/latest/download"
    private const val CHECK_EVERY_MS = 12 * 3600_000L

    class Info(val code: Int, val name: String, val sha256: String, val notes: String)

    /** UI state: what the last check found. */
    var latest by mutableStateOf<Info?>(null); private set
    var status by mutableStateOf(""); private set          // "Checking…", "Up to date", "Downloading 40%", error text
    var busy by mutableStateOf(false); private set

    val installedName: String get() = BuildConfig.VERSION_NAME
    val installedCode: Int get() = BuildConfig.VERSION_CODE
    val updateAvailable: Boolean get() = (latest?.code ?: 0) > installedCode

    private fun sp(c: Context) = c.getSharedPreferences("mc", Context.MODE_PRIVATE)

    private fun open(url: String): HttpURLConnection = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 8000; readTimeout = 30000; instanceFollowRedirects = true
        setRequestProperty("User-Agent", "mission-control-app")
    }

    /** Blocking. Checks GitHub; [force] ignores the 12 h pause (used by the Check button). */
    fun check(c: Context, force: Boolean = false) {
        if (busy) return
        if (!force && System.currentTimeMillis() - sp(c).getLong("update_checked", 0) < CHECK_EVERY_MS && latest != null) return
        busy = true; status = "Checking…"
        try {
            val conn = open("$BASE/mission-control.json")
            try {
                if (conn.responseCode == 404) { status = "No release published yet"; return }
                if (conn.responseCode >= 400) { status = "GitHub answered ${conn.responseCode}"; return }
                val j = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                latest = Info(j.getInt("versionCode"), j.optString("versionName"), j.optString("sha256"), j.optString("notes"))
                sp(c).edit().putLong("update_checked", System.currentTimeMillis()).apply()
                status = if (updateAvailable) "Update ${latest!!.name} available" else "Up to date"
            } finally { conn.disconnect() }
        } catch (e: Exception) {
            status = "Could not check (no internet?)"
        } finally { busy = false }
    }

    /** Blocking. Downloads the APK and opens Android's installer. Returns an error text, or null if the installer opened. */
    fun downloadAndInstall(c: Context): String? {
        val info = latest ?: return "Check for updates first"
        if (busy) return "Busy"
        if (!c.packageManager.canRequestPackageInstalls()) {
            c.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${c.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return "Allow installing from Mission Control, then tap Install again"
        }
        busy = true; status = "Downloading…"
        try {
            val dir = File(c.cacheDir, "update").apply { mkdirs(); listFiles()?.forEach { it.delete() } }
            val apk = File(dir, "mission-control.apk")
            val conn = open("$BASE/mission-control.apk")
            val md = MessageDigest.getInstance("SHA-256")
            try {
                if (conn.responseCode >= 400) return "Download failed (${conn.responseCode})"
                val total = conn.contentLengthLong
                var done = 0L
                conn.inputStream.use { ins -> apk.outputStream().use { out ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = ins.read(buf); if (n < 0) break
                        out.write(buf, 0, n); md.update(buf, 0, n); done += n
                        if (total > 0) status = "Downloading ${done * 100 / total}%"
                    }
                } }
            } finally { conn.disconnect() }
            val sum = md.digest().joinToString("") { "%02x".format(it) }
            if (info.sha256.isNotBlank() && !sum.equals(info.sha256, ignoreCase = true)) { apk.delete(); return "Checksum does not match: not installed" }
            val uri = FileProvider.getUriForFile(c, "${c.packageName}.files", apk)
            c.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
            status = "Update ${info.name} ready: confirm in Android's installer"
            return null
        } catch (e: Exception) {
            return "Download failed: ${e.message}"
        } finally { busy = false }
    }
}
