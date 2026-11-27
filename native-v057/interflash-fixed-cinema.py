#!/usr/bin/env python3
"""Keep the movie catalogue backdrop fixed and reclaim vertical space."""
from pathlib import Path
import subprocess

root = Path("native-source/InterFlashTV-OwnTV")
app = root / "app/src/main/java/tv/own/owntv"
features = app / "features"

def edit(path, old, new):
    s = path.read_text(encoding="utf-8")
    assert s.count(old) == 1, (path, old, s.count(old))
    path.write_text(s.replace(old, new), encoding="utf-8")

# Native vector: a cinematic projection booth, film reels and film strips.
# At television size it renders sharply without a network request or bitmap scaling.
drawable = root / "app/src/main/res/drawable/interflash_cinema_background.xml"
drawable.write_text('''<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="1920dp" android:height="1080dp" android:viewportWidth="1920" android:viewportHeight="1080">
    <path android:fillColor="#172C45" android:fillAlpha="0.38" android:pathData="M0,830 L1920,180 L1920,470 L0,1080 Z" />
    <path android:fillColor="#183D58" android:fillAlpha="0.30" android:pathData="M0,960 L1920,420 L1920,660 L0,1080 Z" />
    <group android:rotation="-18" android:pivotX="1420" android:pivotY="780">
        <path android:fillColor="#3A526B" android:fillAlpha="0.50" android:pathData="M760,610 L2100,610 L2100,870 L760,870 Z" />
        <path android:fillColor="#111C2D" android:pathData="M760,644 L2100,644 L2100,836 L760,836 Z" />
        <path android:strokeColor="#496078" android:strokeWidth="5" android:pathData="M770,674 L2100,674 M770,806 L2100,806 M1000,644 L1000,836 M1240,644 L1240,836 M1480,644 L1480,836 M1720,644 L1720,836 M1960,644 L1960,836" />
        <path android:strokeColor="#081625" android:strokeWidth="15" android:strokeLineCap="round" android:pathData="M790,626 L810,626 M856,626 L876,626 M922,626 L942,626 M988,626 L1008,626 M1054,626 L1074,626 M1120,626 L1140,626 M1186,626 L1206,626 M1252,626 L1272,626 M1318,626 L1338,626 M1384,626 L1404,626 M1450,626 L1470,626 M1516,626 L1536,626 M1582,626 L1602,626 M1648,626 L1668,626 M1714,626 L1734,626 M1780,626 L1800,626 M1846,626 L1866,626 M1912,626 L1932,626 M790,854 L810,854 M856,854 L876,854 M922,854 L942,854 M988,854 L1008,854 M1054,854 L1074,854 M1120,854 L1140,854 M1186,854 L1206,854 M1252,854 L1272,854 M1318,854 L1338,854 M1384,854 L1404,854 M1450,854 L1470,854 M1516,854 L1536,854 M1582,854 L1602,854 M1648,854 L1668,854 M1714,854 L1734,854 M1780,854 L1800,854 M1846,854 L1866,854 M1912,854 L1932,854" />
    </group>
    <group android:translateX="1420" android:translateY="530">
        <path android:fillColor="#27465D" android:strokeColor="#5A798F" android:strokeWidth="6" android:pathData="M0,-240 A240,240 0,1 1,0,240 A240,240 0,1 1,0,-240 Z" />
        <path android:fillColor="#0B192A" android:pathData="M0,-190 A53,53 0,1 1,0,-84 A53,53 0,1 1,0,-190 Z M156,-82 A53,53 0,1 1,156,24 A53,53 0,1 1,156,-82 Z M96,115 A53,53 0,1 1,96,221 A53,53 0,1 1,96,115 Z M-96,115 A53,53 0,1 1,-96,221 A53,53 0,1 1,-96,115 Z M-156,-82 A53,53 0,1 1,-156,24 A53,53 0,1 1,-156,-82 Z M0,-38 A38,38 0,1 1,0,38 A38,38 0,1 1,0,-38 Z" />
        <path android:strokeColor="#4B6980" android:strokeWidth="3" android:pathData="M0,-220 A220,220 0,1 1,0,220 A220,220 0,1 1,0,-220 Z" />
    </group>
    <group android:rotation="-12" android:pivotX="270" android:pivotY="680">
        <path android:fillColor="#243D54" android:fillAlpha="0.62" android:pathData="M-110,580 L580,580 L580,1000 L-110,1000 Z" />
        <path android:fillColor="#48637B" android:fillAlpha="0.55" android:pathData="M-110,472 L580,472 L580,580 L-110,580 Z" />
        <path android:fillColor="#132436" android:pathData="M-110,472 L-40,472 L65,580 L-5,580 Z M25,472 L95,472 L200,580 L130,580 Z M160,472 L230,472 L335,580 L265,580 Z M295,472 L365,472 L470,580 L400,580 Z M430,472 L500,472 L580,553 L580,580 L535,580 Z" />
        <path android:strokeColor="#547086" android:strokeWidth="5" android:pathData="M-80,675 L550,675 M-80,755 L550,755 M-80,835 L550,835 M-80,915 L550,915" />
    </group>
</vector>
''', encoding="utf-8")

