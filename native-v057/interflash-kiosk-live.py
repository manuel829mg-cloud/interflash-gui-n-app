#!/usr/bin/env python3
"""Live-only test variant; keep existing playback engines and account gates."""
from pathlib import Path
root=Path("native-source/InterFlashTV-OwnTV/app/src/main")
app=root/"java/tv/own/owntv"
def edit(p, pairs):
    s=p.read_text()
    for old,new in pairs:
        expected = 2 if old.startswith("onPickAvatar = {") else 1
        assert s.count(old)==expected, f"{p}: expected {expected} anchor(s) {old!r}, found {s.count(old)}"
        s=s.replace(old,new)
    p.write_text(s)
shell=app/"features/shell/OwnTVShell.kt"
edit(shell, [
('val channel = liveVm.lastWatchedLiveChannel()?.takeIf { liveVm.isVisibleToActiveProfile(it) }',
 'val channel = liveVm.lastWatchedLiveChannel()?.takeIf { liveVm.isVisibleToActiveProfile(it) } ?: liveVm.interFlashFirstChannel()'),
('            clientMode && playerMode == PlayerMode.FULLSCREEN -> {\n                if (zapSource == MainSection.MOVIES || zapSource == MainSection.SERIES) exitPlayer() else dockPlayer()\n                onSelectSection(zapSource ?: MainSection.LIVE_TV)\n                restoreFocus = true\n            }',
 '            clientMode -> {\n                if (playerMode == PlayerMode.FULLSCREEN) showChannelList = !showChannelList\n            }'),
('if (clientMode && section !in listOf(MainSection.LIVE_TV, MainSection.MOVIES, MainSection.SERIES)) return@openSection',
 'if (clientMode) { if (playerMode == PlayerMode.FULLSCREEN) showChannelList = true; return@openSection }'),
('visibleSections = visibleSections,','visibleSections = if (clientMode) setOf(MainSection.LIVE_TV) else visibleSections,'),
('onPickAvatar = {\n                    InterFlashClientMode.administrator = !InterFlashClientMode.administrator\n                    onSelectSection(if (InterFlashClientMode.administrator) MainSection.SETTINGS else MainSection.LIVE_TV)\n                },',
 'onPickAvatar = { if (!clientMode) onSelectSection(MainSection.SETTINGS) },'),
('onBack = { if (clientMode) { if (zapSource == MainSection.MOVIES || zapSource == MainSection.SERIES) exitPlayer() else dockPlayer(); onSelectSection(zapSource ?: MainSection.LIVE_TV) } else exitPlayer() },',
 'onBack = { if (clientMode) showChannelList = !showChannelList else exitPlayer() },'),
('onPip = dockPlayer,','onPip = { if (!clientMode) dockPlayer() },'),
('onAudioMode = toAudioMode,','onAudioMode = { if (!clientMode) toAudioMode() },'),
('onOpenChannelList = if (isTunedLive && liveCanZap) { { showChannelList = true } } else null,',
 'onOpenChannelList = if (isTunedLive && (clientMode || liveCanZap)) { { showChannelList = true } } else null,'),
('onOpenHistoryList = if (isTunedLive) { { showHistoryList = true } } else null,',
 'onOpenHistoryList = if (isTunedLive) { { if (clientMode) showChannelList = true else showHistoryList = true } } else null,'),
('if (e.key != Key.Back) return@onPreviewKeyEvent false',
 'if (e.key != Key.Back) return@onPreviewKeyEvent false\n                if (clientMode && playerMode == PlayerMode.FULLSCREEN && !showChannelList) {\n                    if (e.type == KeyEventType.KeyUp && !e.nativeKeyEvent.isCanceled) showChannelList = true\n                    return@onPreviewKeyEvent true\n                }'),
])
vm=app/"features/live/LiveViewModel.kt"
edit(vm,[('    suspend fun lastWatchedLiveChannel(): ChannelEntity? {','    suspend fun interFlashFirstChannel(): ChannelEntity? = channelsInRail(LiveKey.All).firstOrNull { isVisibleToActiveProfile(it) }\n\n    suspend fun lastWatchedLiveChannel(): ChannelEntity? {')])
hud=app/"player/PlayerHud.kt"
edit(hud,[('            // ---- Direct-tune digit capture (before the existing KeyDown guard) ----',
'''            // Live-only client: ordinary OK or horizontal arrow opens the channel overlay.
            if (onOpenChannelList != null && !inert && !controlsVisible && !digitsActive &&
                dialog == HudDialog.NONE && (isPlayerOkKey(e.key) ||
                e.key == Key.DirectionLeft || e.key == Key.DirectionRight)) {
                if (e.type == KeyEventType.KeyUp && !e.nativeKeyEvent.isCanceled) onOpenChannelList()
                return@onPreviewKeyEvent true
            }
            // ---- Direct-tune digit capture (before the existing KeyDown guard) ----''')])
# Android lock task is only enabled if this device has been explicitly provisioned.
# No screen-pinning fallback: that would require a customer confirmation and is escapable.
main=app/"MainActivity.kt"
edit(main,[('    override fun onStart() {','''    override fun onResume() {
        super.onResume()
        runCatching {
            val dpm = getSystemService(android.app.admin.DevicePolicyManager::class.java) ?: return@runCatching
            if (dpm.isDeviceOwnerApp(packageName)) {
                dpm.setLockTaskPackages(android.content.ComponentName(this, InterFlashDeviceAdmin::class.java), arrayOf(packageName))
            }
            if (dpm.isLockTaskPermitted(packageName)) startLockTask()
        }
    }

    override fun onStart() {''')])
(app/"InterFlashDeviceAdmin.kt").write_text('package tv.own.owntv\n\nclass InterFlashDeviceAdmin : android.app.admin.DeviceAdminReceiver()\n')
(root/"res/xml/interflash_device_admin.xml").write_text('<device-admin xmlns:android="http://schemas.android.com/apk/res/android"><uses-policies /></device-admin>\n')
edit(root/"AndroidManifest.xml",[('        <!-- Exposes the downloaded update APK to the system installer. -->','''        <receiver android:name=".InterFlashDeviceAdmin"
            android:permission="android.permission.BIND_DEVICE_ADMIN"
            android:exported="true">
            <meta-data android:name="android.app.device_admin" android:resource="@xml/interflash_device_admin" />
            <intent-filter><action android:name="android.app.action.DEVICE_ADMIN_ENABLED" /></intent-filter>
        </receiver>
        <!-- Exposes the downloaded update APK to the system installer. -->''')])
tech=app/"InterFlashTechDialog.kt"
s=tech.read_text()
# Authorized exits release managed lock task; return keeps it enabled.
for token in ['val home = Intent(Intent.ACTION_MAIN)', 'try { activity.startActivity(Intent(Settings.ACTION_SETTINGS)) }']:
    s=s.replace(token,'runCatching { activity.stopLockTask() }\n            '+token)
tech.write_text(s)
print("Applied live-only navigation and optional managed lock task")
