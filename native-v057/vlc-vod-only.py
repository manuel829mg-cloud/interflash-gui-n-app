#!/usr/bin/env python3
"""Stable Inter Flash TV: LibVLC for non-DRM movies/episodes; leave live TV unchanged."""
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile
import io

app = Path("native-source/InterFlashTV-OwnTV")
core = Path("native-source/OwnTV_Core-main")
assert app.is_dir() and core.is_dir(), "Restore native source first"

def replace_once(path, old, new):
    s = path.read_text()
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one occurrence in {path}; found {count}: {old[:100]}")
    path.write_text(s.replace(old, new, 1))

# Keep production package ID and original playback backend for live TV.
build = app / "app/build.gradle.kts"
replace_once(build, "dependencies {", '''dependencies {
    // LibVLC only for non-DRM Movies / Series. Keep the native live-TV player.
    implementation(files("libs/libvlc-vod.aar"))''')

# LibVLC ships a second libc++_shared.so which collides with the bundled MPV
# native library. Keep the already packaged runtime (as in the isolated 0.65 attempt).
vlc_url = "https://repo.maven.apache.org/maven2/org/videolan/android/libvlc-all/3.7.7/libvlc-all-3.7.7.aar"
lib_dir = app / "app/libs"
lib_dir.mkdir(parents=True, exist_ok=True)
with urlopen(vlc_url, timeout=90) as f:
    vlc_bytes = f.read()
with ZipFile(io.BytesIO(vlc_bytes)) as src, ZipFile(lib_dir / "libvlc-vod.aar", "w") as dst:
    removed = 0
    jni = 0
    for info in src.infolist():
        if info.filename.startswith("jni/") and info.filename.endswith("/libc++_shared.so"):
            removed += 1
            continue
        if info.filename.startswith("jni/") and info.filename.endswith(".so"):
            jni += 1
        dst.writestr(info, src.read(info.filename))
    assert removed > 0 and jni > 0, "Unexpected libvlc AAR layout"

manifest = app / "app/src/main/AndroidManifest.xml"
replace_once(manifest, "    </application>", '''        <!-- Same app, isolated VOD-only LibVLC process; NOT a launcher app. -->
        <activity android:name=".features.vod.VlcVodActivity"
                  android:exported="false"
                  android:screenOrientation="landscape"
                  android:process=":vlc_vod"
                  android:theme="@android:style/Theme.Material.NoActionBar"/>
    </application>''')

src = app / "app/src/main/java/tv/own/owntv/features"
vod = src / "vod"
vod.mkdir(parents=True, exist_ok=True)
(vod / "VlcVodLauncher.kt").write_text(r'''package tv.own.owntv.features.vod

import android.content.Context
import android.content.Intent
import org.koin.core.context.GlobalContext

/** Internal (NOT external VLC) VOD-only playback. TV en vivo never calls this. */
object VlcVodLauncher {
    fun start(url: String, title: String, userAgent: String?, referer: String?, cookie: String?, startPositionMs: Long) {
        val context: Context = GlobalContext.get().get()
        val intent = Intent(context, VlcVodActivity::class.java)
            .putExtra(VlcVodActivity.EXTRA_URL, url)
            .putExtra(VlcVodActivity.EXTRA_TITLE, title)
            .putExtra(VlcVodActivity.EXTRA_USER_AGENT, userAgent ?: "")
            .putExtra(VlcVodActivity.EXTRA_REFERER, referer ?: "")
            .putExtra(VlcVodActivity.EXTRA_COOKIE, cookie ?: "")
            .putExtra(VlcVodActivity.EXTRA_START, startPositionMs.coerceAtLeast(0))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }
}
''')

