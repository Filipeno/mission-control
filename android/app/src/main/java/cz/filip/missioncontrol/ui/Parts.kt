package cz.filip.missioncontrol.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun McCard(modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(18.dp)
    val border = BorderStroke(1.dp, Mc.Border)
    if (onClick != null) {
        Surface(onClick = onClick, color = Mc.Card, shape = shape, border = border, modifier = modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), content = content)
        }
    } else {
        Surface(color = Mc.Card, shape = shape, border = border, modifier = modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), content = content)
        }
    }
}

@Composable
fun Label(text: String, color: Color = Mc.Muted) =
    Text(text.uppercase(), color = color, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.1.em)

@Composable
fun Header(title: String) {
    Column {
        Text("MISSION CONTROL", color = Mc.Accent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.12.em)
        Text(title, color = Mc.Text, fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
    }
}

private val hm = SimpleDateFormat("HH:mm", Locale.ROOT)
private val dhm = SimpleDateFormat("d.M. HH:mm", Locale.ROOT)

/** Unix seconds -> "07:52" today, "8.11. 07:52" otherwise. */
fun clock(unixS: Double): String {
    val d = Date((unixS * 1000).toLong())
    val today = SimpleDateFormat("yyyyMMdd", Locale.ROOT)
    return if (today.format(d) == today.format(Date())) hm.format(d) else dhm.format(d)
}

fun duration(s: Long): String = when {
    s < 3600 -> "${s / 60} min"
    s < 86400 -> "${s / 3600} h"
    else -> "${s / 86400} d"
}

/** Material "power settings new" icon (not in material-icons-core). */
val PowerIcon: ImageVector = ImageVector.Builder("power", 24.dp, 24.dp, 24f, 24f).addPath(
    pathData = addPathNodes(
        "M13,3h-2v10h2L13,3zM17.83,5.17l-1.42,1.42C17.99,7.86 19,9.81 19,12c0,3.87 -3.13,7 -7,7s-7,-3.13 -7,-7" +
            "c0,-2.19 1.01,-4.14 2.58,-5.42L6.17,5.17C4.23,6.82 3,9.26 3,12c0,4.97 4.03,9 9,9s9,-4.03 9,-9c0,-2.74 -1.23,-5.18 -3.17,-6.83z"
    ),
    fill = SolidColor(Color.Black),
).build()
