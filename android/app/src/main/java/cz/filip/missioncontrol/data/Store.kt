package cz.filip.missioncontrol.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import cz.filip.missioncontrol.BuildConfig
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** App settings on the phone. The mc-pi token is encrypted with a key kept in the Android KeyStore. */
object Store {
    private const val KEY_ALIAS = "mc_token_key"

    private fun sp(c: Context) = c.getSharedPreferences("mc", Context.MODE_PRIVATE)

    fun baseUrl(c: Context): String = sp(c).getString("base", null) ?: BuildConfig.PI_URL
    fun setBaseUrl(c: Context, url: String) = sp(c).edit().putString("base", url.trim().trimEnd('/')).apply()

    fun token(c: Context): String? = sp(c).getString("tok", null)?.let { runCatching { decrypt(it) }.getOrNull() }
    fun setToken(c: Context, t: String?) {
        sp(c).edit().apply { if (t == null) remove("tok") else putString("tok", encrypt(t)) }.apply()
    }

    /** Public tunnel address: only /api/events is reachable there (notifications outside home). */
    fun remoteUrl(c: Context): String = sp(c).getString("remote", null) ?: BuildConfig.REMOTE_URL

    /**
     * Release builds from GitHub carry no addresses (the repo is public). A build made on the PC does, so keep
     * them in the app's own settings once: later updates from GitHub then still know where the Pi is.
     */
    fun keepBuildAddresses(c: Context) {
        val e = sp(c).edit()
        if (!sp(c).contains("base") && BuildConfig.PI_URL.isNotBlank()) e.putString("base", BuildConfig.PI_URL)
        if (!sp(c).contains("remote") && BuildConfig.REMOTE_URL.isNotBlank()) e.putString("remote", BuildConfig.REMOTE_URL)
        e.apply()
    }

    /** Short text for the Settings screen ("Registered with ntfy", "ntfy app not installed", ...). */
    fun pushStatus(c: Context): String = sp(c).getString("push_status", "Starting…") ?: ""
    fun setPushStatus(c: Context, s: String) = sp(c).edit().putString("push_status", s).apply()
    fun lastPushAt(c: Context): Long = sp(c).getLong("last_push", 0)
    fun setLastPushAt(c: Context, t: Long) = sp(c).edit().putLong("last_push", t).apply()

    // ------------------------------------------------------------ KeyStore AES-GCM

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
        )
        return gen.generateKey()
    }

    private fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val out = cipher.iv + cipher.doFinal(plain.toByteArray())
        return Base64.encodeToString(out, Base64.NO_WRAP)
    }

    private fun decrypt(stored: String): String {
        val all = Base64.decode(stored, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, all.copyOfRange(0, 12)))
        return String(cipher.doFinal(all.copyOfRange(12, all.size)))
    }
}
