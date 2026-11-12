package cz.filip.missioncontrol.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cz.filip.missioncontrol.data.Api
import cz.filip.missioncontrol.data.ApiError
import cz.filip.missioncontrol.data.Store
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Asked once: the same password as the PC Waker page. mc-pi returns a long-lived token. */
@Composable
fun LoginScreen(onDone: () -> Unit, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf(Store.baseUrl(ctx)) }
    var pw by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    Column(
        modifier.fillMaxSize().imePadding().padding(horizontal = 16.dp, vertical = 22.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Header("Log in")
        McCard {
            Text("Same password as the PC Waker page. You only enter it once.", color = Mc.Muted, fontSize = 14.sp)
            OutlinedTextField(
                value = url, onValueChange = { url = it }, label = { Text("Pi address") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            )
            OutlinedTextField(
                value = pw, onValueChange = { pw = it }, label = { Text("Password") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            error?.let { Text(it, color = Mc.Bad, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp)) }
            Button(
                onClick = {
                    busy = true; error = null
                    scope.launch {
                        try {
                            Store.setBaseUrl(ctx, url)
                            if (pw.startsWith("mctoken:")) {
                                // An existing app token (e.g. from `mcpi.py token-add` for test devices): check it, no password.
                                Store.setToken(ctx, pw.removePrefix("mctoken:").trim())
                                try { withContext(Dispatchers.IO) { Api.get(ctx, "/api/settings") } }
                                catch (e: ApiError) { Store.setToken(ctx, null); throw e }
                                pw = ""; onDone(); return@launch
                            }
                            val r = withContext(Dispatchers.IO) {
                                Api.post(ctx, "/api/login", JSONObject().put("password", pw).put("device", android.os.Build.MODEL))
                            }
                            Store.setToken(ctx, r.getString("token"))
                            pw = ""
                            onDone()
                        } catch (e: ApiError) {
                            error = e.message
                        } finally {
                            busy = false
                        }
                    }
                },
                enabled = !busy && pw.isNotEmpty() && url.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Mc.Accent, contentColor = Color(0xFF04121C)),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth().padding(top = 14.dp).height(50.dp),
            ) { Text(if (busy) "Checking…" else "Log in", fontSize = 16.sp) }
        }
    }
}