(vod / "VlcVodActivity.java").write_text(r'''package tv.own.owntv.features.vod;

import android.app.Activity;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;
import org.videolan.libvlc.LibVLC;
import org.videolan.libvlc.Media;
import org.videolan.libvlc.MediaPlayer;
import org.videolan.libvlc.util.VLCVideoLayout;
import java.util.ArrayList;

/** Internal VOD player on an isolated process. BACK returns to the native catalogue. */
public final class VlcVodActivity extends Activity {
    public static final String EXTRA_URL = "ifvod.url";
    public static final String EXTRA_TITLE = "ifvod.title";
    public static final String EXTRA_USER_AGENT = "ifvod.user_agent";
    public static final String EXTRA_REFERER = "ifvod.referer";
    public static final String EXTRA_COOKIE = "ifvod.cookie";
    public static final String EXTRA_START = "ifvod.start";

    private LibVLC libVlc;
    private MediaPlayer player;
    private VLCVideoLayout layout;
    private TextView label;
    private String url;
    private boolean firstSeekApplied;
    private boolean hasVideoOutput;
    private boolean softwareRetry;
    private volatile int session;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        url = getIntent().getStringExtra(EXTRA_URL);
        Uri uri = url == null ? null : Uri.parse(url);
        if (uri == null || uri.getScheme() == null ||
                !(uri.getScheme().equalsIgnoreCase("http") || uri.getScheme().equalsIgnoreCase("https")) ||
                uri.getHost() == null) {
            finish();
            return;
        }
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        layout = new VLCVideoLayout(this);
        root.addView(layout, new FrameLayout.LayoutParams(-1,-1));
        label = new TextView(this);
        label.setTextColor(Color.WHITE);
        label.setTextSize(18);
        label.setPadding(24, 18, 24, 18);
        label.setBackgroundColor(0xA9000000);
        String title = getIntent().getStringExtra(EXTRA_TITLE);
        label.setText((title == null ? "" : title) + "   ·   Cargando VLC...   ·   Atrás regresa");
        root.addView(label, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));
        setContentView(root);
    }

    // Native LibVLC initialization can block. Never run it on Android's UI thread.
    @Override protected void onStart() {
        super.onStart();
        if (url == null || layout == null || libVlc != null) return;
        final int token = ++session;
        hasVideoOutput = false;
        softwareRetry = false;
        firstSeekApplied = false;
        showStatus("Iniciando VLC... Pulsa Atrás para regresar.");

        Thread init = new Thread(() -> {
            LibVLC instance = null;
            try {
                ArrayList<String> args = new ArrayList<>();
                args.add("--no-video-title-show");
                args.add("--http-reconnect");
                instance = new LibVLC(getApplicationContext(), args);
                final LibVLC ready = instance;
                runOnUiThread(() -> {
                    if (token != session || isFinishing()) {
                        releaseAsync(null, ready);
                        return;
                    }
                    libVlc = ready;
                    startMedia(token, false);
                });
            } catch (Throwable e) {
                Log.e("InterFlashVLC", "LibVLC initialization failed", e);
                if (instance != null) releaseAsync(null, instance);
                runOnUiThread(() -> {
                    if (token == session) showStatus("Error al iniciar VLC (" +
                        e.getClass().getSimpleName() + "). Atrás para regresar.");
                });
            }
        }, "interflash-vlc-init");
        init.setDaemon(true);
        init.start();

        // If native initialization hangs, the TV UI and BACK must remain responsive.
        ui.postDelayed(() -> {
            if (token == session && !hasVideoOutput) {
                if (libVlc == null) {
                    showStatus("VLC no responde al iniciar. Pulsa Atrás para regresar.");
                } else {
                    retryWithSoftware(token);
                }
            }
        }, 16000);
    }

    private void showStatus(String message) {
        if (label != null) {
            label.setText(message);
            label.setVisibility(TextView.VISIBLE);
        }
    }

    private void retryWithSoftware(int token) {
        if (token != session || hasVideoOutput || softwareRetry || isFinishing()) return;
        softwareRetry = true;
        showStatus("Reintentando reproducción con decodificación compatible...");
        Log.w("InterFlashVLC", "No video output - retrying with software decoder");
        startMedia(token, true);
        ui.postDelayed(() -> {
            if (token == session && !hasVideoOutput) {
                showStatus("VLC no pudo mostrar el video. Pulsa Atrás para regresar.");
                Log.e("InterFlashVLC", "Video output unavailable after software fallback");
            }
        }, 18000);
    }

    private void startMedia(int token, boolean software) {
        if (libVlc == null || token != session || isFinishing()) return;
        detachAndReleasePlayer();
        firstSeekApplied = false;
        hasVideoOutput = false;
        try {
            final MediaPlayer next = new MediaPlayer(libVlc);
            player = next;
            next.attachViews(layout, null, false, false);
            next.setEventListener(event -> {
                if (event.type == MediaPlayer.Event.Vout) {
                    runOnUiThread(() -> {
                        if (token != session || player != next) return;
                        if (next.getVoutCount() > 0) {
                            hasVideoOutput = true;
                            if (label != null) {
                                label.postDelayed(() -> {
                                    if (token == session && hasVideoOutput)
                                        label.setVisibility(TextView.GONE);
                                }, 2400);
                            }
                        }
                    });
                } else if (event.type == MediaPlayer.Event.Playing) {
                    runOnUiThread(() -> {
                        if (token != session || player != next) return;
                        if (!firstSeekApplied) {
                            firstSeekApplied = true;
                            long position = getIntent().getLongExtra(EXTRA_START, 0L);
                            if (position > 0 && next.isSeekable()) next.setTime(position);
                        }
                    });
                } else if (event.type == MediaPlayer.Event.EncounteredError) {
                    Log.e("InterFlashVLC", "Playback error; software=" + software);
                    runOnUiThread(() -> {
                        if (token != session || player != next) return;
                        if (!softwareRetry) retryWithSoftware(token);
                        else showStatus("VLC no pudo reproducir este enlace. Atrás para regresar.");
                    });
                }
            });
            Media media = new Media(libVlc, Uri.parse(url));
            try {
                media.setHWDecoderEnabled(!software, false);
                media.addOption(":network-caching=" + (software ? "2000" : "1200"));
                media.addOption(":http-reconnect");
                String ua = getIntent().getStringExtra(EXTRA_USER_AGENT);
                if (ua != null && !ua.isEmpty()) media.addOption(":http-user-agent=" + ua);
                String referer = getIntent().getStringExtra(EXTRA_REFERER);
                if (referer != null && !referer.isEmpty()) media.addOption(":http-referrer=" + referer);
                String cookie = getIntent().getStringExtra(EXTRA_COOKIE);
                if (cookie != null && !cookie.isEmpty()) media.addOption(":http-cookie=" + cookie);
                next.setMedia(media);
            } finally {
                media.release();
            }
            next.play();
        } catch (Throwable e) {
            Log.e("InterFlashVLC", "VLC playback setup error", e);
            if (!softwareRetry) retryWithSoftware(token);
            else showStatus("Error de reproducción (" +
                e.getClass().getSimpleName() + "). Pulsa Atrás.");
        }
    }

    private void detachAndReleasePlayer() {
        final MediaPlayer old = player;
        player = null;
        if (old != null) {
            try { old.detachViews(); } catch (Throwable ignored) { }
            releaseAsync(old, null);
        }
    }

    private static void releaseAsync(MediaPlayer old, LibVLC instance) {
        Thread cleanup = new Thread(() -> {
            try {
                if (old != null) {
                    old.stop();
                    old.release();
                }
            } catch (Throwable e) {
                Log.w("InterFlashVLC", "Player cleanup error", e);
            }
            try {
                if (instance != null) instance.release();
            } catch (Throwable e) {
                Log.w("InterFlashVLC", "Engine cleanup error", e);
            }
        }, "interflash-vlc-cleanup");
        cleanup.setDaemon(true);
        cleanup.start();
    }

    @Override public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK || keyCode == KeyEvent.KEYCODE_ESCAPE) {
            finish();
            return true;
        }
        if (player != null) {
            if (keyCode == KeyEvent.KEYCODE_DPAD_CENTER || keyCode == KeyEvent.KEYCODE_ENTER
                    || keyCode == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE) {
                if (player.isPlaying()) player.pause(); else player.play();
                if (label != null) label.setVisibility(TextView.VISIBLE);
                return true;
            }
            if (keyCode == KeyEvent.KEYCODE_DPAD_RIGHT || keyCode == KeyEvent.KEYCODE_DPAD_LEFT) {
                if (player.isSeekable()) {
                    long change = keyCode == KeyEvent.KEYCODE_DPAD_RIGHT ? 15000L : -15000L;
                    player.setTime(Math.max(0L, player.getTime() + change));
                }
                return true;
            }
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override public void onBackPressed() {
        finish();
    }
    @Override protected void onStop() {
        ++session;  // Invalidate in-flight background engine initialization.
        detachAndReleasePlayer();
        LibVLC old = libVlc;
        libVlc = null;
        if (old != null) releaseAsync(null, old);
        super.onStop();
    }
}
''')

