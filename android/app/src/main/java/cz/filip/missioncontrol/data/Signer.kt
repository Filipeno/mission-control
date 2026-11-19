package cz.filip.missioncontrol.data

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import kotlin.concurrent.thread

/**
 * Answers to mc-pi are signed with EC P-256 keys in the Android KeyStore, so a stolen login token alone cannot
 * approve anything. Fingerprint option C (Filip, 2026-11-19), two keys:
 *  - the every-time key (tier "H"): a fingerprint / strong face / PIN prompt for each single signature;
 *  - the 5-minute window key (tier "M"): one prompt opens a window of [WINDOW_S] seconds in which M answers
 *    are signed without a prompt. mc-pi takes it only for M answers, and only after the H key vouched for it.
 * Tier "0" answers (Deny, option picks) are not signed at all. mc-pi decides the tier; the app follows it.
 */
object Signer {
    private const val ALIAS = "mc_approve_key2"          // v2: fingerprint, strong face or the phone PIN
    private const val OLD_ALIAS = "mc_approve_key"
    private const val WALIAS = "mc_window_key1"          // tier M: usable for WINDOW_S after a strong unlock
    const val WINDOW_S = 300

    private fun ks() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private fun prefs(c: Context) = c.getSharedPreferences("mc", Context.MODE_PRIVATE)

    /** The public key (X.509 SubjectPublicKeyInfo, base64), creating the key pair if needed. */
    fun publicKey(): String = key(ALIAS, 0)

    /** The 5-minute window key's public key, creating it if needed. */
    fun windowPublicKey(): String = key(WALIAS, WINDOW_S)

    private fun key(alias: String, seconds: Int): String {
        val ks = ks()
        if (!ks.containsAlias(alias)) {
            val b = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .setInvalidatedByBiometricEnrollment(true)
            // API 26-29: a validity duration > 0 makes a time-bound key (any lock-screen PIN or fingerprint within the
            // window unlocks it; new fingerprints do not invalidate it there). -1 = a prompt for every use.
            if (Build.VERSION.SDK_INT >= 30) b.setUserAuthenticationParameters(seconds, KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL)
            else @Suppress("DEPRECATION") b.setUserAuthenticationValidityDurationSeconds(if (seconds > 0) seconds else -1)
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply { initialize(b.build()) }
                .generateKeyPair()
        }
        return Base64.encodeToString(ks.getCertificate(alias).publicKey.encoded, Base64.NO_WRAP)
    }

    /**
     * Sends the every-time key to mc-pi (once per login). Blocking. A login's first key is taken as is; a different key
     * later needs a new login (mc-pi refuses to swap it, so a stolen token cannot plant its own key).
     */
    fun register(c: Context) {
        val pk = publicKey()
        Api.post(c, "/api/keys", org.json.JSONObject().put("public_key", pk))
        prefs(c).edit().putString("registered_key", pk.takeLast(40)).remove("registered_wkey").apply()
        runCatching { ks().deleteEntry(OLD_ALIAS) }
    }

    /** True when the Pi has not seen this phone's current key yet (a new key after an update). */
    fun needsRegister(c: Context): Boolean = runCatching {
        prefs(c).getString("registered_key", null) != publicKey().takeLast(40)
    }.getOrDefault(true)

    /** Forget that the window key is registered (a new login, or mc-pi refused it): the next M answer registers it again. */
    fun forgetWindowKey(c: Context) = prefs(c).edit().remove("registered_wkey").apply()

    /** Drop the key (e.g. after new fingerprints made it unusable); the next answer makes and registers a new one. */
    fun reset() = runCatching { ks().deleteEntry(ALIAS); ks().deleteEntry(WALIAS) }

