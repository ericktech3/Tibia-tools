package org.erick.tibiatools;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.util.Log;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;

public class BootReceiver extends BroadcastReceiver {
    private static final String TAG = "TTBootReceiver";

    private static String readAll(File f) throws Exception {
        StringBuilder sb = new StringBuilder();
        BufferedReader br = new BufferedReader(new FileReader(f));
        String line;
        while ((line = br.readLine()) != null) {
            sb.append(line);
        }
        br.close();
        return sb.toString();
    }

    private boolean isNotificationsGranted(Context context) {
        if (Build.VERSION.SDK_INT >= 33) {
            try {
                return context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
            } catch (Throwable t) {
                return false;
            }
        }
        return true;
    }

    private boolean shouldStart(Context context) {
        // Favoritos + flags ficam em /data/data/<package>/files/favorites.json (app_storage_path)
        File f = new File(context.getFilesDir(), "favorites.json");
        if (!f.exists()) {
            // sem arquivo: não tem favoritos para monitorar, então não inicia
            return false;
        }
        try {
            JSONObject st = new JSONObject(readAll(f));

            boolean autostart = st.optBoolean("autostart_on_boot", true);
            boolean monitoring = st.optBoolean("monitoring", true);

            // precisa ter ao menos 1 favorito não-vazio
            boolean hasFavs = false;
            try {
                if (st.has("favorites")) {
                    for (int i = 0; i < st.getJSONArray("favorites").length(); i++) {
                        String name = st.getJSONArray("favorites").optString(i, "");
                        if (name != null && name.trim().length() > 0) {
                            hasFavs = true;
                            break;
                        }
                    }
                }
            } catch (Throwable t) {
                hasFavs = false;
            }

            return autostart && monitoring && hasFavs;
        } catch (Throwable t) {
            // se falhar o parse, evita iniciar para não drenar bateria/loopar
            return false;
        }
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = (intent != null) ? intent.getAction() : "";
        if (action == null) action = "";

        boolean isBoot =
                Intent.ACTION_BOOT_COMPLETED.equals(action) ||
                Intent.ACTION_MY_PACKAGE_REPLACED.equals(action) ||
                "android.intent.action.QUICKBOOT_POWERON".equals(action);

        if (!isBoot) {
            return;
        }

        try {
            if (!isNotificationsGranted(context)) {
                Log.i(TAG, "POST_NOTIFICATIONS não concedido; não iniciando serviço no boot.");
                return;
            }

            if (!shouldStart(context)) {
                Log.i(TAG, "Autostart desativado ou sem favoritos; não iniciando serviço no boot.");
                return;
            }

            // Inicia o serviço Favwatch (gerado pelo python-for-android) como foreground (buildozer: :foreground)
            ServiceFavwatch.start(context, "", "Tibia Tools", "Monitorando favoritos", "");
            Log.i(TAG, "Serviço Favwatch iniciado no boot.");
        } catch (Throwable t) {
            Log.e(TAG, "Falha ao iniciar serviço no boot", t);
        }
    }
}