movievm = src / "movies/MovieViewModel.kt"
replace_once(movievm, "    fun play(movie: MovieEntity, startPositionMs: Long = 0) {\n        viewModelScope.launch {", '''    // Synchronous flag: the screen must not mount MPV while VLC is opening.
    var vlcVodSelected: Boolean = false
        private set

    fun play(movie: MovieEntity, startPositionMs: Long = 0) {
        vlcVodSelected = movie.drmConfig == null
        viewModelScope.launch {''')
replace_once(movievm,
'''            val source = sourceDao.getById(movie.sourceId)
            val sourceUa = source?.userAgent
            // Stalker:''',
'''            if (movie.drmConfig == null) {
                val url = resolvedUrlOrNull(movie) ?: return@launch
                val source = sourceDao.getById(movie.sourceId)
                val referer = runCatching {
                    val json = org.json.JSONObject(SourceOverrides.headersWithReferer(movie.httpHeaders, source).orEmpty())
                    json.keys().asSequence().firstOrNull { it.equals("referer", true) }?.let { json.optString(it) }
                }.getOrNull()
                val cookie = runCatching {
                    val json = org.json.JSONObject(SourceOverrides.headersWithReferer(movie.httpHeaders, source).orEmpty())
                    json.keys().asSequence().firstOrNull { it.equals("cookie", true) }?.let { json.optString(it) }
                }.getOrNull()
                tv.own.owntv.features.vod.VlcVodLauncher.start(
                    url, movie.name, source?.userAgent, referer, cookie, startPositionMs
                )
                if (pid != null) runCatching {
                    historyDao.record(WatchHistoryEntity(profileId = pid, mediaType = MediaType.MOVIE, itemId = movie.id))
                }
                return@launch
            }
            val source = sourceDao.getById(movie.sourceId)
            val sourceUa = source?.userAgent
            // Stalker:''')
