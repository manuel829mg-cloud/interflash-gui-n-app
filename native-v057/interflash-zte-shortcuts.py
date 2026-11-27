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
import android.app.Dialog
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.view.Gravity
import android.view.Window
import android.widget.TextView

/** Only captures keys which Android actually delivers to the foreground application. */
internal object InterFlashRemoteShortcuts {
    private enum class Slot { LIVE, MOVIES, SERIES, MENU }
    private val slots = Slot.values()
    private val labels = intArrayOf(R.string.if_remote_live, R.string.if_remote_movies, R.string.if_remote_series, R.string.if_remote_menu)
    var onSection: ((Int) -> Unit)? = null
    var clientMenuEnabled = false
    private val menuLabels = intArrayOf(R.string.if_menu_live, R.string.if_menu_movies, R.string.if_menu_series)

    fun openMenu(activity: Activity): Boolean {
        if (!clientMenuEnabled || onSection == null || activity.isFinishing || activity.isDestroyed) return false
        val density = activity.resources.displayMetrics.density
        fun dp(value: Int) = (value * density + 0.5f).toInt()
        fun gradient(top: Int, bottom: Int, radius: Int, stroke: Int, color: Int) =
            GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(top, bottom)).apply {
                cornerRadius = dp(radius).toFloat()
                if (stroke > 0) setStroke(dp(stroke), color)
            }
        val panel = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(26), dp(20), dp(26), dp(22))
            background = gradient(Color.argb(246, 12, 32, 51), Color.argb(242, 5, 15, 29),
                22, 1, Color.rgb(49, 90, 121))
        }
        val heading = TextView(activity).apply {
            setText(R.string.if_menu_title)
            textSize = 25f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
        }
        panel.addView(heading, LinearLayout.LayoutParams(-1, -2).apply {
            bottomMargin = dp(16)
        })
        val row = LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        panel.addView(row, LinearLayout.LayoutParams(-1, -2))
        val dialog = Dialog(activity)
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
        dialog.setContentView(panel)
        val icons = intArrayOf(R.drawable.if_menu_icon_tv, R.drawable.if_menu_icon_movies, R.drawable.if_menu_icon_series)
        val accent = intArrayOf(Color.rgb(73, 220, 246), Color.rgb(193, 150, 255), Color.rgb(255, 197, 100))
        val topColors = intArrayOf(Color.rgb(19, 75, 97), Color.rgb(63, 42, 105), Color.rgb(91, 64, 33))
        val buttons = menuLabels.mapIndexed { index, label ->
            Button(activity).apply {
                id = View.generateViewId()
                setText(label)
                isAllCaps = false
                textSize = 20f
                typeface = Typeface.DEFAULT_BOLD
                setTextColor(Color.WHITE)
                gravity = Gravity.CENTER
                isFocusable = true
                minWidth = 0
                minimumWidth = 0
                minHeight = 0
                minimumHeight = 0
                setPadding(dp(8), dp(16), dp(8), dp(13))
                val icon = activity.getDrawable(icons[index])?.mutate()
                icon?.setTint(accent[index])
                setCompoundDrawablesWithIntrinsicBounds(null, icon, null, null)
                compoundDrawablePadding = dp(9)
                backgroundTintList = null
                background = StateListDrawable().apply {
                    addState(intArrayOf(android.R.attr.state_focused),
                        gradient(topColors[index], Color.rgb(11, 31, 48), 16, 3, accent[index]))
                    addState(intArrayOf(android.R.attr.state_pressed),
                        gradient(topColors[index], Color.rgb(11, 31, 48), 16, 3, accent[index]))
                    addState(intArrayOf(),
                        gradient(topColors[index], Color.rgb(15, 24, 38), 16, 1, Color.rgb(57, 75, 98)))
                }
                elevation = dp(2).toFloat()
                setOnFocusChangeListener { view, focused ->
                    view.animate().scaleX(if (focused) 1.035f else 1f)
                        .scaleY(if (focused) 1.035f else 1f).setDuration(130).start()
                }
                setOnClickListener {
                    dialog.dismiss()
                    onSection?.invoke(index)
                }
                row.addView(this, LinearLayout.LayoutParams(0, dp(142), 1f).apply {
                    setMargins(dp(7), dp(4), dp(7), dp(4))
                })
            }
        }
        val hint = TextView(activity).apply {
            setText(R.string.if_menu_hint)
            textSize = 13f
            setTextColor(Color.rgb(159, 190, 211))
            gravity = Gravity.CENTER
        }
        panel.addView(hint, LinearLayout.LayoutParams(-1, -2).apply {
            topMargin = dp(14)
        })
        buttons.forEachIndexed { index, button ->
            button.nextFocusLeftId = buttons[(index + buttons.size - 1) % buttons.size].id
            button.nextFocusRightId = buttons[(index + 1) % buttons.size].id
        }
        dialog.setOnKeyListener { _, code, event ->
            if (isMenuKey(activity, event)) {
                if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) dialog.dismiss()
                true
            } else false
        }
        dialog.show()
        dialog.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            setDimAmount(0.36f)
            setLayout((activity.resources.displayMetrics.widthPixels * 0.88f).toInt(), -2)
        }
        buttons.first().requestFocus()
        return true
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(InterFlashRemoteShortcuts::class.java.simpleName, Context.MODE_PRIVATE)

    private fun defaultKey(slot: Slot): Int = when (slot) {
        Slot.LIVE -> KeyEvent.KEYCODE_PROG_RED
        Slot.MOVIES -> 0
        Slot.SERIES -> KeyEvent.KEYCODE_PROG_BLUE
        Slot.MENU -> KeyEvent.KEYCODE_MENU
    }

    private fun key(context: Context, slot: Slot) = prefs(context).getInt(slot.name, defaultKey(slot))
    private fun identity(event: KeyEvent): Int =
        if (event.keyCode != KeyEvent.KEYCODE_UNKNOWN) event.keyCode else -event.scanCode

    private fun standardMenu(code: Int): Boolean = code == KeyEvent.KEYCODE_MENU ||
        code == KeyEvent.KEYCODE_TV_CONTENTS_MENU || code == KeyEvent.KEYCODE_TV_MEDIA_CONTEXT_MENU

    private fun isMenuKey(context: Context, event: KeyEvent): Boolean =
        standardMenu(event.keyCode) || (identity(event) != 0 && key(context, Slot.MENU) == identity(event))

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
                KeyEvent.KEYCODE_DEL, KeyEvent.KEYCODE_ESCAPE,
                KeyEvent.KEYCODE_TV_CONTENTS_MENU, KeyEvent.KEYCODE_TV_MEDIA_CONTEXT_MENU)
    }

    fun handle(activity: Activity, event: KeyEvent): Boolean {
        val callback = onSection ?: return false
        if (clientMenuEnabled && isMenuKey(activity, event)) {
            if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) openMenu(activity)
            return true
        }
        if (!eligible(event)) return false
        val slot = slots.firstOrNull { it != Slot.MENU && key(activity, it) == identity(event) } ?: return false
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
            if (!(eligible(event) || (slot == Slot.MENU && standardMenu(event.keyCode)))) false
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
               "Prime button - Series", "Press the desired remote button once. If nothing happens or another app opens, Android did not deliver that button.", "Reset buttons", "INTER FLASH TV", "TV en vivo", "Películas", "Series", "Menu button - Sections", "◀  ▶  Elegir     •     OK  Entrar     •     Atrás  Cerrar"],
    "values-es": ["Configurar botones del control", "Botón rojo - Canales", "Botón Netflix - Películas",
                  "Botón Prime - Series", "Pulsa una vez el botón del control. Si no ocurre nada o se abre otra aplicación, Android no entregó esa tecla.", "Restablecer botones", "INTER FLASH TV", "TV en vivo", "Películas", "Series", "Botón de tres rayas - Menú", "◀  ▶  Elegir     •     OK  Entrar     •     Atrás  Cerrar"]
}.items():
    names = ["if_tech_remote_setup", "if_remote_live", "if_remote_movies", "if_remote_series", "if_remote_press", "if_remote_reset", "if_menu_title", "if_menu_live", "if_menu_movies", "if_menu_series", "if_remote_menu", "if_menu_hint"]
    path = res / locale / "strings_interflash_remote.xml"
    path.write_text("<resources>\n" + "".join(f'    <string name="{k}">{escape(v)}</string>\n' for k,v in zip(names,strings)) + "</resources>\n", encoding="utf-8")
