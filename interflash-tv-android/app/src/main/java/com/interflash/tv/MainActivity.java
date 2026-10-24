package com.interflash.tv;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import androidx.media3.common.MediaItem;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.ui.PlayerView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

/** Prototype Android TV client. Requires an authorized subscriber device token. */
public final class MainActivity extends Activity {
    private ExoPlayer player;
    private LinearLayout root;
    private TextView status;
    private PlayerView video;
    private EditText server, token;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(24, 18, 24, 18);
        root.setBackgroundColor(Color.rgb(9, 22, 39));
        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);
        TextView title = new TextView(this);
        title.setText("INTER FLASH TV");
        title.setTextColor(Color.WHITE);
        title.setTextSize(28);
        root.addView(title);
        status = new TextView(this);
        status.setText("Introduce la dirección HTTPS de Inter Flash y la clave de tu televisor.");
        status.setTextColor(Color.WHITE);
        status.setTextSize(17);
        root.addView(status);
        server = new EditText(this);
        server.setSingleLine(true);
        server.setHint("https://tu-servidor.example");
        server.setTextColor(Color.WHITE);
        server.setHintTextColor(Color.LTGRAY);
        root.addView(server);
        token = new EditText(this);
        token.setSingleLine(true);
        token.setHint("Clave del televisor");
        token.setTextColor(Color.WHITE);
        token.setHintTextColor(Color.LTGRAY);
        root.addView(token);
        Button connect = new Button(this);
        connect.setText("Cargar canales");
        connect.setOnClickListener(v -> loadChannels());
        root.addView(connect);
    }

    private void loadChannels() {
        String base = server.getText().toString().trim();
        String key = token.getText().toString().trim();
        if (!base.matches("https://[^\\s/]+(?:/)?") || key.length() < 32) {
            status.setText("Comprueba la dirección HTTPS y la clave del televisor.");
            return;
        }
        status.setText("Consultando canales...");
        new Thread(() -> {
            try {
                String endpoint = base.replaceAll("/$", "") + "/interflash-tv/api/device/channels";
                HttpURLConnection conn = (HttpURLConnection) new URL(endpoint).openConnection();
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(10000);
                conn.setRequestProperty("Authorization", "Bearer " + key);
                int code = conn.getResponseCode();
                if (code != 200) {
                    conn.disconnect();
                    runOnUiThread(() -> status.setText("Sin acceso (" + code + "). Comprueba la suscripción."));
                    return;
                }
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                try (InputStream in = conn.getInputStream()) {
                    byte[] buf = new byte[4096];
                    int n;
                    while ((n = in.read(buf)) != -1 && bytes.size() < 1000000) bytes.write(buf, 0, n);
                }
                conn.disconnect();
                JSONArray channels = new JSONObject(bytes.toString("UTF-8")).getJSONArray("channels");
                runOnUiThread(() -> showChannels(channels));
            } catch (Exception ex) {
                runOnUiThread(() -> status.setText("No se pudo conectar al servidor."));
            }
        }).start();
    }

    private void showChannels(JSONArray channels) {
        status.setText(channels.length() + " canales disponibles");
        if (video != null) { root.removeView(video); video = null; }
        while (root.getChildCount() > 5) root.removeViewAt(root.getChildCount() - 1);
        for (int i = 0; i < channels.length(); i++) {
            JSONObject channel = channels.optJSONObject(i);
            if (channel == null) continue;
            String url = channel.optString("stream_url", "");
            String name = channel.optString("name", "Canal");
            Button b = new Button(this);
            b.setText(name);
            b.setOnClickListener(v -> playAuthorizedStream(url, name));
            root.addView(b);
        }
    }

    private void playAuthorizedStream(String url, String name) {
        if (!url.startsWith("https://")) { status.setText("Canal sin enlace HTTPS válido."); return; }
        if (player != null) player.release();
        if (video != null) root.removeView(video);
        player = new ExoPlayer.Builder(this).build();
        video = new PlayerView(this);
        video.setPlayer(player);
        root.addView(video, 5, new LinearLayout.LayoutParams(-1, 400));
        player.setMediaItem(MediaItem.fromUri(url));
        player.prepare();
        player.play();
        status.setText("Reproduciendo: " + name);
    }
    @Override protected void onStop() {
        super.onStop();
        if (player != null) { player.release(); player = null; }
    }
}