movies = features / "movies/MoviesScreen.kt"
edit(movies, 'if (cinemaRows) tv.own.owntv.features.shell.components.CatalogueMovieBackdrop(titleInfo?.backdropUrl ?: titleInfo?.posterUrl)',
    'if (clientCatalogue) tv.own.owntv.features.shell.components.CatalogueMovieBackdrop()')
edit(movies, 'if (!cinemaRows) VodCinematicBackdrop(titleInfo?.backdropUrl ?: titleInfo?.posterUrl,',
    'if (!clientCatalogue && !cinemaRows) VodCinematicBackdrop(titleInfo?.backdropUrl ?: titleInfo?.posterUrl,')

rows = features / "shell/components/CinemaCategoryRows.kt"
s = rows.read_text(encoding="utf-8")
start = s.index('internal fun CatalogueMovieBackdrop(url: String?) {')
assert s[start:].rstrip().endswith('}')
# This function is appended by catalogue-v061.py at the end of the file.
s = s[:start] + '''internal fun CatalogueMovieBackdrop() {
    Box(Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Brush.linearGradient(
        listOf(Color(0xFF071322), Color(0xFF142C43), Color(0xFF080F1B))))) {
        androidx.compose.foundation.Image(
            painter = androidx.compose.ui.res.painterResource(tv.own.owntv.R.drawable.interflash_cinema_background),
            contentDescription = null, contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(), alpha = 0.50f)
        Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.20f)))
    }
}
'''
rows.write_text(s, encoding="utf-8")

shell = features / "shell/OwnTVShell.kt"
edit(shell, 'top = if (clientMode && selectedSection == MainSection.SERIES) 80.mpx else if (classicVod) 94.mpx else if (clientMode) 112.mpx else 0.dp,',
    'top = if (clientMode && selectedSection == MainSection.MOVIES) 66.mpx else if (clientMode && selectedSection == MainSection.SERIES) 80.mpx else if (classicVod) 94.mpx else if (clientMode) 112.mpx else 0.dp,')
rail = features / "shell/components/StageRail.kt"
edit(rail, 'modifier.fillMaxWidth().padding(top = if (selected == MainSection.SERIES) 8.mpx else 20.mpx).height(72.mpx)',
    'modifier.fillMaxWidth().padding(top = if (selected == MainSection.MOVIES) 4.mpx else if (selected == MainSection.SERIES) 8.mpx else 20.mpx).height(if (selected == MainSection.MOVIES) 62.mpx else 72.mpx)')

checker = "tools/i18n/check_hardcoded_strings.py"
subprocess.run(["python3", checker, "prune-safe"], cwd=root, check=True)
subprocess.run(["python3", checker, "verify", "--bootstrap"], cwd=root, check=True)
print("Fixed vector cinema background and compact Movies header applied.")
