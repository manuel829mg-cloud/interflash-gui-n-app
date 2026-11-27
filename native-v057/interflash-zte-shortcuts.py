#!/usr/bin/env python3
"""PIN-gated remote key learning, with in-app TV, movies and series shortcuts."""
from pathlib import Path
from xml.sax.saxutils import escape
app = Path("native-source/InterFlashTV-OwnTV/app/src/main/java/tv/own/owntv")
def edit(path, before, after):
    s = path.read_text(encoding="utf-8")
    assert s.count(before) == 1, f"Unexpected source: {path}: {before}"
    path.write_text(s.replace(before, after, 1), encoding="utf-8")

edit(app / "MainActivity.kt",
    "    override fun dispatchKeyEvent(event: KeyEvent): Boolean {",
    """    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (InterFlashRemoteShortcuts.handle(this, event)) return true""")
edit(app / "MainActivity.kt",
    "                        InterFlashTechDialog.show(this)\n                        return true\n                    }",
    """                        InterFlashTechDialog.show(this)
                        return true
                    }
                    if (started >= 0L && !event.isCanceled && event.eventTime - started >= 2_000L &&
                        InterFlashRemoteShortcuts.openMenu(this)) return true""")
edit(app / "InterFlashTechDialog.kt",
    "        addOption(activity.getString(R.string.if_tech_return)) { dialog.dismiss() }",
    """        addOption(activity.getString(R.string.if_tech_remote_setup)) {
            InterFlashRemoteShortcuts.configure(activity)
        }
        addOption(activity.getString(R.string.if_tech_return)) { dialog.dismiss() }""")

edit(app / "features/shell/OwnTVShell.kt",
    "    val interFlashLiveBackground = selectedSection == MainSection.LIVE_TV",
    """    androidx.compose.runtime.DisposableEffect(Unit) {
        onDispose {
            tv.own.owntv.InterFlashRemoteShortcuts.onSection = null
            tv.own.owntv.InterFlashRemoteShortcuts.clientMenuEnabled = false
        }
    }
    androidx.compose.runtime.SideEffect {
        tv.own.owntv.InterFlashRemoteShortcuts.clientMenuEnabled = clientMode
        tv.own.owntv.InterFlashRemoteShortcuts.onSection = { slot ->
            when (slot) {
                0 -> openShortcutSection(MainSection.LIVE_TV)
                1 -> openShortcutSection(MainSection.MOVIES)
                2 -> openShortcutSection(MainSection.SERIES)
                else -> Unit
            }
        }
    }
    val interFlashLiveBackground = selectedSection == MainSection.LIVE_TV""")

