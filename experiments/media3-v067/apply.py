#!/usr/bin/env python3
"""Isolated Media3/ExoPlayer test for live TV. No LibVLC code is added."""
from pathlib import Path
import re

root = Path("native-source/InterFlashTV-OwnTV")
build = root / "app/build.gradle.kts"
screen = root / "app/src/main/java/tv/own/owntv/features/live/LiveScreen.kt"

def replace_one(path, old, new):
    s = path.read_text()
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"Expected 1 anchor in {path}, got {count}: {old[:90]!r}")
    path.write_text(s.replace(old, new, 1))

# Independent package; don't overwrite installed production or VLC test APKs.
source = build.read_text()
source, count = re.subn(
    r'(?m)^(\s*applicationId\s*=\s*)"[^"]+"',
    r'\1"tv.own.owntv.exopreviewtest"',
    source,
)
if count != 1:
    raise RuntimeError(f"Expected one applicationId, found {count}")
build.write_text(source)

# The underlying native app ALREADY includes Media3, LivePreviewEngine,
# ExoPreviewSurface, and the full-screen Exo promotion + mpv fallback ladder.
# Preserve those paths instead of adding duplicate player instances.
replace_one(
    screen,
    '    var clientFocusedChannelId by remember { mutableStateOf<Long?>(null) }',
    '''    var clientFocusedChannelId by remember { mutableStateOf<Long?>(null) }
    // Explicit preview only after first OK: never auto-tune while browsing the client list.
    var clientExoPreviewId by remember { mutableStateOf<Long?>(null) }
    LaunchedEffect(isBrowsePlaying) {
        if (isBrowsePlaying) clientExoPreviewId = null
    }''',
)

s = screen.read_text()
start_needle = 'if (clientMode && !externalPlayerOn) {'
end_needle = 'onLongClick = { contextChannel = channel; contextChannelId = channel.id },'
if s.count(start_needle) != 1 or s.count(end_needle) != 1:
    raise RuntimeError("Cannot identify original live channel click callback")
token_pos = s.index(start_needle)
start = s.rfind('onClick = {', 0, token_pos)
stop = s.index(end_needle, token_pos)
if start < 0 or stop < start:
    raise RuntimeError("Invalid live channel callback anchors")
old_handler = s[start:stop]
if "vm.watchFullscreen(channel" not in old_handler or "onFullscreen()" not in old_handler:
    raise RuntimeError("Expected original playback callback, aborting")
s = s[:start] + '''onClick = {
    if (clientMode && !externalPlayerOn) {
        if (clientExoPreviewId == channel.id && previewChannel?.id == channel.id) {
            // Second OK: promote the selected live stream to the full-screen player.
            vm.watchFullscreen(channel, channels.itemSnapshotList.items.filterNotNull())
            onFullscreen()
        } else {
            // First OK: ExoPlayer video inside the EXISTING small stage rectangle.
            // Keep the channel list on screen; never create a VLC surface.
            vm.onChannelFocused(channel)
            clientExoPreviewId = channel.id
            vm.playPreview(channel)
        }
    } else {
        // Preserve administrator and external-player behavior.
        vm.watchFullscreen(channel, channels.itemSnapshotList.items.filterNotNull())
        if (!externalPlayerOn) onFullscreen()
    }
},
''' + s[stop:]
screen.write_text(s)

# In client mode the original automatic preview is OFF; explicitly expose the
# ExoPlayer surface only once the user presses OK on a channel.
replace_one(
    screen,
    'showVideo = effectivePreview,',
    'showVideo = effectivePreview || (clientMode && previewEnabled && clientExoPreviewId != null && clientExoPreviewId == previewChannel?.id),',
)

print("Media3 0.67 patch: first OK ExoPlayer stage, second OK fullscreen; separate test package")
