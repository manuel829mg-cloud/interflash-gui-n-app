#!/usr/bin/env python3
"""Add Inter Flash's hidden 10s-OK technician dialog to the stable native TV app.

This script runs only on the isolated experiment branch, after the stable 0.70
layout adjustments. It preserves the app's normal short-OK dispatch and player.
"""
from pathlib import Path

APP = Path("native-source/InterFlashTV-OwnTV/app/src/main/java/tv/own/owntv")
main_file = APP / "MainActivity.kt"
source = main_file.read_text(encoding="utf-8")
anchor = "open class MainActivity : ComponentActivity() {"
assert source.count(anchor) == 1, "Unexpected MainActivity; refusing to edit"
assert "InterFlashTechDialog.show(this)" not in source, "Already patched"
assert "import android.view.KeyEvent" not in source, "KeyEvent import already exists"

source = source.replace(
    "import android.view.WindowManager\n",
    "import android.view.WindowManager\nimport android.view.KeyEvent\n",
    1,
)

handler = """open class MainActivity : ComponentActivity() {
    // Technician shortcut: OK held for 10 seconds, confirmed on release.
    // KeyDown and short KeyUp still go through the original player/Compose handlers.
    private var interFlashTechOkDownAtMs = -1L

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val okKey = event.keyCode == KeyEvent.KEYCODE_DPAD_CENTER ||
            event.keyCode == KeyEvent.KEYCODE_ENTER ||
            event.keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER
        if (okKey) {
            when (event.action) {
                KeyEvent.ACTION_DOWN -> {
                    if (event.repeatCount == 0) interFlashTechOkDownAtMs = event.eventTime
                }
                KeyEvent.ACTION_UP -> {
                    val started = interFlashTechOkDownAtMs
                    interFlashTechOkDownAtMs = -1L
                    if (started >= 0L && !event.isCanceled &&
                        event.eventTime - started >= 10_000L
                    ) {
                        // Consume the long KeyUp so the player's regular OK action
                        // does not also run after opening the technician PIN menu.
                        InterFlashTechDialog.show(this)
                        return true
                    }
                }
                else -> Unit
            }
        }
        return super.dispatchKeyEvent(event)
    }

"""
source = source.replace(anchor, handler, 1)
assert "override fun onStop() {" in source, "Missing onStop()"
source = source.replace("override fun onStop() {\n", "override fun onStop() {\ninterFlashTechOkDownAtMs = -1L\n", 1)
main_file.write_text(source, encoding="utf-8")