(app / "InterFlashRemoteShortcuts.kt").write_text(r'''package tv.own.owntv

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.view.KeyEvent
import android.view.View
import android.widget.Button
import android.widget.LinearLayout

/** Only captures keys which Android actually delivers to the foreground application. */
internal object InterFlashRemoteShortcuts {
    private enum class Slot { LIVE, MOVIES, SERIES }
    private val slots = Slot.values()
    private val labels = intArrayOf(R.string.if_remote_live, R.string.if_remote_movies, R.string.if_remote_series)
    var onSection: ((Int) -> Unit)? = null
    var clientMenuEnabled = false
    private val menuLabels = intArrayOf(R.string.if_menu_live, R.string.if_menu_movies, R.string.if_menu_series)

    fun openMenu(activity: Activity): Boolean {
        if (!clientMenuEnabled || onSection == null || activity.isFinishing || activity.isDestroyed) return false
        val density = activity.resources.displayMetrics.density
        fun dp(value: Int) = (value * density + 0.5f).toInt()
        val row = LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(16), dp(12), dp(16), dp(20))
        }
        val dialog = AlertDialog.Builder(activity)
            .setTitle(R.string.if_menu_title)
            .setView(row)
            .create()
        val buttons = menuLabels.mapIndexed { index, label ->
            Button(activity).apply {
                id = View.generateViewId()
                setText(label)
                textSize = 20f
                isFocusable = true
                setOnClickListener {
                    dialog.dismiss()
                    onSection?.invoke(index)
                }
                row.addView(this, LinearLayout.LayoutParams(0, dp(76), 1f).apply {
                    setMargins(dp(6), 0, dp(6), 0)
                })
            }
        }
        buttons.forEachIndexed { index, button ->
            button.nextFocusLeftId = buttons[(index + buttons.size - 1) % buttons.size].id
            button.nextFocusRightId = buttons[(index + 1) % buttons.size].id
        }
        dialog.setOnKeyListener { _, code, event ->
            if (code == KeyEvent.KEYCODE_MENU) {
                if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) dialog.dismiss()
                true
            } else false
        }
        dialog.show()
        dialog.window?.setLayout((activity.resources.displayMetrics.widthPixels * 0.88f).toInt(), -2)
        buttons.first().requestFocus()
        return true
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(InterFlashRemoteShortcuts::class.java.simpleName, Context.MODE_PRIVATE)

    private fun defaultKey(slot: Slot): Int = when (slot) {
        Slot.LIVE -> KeyEvent.KEYCODE_PROG_RED
        Slot.MOVIES -> 0
        Slot.SERIES -> KeyEvent.KEYCODE_PROG_BLUE
    }

    private fun key(context: Context, slot: Slot) = prefs(context).getInt(slot.name, defaultKey(slot))
    private fun identity(event: KeyEvent): Int =
        if (event.keyCode != KeyEvent.KEYCODE_UNKNOWN) event.keyCode else -event.scanCode

    private fun eligible(event: KeyEvent): Boolean {
        val code = event.keyCode
        return identity(event) != 0 && code !in KeyEvent.KEYCODE_0..KeyEvent.KEYCODE_9 &&
            code !in KeyEvent.KEYCODE_NUMPAD_0..KeyEvent.KEYCODE_NUMPAD_9 &&
            code !in KeyEvent.KEYCODE_DPAD_UP..KeyEvent.KEYCODE_DPAD_CENTER &&
            code !in listOf(KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER,
                KeyEvent.KEYCODE_BACK, KeyEvent.KEYCODE_HOME, KeyEvent.KEYCODE_POWER,
                KeyEvent.KEYCODE_VOLUME_UP, KeyEvent.KEYCODE_VOLUME_DOWN,
                KeyEvent.KEYCODE_VOLUME_MUTE, KeyEvent.KEYCODE_MUTE, KeyEvent.KEYCODE_MENU,
                KeyEvent.KEYCODE_CHANNEL_UP, KeyEvent.KEYCODE_CHANNEL_DOWN,
                KeyEvent.KEYCODE_DEL, KeyEvent.KEYCODE_ESCAPE)
    }

    fun handle(activity: Activity, event: KeyEvent): Boolean {
        val callback = onSection ?: return false
        if (clientMenuEnabled && event.keyCode == KeyEvent.KEYCODE_MENU) {
            if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) openMenu(activity)
            return true
        }
        if (!eligible(event)) return false
        val slot = slots.firstOrNull { key(activity, it) == identity(event) } ?: return false
        if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) callback(slot.ordinal)
        return true
    }

    fun configure(activity: Activity) {
        AlertDialog.Builder(activity)
            .setTitle(R.string.if_tech_remote_setup)
            .setItems(labels.map { activity.getString(it) }.toTypedArray()) { _, which ->
                learn(activity, slots[which])
            }
            .setNeutralButton(R.string.if_remote_reset) { _, _ -> prefs(activity).edit().clear().apply() }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun learn(activity: Activity, slot: Slot) {
        val dialog = AlertDialog.Builder(activity)
            .setTitle(labels[slot.ordinal])
            .setMessage(R.string.if_remote_press)
            .setNegativeButton(android.R.string.cancel, null)
            .create()
        dialog.setOnKeyListener { _, _, event ->
            if (!eligible(event)) false
            else {
                if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) {
                    val captured = identity(event)
                    val editor = prefs(activity).edit()
                    slots.filter { it != slot && key(activity, it) == captured }.forEach {
                        editor.putInt(it.name, 0)
                    }
                    editor.putInt(slot.name, captured).apply()
                    dialog.dismiss()
                }
                true
            }
        }
        dialog.show()
    }
}
''', encoding="utf-8")

res = Path("native-source/InterFlashTV-OwnTV/app/src/main/res")
for locale, strings in {
    "values": ["Configure remote buttons", "Red button - Live TV", "Netflix button - Movies",
               "Prime button - Series", "Press the desired remote button once. If nothing happens or another app opens, Android did not deliver that button.", "Reset buttons", "INTER FLASH TV", "TV en vivo", "Películas", "Series"],
    "values-es": ["Configurar botones del control", "Botón rojo - Canales", "Botón Netflix - Películas",
                  "Botón Prime - Series", "Pulsa una vez el botón del control. Si no ocurre nada o se abre otra aplicación, Android no entregó esa tecla.", "Restablecer botones", "INTER FLASH TV", "TV en vivo", "Películas", "Series"]
}.items():
    names = ["if_tech_remote_setup", "if_remote_live", "if_remote_movies", "if_remote_series", "if_remote_press", "if_remote_reset", "if_menu_title", "if_menu_live", "if_menu_movies", "if_menu_series"]
    path = res / locale / "strings_interflash_remote.xml"
    path.write_text("<resources>\n" + "".join(f'    <string name="{k}">{escape(v)}</string>\n' for k,v in zip(names,strings)) + "</resources>\n", encoding="utf-8")
print("ZTE remote shortcuts added; branded buttons require real-device learning.")

