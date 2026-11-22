#!/usr/bin/env python3
"""Prepare an opt-in, side-by-side LibVLC live-TV trial from the restored v0.62 native code.

Run after the existing v0.62 UI patch steps, before Gradle compilation.
This is intentionally an isolated test: existing engines and normal channel OK stay untouched.
"""
from pathlib import Path

root = Path("native-source")
app = root / "InterFlashTV-OwnTV"
core = root / "OwnTV_Core-main"
if not app.is_dir() or not core.is_dir():
    raise RuntimeError("v0.62 native source archive was not restored")

def replace_one(path: Path, old: str, new: str):
    s = path.read_text()
    found = s.count(old)
    if found != 1:
        raise RuntimeError(f"Expected one anchor in {path}; got {found}: {old[:90]!r}")
    path.write_text(s.replace(old, new, 1))

build = app / "app/build.gradle.kts"
# The recovered 0.62 archive can use the Inter Flash-specific application ID.
# Replace the single Gradle declaration, not an assumed upstream ID.
import re
build_source = build.read_text()
build_source, package_count = re.subn(
    r'(?m)^(\s*applicationId\s*=\s*)"[^"]+"',
    lambda m: m.group(1) + '"tv.own.owntv.vlctest"',
    build_source,
)
if package_count != 1:
    raise RuntimeError(f"Expected one applicationId in {build}; found {package_count}")
build.write_text(build_source)
replace_one(build, 'dependencies {', '''dependencies {
    // Use a locally sanitized VLC AAR, keeping the original MPV C++ runtime intact.
    implementation(files("libs/libvlc-no-cxx.aar"))''')


# Do not use Gradle pickFirst for libc++: it silently selects an arbitrary STL and
# caused the normal MPV path to crash in the previous 0.63 APK on the user's TV.
# Remove ONLY the bundled STL from the VLC AAR; Android will then package the
# existing MPV libc++_shared.so, with all VLC JNI libraries preserved.
# This creates a new local test dependency and never changes the official app.
import io
from urllib.request import urlopen
from zipfile import ZipFile

vlc_url = "https://repo.maven.apache.org/maven2/org/videolan/android/libvlc-all/3.7.7/libvlc-all-3.7.7.aar"
vlc_dir = app / "app/libs"
vlc_dir.mkdir(exist_ok=True, parents=True)
vlc_target = vlc_dir / "libvlc-no-cxx.aar"
with urlopen(vlc_url, timeout=90) as response:
    vlc_data = response.read()
with ZipFile(io.BytesIO(vlc_data)) as source, ZipFile(vlc_target, "w") as dest:
    skipped = []
    found_vlc_jni = 0
    for item in source.infolist():
        if item.filename.endswith("/libc++_shared.so") and item.filename.startswith("jni/"):
            skipped.append(item.filename)
            continue
        if item.filename.startswith("jni/") and item.filename.endswith(".so"):
            found_vlc_jni += 1
        dest.writestr(item, source.read(item.filename))
    if not skipped or found_vlc_jni == 0:
        raise RuntimeError("Unexpected VLC AAR: C++ runtime or VLC JNI binaries missing")
print("Prepared VLC AAR for test (MPV libc++ retained, dropped VLC duplicate from", len(skipped), "ABIs)")

manifest = app / "app/src/main/AndroidManifest.xml"
replace_one(manifest, '    </application>', '''        <!-- Separate, opt-in VLC experiment; never registered as a launcher. -->
        <activity android:name=".features.live.VlcTrialActivity"
                  android:exported="false"
                  android:screenOrientation="landscape"
                  android:process=":vlc_trial"
                  android:theme="@android:style/Theme.Material.NoActionBar"/>
    </application>''')

viewmodel = app / "app/src/main/java/tv/own/owntv/features/live/LiveViewModel.kt"
insert_method = '''
    /**
     * Explicit per-channel test of an embedded LibVLC surface. Normal playback paths remain
     * ExoPlayer/mpv. Protected streams and custom HTTP headers are deliberately not forwarded.
     */
    fun playVlcTrial(channel: ChannelEntity) {
        viewModelScope.launch {
            if (channel.drmConfig != null) return@launch
            val pid = currentProfileId() ?: return@launch
            if (!tv.own.owntv.core.content.AdultCategoryClassifier.allows(pid, channel.categoryId, profileDao, categoryDao)
                || customize.sealsCategory(pid, channel.categoryId)) return@launch
            val source = withContext(Dispatchers.IO) { sourceDao.getById(channel.sourceId) }
            // Stalker URLs must be resolved before being passed to a native video engine.
            val url = if (streamUrlResolver.needsResolve(source)) {
                withContext(Dispatchers.IO) {
                    runCatching { streamUrlResolver.resolve(source!!, channel.streamUrl) }.getOrNull()
                } ?: return@launch
            } else channel.streamUrl
            // A trial URL must be an ordinary HTTP stream. No passwords or stream URLs in logs.
            if (!(url.startsWith("https://") || url.startsWith("http://"))) return@launch
            val intent = android.content.Intent(appContext, VlcTrialActivity::class.java)
                .putExtra(VlcTrialActivity.EXTRA_URL, url)
                .putExtra(VlcTrialActivity.EXTRA_TITLE, channel.name)
                .putExtra(VlcTrialActivity.EXTRA_USER_AGENT, source?.userAgent ?: "")
                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
            appContext.startActivity(intent)
            recordLiveHistory(channel, immediate = true)
        }
    }

'''
replace_one(viewmodel, '    fun playExternal(channel: ChannelEntity) {',
            insert_method + '    fun playExternal(channel: ChannelEntity) {')