(APP / "InterFlashTechDialog.kt").write_text(
    r'''package tv.own.owntv

import android.app.Activity
import android.app.Dialog
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.provider.Settings
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.GridLayout
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Hidden in-player menu for technicians, opened only after holding OK for 10 seconds.
 * The PIN only gates buttons inside Inter Flash TV; it cannot lock system-level Settings.
 */
internal object InterFlashTechDialog {
    private val TECH_PIN = (8 * 1111).toString()

    fun show(activity: Activity) {
        if (activity.isFinishing || activity.isDestroyed) return

        val pixelsPerDp = activity.resources.displayMetrics.density
        fun dp(value: Int) = (value * pixelsPerDp + 0.5f).toInt()

        val dialog = Dialog(activity)
        val root = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(28), dp(24), dp(28), dp(24))
            setBackgroundColor(Color.rgb(12, 24, 38))
        }

        val heading = TextView(activity).apply {
            text = activity.getString(R.string.if_tech_title)
            setTextColor(Color.WHITE)
            textSize = 25f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
        }
        root.addView(heading, LinearLayout.LayoutParams(-1, -2))

        val indicators = TextView(activity).apply {
            setTextColor(Color.WHITE)
            textSize = 29f
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, 0)
        }
        root.addView(indicators, LinearLayout.LayoutParams(-1, -2))

        val message = TextView(activity).apply {
            text = activity.getString(R.string.if_tech_enter_pin)
            textSize = 16f
            setTextColor(Color.LTGRAY)
            gravity = Gravity.CENTER
            setPadding(0, dp(6), 0, dp(9))
        }
        root.addView(message, LinearLayout.LayoutParams(-1, -2))

        val keypad = GridLayout(activity).apply {
            columnCount = 3
        }
        root.addView(keypad)

        val options = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        root.addView(options)

        var authorized = false
        val pin = StringBuilder()
        var firstKey: Button? = null

        fun drawPin() {
            indicators.text = activity.getString(R.string.if_tech_filled).repeat(pin.length) + activity.getString(R.string.if_tech_empty).repeat(4 - pin.length)
        }

        fun addOption(title: String, action: () -> Unit) {
            val b = Button(activity).apply {
                text = title
                textSize = 17f
                setOnClickListener { if (authorized) action() }
            }
            options.addView(b, LinearLayout.LayoutParams(dp(450), dp(56)))
        }

        addOption(activity.getString(R.string.if_tech_go_home)) {
            dialog.dismiss()
            val home = Intent(Intent.ACTION_MAIN).apply {
                addCategory(Intent.CATEGORY_HOME)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            try { activity.startActivity(home) }
            catch (_: Exception) { activity.moveTaskToBack(true) }
        }
        addOption(activity.getString(R.string.if_tech_settings)) {
            dialog.dismiss()
            try { activity.startActivity(Intent(Settings.ACTION_SETTINGS)) }
            catch (_: Exception) { }
        }
        addOption(activity.getString(R.string.if_tech_return)) { dialog.dismiss() }
        addOption(activity.getString(R.string.if_tech_safe_start)) {
            // Show a technician-only launch menu with the two Android shortcuts.
            // This is an in-app equivalent, not the device's separate boot screen.
            val safeDialog = Dialog(activity)
            val safeRoot = LinearLayout(activity).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER
                setPadding(dp(28), dp(28), dp(28), dp(28))
                setBackgroundColor(Color.rgb(72, 130, 171))
            }
            val safeTitle = TextView(activity).apply {
                text = activity.getString(R.string.if_tech_safe_title)
                setTextColor(Color.WHITE)
                textSize = 26f
                typeface = Typeface.DEFAULT_BOLD
                gravity = Gravity.CENTER
            }
            safeRoot.addView(safeTitle, LinearLayout.LayoutParams(dp(480), dp(70)))
            fun safeButton(label: String, action: () -> Unit) {
                val button = Button(activity).apply {
                    text = label
                    textSize = 18f
                    setOnClickListener {
                        safeDialog.dismiss()
                        dialog.dismiss()
                        action()
                    }
                }
                safeRoot.addView(button, LinearLayout.LayoutParams(dp(450), dp(64)))
            }
            safeButton(activity.getString(R.string.if_tech_go_home)) {
                val home = Intent(Intent.ACTION_MAIN).apply {
                    addCategory(Intent.CATEGORY_HOME)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                try { activity.startActivity(home) }
                catch (_: Exception) { activity.moveTaskToBack(true) }
            }
            safeButton(activity.getString(R.string.if_tech_settings)) {
                try { activity.startActivity(Intent(Settings.ACTION_SETTINGS)) }
                catch (_: Exception) { }
            }
            safeButton(activity.getString(R.string.if_tech_return)) { }
            safeDialog.setContentView(safeRoot)
            safeDialog.show()
            safeDialog.window?.setLayout(dp(540), ViewGroup.LayoutParams.WRAP_CONTENT)
        }

        fun enterDigit(value: String) {
            if (authorized || pin.length >= 4) return
            pin.append(value)
            if (pin.length == 4) {
                if (pin.toString() == TECH_PIN) {
                    authorized = true
                    keypad.visibility = View.GONE
                    options.visibility = View.VISIBLE
                    indicators.text = activity.getString(R.string.if_tech_authorized)
                    message.text = activity.getString(R.string.if_tech_options)
                    options.getChildAt(0)?.requestFocus()
                } else {
                    pin.clear()
                    drawPin()
                    message.text = activity.getString(R.string.if_tech_wrong)
                }
            } else {
                drawPin()
                message.text = activity.getString(R.string.if_tech_enter_pin)
            }
        }

        fun eraseDigit() {
            if (authorized) return
            if (pin.isNotEmpty()) pin.deleteCharAt(pin.length - 1)
            drawPin()
        }

        val eraseLabel = activity.getString(R.string.if_tech_erase)
        val exitLabel = activity.getString(R.string.if_tech_exit)
        ((1..9).map { it.toString() } + eraseLabel + 0.toString() + exitLabel).forEach { digit ->
            val button = Button(activity).apply {
                text = digit
                textSize = 20f
            }
            val params = GridLayout.LayoutParams().apply {
                width = dp(143)
                height = dp(58)
                setMargins(dp(2), dp(2), dp(2), dp(2))
            }
            keypad.addView(button, params)
            if (firstKey == null) firstKey = button
            button.setOnClickListener {
                when (digit) {
                    eraseLabel -> eraseDigit()
                    exitLabel -> dialog.dismiss()
                    else -> enterDigit(digit)
                }
            }
        }
        drawPin()
        dialog.setContentView(root)
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
        dialog.window?.setLayout(dp(520), ViewGroup.LayoutParams.WRAP_CONTENT)
        dialog.setOnKeyListener { _, keyCode, event ->
            if (!authorized && event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
                when (keyCode) {
                    in KeyEvent.KEYCODE_0..KeyEvent.KEYCODE_9 -> {
                        enterDigit((keyCode - KeyEvent.KEYCODE_0).toString())
                        true
                    }
                    in KeyEvent.KEYCODE_NUMPAD_0..KeyEvent.KEYCODE_NUMPAD_9 -> {
                        enterDigit((keyCode - KeyEvent.KEYCODE_NUMPAD_0).toString())
                        true
                    }
                    KeyEvent.KEYCODE_DEL -> { eraseDigit(); true }
                    else -> false
                }
            } else false
        }
        dialog.show()
        dialog.window?.setLayout(dp(520), ViewGroup.LayoutParams.WRAP_CONTENT)
        firstKey?.requestFocus()
    }
}
''',
    encoding="utf-8",
)

