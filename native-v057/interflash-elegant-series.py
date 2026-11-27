#!/usr/bin/env python3
"""Match Series to the approved movie catalogue and use authentic branding."""
from pathlib import Path
import subprocess

root = Path("native-source/InterFlashTV-OwnTV")
features = root / "app/src/main/java/tv/own/owntv/features"

def edit(path, old, new, expected=1):
    s = path.read_text(encoding="utf-8")
    assert s.count(old) == expected, (path, old, s.count(old))
    path.write_text(s.replace(old, new), encoding="utf-8")

series = features / "series/SeriesScreen.kt"
shell = features / "shell/OwnTVShell.kt"
rail = features / "shell/components/StageRail.kt"

# The shell receives a catalogue action only while the Series grid is mounted.
# The episode/season screen continues to use its existing navigation.
edit(series, '    onTopMenu: () -> Unit = {},\n', '    onTopMenu: () -> Unit = {},\n    onCatalogueHook: ((() -> Unit)?) -> Unit = {},\n')
edit(series, '            onTopMenu = onTopMenu,\n            modifier = modifier,', '            onTopMenu = onTopMenu,\n            onCatalogueHook = onCatalogueHook,\n            modifier = modifier,')
edit(series, '    onTopMenu: () -> Unit,\n    modifier: Modifier,', '    onTopMenu: () -> Unit,\n    onCatalogueHook: ((() -> Unit)?) -> Unit,\n    modifier: Modifier,')
edit(series, '    val catalogueFocus = remember { FocusRequester() }\n', '')
edit(series, '    var restoreCatalogueFocus by remember { mutableStateOf(false) }', '''    var restoreCatalogueFocus by remember { mutableStateOf(false) }
    DisposableEffect(Unit) {
        onCatalogueHook { vm.setCategoryQuery(""); categoriesOpen = true }
        onDispose { onCatalogueHook(null) }
    }''')
source = series.read_text(encoding="utf-8")
start = source.index('                    if (cinemaRows) {\n                        Row(')
end = source.index('                        CinemaCategoryRows(', start)
assert 'catalogueFocus' in source[start:end]
series.write_text(source[:start] + '                    if (cinemaRows) {\n' + source[end:], encoding="utf-8")
edit(series, 'onTopMenu = { runCatching { catalogueFocus.requestFocus() } },', 'onTopMenu = onTopMenu,')
edit(series, '                            placeholder = OwnTVIcon.SERIES,\n                            firstFocus = firstItemFocus,', '                            placeholder = OwnTVIcon.SERIES,\n                            cleanMovieCards = true,\n                            firstFocus = firstItemFocus,')
edit(series, '                if (!cinemaRows) VodCinematicBackdrop(titleInfo?.backdropUrl ?: titleInfo?.posterUrl, series = true,', '''                if (!tv.own.owntv.features.shell.InterFlashClientMode.administrator && lockedKey == null)
                    tv.own.owntv.features.shell.components.CatalogueMovieBackdrop()
                if (tv.own.owntv.features.shell.InterFlashClientMode.administrator && !cinemaRows) VodCinematicBackdrop(titleInfo?.backdropUrl ?: titleInfo?.posterUrl, series = true,''')

edit(shell, '    var movieCatalogueAction by remember { mutableStateOf<(() -> Unit)?>(null) }', '    var movieCatalogueAction by remember { mutableStateOf<(() -> Unit)?>(null) }\n    var seriesCatalogueAction by remember { mutableStateOf<(() -> Unit)?>(null) }')
edit(shell, '''                        selectedSection == MainSection.SERIES -> SeriesScreen(
                            onFullscreen = { openFullscreen() },''', '''                        selectedSection == MainSection.SERIES -> SeriesScreen(
                            onCatalogueHook = { seriesCatalogueAction = it },
                            onFullscreen = { openFullscreen() },''')
edit(shell, 'top = if (clientMode && selectedSection == MainSection.MOVIES) 66.mpx else if (clientMode && selectedSection == MainSection.SERIES) 80.mpx', 'top = if (clientMode && selectedSection in listOf(MainSection.MOVIES, MainSection.SERIES)) 66.mpx')
edit(shell, '''placeholder = if (selectedSection == MainSection.MOVIES) stringResource(R.string.if_movies_search)
                                else stringResource(R.string.content_search_in, stringResource(R.string.content_category_all_series)),
                            modifier = Modifier.width(if (selectedSection == MainSection.MOVIES) 840.mpx else 400.mpx),''', '''placeholder = stringResource(if (selectedSection == MainSection.MOVIES) R.string.if_movies_search else R.string.if_series_search),
                            modifier = Modifier.width(840.mpx),''')
edit(shell, '''                clientCatalogue = {
                    if (selectedSection == MainSection.MOVIES) {''', '''                clientCatalogue = {
                    if (selectedSection == MainSection.MOVIES || (selectedSection == MainSection.SERIES && seriesCatalogueAction != null)) {''')
edit(shell, '                            onClick = { movieCatalogueAction?.invoke() },', '                            onClick = { if (selectedSection == MainSection.MOVIES) movieCatalogueAction?.invoke() else seriesCatalogueAction?.invoke() },')

# Use the existing approved Inter Flash emblem, not the generic player mark.
edit(rail, '                    BrandMark(rememberAppliedIcon(), 36.mpx)', '''                    Image(painterResource(R.drawable.interflash_brand), contentDescription = null,
                        modifier = Modifier.size(48.mpx))''')
edit(rail, '.then(if (selected == MainSection.MOVIES) Modifier.background(Color(0xFF080F1B)).padding(horizontal = 28.mpx) else Modifier)', '.then(if (classicVod) Modifier.background(Color(0xFF080F1B)).padding(horizontal = 28.mpx) else Modifier)')
edit(rail, '.padding(top = if (selected == MainSection.MOVIES) 4.mpx else if (selected == MainSection.SERIES) 8.mpx else 20.mpx)', '.padding(top = if (classicVod) 4.mpx else 20.mpx)')
edit(rail, '.height(if (selected == MainSection.MOVIES) 62.mpx else 72.mpx)', '.height(if (classicVod) 62.mpx else 72.mpx)')
edit(rail, 'if (selected == MainSection.MOVIES) Alignment.Start else Alignment.CenterHorizontally', 'if (classicVod) Alignment.Start else Alignment.CenterHorizontally')
edit(rail, '            if (selected == MainSection.MOVIES) {\n', '            if (classicVod) {\n', 2)
edit(rail, 'text = stringResource(if (section == MainSection.MOVIES) R.string.if_menu_movies else section.labelRes),', 'text = stringResource(when (section) { MainSection.MOVIES -> R.string.if_menu_movies; MainSection.SERIES -> R.string.if_menu_series; else -> section.labelRes }),')

for locale in ("values", "values-es"):
    p = root / "app/src/main/res" / locale / "strings_interflash_movie_design.xml"
    edit(p, '</resources>', '    <string name="if_series_search">Buscar series</string>\n</resources>')

checker = "tools/i18n/check_hardcoded_strings.py"
subprocess.run(["python3", checker, "prune-safe"], cwd=root, check=True)
subprocess.run(["python3", checker, "verify", "--bootstrap"], cwd=root, check=True)
print("Series matches Movies catalogue; original Inter Flash logo applied to both.")