screen = app / "app/src/main/java/tv/own/owntv/features/live/LiveScreen.kt"
replace_one(screen,
            '            onPlayExternal = { vm.playExternal(ch); contextChannel = null },',
            '''            onPlayExternal = { vm.playExternal(ch); contextChannel = null },
            onPlayVlcTrial = { vm.playVlcTrial(ch); contextChannel = null },''')
replace_one(screen,
            '    onPlayExternal: () -> Unit,',
            '''    onPlayExternal: () -> Unit,
    onPlayVlcTrial: () -> Unit,''')
replace_one(screen,
            '        add(MenuAction("play_external", stringResource(R.string.content_play_external_short), OwnTVIcon.EXTERNAL, group = watch, onClick = onPlayExternal))',
            '''        add(MenuAction("play_external", stringResource(R.string.content_play_external_short), OwnTVIcon.EXTERNAL, group = watch, onClick = onPlayExternal))
        add(MenuAction("vlc_trial", stringResource(R.string.interflash_vlc_trial), OwnTVIcon.EXTERNAL, group = watch, onClick = onPlayVlcTrial))''')

for qualifier, title in [("values", "Test with VLC"), ("values-es", "Probar VLC (prueba)")]:
    resource = core / "core/src/main/res" / qualifier / "strings_interflash_vlc.xml"
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_text('<?xml version="1.0" encoding="utf-8"?>\n<resources><string name="interflash_vlc_trial">' + title + '</string></resources>\n')

activity = app / "app/src/main/java/tv/own/owntv/features/live/VlcTrialActivity.java"
activity.write_text(r'''package tv.own.owntv.features.live;

import android.app.Activity;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;

import org.videolan.libvlc.LibVLC;
import org.videolan.libvlc.Media;
import org.videolan.libvlc.MediaPlayer;
import org.videolan.libvlc.util.VLCVideoLayout;

import java.util.ArrayList;

/**
 * Isolated LibVLC playback test for ONE selected live channel. The main player is not modified.
 * BACK returns to Inter Flash TV's ordinary channel list and ExoPlayer/mpv engines.
 */
public final class VlcTrialActivity extends Activity {
    public static final String EXTRA_URL = "ifvlc.url";
    public static final String EXTRA_TITLE = "ifvlc.title";
    public static final String EXTRA_USER_AGENT = "ifvlc.userAgent";

    private LibVLC libVlc;
    private MediaPlayer mediaPlayer;
    private VLCVideoLayout videoLayout;
    private TextView status;
    private String streamUrl;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        streamUrl = getIntent().getStringExtra(EXTRA_URL);
        Uri uri = streamUrl == null ? null : Uri.parse(streamUrl);
        if (uri == null || !(uri.getScheme().equalsIgnoreCase("https")
                || uri.getScheme().equalsIgnoreCase("http")) || uri.getHost() == null) {
            finish();
            return;
        }
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        videoLayout = new VLCVideoLayout(this);
        root.addView(videoLayout, new FrameLayout.LayoutParams(-1, -1));
        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setTextSize(17);
        status.setPadding(24, 18, 24, 18);
        status.setBackgroundColor(0xBB111111);
        String title = getIntent().getStringExtra(EXTRA_TITLE);
        status.setText((title == null ? "" : title) + " · VLC (prueba) · Atrás para salir");
        root.addView(status, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));
        setContentView(root);
    }

    @Override protected void onStart() {
        super.onStart();
        if (streamUrl == null || videoLayout == null || mediaPlayer != null) return;
        try {
            ArrayList<String> options = new ArrayList<>();
            options.add("--no-video-title-show");
            libVlc = new LibVLC(this, options);
            mediaPlayer = new MediaPlayer(libVlc);
            mediaPlayer.attachViews(videoLayout, null, false, false);
            mediaPlayer.setEventListener(event -> {
                if (event.type == MediaPlayer.Event.Playing) {
                    runOnUiThread(() -> {
                        if (status != null) status.postDelayed(() -> status.setVisibility(TextView.GONE), 2500);
                    });
                } else if (event.type == MediaPlayer.Event.EncounteredError) {
                    runOnUiThread(() -> {
                        if (status != null) {
                            status.setVisibility(TextView.VISIBLE);
                            status.setText("VLC no abrió este canal. Pulsa Atrás para usar el reproductor habitual.");
                        }
                    });
                }
            });
            Media media = new Media(libVlc, Uri.parse(streamUrl));
            media.setHWDecoderEnabled(true, false);
            media.addOption(":network-caching=1200");
            String userAgent = getIntent().getStringExtra(EXTRA_USER_AGENT);
            if (userAgent != null && !userAgent.isEmpty()) {
                // Keep user-supplied headers out of console output.
                media.addOption(":http-user-agent=" + userAgent);
            }
            mediaPlayer.setMedia(media);
            media.release();
            mediaPlayer.play();
        } catch (Exception | LinkageError exception) {
            if (status != null) status.setText("No se pudo iniciar VLC. Pulsa Atrás para regresar.");
            releasePlayer();
        }
    }

    @Override protected void onStop() {
        releasePlayer();
        super.onStop();
    }

    private void releasePlayer() {
        if (mediaPlayer != null) {
            mediaPlayer.stop();
            mediaPlayer.detachViews();
            mediaPlayer.release();
            mediaPlayer = null;
        }
        if (libVlc != null) {
            libVlc.release();
            libVlc = null;
        }
    }
}
''')

print("LibVLC 0.64 trial patched: sanitized VLC AAR, isolated VLC process, current MPV runtime")
