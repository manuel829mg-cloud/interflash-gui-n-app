#!/usr/bin/env python3
"""Persist Dominican channel placement on import and compact the live information banner."""
from pathlib import Path
import json
import re
import subprocess

root = Path('native-source')
app_root = root / 'InterFlashTV-OwnTV'
core_root = root / 'OwnTV_Core-main'
app = app_root / 'app/src/main/java/tv/own/owntv'
core = core_root / 'core/src/main/java/tv/own/owntv/core'

def edit(path, old, new):
    source = path.read_text()
    assert source.count(old) == 1, (path, old)
    path.write_text(source.replace(old, new))

# Share the existing agreed broadcast-number mapping with the playlist importer.
mapping = app / 'interflash/DominicanChannelNumbers.kt'
edit(mapping, 'Normalizer.Form.NFD', 'Normalizer.Form.NFKD')
edit(mapping, '5 to listOf("telemicro")', '5 to listOf("telemicro", "telemicro int", "telemicro internacional")')
mapper = core / 'sync/DominicanChannelNumbers.kt'
mapper.write_text(mapping.read_text().replace('package tv.own.owntv.interflash', 'package tv.own.owntv.core.sync') + '''
internal object DominicanPlacement {
    fun isDominican(name: String, group: String?): Boolean {
        val region = group.orEmpty().lowercase(Locale.ROOT)
        val title = name.trim().lowercase(Locale.ROOT)
        return region.contains("dominican") || title.startsWith("rd |") || title.startsWith("rd:") ||
            title.startsWith("do |") || title.startsWith("do:")
    }
    fun group(name: String, original: String?): String? =
        if (isDominican(name, original)) "Dominicana" else original
}
''')

sync = core / 'sync/M3uSyncer.kt'
edit(sync, 'categoryId = group?.let { groupToCategoryId[MediaType.LIVE to it] },',
     'categoryId = DominicanPlacement.group(entry.name, group)?.let { groupToCategoryId[MediaType.LIVE to it] },')
edit(sync, 'sortOrder = item.order,\n                        catchup', '''sortOrder = if (DominicanPlacement.isDominican(entry.name, group)) {
                            val fixed = DominicanChannelNumbers.known(entry.name)
                            if (fixed != null) fixed * 10000 + item.order.coerceAtMost(9999)
                            else 10000000 + item.order
                        } else item.order,
                        catchup''')
edit(sync, 'e.groupTitle?.let { queueCategory(MediaType.LIVE, it) }',
     'DominicanPlacement.group(e.name, e.groupTitle)?.let { queueCategory(MediaType.LIVE, it) }')
edit(sync, 'val renumbered = PlaylistNumbering.apply(channelDao, s.id, providerNumbered, unnumberedKeys)', '''val renumbered = PlaylistNumbering.apply(channelDao, s.id, providerNumbered, unnumberedKeys)
                groupToCategoryId[MediaType.LIVE to "Dominicana"]?.let { categoryId ->
                    val fixed = channelDao.dominicanNumericChannels(listOf(categoryId)).mapNotNull { ch ->
                        DominicanChannelNumbers.known(ch.name)?.let { ch.id to it }
                    }
                    if (fixed.isNotEmpty()) channelDao.applyNumbers(fixed.map { it.first }, fixed.map { it.second })
                }''')

# The normal live banner already auto-hides after five seconds. Keep that behavior;
# tighten the card and put the station number alongside the name.
chrome = app / 'player/PlayerHudChrome.kt'
edit(chrome, 'modifier.widthIn(max = if (guide != null) 600.dp else 420.dp).clip(RoundedCornerShape(14.dp)).background(Color.Black.copy(alpha = 0.88f)).padding(14.dp)',
     'modifier.widthIn(max = if (guide != null) 600.dp else 420.dp).clip(RoundedCornerShape(8.dp)).background(Color.Black.copy(alpha = 0.82f)).padding(horizontal = 12.dp, vertical = 7.dp)')
edit(chrome, '''        Column {
            Text(title ?: "", style = tv.own.owntv.ui.theme.stageText(25, 500), color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
            subtitle?.takeIf { it.isNotBlank() }?.let {
                Text(it.removePrefix("#").trim(), style = tv.own.owntv.ui.theme.stageText(36, 800), color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            guide?.invoke()
        }''', '''        Column(Modifier.weight(1f, fill = false)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                subtitle?.takeIf { it.isNotBlank() }?.let {
                    Text(it.removePrefix("#").trim(), style = tv.own.owntv.ui.theme.stageText(25, 800), color = Color.White, maxLines = 1)
                }
                Text(title ?: "", modifier = Modifier.weight(1f, fill = false), style = tv.own.owntv.ui.theme.stageText(22, 600), color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            guide?.invoke()
        }''')

hud = app / 'player/PlayerHud.kt'
edit(hud, 'Text(stringResource(R.string.content_live_time_range, clock(programme.startMs), clock(programme.stopMs)), style = tv.own.owntv.ui.theme.stageText(18, 500), color = Color.White.copy(alpha = 0.9f))', '''val now = System.currentTimeMillis()
                    val active = now >= programme.startMs && now < programme.stopMs
                    val remaining = ((programme.stopMs - now + 59999L) / 60000L).toInt()
                    Text(if (active) stringResource(R.string.content_live_time_remaining, clock(programme.stopMs), remaining)
                         else stringResource(R.string.content_live_time_range, clock(programme.startMs), clock(programme.stopMs)), style = tv.own.owntv.ui.theme.stageText(18, 500), color = Color.White.copy(alpha = 0.9f))
                    if (active && programme.stopMs > programme.startMs) {
                        val progress = ((now - programme.startMs).toFloat() / (programme.stopMs - programme.startMs)).coerceIn(0f, 1f)
                        Box(Modifier.fillMaxWidth().height(3.dp).clip(RoundedCornerShape(2.dp)).background(Color.White.copy(alpha = 0.25f))) {
                            Box(Modifier.fillMaxWidth(progress).height(3.dp).background(tv.own.owntv.ui.theme.stageAccent.accent))
                        }
                    }''')
guide = app / 'features/shell/components/LiveEpgCard.kt'
edit(guide, '            val remaining = ((entry.stopMs - nowMs) / 60_000L).toInt()\n            Text(',
     '            val remaining = ((entry.stopMs - nowMs + 59_999L) / 60_000L).toInt()\n            Text(')

def classify(base, path, value, category):
    subprocess.run(['python3', 'tools/i18n/check_hardcoded_strings.py', 'classify-safe',
                    '--path', str(path.relative_to(base)), '--text', value, '--category', category], cwd=base, check=True)

for base, path in [(app_root, mapping), (core_root, mapper)]:
    for value in sorted(set(json.loads(m.group()) for m in re.finditer(r'"(?:\\.|[^"\\])*"', path.read_text()))):
        classify(base, path, value, 'empty' if not value.strip() else 'regex')
classify(core_root, sync, 'Dominicana', 'protocol')