movie_screen = src / "movies/MoviesScreen.kt"
replace_once(movie_screen, 
    'val goFullscreen: () -> Unit = { if (!externalPlayerOn) onFullscreen() }',
    'val goFullscreen: () -> Unit = { if (!externalPlayerOn && !vm.vlcVodSelected) onFullscreen() }')

seriesvm = src / "series/SeriesViewModel.kt"
replace_once(seriesvm, '    fun playEpisodeQueue(show: SeriesEntity, queue: List<EpisodeEntity>, episode: EpisodeEntity, startPositionMs: Long = 0) {\n',
'''    // Synchronous flag for UI fullscreen routing, DRM stays on the existing player.
    var vlcVodSelected: Boolean = false
        private set

    fun playEpisodeQueue(show: SeriesEntity, queue: List<EpisodeEntity>, episode: EpisodeEntity, startPositionMs: Long = 0) {
        vlcVodSelected = episode.drmConfig == null
''')
replace_once(seriesvm,
'''            val startIndex = queue.indexOfFirst { it.id == episode.id }.coerceAtLeast(0)
''',
'''            if (episode.drmConfig == null) {
                val url = resolvedEpisodeUrlOrNull(episode) ?: return@launch
                val source = sourceDao.getById(show.sourceId)
                val referer = runCatching {
                    val json = org.json.JSONObject(tv.own.owntv.core.settings.SourceOverrides.headersWithReferer(episode.httpHeaders, source).orEmpty())
                    json.keys().asSequence().firstOrNull { it.equals("referer", true) }?.let { json.optString(it) }
                }.getOrNull()
                val cookie = runCatching {
                    val json = org.json.JSONObject(tv.own.owntv.core.settings.SourceOverrides.headersWithReferer(episode.httpHeaders, source).orEmpty())
                    json.keys().asSequence().firstOrNull { it.equals("cookie", true) }?.let { json.optString(it) }
                }.getOrNull()
                tv.own.owntv.features.vod.VlcVodLauncher.start(
                    url, episode.name.ifBlank { show.name }, source?.userAgent, referer, cookie, startPositionMs
                )
                if (pid != null) {
                    runCatching { historyDao.record(WatchHistoryEntity(profileId = pid, mediaType = MediaType.EPISODE, itemId = episode.id)) }
                    runCatching { historyDao.record(WatchHistoryEntity(profileId = pid, mediaType = MediaType.SERIES, itemId = show.id)) }
                }
                return@launch
            }
            val startIndex = queue.indexOfFirst { it.id == episode.id }.coerceAtLeast(0)
''')
series_screen = src / "series/SeriesScreen.kt"
replace_once(series_screen, 
    'val goFullscreen: () -> Unit = { if (!externalPlayerOn) onFullscreen() }',
    'val goFullscreen: () -> Unit = { if (!externalPlayerOn && !vm.vlcVodSelected) onFullscreen() }')
# The stable build already replaces catalogue auto-play with openSeries in its
# earlier layout patch. The EpisodeView goFullscreen guard above covers playback.

# Protocol field names and empty default values are technical literals, not UI copy.
# Register them after generating the VOD source files so the Gradle translation
# audit does not reject the build.
import subprocess
for relative_path, literal, category in [
    ("movies/MovieViewModel.kt", "referer", "json"),
    ("series/SeriesViewModel.kt", "referer", "json"),
    ("vod/VlcVodLauncher.kt", "", "empty"),
]:
    subprocess.run([
        "python3", "tools/i18n/check_hardcoded_strings.py", "classify-safe",
        "--path", "app/src/main/java/tv/own/owntv/features/" + relative_path,
        "--text", literal, "--category", category
    ], cwd=app, check=True)

print("Prepared production-ID VOD-only VLC, live TV untouched")
