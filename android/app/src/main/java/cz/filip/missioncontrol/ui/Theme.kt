package cz.filip.missioncontrol.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Style A (dark dashboard) colors from the approved mockups. */
object Mc {
    val Bg = Color(0xFF0B0E14)
    val Card = Color(0xFF141922)
    val Border = Color(0xFF232B38)
    val Text = Color(0xFFE6EAF2)
    val Muted = Color(0xFF9AA4B5)
    val Accent = Color(0xFF4CC2FF)
    val Warn = Color(0xFFFFB547)
    val Good = Color(0xFF4ADE9A)
    val GoodBg = Color(0xFF0F2A1F)
    val Bad = Color(0xFFFF6B6B)
    val Idle = Color(0xFF6B7385)
    val ButtonDark = Color(0xFF1B2230)
    val Nav = Color(0xFF0F131B)
    val NavSelected = Color(0xFF13202C)
    val NavIdle = Color(0xFF8C96A8)
}

@Composable
fun McTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Mc.Accent, onPrimary = Color(0xFF04121C),
            background = Mc.Bg, onBackground = Mc.Text,
            surface = Mc.Card, onSurface = Mc.Text,
            surfaceVariant = Mc.Card, onSurfaceVariant = Mc.Muted,
            outline = Mc.NavIdle, tertiary = Mc.Warn,
        ),
        content = content,
    )
}
