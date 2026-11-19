from pathlib import Path

root = Path('native-source/InterFlashTV-OwnTV/app/src/main/java/tv/own/owntv/features')

def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Unexpected source: {old}')
    return source.replace(old, new)

for section, filename, items in [('movies', 'MoviesScreen.kt', 'movies'), ('series', 'SeriesScreen.kt', 'series')]:
    path = root / section / filename
    s = path.read_text()
    s = replace_once(s, 'var categoriesOpen by remember { mutableStateOf(false) }', '''var categoriesOpen by remember { mutableStateOf(false) }
    val catalogueFocus = remember { FocusRequester() }
    var restoreCatalogueFocus by remember { mutableStateOf(false) }''')
    s = replace_once(s, 'androidx.activity.compose.BackHandler(enabled = categoriesOpen && tv.own.owntv.features.shell.InterFlashClientMode.administrator) { categoriesOpen = false; focusCurrentTitle() }', '''androidx.activity.compose.BackHandler(enabled = categoriesOpen || (!tv.own.owntv.features.shell.InterFlashClientMode.administrator && lockedKey == null && selectedKey != LiveKey.All)) {
        if (categoriesOpen) categoriesOpen = false else vm.select(LiveKey.All)
        vm.setCategoryQuery("")
        if (tv.own.owntv.features.shell.InterFlashClientMode.administrator) focusCurrentTitle() else restoreCatalogueFocus = true
    }
    LaunchedEffect(restoreCatalogueFocus, selectedKey, categoriesOpen) {
        if (restoreCatalogueFocus && !categoriesOpen) {
            for (attempt in 0 until 60) {
                withFrameNanos { }
                if (runCatching { firstItemFocus.requestFocus() }.getOrDefault(false)) break
            }
            restoreCatalogueFocus = false
        }
    }''')
    # A choice should restore focus after the newly filtered dataset has mounted.
    s = replace_once(s, 'if (categoriesOpen) { categoriesOpen = false; focusTitles() }', 'if (categoriesOpen) { categoriesOpen = false; vm.setCategoryQuery(""); if (tv.own.owntv.features.shell.InterFlashClientMode.administrator) focusTitles() else restoreCatalogueFocus = true }')
    s = replace_once(s, '''Modifier.padding(start = fx(68), end = fx(64)).fillMaxWidth(),
                            verticalAlignment''', '''Modifier.padding(horizontal = 12.mpx).fillMaxWidth(),
                            verticalAlignment''')
    s = replace_once(s, '''text = stringResource(R.string.interflash_view_catalog),
                                icon = OwnTVIcon.LIST,
                                onClick = { categoriesOpen = true },''', '''text = stringResource(R.string.interflash_view_catalog),
                                icon = OwnTVIcon.LIST, boxed = true,
                                modifier = Modifier.focusRequester(catalogueFocus).onPreviewKeyEvent { e ->
                                    e.type == KeyEventType.KeyDown && when (e.key) {
                                        Key.DirectionUp -> { onTopMenu(); true }
                                        Key.DirectionDown -> runCatching { firstItemFocus.requestFocus() }.getOrDefault(false)
                                        else -> false
                                    }
                                },
                                onClick = { vm.setCategoryQuery(""); categoriesOpen = true },''')
    s = replace_once(s, 'onTopMenu = onTopMenu,\n                            modifier = Modifier.fillMaxWidth().weight(1f),', 'onTopMenu = { runCatching { catalogueFocus.requestFocus() } },\n                            modifier = Modifier.fillMaxWidth().weight(1f),')
    if section == 'movies':
        s = replace_once(s, 'if (!cinemaRows) VodCinematicBackdrop(', '''if (cinemaRows) tv.own.owntv.features.shell.components.CatalogueMovieBackdrop(titleInfo?.backdropUrl)
                if (!cinemaRows) VodCinematicBackdrop(''')
    path.write_text(s)

p = root / 'shell/components/CinemaCategoryRows.kt'
s = p.read_text()
s = replace_once(s, '''            Column(Modifier.drawWithContent {
                val layout = columnState.layoutInfo
                val entry = layout.visibleItemsInfo.firstOrNull { it.index == row }
                if (row == activeRow || (entry != null && entry.offset >= layout.viewportStartOffset &&
                            entry.offset + entry.size <= layout.viewportEndOffset)) {
                    drawContent()
                }
            }) {''', '            Column {')
s = replace_once(s, 'contentPadding = PaddingValues(top = 2.mpx, bottom = 10.mpx)', 'contentPadding = PaddingValues(top = 0.mpx, bottom = 0.mpx)')
s = replace_once(s, 'Arrangement.spacedBy(6.mpx)', 'Arrangement.spacedBy(3.mpx)')
s = replace_once(s, 'minOf(640.mpx, maxWidth)', 'minOf(480.mpx, maxWidth)')
s = replace_once(s, 'if (selected) 360.mpx else 276.mpx', 'if (selected) 270.mpx else 214.mpx')
s = replace_once(s, 'val posterWidth = 184.mpx', 'val posterWidth = 144.mpx')
s = replace_once(s, 'minOf(192.mpx,', 'minOf(152.mpx,')
s = replace_once(s, 'bottom = 6.mpx))', 'bottom = 2.mpx))')
s = replace_once(s, '(singleTitles.itemCount + 7) / 8', '(singleTitles.itemCount + 11) / 12')
s = replace_once(s, 'if (singleTitles != null) row * 8 else 0', 'if (singleTitles != null) row * 12 else 0')
s = replace_once(s, '(titles.itemCount - startIndex).coerceIn(0, 8)', '(titles.itemCount - startIndex).coerceIn(0, 12)')
s = replace_once(s, 'var activeRow by remember { mutableIntStateOf(0) }', 'var activeRow by remember(categories.map { it.item.key }) { mutableIntStateOf(0) }')
s += '''

/** Movie-only artwork, with a dark wash so catalogue labels stay legible. */
@Composable
internal fun CatalogueMovieBackdrop(url: String?) {
    if (url.isNullOrBlank()) return
    val context = LocalContext.current
    val sharp = if (url.startsWith("https://image.tmdb.org/t/p/"))
        url.replace(Regex("/w[0-9]+/"), "/original/") else url
    val request = remember(sharp) { ImageRequest.Builder(context).data(sharp).size(1920, 1080).build() }
    Box(Modifier.fillMaxSize()) {
        AsyncImage(model = request, contentDescription = null, contentScale = ContentScale.Crop,
            filterQuality = FilterQuality.High, modifier = Modifier.fillMaxSize())
        Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.58f)))
    }
}
'''
p.write_text(s)

p = root / 'shell/OwnTVShell.kt'
s = replace_once(p.read_text(), 'top = if (clientMode) 112.mpx else 0.dp,', 'top = if (classicVod) 94.mpx else if (clientMode) 112.mpx else 0.dp,')
p.write_text(s)