# Decoder-style live playback. Explicit section shortcuts are the only way
# to leave live video for the VOD catalog; ordinary Back never docks it.
shell = app / "features/shell/OwnTVShell.kt"
edit(shell, 'val channel = liveVm.lastWatchedLiveChannel()?.takeIf { liveVm.isVisibleToActiveProfile(it) }',
    'val channel = liveVm.lastWatchedLiveChannel()?.takeIf { liveVm.isVisibleToActiveProfile(it) } ?: liveVm.interFlashFirstChannel()')
edit(app / "features/live/LiveViewModel.kt", '    suspend fun lastWatchedLiveChannel(): ChannelEntity? {',
    '    suspend fun interFlashFirstChannel(): ChannelEntity? = channelsInRail(LiveKey.All).firstOrNull { isVisibleToActiveProfile(it) }\n\n    suspend fun lastWatchedLiveChannel(): ChannelEntity? {')
edit(shell, '    val dockPlayer = {\n        resumeVideo()\n        playerMode = PlayerMode.MINI\n        restoreFocus = true\n        focusRail()\n        Unit\n    }',
    '''    val dockPlayer = {
        if (!(clientMode && zapSource == MainSection.LIVE_TV)) {
            resumeVideo()
            playerMode = PlayerMode.MINI
            restoreFocus = true
            focusRail()
        }
        Unit
    }''')
edit(shell, '    val toAudioMode = {\n        (if (liveOnExo) liveVm.previewEngine else mpvEngine).enterAudioOnly()\n        playerMode = PlayerMode.AUDIO\n        restoreFocus = true\n        focusRail()\n        Unit\n    }',
    '''    val toAudioMode = {
        if (!(clientMode && zapSource == MainSection.LIVE_TV)) {
            (if (liveOnExo) liveVm.previewEngine else mpvEngine).enterAudioOnly()
            playerMode = PlayerMode.AUDIO
            restoreFocus = true
            focusRail()
        }
        Unit
    }''')
edit(shell, '        if (playerMode == PlayerMode.FULLSCREEN) dockPlayer()\n        if (section == MainSection.SEARCH)',
    '''        if (clientMode) {
            liveShortcutJob?.cancel()
            if (section == MainSection.LIVE_TV) {
                if (zapSource == MainSection.LIVE_TV && playerMode == PlayerMode.FULLSCREEN) return@openSection
                if (playerMode != PlayerMode.NONE) exitPlayer()
                onSelectSection(MainSection.LIVE_TV)
                liveVm.select(tv.own.owntv.core.live.LiveKey.All)
                liveShortcutJob = scope.launch {
                    val channel = liveVm.lastWatchedLiveChannel()?.takeIf { liveVm.isVisibleToActiveProfile(it) }
                        ?: liveVm.interFlashFirstChannel()
                    if (channel != null) {
                        zapSource = MainSection.LIVE_TV
                        liveVm.watchFullscreen(channel, emptyList())
                        playerMode = PlayerMode.FULLSCREEN
                    }
                }
                return@openSection
            }
            if (playerMode != PlayerMode.NONE) exitPlayer()
            liveVm.stopPreview()
            homeVm.stopPreview()
            if (section == MainSection.MOVIES) movieVm.select(tv.own.owntv.core.live.LiveKey.All)
            if (section == MainSection.SERIES) seriesVm.select(tv.own.owntv.core.live.LiveKey.All)
        } else if (playerMode == PlayerMode.FULLSCREEN) dockPlayer()
        if (section == MainSection.SEARCH)''')
edit(shell, '    val openShortcutSection: (MainSection) -> Unit = openSection@{ section ->',
    '    var liveShortcutJob by remember { mutableStateOf<kotlinx.coroutines.Job?>(null) }\n    val openShortcutSection: (MainSection) -> Unit = openSection@{ section ->')
edit(shell, '            clientMode && playerMode == PlayerMode.FULLSCREEN -> {',
    '            clientMode && playerMode == PlayerMode.FULLSCREEN && zapSource == MainSection.LIVE_TV -> Unit\n            clientMode && playerMode == PlayerMode.FULLSCREEN -> {')
edit(shell, '                    onBack = { if (clientMode) { if (zapSource == MainSection.MOVIES || zapSource == MainSection.SERIES) exitPlayer() else dockPlayer(); onSelectSection(zapSource ?: MainSection.LIVE_TV) } else exitPlayer() },',
    '                    onBack = { if (clientMode && zapSource == MainSection.LIVE_TV) Unit else if (clientMode) { exitPlayer(); onSelectSection(zapSource ?: MainSection.LIVE_TV) } else exitPlayer() },')
edit(shell, '                                playerMode = PlayerMode.MINI\n                            },\n                            onPreviewVideoBoundsChanged',
    '                                playerMode = if (clientMode) PlayerMode.FULLSCREEN else PlayerMode.MINI\n                            },\n                            onPreviewVideoBoundsChanged')
