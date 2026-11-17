package cz.filip.missioncontrol

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import cz.filip.missioncontrol.data.Store
import cz.filip.missioncontrol.data.Updater
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.ui.graphics.Color
import cz.filip.missioncontrol.push.Notifs
import cz.filip.missioncontrol.push.EventService
import cz.filip.missioncontrol.ui.ClaudeScreen
import cz.filip.missioncontrol.ui.DocsScreen
import cz.filip.missioncontrol.ui.HomeScreen
import cz.filip.missioncontrol.ui.LoginScreen
import cz.filip.missioncontrol.ui.Mc
import cz.filip.missioncontrol.ui.McTheme
import cz.filip.missioncontrol.ui.SettingsScreen
import cz.filip.missioncontrol.ui.SystemScreen
import cz.filip.missioncontrol.ui.TodoCount
import cz.filip.missioncontrol.ui.TodoScreen
import cz.filip.missioncontrol.widget.McWidget

private data class Tab(val title: String, val icon: ImageVector, val stage: Int)

private val tabs = listOf(
    Tab("Home", Icons.Filled.Home, 3),
    Tab("Claude", Icons.Filled.Star, 4),
    Tab("Docs", Icons.Filled.List, 5),
    Tab("System", Icons.Filled.Settings, 6),
    Tab("To-do", Icons.Filled.CheckCircle, 11),
)
private const val TODO_TAB = 4

class MainActivity : FragmentActivity() {
    companion object {
        /** Set by the widget: which tab to open, and whether to ask "Put the PC to sleep?". */
        val wantTab = mutableIntStateOf(-1)
        val wantSleep = mutableStateOf(false)
        const val EXTRA_SESSION = "mc_session"
        const val EXTRA_DOC = "mc_doc"
        /** Set by a notification tap or a plan card: open this doc in the Docs tab. */
        val wantDoc = mutableStateOf("")
        /** Set by a notification tap: open this Claude session. */
        val wantSession = mutableStateOf("")
    }

    private fun readIntent(i: android.content.Intent?) {
        i?.getStringExtra(EXTRA_SESSION)?.takeIf { it.isNotBlank() }?.let { wantSession.value = it; wantTab.intValue = 1; i.removeExtra(EXTRA_SESSION) }
        i?.getStringExtra(EXTRA_DOC)?.takeIf { it.isNotBlank() }?.let { wantDoc.value = it; wantTab.intValue = 2; i.removeExtra(EXTRA_DOC) }
        val t = i?.getIntExtra(McWidget.EXTRA_TAB, -1) ?: -1
        if (t >= 0) { wantTab.intValue = t; i?.removeExtra(McWidget.EXTRA_TAB) }
        if (i?.getBooleanExtra(McWidget.EXTRA_SLEEP, false) == true) { wantSleep.value = true; i.removeExtra(McWidget.EXTRA_SLEEP) }
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        readIntent(intent)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        readIntent(intent)
        enableEdgeToEdge()
        Notifs.createChannels(this)
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        EventService.start(this)
        Store.keepBuildAddresses(this)
        kotlin.concurrent.thread { Updater.check(applicationContext) }   // at most every 12 h
        if (Store.token(this) != null) kotlin.concurrent.thread {
            runCatching { if (cz.filip.missioncontrol.data.Signer.needsRegister(this)) cz.filip.missioncontrol.data.Signer.register(this) }
        }
        setContent { McTheme { App(onLoggedIn = { EventService.start(this); askBatteryExemption(); kotlin.concurrent.thread { runCatching { cz.filip.missioncontrol.data.Signer.register(this) } } }) } }
    }

    /** Without it, Doze cuts the connection and notifications arrive late (same as the PC Waker app). */
    private fun askBatteryExemption() {
        val pm = getSystemService(android.os.PowerManager::class.java)
        if (!pm.isIgnoringBatteryOptimizations(packageName)) runCatching {
            startActivity(android.content.Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                android.net.Uri.parse("package:$packageName")))
        }
    }
}

@Composable
private fun App(onLoggedIn: () -> Unit) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var loggedIn by remember { mutableStateOf(Store.token(ctx) != null) }
    var selected by rememberSaveable { mutableIntStateOf(0) }
    var settings by rememberSaveable { mutableStateOf(false) }
    val logout = { Store.setToken(ctx, null); EventService.stop(ctx); loggedIn = false; settings = false }

    BackHandler(enabled = settings) { settings = false }
    val want = MainActivity.wantTab.intValue
    LaunchedEffect(want) { if (want >= 0) { selected = want; settings = false; MainActivity.wantTab.intValue = -1 } }

    Scaffold(
        containerColor = Mc.Bg,
        bottomBar = {
            if (loggedIn && !settings) NavigationBar(containerColor = Mc.Nav) {
                tabs.forEachIndexed { i, tab ->
                    NavigationBarItem(
                        selected = i == selected,
                        onClick = { selected = i },
                        icon = {
                            if (i == TODO_TAB && TodoCount.open > 0) BadgedBox(badge = { Badge { Text("${TodoCount.open}") } }) { Icon(tab.icon, contentDescription = null) }
                            else Icon(tab.icon, contentDescription = null)
                        },
                        label = { Text(tab.title) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Mc.Accent, selectedTextColor = Mc.Accent,
                            indicatorColor = Mc.NavSelected,
                            unselectedIconColor = Mc.NavIdle, unselectedTextColor = Mc.NavIdle,
                        ),
                    )
                }
            }
        },
    ) { inner ->
        Column(Modifier.padding(inner)) {
            if (loggedIn && !settings && Updater.updateAvailable) {
                Text("Update ${Updater.latest?.name} available · tap to install", color = Color(0xFF04121C), fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, modifier = Modifier.fillMaxWidth().background(Mc.Warn).clickable { settings = true }
                        .padding(horizontal = 16.dp, vertical = 10.dp))
            }
            val m = Modifier.weight(1f)
            when {
                !loggedIn -> LoginScreen(onDone = { loggedIn = true; onLoggedIn() }, modifier = m)
                settings -> SettingsScreen(onBack = { settings = false }, onLoggedOut = logout, modifier = m)
                selected == 0 -> HomeScreen(onSettings = { settings = true }, onLoggedOut = logout, modifier = m, onOpenTodos = { selected = TODO_TAB },
                    sleepAsk = MainActivity.wantSleep.value, onSleepAsked = { MainActivity.wantSleep.value = false })
                selected == 1 -> ClaudeScreen(onSettings = { settings = true }, onLoggedOut = logout, modifier = m)
                selected == 2 -> DocsScreen(onSettings = { settings = true }, onLoggedOut = logout, modifier = m)
                selected == TODO_TAB -> TodoScreen(onSettings = { settings = true }, onLoggedOut = logout, modifier = m)
                else -> SystemScreen(onSettings = { settings = true }, onLoggedOut = logout, modifier = m)
            }
        }
    }
}

@Composable
private fun PlaceholderTab(tab: Tab, modifier: Modifier = Modifier) {
    Column(
        modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 22.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column {
            Text("MISSION CONTROL", color = Mc.Accent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.12.em)
            Text(tab.title, color = Mc.Text, fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
        }
        Surface(
            color = Mc.Card,
            shape = RoundedCornerShape(16.dp),
            border = BorderStroke(1.dp, Mc.Border),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(Modifier.padding(16.dp)) {
                Text("COMING IN STAGE ${tab.stage}", color = Mc.Muted, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.08.em)
                Text("This tab is an empty shell for now.", color = Mc.Text, fontSize = 15.sp, modifier = Modifier.padding(top = 6.dp))
            }
        }
    }
}
