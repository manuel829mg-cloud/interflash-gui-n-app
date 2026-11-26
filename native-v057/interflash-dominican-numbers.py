#!/usr/bin/env python3
"""Use Dominican broadcast channel numbers, not the IPTV playlist's positions."""
from pathlib import Path
root = Path("native-source")
app = root / "InterFlashTV-OwnTV/app/src/main/java/tv/own/owntv"
core = root / "OwnTV_Core-main/core/src/main/java/tv/own/owntv/core"

def edit(path, old, new):
    s = path.read_text(encoding="utf-8")
    assert s.count(old) == 1, f"Expected one anchor in {path}: {old[:120]}"
    path.write_text(s.replace(old, new, 1), encoding="utf-8")

dao = core / "database/dao/ChannelDao.kt"
edit(dao, "    // --- Direct tune (channel-number lookup) ---", """    @Query("SELECT * FROM channels WHERE categoryId IN (:categoryIds) ORDER BY sourceId, sortOrder, id")
    suspend fun dominicanNumericChannels(categoryIds: List<Long>): List<ChannelEntity>

    // --- Direct tune (channel-number lookup) ---""")

mapping = app / "interflash/DominicanChannelNumbers.kt"
mapping.write_text(r'''package tv.own.owntv.interflash

import java.text.Normalizer
import java.util.Locale

/** Integer shortcuts for known Dominican TV identities. No inferred playlist positions. */
internal object DominicanChannelNumbers {
    private fun normalize(value: String): String =
        Normalizer.normalize(value, Normalizer.Form.NFD)
            .replace(Regex("\\p{M}+"), "")
            .lowercase(Locale.ROOT)
            .replace(Regex("[^a-z0-9]+"), " ")
            .trim()

    private val aliases = linkedMapOf(
        2 to listOf("teleantillas", "tele antillas"),
        4 to listOf("rtvd canal 4", "canal 4 rd", "certv", "rtvd", "canal 4"),
        5 to listOf("telemicro"),
        6 to listOf("el seis"),
        7 to listOf("antena 7", "antena latina"),
        8 to listOf("telemedios dominicana", "telemedios"),
        9 to listOf("color vision", "colorvision"),
        10 to listOf("microvision"),
        11 to listOf("telesistema"),
        12 to listOf("teleunion"),
        13 to listOf("telecentro"),
        14 to listOf("atv", "atv 14"),
        15 to listOf("digital 15", "digital quince", "telemicro digital 15"),
        16 to listOf("noticias 16"),
        17 to listOf("rtvd 17", "quisqueya television", "qtv 17"),
        18 to listOf("ame 47", "ame tv", "ame 18"),
        19 to listOf("cinevision"),
        20 to listOf("teleradio america", "tele radio america"),
        21 to listOf("antena 21"),
        23 to listOf("telefuturo"),
        26 to listOf("canal del sol"),
        27 to listOf("rnn", "rnn canal 27"),
        28 to listOf("telecanal 28", "galaxia teve"),
        29 to listOf("teleuniverso", "tele universo"),
        32 to listOf("vtv", "vtv television"),
        33 to listOf("supercanal", "super canal"),
        35 to listOf("telecontacto"),
        25 to listOf("cdn deportes", "cdn sports"),
        37 to listOf("cdn", "cdn 37"),
        39 to listOf("coral 39", "coral tv"),
        41 to listOf("televida"),
        42 to listOf("romana tv"),
        44 to listOf("tele ola"),
        53 to listOf("la voz de maria"),
        55 to listOf("super tv 55", "super tv"),
        57 to listOf("ecos 57", "ecos tv"),
        63 to listOf("digital vision"),
        70 to listOf("carivision", "cari vision"),
        72 to listOf("entelevision", "en television"),
        75 to listOf("catorce tv"),
        77 to listOf("hilando fino tv"),
        90 to listOf("biz tv"),
        99 to listOf("nexxo tv")
    )

    fun known(name: String): Int? {
        val cleaned = normalize(name)
            .replace(Regex("^(?:(?:rd|do|dominicana|republica dominicana|latino) )+"), "")
            .replace(Regex(" (?:fhd|uhd|hd|sd|4k|1080p|720p|480p|hevc|h265|h264|rd|do|dominicana|republica dominicana|backup|vip)(?= |$)"), "")
            .trim()
        val withoutLabel = cleaned.replace(Regex(" (?:canal )?[0-9]{1,3}$"), "")
        // Prefer exact aliases (e.g. RTVD 17, CDN Deportes, not RTVD or CDN).
        return aliases.entries.firstOrNull { (_, names) -> names.any { Regex(it).matches(cleaned) } }?.key
            ?: aliases.entries.firstOrNull { (_, names) -> names.any { Regex(it).matches(withoutLabel) } }?.key
    }

    /** Unknown channels need an explicit on-air number in their title, not the stream ID. */
    fun explicit(name: String): Int? {
        val n = normalize(name)
        if (Regex("\\b(?:espn|fox sports|hbo|discovery|history|nick|rnn2|edumas)\\b").containsMatchIn(n)) return null
        return Regex("\\b(?:canal|channel) ([0-9]{1,3})\\b").find(n)
            ?.groupValues?.get(1)?.toIntOrNull()?.takeIf { it in 1..999 }
            ?: Regex("\\b([0-9]{1,3})(?: (?:hd|fhd|sd|uhd|rd|do|backup))*$").find(n)
                ?.groupValues?.get(1)?.toIntOrNull()?.takeIf { it in 1..999 }
    }
}
''', encoding="utf-8")

