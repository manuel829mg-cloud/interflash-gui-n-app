#!/usr/bin/env python3
"""Apply the approved compact, Spanish, premium movie catalogue layout."""
from pathlib import Path
import subprocess

root = Path("native-source/InterFlashTV-OwnTV")
app = root / "app/src/main/java/tv/own/owntv"
features = app / "features"

def edit(path, old, new, expected=1):
    s = path.read_text(encoding="utf-8")
    assert s.count(old) == expected, (path, old, s.count(old))
    path.write_text(s.replace(old, new), encoding="utf-8")

movies = features / "movies/MoviesScreen.kt"
shell = features / "shell/OwnTVShell.kt"
rail = features / "shell/components/StageRail.kt"
rows = features / "shell/components/CinemaCategoryRows.kt"

# Move the catalogue action into the top bar; keep the existing category sheet
# and focus restoration behavior. The callback is installed only while Movies
# is mounted, so it cannot accidentally affect another section.
edit(movies, '    onTopMenu: () -> Unit = {},\n', '    onTopMenu: () -> Unit = {},\n    onCatalogueHook: ((() -> Unit)?) -> Unit = {},\n')
edit(movies, '    val catalogueFocus = remember { FocusRequester() }\n', '')
edit(movies, '    var restoreCatalogueFocus by remember { mutableStateOf(false) }', '''    var restoreCatalogueFocus by remember { mutableStateOf(false) }
    DisposableEffect(Unit) {
        onCatalogueHook { vm.setCategoryQuery(""); categoriesOpen = true }
        onDispose { onCatalogueHook(null) }
    }''')
source = movies.read_text(encoding="utf-8")
start = source.index('                    if (cinemaRows) {\n                        Row(')
end = source.index('                        CinemaCategoryRows(', start)
assert 'catalogueFocus' in source[start:end]
movies.write_text(source[:start] + '                    if (cinemaRows) {\n' + source[end:], encoding="utf-8")
edit(movies, 'onTopMenu = { runCatching { catalogueFocus.requestFocus() } },', 'onTopMenu = onTopMenu,')
edit(movies, '                            placeholder = OwnTVIcon.MOVIES,\n                            firstFocus = firstItemFocus,', '                            placeholder = OwnTVIcon.MOVIES,\n                            cleanMovieCards = true,\n                            firstFocus = firstItemFocus,')

edit(shell, '    var vodEntry by remember { mutableStateOf<(() -> Boolean)?>(null) }', '''    var vodEntry by remember { mutableStateOf<(() -> Boolean)?>(null) }
    var movieCatalogueAction by remember { mutableStateOf<(() -> Unit)?>(null) }''')
edit(shell, '''                        selectedSection == MainSection.MOVIES -> MoviesScreen(
                            onFullscreen = { openFullscreen() },''', '''                        selectedSection == MainSection.MOVIES -> MoviesScreen(
                            onCatalogueHook = { movieCatalogueAction = it },
                            onFullscreen = { openFullscreen() },''')
edit(shell, '''                            placeholder = stringResource(R.string.content_search_in,
                                stringResource(if (selectedSection == MainSection.MOVIES) R.string.content_category_all_movies else R.string.content_category_all_series)),
                            modifier = Modifier.width(400.mpx),''', '''                            placeholder = if (selectedSection == MainSection.MOVIES) stringResource(R.string.if_movies_search)
                                else stringResource(R.string.content_search_in, stringResource(R.string.content_category_all_series)),
                            modifier = Modifier.width(if (selectedSection == MainSection.MOVIES) 840.mpx else 400.mpx),''')
edit(shell, '                nowPlaying = nowPlayingRail,\n                onNowPlaying = enterNowPlaying,', '''                clientCatalogue = {
                    if (selectedSection == MainSection.MOVIES) {
                        tv.own.owntv.ui.stage.StageTool(
                            text = stringResource(R.string.if_movies_catalog),
                            icon = tv.own.owntv.ui.components.OwnTVIcon.LIST,
                            boxed = true,
                            onClick = { movieCatalogueAction?.invoke() },
                        )
                    }
                },
                nowPlaying = nowPlayingRail,
                onNowPlaying = enterNowPlaying,''')