    /**
     * Signs [message] for an answer of [tier] ("H", or "M" = the 5-minute window; anything else is treated as "H").
     * Calls [done] on the main thread with the base64 DER signature, or with null and a reason when cancelled or failed.
     * M: no prompt while the window is open; else one prompt opens it. If the window key can't be used (an old Pi,
     * a weak face unlock on API 28-29, ...) it falls back to the every-time key, which mc-pi takes for M too.
     */
    fun sign(a: FragmentActivity, title: String, message: String, tier: String = "H", done: (String?, String?) -> Unit) {
        if (tier != "M") return signH(a, title, message, done)
        val c = a.applicationContext
        val wpk = try { windowPublicKey() } catch (e: Exception) { return signH(a, title, message, done) }
        if (prefs(c).getString("registered_wkey", null) != wpk.takeLast(40)) {
            // First M answer of this login: the every-time key vouches for the window key (this prompt also opens the window).
            val ts = System.currentTimeMillis() / 1000
            signH(a, "Unlock answers for 5 minutes", "keyreg|m|$wpk|$ts") { sig, err ->
                if (sig == null) return@signH done(null, err)
                thread {
                    val ok = runCatching { Api.post(c, "/api/keys/window", org.json.JSONObject().put("public_key", wpk).put("ts", ts).put("sig", sig)) }.isSuccess
                    if (ok) prefs(c).edit().putString("registered_wkey", wpk.takeLast(40)).apply()
                    a.runOnUiThread { if (ok) signWindow(a, title, message, done) else signH(a, title, message, done) }
                }
            }
            return
        }
        signWindow(a, title, message, done)
    }

    private fun windowOpen(c: Context): Boolean {
        val age = System.currentTimeMillis() / 1000 - prefs(c).getLong("window_at", 0L)
        return age >= 0L && age < WINDOW_S - 5L
    }

    private fun markWindow(c: Context) = prefs(c).edit().putLong("window_at", System.currentTimeMillis() / 1000).apply()

    /** Signs with the window key; null when the KeyStore wants a fresh unlock first. */
    private fun trySignWindow(message: String): String? = try {
        Signature.getInstance("SHA256withECDSA").run {
            initSign(ks().getKey(WALIAS, null) as PrivateKey)
            update(message.toByteArray())
            Base64.encodeToString(sign(), Base64.NO_WRAP)
        }
    } catch (e: android.security.keystore.KeyPermanentlyInvalidatedException) {
        runCatching { ks().deleteEntry(WALIAS) }; null
    } catch (e: Exception) { null }

    private fun signWindow(a: FragmentActivity, title: String, message: String, done: (String?, String?) -> Unit) {
        val c = a.applicationContext
        // The app's own clock as well as the KeyStore's: unlocking the phone alone must not open the window.
        if (windowOpen(c)) trySignWindow(message)?.let { return done(it, null) }
        val prompt = BiometricPrompt(a, ContextCompat.getMainExecutor(a), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(r: BiometricPrompt.AuthenticationResult) {
                markWindow(c)
                val sig = trySignWindow(message)
                if (sig != null) done(sig, null) else signH(a, title, message, done)   // the unlock did not reach the key
            }
            override fun onAuthenticationError(code: Int, err: CharSequence) = done(null, err.toString())
        })
        prompt.authenticate(promptInfo(title, "Confirm: opens a 5-minute window"))
    }

    private fun promptInfo(subtitle: String, title: String = "Confirm with fingerprint") = BiometricPrompt.PromptInfo.Builder()
        .setTitle(title)
        .setSubtitle(subtitle)
        .setAllowedAuthenticators(if (Build.VERSION.SDK_INT >= 30) BIOMETRIC_STRONG or androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL else BIOMETRIC_STRONG)
        .apply { if (Build.VERSION.SDK_INT < 30) setNegativeButtonText("Cancel") }
        .build()

    /** The every-time key: a prompt bound to this one signature. A success also opens the 5-minute window. */
    private fun signH(a: FragmentActivity, title: String, message: String, done: (String?, String?) -> Unit) {
        val sig = try {
            publicKey()
            Signature.getInstance("SHA256withECDSA").apply { initSign(ks().getKey(ALIAS, null) as PrivateKey) }
        } catch (e: android.security.keystore.KeyPermanentlyInvalidatedException) {
            reset(); done(null, "Fingerprints changed: the signing key was reset. Log out and log in again (Settings) to use the new key."); return
        } catch (e: Exception) {
            done(null, "Signing key error: ${e.message}"); return
        }
        val prompt = BiometricPrompt(a, ContextCompat.getMainExecutor(a), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(r: BiometricPrompt.AuthenticationResult) {
                try {
                    val s = r.cryptoObject!!.signature!!
                    s.update(message.toByteArray())
                    markWindow(a.applicationContext)
                    done(Base64.encodeToString(s.sign(), Base64.NO_WRAP), null)
                } catch (e: Exception) {
                    done(null, "Signing failed: ${e.message}")
                }
            }
            override fun onAuthenticationError(code: Int, err: CharSequence) = done(null, err.toString())
        })
        prompt.authenticate(promptInfo(title), BiometricPrompt.CryptoObject(sig))
    }
}