vm = app / "features/live/LiveViewModel.kt"
s = vm.read_text(encoding="utf-8")
start = s.index("            val restrictedCategoryId = if (isDominicanFolder(snapshotZapTitle))")
end = s.index("            // DB queries on IO", start)
s = s[:start] + s[end:]
start = s.index("                // Stage 1: query the currently playing source.")
end = s.index("\n            }\n\n            // Dispatch the lookup outcome.", start)
s = s[:start] + """                val numericSources = (listOf(currentChannel.sourceId) + snapshotSourceIds).distinct()
                val dominicanIds = categoryDao.observe(numericSources, MediaType.LIVE).first()
                    .filter { isDominicanFolder(it.name) }
                    .map { it.id }
                if (dominicanIds.isEmpty()) return@withContext ChannelNumberLookupResult.NotFound
                val candidates = channelDao.dominicanNumericChannels(dominicanIds)
                    .filter { isChannelVisible(it, currentCustom, activeHiddenCats) }
                val knownMatches = candidates.filter {
                    tv.own.owntv.interflash.DominicanChannelNumbers.known(it.name) == number
                }
                val matches = knownMatches.ifEmpty {
                    candidates.filter {
                        tv.own.owntv.interflash.DominicanChannelNumbers.known(it.name) == null &&
                            tv.own.owntv.interflash.DominicanChannelNumbers.explicit(it.name) == number
                    }
                }
                if (matches.isEmpty()) return@withContext ChannelNumberLookupResult.NotFound
                val local = matches.filter { it.sourceId == currentChannel.sourceId }.ifEmpty { matches }
                val r = tv.own.owntv.player.resolveDirectTuneCandidate(
                    local.map { it.id }, snapshotZapList.map { it.id }.toSet(),
                )?.let { id -> local.first { it.id == id } }
                    // Prefer the original HD/SD variants of the same known station, not another channel.
                    ?: if (knownMatches.isNotEmpty()) local.firstOrNull { it.id == currentChannel.id }
                        ?: local.firstOrNull { it.id in snapshotZapList.map { ch -> ch.id }.toSet() }
                        ?: local.first()
                    else return@withContext ChannelNumberLookupResult.Ambiguous(local.size)
                val customName = currentCustom.itemNames[CustomizeKeys.channel(r)]
                ChannelNumberLookupResult.Found(r.copy(name = customName ?: r.name, number = number))
""" + s[end:]
vm.write_text(s, encoding="utf-8")

# Preserve the existing number-entry timer, playback and technician shortcut.
print("Dominican numeric routing patched; ambiguous regional labels fail safely.")


# Explicitly classify technical matching patterns, never UI strings.
import re
import json
import subprocess
app_root = root / "InterFlashTV-OwnTV"
core_root = root / "OwnTV_Core-main"
app_path = "app/src/main/java/tv/own/owntv/interflash/DominicanChannelNumbers.kt"
core_path = "core/src/main/java/tv/own/owntv/core/database/dao/ChannelDao.kt"
def classify(base, relpath, value, category):
    subprocess.run(["python3", "tools/i18n/check_hardcoded_strings.py",
                    "classify-safe", "--path", relpath, "--text", value,
                    "--category", category], cwd=base, check=True)

strings = set(json.loads(m.group()) for m in re.finditer(r'"(?:\\.|[^"\\])*"', mapping.read_text(encoding="utf-8")))
for value in sorted(strings):
    classify(app_root, app_path, value, "empty" if not value.strip() else "regex")
classify(core_root, core_path, "SELECT * FROM channels WHERE categoryId IN (:categoryIds) ORDER BY sourceId, sortOrder, id", "sql")
