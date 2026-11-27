#!/usr/bin/env python3
"""Remove media download entry points and enable sharp movie catalogue art."""
from pathlib import Path
import re
import subprocess

root = Path("native-source")
app = root / "InterFlashTV-OwnTV/app/src/main/java/tv/own/owntv"
core = root / "OwnTV_Core-main/core/src/main/java/tv/own/owntv/core"

def edit(path, old, new, expected=1):
    source = path.read_text(encoding="utf-8")
    assert source.count(old) == expected, (path, old, source.count(old))
    path.write_text(source.replace(old, new), encoding="utf-8")

def remove_actions(path, count):
    source = path.read_text(encoding="utf-8")
    source, found = re.subn(r'^            add\(MenuAction\("download",[^\n]*\{\n(?:[^\n]*\n)*?            \}\)\n', '', source, flags=re.M)
    assert found == count, (path, found)
    path.write_text(source, encoding="utf-8")

movies = app / "features/movies/MoviesScreen.kt"
series = app / "features/series/SeriesScreen.kt"
remove_actions(movies, 1)
remove_actions(series, 3)
edit(series, '''                if (visibleEpisodes.isNotEmpty() || seasonEpisodes.isNotEmpty()) {
                    StageButton(
                        text = stringResource(R.string.content_download_season),
                        onClick = { vm.downloadSeason(series, activeSeason) },
                        icon = OwnTVIcon.DOWNLOADS, height = 60.mpx, textSize = 20,
                    )
                }
''', '')
edit(series, 'firstFocusKey = "download",', 'firstFocusKey = "play_start",')
edit(movies, '    val alreadyDownloadedMessage = stringResource(R.string.content_already_downloaded)\n', '')
edit(movies, '    val downloadStates by vm.downloadStates.collectAsStateWithLifecycle()\n', '')
edit(movies, '        val alreadyDownloaded = downloadStates[m.id] != null\n', '')
edit(series, '    val alreadyDownloadedMessage = stringResource(R.string.content_already_downloaded)\n', '', 2)
edit(series, '    val downloads by vm.episodeDownloads.collectAsStateWithLifecycle()\n', '')

# Hide media download choices even from navigation and context-menu customization.
menus = core / "menu/ContentMenus.kt"
edit(menus, '    MenuActionRef("download", R.string.content_download),\n', '', 2)
edit(menus, '    MenuActionRef("download", R.string.content_download_all_episodes),\n', '')
edit(app / "features/shell/components/StageRail.kt", '    MainSection.MOVIES, MainSection.SERIES, MainSection.DOWNLOADS,', '    MainSection.MOVIES, MainSection.SERIES,')
edit(app / "features/settings/NavigationSettingsPopup.kt", '    MainSection.DOWNLOADS to OwnTVIcon.DOWNLOADS,\n', '')
edit(app / "features/settings/ChNavSettingsScreen.kt", 'val actionOptions = RemoteShortcutAction.entries.map', 'val actionOptions = RemoteShortcutAction.entries.filter { it != RemoteShortcutAction.OPEN_DOWNLOADS }.map')
edit(app / "features/settings/ChNavSettingsScreen.kt", 'val sorted = bindings.sortedWith(', 'val sorted = bindings.filter { it.action != RemoteShortcutAction.OPEN_DOWNLOADS }.sortedWith(')
edit(app / "features/shell/OwnTVShell.kt", 'RemoteShortcutAction.OPEN_DOWNLOADS -> openShortcutSection(MainSection.DOWNLOADS)', 'RemoteShortcutAction.OPEN_DOWNLOADS -> Unit')
edit(app / "features/shell/OwnTVShell.kt", '    tv.own.owntv.features.downloads.DownloadWatchPrompt(onClosePlayer = { if (playerMode != PlayerMode.NONE) exitPlayer() })\n', '')

# Movie art: request source-resolution TMDB backdrops; decode at TV resolution,
# retain existing previews and use a separate low-contrast wash behind rows.
edit(movies, 'MetadataImages.backdrop(meta?.backdropPath)', 'MetadataImages.backdrop(meta?.backdropPath, size = "original")')
edit(movies, 'MetadataImages.backdrop(meta?.backdropPath, size = "w1280")', 'MetadataImages.backdrop(meta?.backdropPath, size = "original")')
edit(movies, 'CatalogueMovieBackdrop(titleInfo?.backdropUrl)', 'CatalogueMovieBackdrop(titleInfo?.backdropUrl ?: titleInfo?.posterUrl)')
edit(app / "features/shell/components/CinemaCategoryRows.kt", 'Color.Black.copy(alpha = 0.58f)', 'Color.Black.copy(alpha = 0.32f)')
vod = app / "features/shell/components/VodStage.kt"
edit(vod, '''    resolvePreview: suspend () -> String? = { null },
) {
    var settled''', '''    resolvePreview: suspend () -> String? = { null },
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var settled''')
edit(vod, '''                AsyncImage(model = u, contentDescription = null, contentScale = ContentScale.Crop, alignment = focus, modifier = Modifier.fillMaxSize())''', '''                val request = if (!series) remember(u) { ImageRequest.Builder(context).data(u).size(1920, 1080).build() } else u
                AsyncImage(model = request, contentDescription = null, contentScale = ContentScale.Crop, alignment = focus,
                    filterQuality = androidx.compose.ui.graphics.FilterQuality.High, modifier = Modifier.fillMaxSize())''')
print("Media download UI removed; movie catalogue backgrounds enabled in HD.")

# Refresh the strict translation inventory after removing obsolete technical
# action keys and changing the TMDB image-size and episode focus identifiers.
app_root = root / "InterFlashTV-OwnTV"
core_root = root / "OwnTV_Core-main"
checker = "tools/i18n/check_hardcoded_strings.py"
for module in (app_root, core_root):
    subprocess.run(["python3", checker, "prune-safe"], cwd=module, check=True)
for path, value, category in (
    ("app/src/main/java/tv/own/owntv/features/movies/MoviesScreen.kt", "original", "uri"),
    ("app/src/main/java/tv/own/owntv/features/series/SeriesScreen.kt", "play_start", "technical"),
):
    subprocess.run(["python3", checker, "classify-safe", "--path", path,
                    "--text", value, "--category", category], cwd=app_root, check=True)
for module in (app_root, core_root):
    subprocess.run(["python3", checker, "verify", "--bootstrap"], cwd=module, check=True)