# Declare UI-visible text as Android string resources rather than Kotlin literals.
res = Path("native-source/InterFlashTV-OwnTV/app/src/main/res")
translations = {
    "values": {
        "if_tech_safe_start": "Safe Android start menu",
        "if_tech_safe_title": "INTER FLASH TV",
        "if_tech_title": "INTER FLASH - TECHNICIAN ACCESS",
        "if_tech_enter_pin": "Enter technician PIN.",
        "if_tech_filled": "● ",
        "if_tech_empty": "○ ",
        "if_tech_go_home": "Exit to Android home",
        "if_tech_settings": "Open Android settings",
        "if_tech_return": "Return to Inter Flash TV",
        "if_tech_authorized": "Access granted",
        "if_tech_options": "Choose a technician option.",
        "if_tech_wrong": "Incorrect PIN. Try again.",
        "if_tech_erase": "Delete",
        "if_tech_exit": "Close",
    },
    "values-es": {
        "if_tech_safe_start": "Menú de inicio seguro",
        "if_tech_safe_title": "INTER FLASH TV",
        "if_tech_title": "INTER FLASH - ACCESO TÉCNICO",
        "if_tech_enter_pin": "Introduce el PIN técnico.",
        "if_tech_filled": "● ",
        "if_tech_empty": "○ ",
        "if_tech_go_home": "Salir al menú de Android",
        "if_tech_settings": "Abrir ajustes de Android",
        "if_tech_return": "Volver a Inter Flash TV",
        "if_tech_authorized": "Acceso autorizado",
        "if_tech_options": "Selecciona una opción técnica.",
        "if_tech_wrong": "PIN incorrecto. Inténtalo de nuevo.",
        "if_tech_erase": "Borrar",
        "if_tech_exit": "Salir",
    },
}
from xml.sax.saxutils import escape
for locale, pairs in translations.items():
    folder = res / locale
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "strings_interflash_tech.xml"
    path.write_text(
        "<resources>\n" + "".join(
            f'    <string name="{key}">{escape(value)}</string>\n'
            for key, value in pairs.items()
        ) + "</resources>\n", encoding="utf-8"
    )

print("Patched MainActivity with 10-second OK release and native PIN technician menu.")
