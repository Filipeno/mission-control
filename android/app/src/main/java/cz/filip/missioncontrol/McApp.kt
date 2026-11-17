package cz.filip.missioncontrol

import android.app.Application

/**
 * Registered in the manifest so the crash catcher is in place before any activity, service or receiver starts.
 * (Application.onCreate is the earliest app code and is safe here: it only installs a handler and starts one daemon thread.)
 */
class McApp : Application() {
    override fun onCreate() {
        super.onCreate()
        CrashLog.install(this)
        CrashLog.sendPending(this)
    }
}
