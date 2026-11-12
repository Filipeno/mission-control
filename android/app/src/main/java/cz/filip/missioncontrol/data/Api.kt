package cz.filip.missioncontrol.data

import android.content.Context
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

class ApiError(val code: Int, message: String) : Exception(message)

/** Blocking calls to mc-pi. Call from Dispatchers.IO or a background thread. */
object Api {
    fun call(c: Context, method: String, path: String, body: JSONObject? = null, timeoutMs: Int = 8000): JSONObject {
        val base = Store.baseUrl(c)
        if (base.isBlank()) throw ApiError(0, "No Pi address set")
        val conn = try {
            URL(base + path).openConnection() as HttpURLConnection
        } catch (e: Exception) {
            throw ApiError(0, "Bad Pi address")
        }
        try {
            conn.requestMethod = method
            conn.connectTimeout = 4000
            conn.readTimeout = timeoutMs
            Store.token(c)?.let { conn.setRequestProperty("Authorization", "Bearer $it") }
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val code = conn.responseCode
            val text = (if (code < 400) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            val json = runCatching { JSONObject(text) }.getOrElse { JSONObject() }
            if (code >= 400) throw ApiError(code, json.optString("error").ifBlank { "Error $code" })
            return json
        } catch (e: IOException) {
            throw ApiError(0, "Pi not reachable (home Wi-Fi or VPN?)")
        } finally {
            conn.disconnect()
        }
    }

    /** Raw bytes (pictures) or an upload of raw bytes (audio). Blocking. */
    fun bytes(c: Context, path: String, upload: ByteArray? = null, contentType: String = "application/octet-stream"): ByteArray {
        val conn = URL(Store.baseUrl(c) + path).openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = 4000
            conn.readTimeout = 30000
            Store.token(c)?.let { conn.setRequestProperty("Authorization", "Bearer $it") }
            if (upload != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", contentType)
                conn.outputStream.use { it.write(upload) }
            }
            if (conn.responseCode >= 400) throw ApiError(conn.responseCode, "Error ${conn.responseCode}")
            return conn.inputStream.use { it.readBytes() }
        } catch (e: IOException) {
            throw ApiError(0, "Pi not reachable (home Wi-Fi or VPN?)")
        } finally {
            conn.disconnect()
        }
    }

    fun get(c: Context, path: String) = call(c, "GET", path)
    fun post(c: Context, path: String, body: JSONObject = JSONObject()) = call(c, "POST", path, body)
}
