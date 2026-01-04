import json
import os
import sys
import time
from typing import Dict, Any

from core.state import load_state, save_state
from core.tibia import fetch_character_snapshot

def _android_notify(title: str, text: str, notif_id: int = 1002):
    try:
        from jnius import autoclass
        Build = autoclass("android.os.Build")
        Context = autoclass("android.content.Context")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        NotificationManager = autoclass("android.app.NotificationManager")
        NotificationBuilder = autoclass("android.app.Notification$Builder")
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        nm = service.getSystemService(Context.NOTIFICATION_SERVICE)

        icon_id = service.getApplicationInfo().icon
        channel_id = "tibiatools_watch"

        if Build.VERSION.SDK_INT >= 26:
            channel = NotificationChannel(channel_id, "Tibia Tools", NotificationManager.IMPORTANCE_DEFAULT)
            nm.createNotificationChannel(channel)
            builder = NotificationBuilder(service, channel_id)
        else:
            builder = NotificationBuilder(service)

        n = (builder.setContentTitle(title)
                    .setContentText(text)
                    .setSmallIcon(icon_id)
                    .setAutoCancel(True)
                    .build())
        nm.notify(notif_id, n)
    except Exception:
        pass

def _start_foreground():
    try:
        from jnius import autoclass
        Build = autoclass("android.os.Build")
        Context = autoclass("android.content.Context")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        NotificationManager = autoclass("android.app.NotificationManager")
        NotificationBuilder = autoclass("android.app.Notification$Builder")
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        nm = service.getSystemService(Context.NOTIFICATION_SERVICE)
        icon_id = service.getApplicationInfo().icon
        channel_id = "tibiatools_fg"

        if Build.VERSION.SDK_INT >= 26:
            channel = NotificationChannel(channel_id, "Tibia Tools (Monitor)", NotificationManager.IMPORTANCE_LOW)
            nm.createNotificationChannel(channel)
            builder = NotificationBuilder(service, channel_id)
        else:
            builder = NotificationBuilder(service)

        notif = (builder.setContentTitle("Tibia Tools")
                        .setContentText("Monitorando favoritos…")
                        .setSmallIcon(icon_id)
                        .setOngoing(True)
                        .build())
        service.startForeground(1, notif)
    except Exception:
        pass

def _key_death(d: Dict[str, Any]) -> str:
    t = d.get("time") or d.get("date") or ""
    killers = d.get("killers") or d.get("involved") or []
    k0 = ""
    if killers and isinstance(killers, list):
        first = killers[0]
        if isinstance(first, dict):
            k0 = first.get("name") or ""
        else:
            k0 = str(first)
    return f"{t}|{k0}"

def main():
    payload = sys.argv[1] if len(sys.argv) > 1 else "{}"
    try:
        cfg = json.loads(payload)
    except Exception:
        cfg = {}

    user_data_dir = cfg.get("user_data_dir") or os.getcwd()
    interval = int(cfg.get("interval") or 60)

    _start_foreground()
    _android_notify("Monitor", f"Serviço iniciado (intervalo {interval}s).", 1003)

    while True:
        try:
            st = load_state(user_data_dir)
            fav = st.get("favorites", [])[:10]
            last = st.get("last", {}) if isinstance(st.get("last", {}), dict) else {}

            for name in fav:
                try:
                    snap = fetch_character_snapshot(name, timeout=12)
                except Exception:
                    continue

                prev = last.get(name, {})
                prev_online = prev.get("online")
                prev_level = prev.get("level")
                prev_death_key = prev.get("last_death_key")

                online = snap.get("online")
                level = snap.get("level")

                deaths = snap.get("deaths") or []
                death_key = _key_death(deaths[0]) if deaths else None

                if prev_online is not None and online is True and prev_online is False:
                    _android_notify("Login", f"{name} logou!", 2000)

                if isinstance(prev_level, int) and isinstance(level, int) and level > prev_level:
                    _android_notify("Level Up", f"{name} subiu para {level}!", 2001)

                if death_key and prev_death_key and death_key != prev_death_key:
                    _android_notify("Morte", f"{name} morreu recentemente.", 2002)

                if prev_online is None and online is True:
                    _android_notify("Status", f"{name} está ONLINE agora.", 2003)

                last[name] = {
                    "online": online,
                    "level": level if isinstance(level, int) else prev_level,
                    "last_death_key": death_key or prev_death_key,
                    "ts": int(time.time()),
                }

            st["last"] = last
            save_state(user_data_dir, st)
        except Exception:
            pass

        time.sleep(max(10, interval))

if __name__ == "__main__":
    main()