edit(rail, '    clientSearch: (@Composable () -> Unit)? = null,', '    clientSearch: (@Composable () -> Unit)? = null,\n    clientCatalogue: (@Composable () -> Unit)? = null,')
edit(rail, 'modifier.fillMaxWidth().padding(top = if (selected == MainSection.MOVIES) 4.mpx else if (selected == MainSection.SERIES) 8.mpx else 20.mpx).height(if (selected == MainSection.MOVIES) 62.mpx else 72.mpx)', '''modifier.fillMaxWidth()
                .then(if (selected == MainSection.MOVIES) Modifier.background(Color(0xFF080F1B)).padding(horizontal = 28.mpx) else Modifier)
                .padding(top = if (selected == MainSection.MOVIES) 4.mpx else if (selected == MainSection.SERIES) 8.mpx else 20.mpx)
                .height(if (selected == MainSection.MOVIES) 62.mpx else 72.mpx)''')
edit(rail, 'horizontalArrangement = Arrangement.spacedBy(18.mpx, Alignment.CenterHorizontally),', 'horizontalArrangement = Arrangement.spacedBy(18.mpx, if (selected == MainSection.MOVIES) Alignment.Start else Alignment.CenterHorizontally),')
edit(rail, '''            items.forEach { section ->
                tv.own.owntv.ui.stage.StageTool(
                    text = stringResource(section.labelRes),''', '''            if (selected == MainSection.MOVIES) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.mpx)) {
                    BrandMark(rememberAppliedIcon(), 36.mpx)
                    Wordmark(260.mpx)
                }
            }
            items.forEach { section ->
                tv.own.owntv.ui.stage.StageTool(
                    text = stringResource(if (section == MainSection.MOVIES) R.string.if_menu_movies else section.labelRes),''')
edit(rail, '            clientSearch?.invoke()\n', '''            clientSearch?.invoke()
            if (selected == MainSection.MOVIES) {
                Spacer(Modifier.weight(1f))
                clientCatalogue?.invoke()
            }
''')

# Restrict cosmetic changes to movie cards. Poster labels remain available on
# cards lacking artwork, and the focused movie retains title and rating below.
edit(rows, '    modifier: Modifier = Modifier,\n) {', '    modifier: Modifier = Modifier,\n    cleanMovieCards: Boolean = false,\n) {')
edit(rows, 'Text(category.label, style = stageText(25, 700),', '''Text(if (cleanMovieCards && '|' in category.label) category.label.substringBefore('|').trim().lowercase().replaceFirstChar { it.titlecase() } else category.label, style = stageText(if (cleanMovieCards) 29 else 25, 700),''')
edit(rows, 'if (!selected) Text(title(item),', 'if (!selected && (!cleanMovieCards || artwork == null)) Text(title(item),')
edit(rows, '.border(if (selected) 3.mpx else 0.mpx,', '.border(if (selected) (if (cleanMovieCards) 4 else 3).mpx else 0.mpx,')
edit(rows, 'listOf(Color(0xFF071322), Color(0xFF142C43), Color(0xFF080F1B))', 'listOf(Color(0xFF050B14), Color(0xFF0C1A2B), Color(0xFF060D17))')
edit(rows, 'modifier = Modifier.fillMaxSize(), alpha = 0.50f)', 'modifier = Modifier.fillMaxSize(), alpha = 0.22f)')

res = root / "app/src/main/res"
for locale in ("values", "values-es"):
    (res / locale / "strings_interflash_movie_design.xml").write_text('''<resources>
    <string name="if_movies_search">Buscar películas</string>
    <string name="if_movies_catalog">Ver catálogo</string>
</resources>
''', encoding="utf-8")

checker = "tools/i18n/check_hardcoded_strings.py"
subprocess.run(["python3", checker, "prune-safe"], cwd=root, check=True)
subprocess.run(["python3", checker, "verify", "--bootstrap"], cwd=root, check=True)
print("Applied elegant movie catalogue layout, compact header and clean posters.")
