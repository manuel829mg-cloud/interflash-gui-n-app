#!/usr/bin/env python3
"""Keep normal live playback full screen; use Android lock-task only when administrator permits it."""
from pathlib import Path
app = Path("native-source/InterFlashTV-OwnTV/app/src/main/java/tv/own/owntv")
def edit(path, old, new):
    s = path.read_text(encoding="utf-8")
    assert s.count(old) == 1, f"Unexpected anchor in {path}: {old[:100]}"
    path.write_text(s.replace(old, new, 1), encoding="utf-8")
shell = app / "features/shell/OwnTVShell.kt"
edit(shell, "    BackHandler {", """    val interFlashMaintenance = tv.own.owntv.InterFlashKiosk.maintenance.value
    val interFlashLiveLocked = !interFlashMaintenance && playerMode == PlayerMode.FULLSCREEN &&
        zapSource == MainSection.LIVE_TV
    val interFlashActivity = androidx.compose.ui.platform.LocalContext.current as? android.app.Activity
    LaunchedEffect(interFlashLiveLocked, interFlashActivity) {
        if (interFlashLiveLocked) interFlashActivity?.let {
            tv.own.owntv.InterFlashKiosk.enterIfPermitted(it)
        }
    }
    BackHandler {""")
edit(shell, "            clientMode && playerMode == PlayerMode.FULLSCREEN -> {", """            interFlashLiveLocked -> Unit
            clientMode && playerMode == PlayerMode.FULLSCREEN -> {""")
edit(shell, "onBack = { if (clientMode) { if (zapSource == MainSection.MOVIES || zapSource == MainSection.SERIES) exitPlayer() else dockPlayer(); onSelectSection(zapSource ?: MainSection.LIVE_TV) } else exitPlayer() },", "onBack = { if (!interFlashLiveLocked) { if (clientMode) { if (zapSource == MainSection.MOVIES || zapSource == MainSection.SERIES) exitPlayer() else dockPlayer(); onSelectSection(zapSource ?: MainSection.LIVE_TV) } else exitPlayer() } },")
(app / "InterFlashKiosk.kt").write_text(r'''package tv.own.owntv

import android.app.Activity
import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import androidx.compose.runtime.mutableStateOf

internal object InterFlashKiosk {
    val maintenance = mutableStateOf(false)

    fun enterIfPermitted(activity: Activity) {
        if (maintenance.value) return
        val policy = activity.getSystemService(DevicePolicyManager::class.java) ?: return
        val manager = activity.getSystemService(ActivityManager::class.java) ?: return
        // Never fall back to screen pinning or try to self-provision a device.
        if (policy.isLockTaskPermitted(activity.packageName) &&
            manager.lockTaskModeState == ActivityManager.LOCK_TASK_MODE_NONE) {
            runCatching { activity.startLockTask() }
        }
    }

    fun unlock(activity: Activity) {
        maintenance.value = true
        val manager = activity.getSystemService(ActivityManager::class.java) ?: return
        if (manager.lockTaskModeState == ActivityManager.LOCK_TASK_MODE_LOCKED) {
            runCatching { activity.stopLockTask() }
        }
    }

    fun returnToTv(activity: Activity) {
        maintenance.value = false
        enterIfPermitted(activity)
    }
}
''', encoding="utf-8")
tech = app / "InterFlashTechDialog.kt"
edit(tech, "        addOption(activity.getString(R.string.if_tech_go_home)) {\n            dialog.dismiss()", "        addOption(activity.getString(R.string.if_tech_go_home)) {\n            InterFlashKiosk.unlock(activity)\n            dialog.dismiss()")
edit(tech, "        addOption(activity.getString(R.string.if_tech_settings)) {\n            dialog.dismiss()", "        addOption(activity.getString(R.string.if_tech_settings)) {\n            InterFlashKiosk.unlock(activity)\n            dialog.dismiss()")
edit(tech, "        addOption(activity.getString(R.string.if_tech_return)) { dialog.dismiss() }", """        addOption(activity.getString(R.string.if_tech_return)) {
            InterFlashKiosk.returnToTv(activity)
            dialog.dismiss()
        }
        addOption(activity.getString(R.string.if_tech_unlock_menu)) {
            InterFlashKiosk.unlock(activity)
            dialog.dismiss()
        }""")
edit(tech, "            safeButton(activity.getString(R.string.if_tech_settings)) {\n                try", "            safeButton(activity.getString(R.string.if_tech_settings)) {\n                InterFlashKiosk.unlock(activity)\n                try")
res = app.parent.parent.parent.parent.parent / "res"
# Use the same known resource root as the technician script.
res = Path("native-source/InterFlashTV-OwnTV/app/src/main/res")
for locale, label in (("values", "Unlock TV menus"), ("values-es", "Desbloquear menús de TV")):
    p = res / locale / "strings_interflash_tech.xml"
    edit(p, "</resources>", f'    <string name="if_tech_unlock_menu">{label}</string>\n</resources>')
print("Added guarded live Back and administrator-authorized kiosk integration; physical Home requires device provisioning.")
