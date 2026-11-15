import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

// Machine-specific values (Pi address) live in mc.local.properties, which is git-ignored.
val mcLocal = Properties().apply {
    val f = rootProject.file("mc.local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

// Command-line builds (gradlew -PcliBuild) use their own folder, so an open Android Studio can't lock them.
if (project.hasProperty("cliBuild")) layout.buildDirectory.set(rootProject.file("build-cli/app"))

android {
    namespace = "cz.filip.missioncontrol"
    compileSdk {
        version = release(37) { minorApiLevel = 2 }
    }
    defaultConfig {
        applicationId = "cz.filip.missioncontrol"
        minSdk = 26
        targetSdk = 36
        versionCode = 16
        versionName = "0.10.0"
        // -PpublicBuild (tools/release.ps1): no addresses inside the APK, because it is published on GitHub.
        val publicBuild = project.hasProperty("publicBuild")
        buildConfigField("String", "PI_URL", "\"${if (publicBuild) "" else mcLocal.getProperty("mc.piUrl", "")}\"")
        buildConfigField("String", "REMOTE_URL", "\"${if (publicBuild) "" else mcLocal.getProperty("mc.remoteUrl", "")}\"")
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons.core)
    implementation(libs.androidx.biometric)
    implementation(libs.androidx.glance.appwidget)
    debugImplementation(libs.compose.ui.tooling)
}
