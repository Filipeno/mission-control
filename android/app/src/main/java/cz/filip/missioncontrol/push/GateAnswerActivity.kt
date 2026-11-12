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
        thread {
            val reg = runCatching { if (Signer.needsRegister(app)) Signer.register(app); true }.getOrDefault(false)
            runOnUiThread {
                if (!reg) { toast("Could not reach the Pi to register the key"); return@runOnUiThread finish() }
                val ts = System.currentTimeMillis() / 1000
                Signer.sign(this, (if (decision == "allow") "Allow: " else "Deny: ") + summary.take(80), "gate|$gate|$decision||$ts") { sig, err ->
                    if (sig == null) { toast(err ?: "Cancelled"); return@sign finish() }
                    thread {
                        val msg = try {
                            Api.post(app, "/api/gate/$gate/answer", JSONObject().put("decision", decision).put("payload", "").put("ts", ts).put("sig", sig))
                            app.getSystemService(NotificationManager::class.java).cancel(notif)
                            if (decision == "allow") "Allowed" else "Denied"
                        } catch (e: Exception) { e.message ?: "Failed" }
                        runOnUiThread { toast(msg); finish() }
                    }
                }
            }
        }
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
