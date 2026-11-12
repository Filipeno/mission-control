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

/**
 * Approval answers are signed with an EC P-256 key in the Android KeyStore that only works right
 * after a fingerprint (BIOMETRIC_STRONG, every single use). mc-pi has the public key and checks
 * each signature, so a stolen login token alone cannot approve anything.
 */
object Signer {
    private const val ALIAS = "mc_approve_key2"          // v2: fingerprint, strong face or the phone PIN
    private const val OLD_ALIAS = "mc_approve_key"

    private fun ks() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    /** The public key (X.509 SubjectPublicKeyInfo, base64), creating the key pair if needed. */
    fun publicKey(): String {
        val ks = ks()
        if (!ks.containsAlias(ALIAS)) {
            val b = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .setInvalidatedByBiometricEnrollment(true)
            if (Build.VERSION.SDK_INT >= 30) b.setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL)
            else @Suppress("DEPRECATION") b.setUserAuthenticationValidityDurationSeconds(-1)
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply { initialize(b.build()) }
                .generateKeyPair()
        }
        return Base64.encodeToString(ks.getCertificate(ALIAS).publicKey.encoded, Base64.NO_WRAP)
    }

    /** Sends the public key to mc-pi (once per login). Blocking. */
    fun register(c: Context) {
        val pk = publicKey()
        Api.post(c, "/api/keys", org.json.JSONObject().put("public_key", pk))
        c.getSharedPreferences("mc", Context.MODE_PRIVATE).edit().putString("registered_key", pk.takeLast(40)).apply()
        runCatching { ks().deleteEntry(OLD_ALIAS) }
    }

    /** True when the Pi has not seen this phone's current key yet (a new key after an update). */
    fun needsRegister(c: Context): Boolean = runCatching {
        c.getSharedPreferences("mc", Context.MODE_PRIVATE).getString("registered_key", null) != publicKey().takeLast(40)
    }.getOrDefault(true)

    /** Drop the key (e.g. after new fingerprints made it unusable); the next answer makes and registers a new one. */
    fun reset() = runCatching { ks().deleteEntry(ALIAS) }

    /**
     * Shows the fingerprint prompt, then signs [message]. Calls [done] with the base64 DER signature,
     * or with null and a reason when cancelled or failed.
     */
    fun sign(a: FragmentActivity, title: String, message: String, done: (String?, String?) -> Unit) {
        val sig = try {
            publicKey()
            Signature.getInstance("SHA256withECDSA").apply { initSign(ks().getKey(ALIAS, null) as PrivateKey) }
        } catch (e: android.security.keystore.KeyPermanentlyInvalidatedException) {
            reset(); done(null, "Fingerprints changed: the signing key was reset. Try again."); return
        } catch (e: Exception) {
            done(null, "Signing key error: ${e.message}"); return
        }
        val prompt = BiometricPrompt(a, ContextCompat.getMainExecutor(a), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(r: BiometricPrompt.AuthenticationResult) {
                try {
                    val s = r.cryptoObject!!.signature!!
                    s.update(message.toByteArray())
                    done(Base64.encodeToString(s.sign(), Base64.NO_WRAP), null)
                } catch (e: Exception) {
                    done(null, "Signing failed: ${e.message}")
                }
            }
            override fun onAuthenticationError(code: Int, err: CharSequence) = done(null, err.toString())
        })
        prompt.authenticate(
            BiometricPrompt.PromptInfo.Builder()
                .setTitle("Confirm with fingerprint")
                .setSubtitle(title)
                .setAllowedAuthenticators(if (Build.VERSION.SDK_INT >= 30) BIOMETRIC_STRONG or androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL else BIOMETRIC_STRONG)
                .apply { if (Build.VERSION.SDK_INT < 30) setNegativeButtonText("Cancel") }
                .build(),
            BiometricPrompt.CryptoObject(sig),
        )
    }
}