# Native vector artwork stays sharp at every TV resolution; no downloaded images.
icons = {
    "if_menu_icon_tv": "M5,8 L43,8 Q45,8 45,10 L45,34 Q45,36 43,36 L5,36 Q3,36 3,34 L3,10 Q3,8 5,8 M24,36 L24,42 M14,42 L34,42 M17,2 L24,8 L31,2",
    "if_menu_icon_movies": "M6,20 L42,20 L42,41 L6,41 Z M6,20 L3,11 L39,2 L42,11 L6,20 M12,9 L19,17 M24,6 L31,14 M18,25 L31,31 L18,37 Z",
    "if_menu_icon_series": "M10,5 L42,5 L42,31 M6,10 L38,10 L38,36 M3,15 L34,15 Q36,15 36,17 L36,41 Q36,43 34,43 L3,43 Q1,43 1,41 L1,17 Q1,15 3,15 M14,22 L26,29 L14,36 Z",
}
drawable = res / "drawable"
drawable.mkdir(exist_ok=True)
for name, path_data in icons.items():
    (drawable / (name + ".xml")).write_text(
        '<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="54dp" android:height="54dp" android:viewportWidth="48" android:viewportHeight="48">\n'
        '    <path android:fillColor="#00000000" android:strokeColor="#FFFFFF" android:strokeWidth="2.5" android:strokeLineCap="round" android:strokeLineJoin="round" android:pathData="' + path_data + '"/>\n'
        '</vector>\n', encoding="utf-8")
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

# The client-mode StageRail builds its own fixed navigation list, ignoring
# visibleSections. Filter that actual list so each VOD screen is independent.
edit(app / "features/shell/components/StageRail.kt",
    'val items = if (clientMode) listOf(MainSection.LIVE_TV, MainSection.MOVIES, MainSection.SERIES)',
    'val items = if (classicVod) listOf(selected) else if (clientMode) listOf(MainSection.LIVE_TV, MainSection.MOVIES, MainSection.SERIES)')
