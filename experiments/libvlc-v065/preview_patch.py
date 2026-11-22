#!/usr/bin/env python3
"""Isolated v0.66: put LibVLC in the original Live Stage preview before fullscreen.

Run AFTER the v0.65 VLC Activity patch and before the Gradle build.
Neither the official 0.62 nor the 0.65 test source branch is changed.
"""
from pathlib import Path
import re

app = Path("native-source/InterFlashTV-OwnTV")
base = app / "app/src/main/java/tv/own/owntv/features/live"
screen = base / "LiveScreen.kt"
vm = base / "LiveViewModel.kt"
stage = base / "LiveStage.kt"
build = app / "app/build.gradle.kts"

def replace_one(path: Path, old: str, new: str):
    s = path.read_text()
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one anchor in {path}, found {count}: {old[:100]!r}")
    path.write_text(s.replace(old, new, 1))

# Different APK package than both the production app and the v0.65 test.
replace_one(build, '"tv.own.owntv.vlconlytest"', '"tv.own.owntv.vlcpreviewtest"')

# The v0.65 separate Activity remains available for fullscreen, but a normal
# channel press first prepares its own embedded preview. A second press opens
# fullscreen VLC. No ExoPlayer/mpv video is started for the preview trial.
viewmodel_code = '''
    /** A resolved non-DRM live stream for the in-pane VLC picture. */
    data class VlcPreviewStream(val channelId: Long, val url: String, val userAgent: String)

    private val _vlcPreviewStream =
        kotlinx.coroutines.flow.MutableStateFlow<VlcPreviewStream?>(null)
    val vlcPreviewStream: kotlinx.coroutines.flow.StateFlow<VlcPreviewStream?> = _vlcPreviewStream
    private var vlcPreviewJob: kotlinx.coroutines.Job? = null

    fun clearVlcPreview() {
        vlcPreviewJob?.cancel()
        vlcPreviewJob = null
        _vlcPreviewStream.value = null
    }

    fun selectVlcPreview(channel: ChannelEntity) {
        clearVlcPreview()
        _previewChannel.value = channel
        vlcPreviewJob = viewModelScope.launch {
            if (channel.drmConfig != null) return@launch
            val pid = currentProfileId() ?: return@launch
            if (!tv.own.owntv.core.content.AdultCategoryClassifier.allows(
                    pid, channel.categoryId, profileDao, categoryDao
                ) || customize.sealsCategory(pid, channel.categoryId)) return@launch
            val source = withContext(Dispatchers.IO) { sourceDao.getById(channel.sourceId) }
            val url = if (streamUrlResolver.needsResolve(source)) {
                withContext(Dispatchers.IO) {
                    runCatching { streamUrlResolver.resolve(source!!, channel.streamUrl) }.getOrNull()
                } ?: return@launch
            } else channel.streamUrl
            val uri = android.net.Uri.parse(url)
            if (uri.scheme !in listOf("http", "https") || uri.host.isNullOrBlank()) return@launch
            _vlcPreviewStream.value = VlcPreviewStream(channel.id, url, source?.userAgent ?: "")
        }
    }

'''
replace_one(vm, '    fun playVlcTrial(channel: ChannelEntity) {',
            viewmodel_code + '    fun playVlcTrial(channel: ChannelEntity) {')

replace_one(screen,
    '    val previewChannel by vm.previewChannel.collectAsStateWithLifecycle()',
    '''    val previewChannel by vm.previewChannel.collectAsStateWithLifecycle()
    val vlcPreviewStream by vm.vlcPreviewStream.collectAsStateWithLifecycle()''')

# Client mode had not updated previewChannel when the remote moved to a new row.
# Update the model's selected-channel metadata but leave its Exo playback disabled
# by the v0.65 isolated patch's preview guard.
replace_one(screen,
    'if (clientMode) clientFocusedChannelId = channel.id else vm.onChannelFocused(channel)',
    '''if (clientMode) clientFocusedChannelId = channel.id
                                        vm.onChannelFocused(channel)''')

# Replace the native channel click callback (patched to "VLC fullscreen directly" in v0.65).
s = screen.read_text()
start_anchor = '''                                    onClick = {
                                         if (true) { vm.playVlcTrial(channel) } else if (clientMode && !externalPlayerOn) {'''
stop_anchor = '''                                    onLongClick = { contextChannel = channel; contextChannelId = channel.id },'''
if s.count(start_anchor) != 1 or s.count(stop_anchor) != 1:
    raise RuntimeError("Unexpected original LiveStageRow click handler")
