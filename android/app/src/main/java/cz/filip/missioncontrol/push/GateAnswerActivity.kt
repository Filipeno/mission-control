package cz.filip.missioncontrol.push

import android.app.NotificationManager
import android.os.Bundle
import android.widget.Toast
import androidx.fragment.app.FragmentActivity
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.Signer
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * Invisible screen behind the Allow / Deny buttons of a permission notification: shows the system
 * fingerprint / face / PIN prompt (with what will be allowed), signs the answer and posts it, then closes.
 */
class GateAnswerActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val gate = intent.getStringExtra("gate") ?: return finish()
        val decision = intent.getStringExtra("decision") ?: return finish()
        val summary = intent.getStringExtra("summary") ?: ""
        val notif = intent.getIntExtra("notif", 0)
        val app = applicationContext
        val oneTapDeny = decision == "deny"     // fingerprint option C: any Deny is one tap (the Pi takes an unsigned Deny)
        if (intent.getStringExtra("gkind") == "appcard" && decision != "deny" && !intent.getBooleanExtra("tap", false)) return finish()  // notification: no Allow for app cards
        if (oneTapDeny) {
            // Any Deny (notification, app card, widget): one tap, no fingerprint (the Pi takes an unsigned answer only as Deny).
            app.getSystemService(NotificationManager::class.java).cancel(notif)
            toast("Deny sent to the PC")
            thread {
                try {
                    Api.post(app, "/api/gate/$gate/answer", JSONObject().put("decision", "deny").put("payload", ""))
                    cz.filip.missioncontrol.widget.SessionWidget.refresh(app)
                } catch (e: Exception) {
                    android.os.Handler(android.os.Looper.getMainLooper()).post {
                        Toast.makeText(app, "Not sent: ${e.message ?: "failed"}. Answer it in the app.", Toast.LENGTH_LONG).show()
                    }
                }
            }
            return finish()
        }
        thread {
            val reg = runCatching { if (Signer.needsRegister(app)) Signer.register(app); true }.getOrDefault(false)
            runOnUiThread {
                if (!reg) { toast("Could not reach the Pi to register the key"); return@runOnUiThread finish() }
                val ts = System.currentTimeMillis() / 1000
                // The Pi's tier for this Allow (fingerprint option C): "M" = the 5-minute window, else a prompt every time.
                val tier = if (decision == "allow" && intent.getStringExtra("tier") == "M") "M" else "H"
                Signer.sign(this, (if (decision == "allow") "Allow: " else "Deny: ") + summary.take(80), "gate|$gate|$decision||$ts", tier) { sig, err ->
                    if (sig == null) { toast(err ?: "Cancelled"); return@sign finish() }
                    // Fingerprint done: close the notification and the screen now; the answer goes out in the background.
                    val nm = app.getSystemService(NotificationManager::class.java)
                    nm.cancel(notif)
                    toast(if (decision == "allow") "Allowed" else "Denied")
                    thread {
                        try {
                            Api.post(app, "/api/gate/$gate/answer", JSONObject().put("decision", decision).put("payload", "").put("ts", ts).put("sig", sig))
                            cz.filip.missioncontrol.widget.SessionWidget.refresh(app)
                        } catch (e: Exception) {
                            android.os.Handler(android.os.Looper.getMainLooper()).post {
                                Toast.makeText(app, "Not sent: ${e.message ?: "failed"}. Answer it in the app.", Toast.LENGTH_LONG).show()
                            }
                        }
                    }
                    finish()
                }
            }
        }
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
