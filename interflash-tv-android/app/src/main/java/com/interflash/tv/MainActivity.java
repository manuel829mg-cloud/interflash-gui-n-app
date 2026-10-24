package com.interflash.tv;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.media3.common.MediaItem;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.ui.PlayerView;

/** Android TV / Fire TV prototype. Playback requires an authorized HTTPS HLS URL. */
public final class MainActivity extends Activity {
    private ExoPlayer player;
    private LinearLayout root;
    private TextView status;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 24, 32, 24);
        root.setBackgroundColor(Color.rgb(9, 22, 39));
        TextView title = new TextView(this);
        title.setText("INTER FLASH TV");
        title.setTextColor(Color.WHITE);
        title.setTextSize(30);
        root.addView(title);
        status = new TextView(this);
        status.setText("Aplicación de prueba. Esperando conexión segura con Inter Flash y canales autorizados.");
        status.setTextColor(Color.LTGRAY);
        status.setTextSize(19);
        root.addView(status);
        Button info = new Button(this);
        info.setText("Estado del servicio");
        info.setOnClickListener(v -> status.setText("Pendiente: acceso de suscriptores y catálogo con licencia."));
        root.addView(info);
        setContentView(root);
    }
    // Called only after the backend has authenticated the subscriber and authorized playback.
    private void playAuthorizedStream(String httpsHlsUrl) {
        if (httpsHlsUrl == null || !httpsHlsUrl.startsWith("https://")) return;
        if (player != null) { player.release(); }
        player = new ExoPlayer.Builder(this).build();
        PlayerView video = new PlayerView(this);
        video.setPlayer(player);
        root.addView(video, new LinearLayout.LayoutParams(-1, 0, 1));
        player.setMediaItem(MediaItem.fromUri(httpsHlsUrl));
        player.prepare();
        player.play();
    }
    @Override protected void onStop() { super.onStop(); if (player != null) { player.release(); player = null; } }
}