start = s.index(start_anchor)
stop = s.index(stop_anchor, start)
s = s[:start] + '''                                    onClick = {
                                        if (vlcPreviewStream?.channelId == channel.id) {
                                            // Release the in-pane decoder before fullscreen, avoiding a
                                            // second session on one-connection IPTV subscriptions.
                                            vm.clearVlcPreview()
                                            vm.playVlcTrial(channel)
                                        } else {
                                            // First OK: keep the channel list and stage visible.
                                            vm.selectVlcPreview(channel)
                                        }
                                    },
''' + s[stop:]
screen.write_text(s)

replace_one(screen,
    '                    previewEngine = vm.previewEngine,',
    '''                    previewEngine = vm.previewEngine,
                    vlcPreviewStream = vlcPreviewStream,''')

replace_one(stage,
    '    previewEngine: tv.own.owntv.player.LivePreviewEngine,',
    '''    previewEngine: tv.own.owntv.player.LivePreviewEngine,
    vlcPreviewStream: LiveViewModel.VlcPreviewStream? = null,''')
replace_one(stage,
    '''    val playing = showVideo && previewState != tv.own.owntv.player.LivePreviewEngine.State.ERROR &&
        previewState != tv.own.owntv.player.LivePreviewEngine.State.IDLE''',
    '''    val activeVlc = vlcPreviewStream?.takeIf { it.channelId == channel?.id }
    val playing = activeVlc != null || (showVideo &&
        previewState != tv.own.owntv.player.LivePreviewEngine.State.ERROR &&
        previewState != tv.own.owntv.player.LivePreviewEngine.State.IDLE)''')
replace_one(stage,
    '''            if (playing) tv.own.owntv.player.ExoPreviewSurface(engine = previewEngine, modifier = Modifier.fillMaxSize())''',
    '''            if (activeVlc != null) {
                VlcEmbeddedSurface(activeVlc, Modifier.fillMaxSize())
            } else if (playing) {
                tv.own.owntv.player.ExoPreviewSurface(engine = previewEngine, modifier = Modifier.fillMaxSize())
            }''')

# LibVLC runs inside the Compose Stage's actual 16:9 video rectangle.
# The AndroidView owns the LibVLC surface, and composable disposal always
# releases the decoder and socket. No Activity overlays the channel list.
(base / "VlcEmbeddedSurface.kt").write_text(r'''package tv.own.owntv.features.live

import android.net.Uri
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import org.videolan.libvlc.LibVLC
import org.videolan.libvlc.Media
import org.videolan.libvlc.MediaPlayer
import org.videolan.libvlc.util.VLCVideoLayout

/** Experimental LibVLC video surface attached to the existing Live Stage rectangle. */
@Composable
internal fun VlcEmbeddedSurface(
    stream: LiveViewModel.VlcPreviewStream,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val videoLayout = remember(stream.url, stream.userAgent) { VLCVideoLayout(context) }

    AndroidView(factory = { videoLayout }, modifier = modifier)
    DisposableEffect(videoLayout, stream.url, stream.userAgent) {
        var vlc: LibVLC? = null
        var mediaPlayer: MediaPlayer? = null
        try {
            val instance = LibVLC(context, arrayListOf("--no-video-title-show"))
            vlc = instance
            val player = MediaPlayer(instance)
            mediaPlayer = player
            player.attachViews(videoLayout, null, false, false)
            val media = Media(instance, Uri.parse(stream.url))
            media.setHWDecoderEnabled(true, false)
            media.addOption(":network-caching=1200")
            if (stream.userAgent.isNotBlank()) {
                media.addOption(":http-user-agent=" + stream.userAgent)
            }
            player.setMedia(media)
            media.release()
            player.play()
        } catch (_: Exception) {
            runCatching { mediaPlayer?.stop() }
            runCatching { mediaPlayer?.detachViews() }
            runCatching { mediaPlayer?.release() }
            runCatching { vlc?.release() }
            mediaPlayer = null
            vlc = null
        } catch (_: LinkageError) {
            runCatching { mediaPlayer?.stop() }
            runCatching { mediaPlayer?.detachViews() }
            runCatching { mediaPlayer?.release() }
            runCatching { vlc?.release() }
            mediaPlayer = null
            vlc = null
        }
        onDispose {
            runCatching { mediaPlayer?.stop() }
            runCatching { mediaPlayer?.detachViews() }
            runCatching { mediaPlayer?.release() }
            runCatching { vlc?.release() }
        }
    }
}
''')
print("VLC 0.66 preview patch applied: first OK in Stage, second OK fullscreen VLC; test package only")
