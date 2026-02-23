import os
import sys
import time
import json
import traceback
import importlib
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

def _try_get_storage_dir() -> str:
    try:
        from android.storage import app_storage_path  # type: ignore
        p = app_storage_path()
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass
    return os.getcwd()

_CRASH_DIR = _try_get_storage_dir()
_CRASH_FILE = os.path.join(_CRASH_DIR, "tibia_tools_service_crash.log")

def _append_crash_log(text: str) -> None:
    try:
        with open(_CRASH_FILE, "a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except Exception:
        pass

def import_core_modules() -> Tuple[Any, Any, str]:
    last_err: Optional[BaseException] = None
    for prefix in ("core", "Core"):
        try:
            state_mod = importlib.import_module(f"{prefix}.state")
            tibia_mod = importlib.import_module(f"{prefix}.tibia")
            return state_mod, tibia_mod, prefix
        except BaseException as e:
            last_err = e
    raise last_err or RuntimeError("Falha ao importar core/Core")

def _android_notify(
    title: str,
    text: str,
    notif_id: int = 1002,
    *,
    char_name: Optional[str] = None,
    event_type: Optional[str] = None,
):
    try:
        from jnius import autoclass
        # Intent para abrir o app ao tocar na notificação
        Intent = autoclass("android.content.Intent")
        PendingIntent = autoclass("android.app.PendingIntent")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        VERSION = autoclass("android.os.Build$VERSION")
        Context = autoclass("android.content.Context")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        NotificationManager = autoclass("android.app.NotificationManager")
        NotificationBuilder = autoclass("android.app.Notification$Builder")
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        nm = service.getSystemService(Context.NOTIFICATION_SERVICE)

        channel_id = "tibia_tools_events"
        if hasattr(nm, "createNotificationChannel"):
            channel = NotificationChannel(channel_id, "Tibia Tools Alertas", NotificationManager.IMPORTANCE_DEFAULT)
            nm.createNotificationChannel(channel)

        builder = NotificationBuilder(service, channel_id)
        builder.setContentTitle(title)
        builder.setContentText(text)
        builder.setSmallIcon(service.getApplicationInfo().icon)

        # Abre o app ao clicar (em alguns devices, sem isso o toque não faz nada)
        try:
            # Usa o launch intent do pacote (mais robusto); fallback para PythonActivity.
            intent = None
            try:
                pm = service.getPackageManager()
                intent = pm.getLaunchIntentForPackage(service.getPackageName())
            except Exception:
                intent = None
            if intent is None:
                intent = Intent(service, PythonActivity)
            try:
                intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP)
            except Exception:
                pass

            # Extras para o app abrir direto na aba Char e disparar a busca.
            # Obs: setAction único ajuda a evitar que o Android "reaproveite" um PendingIntent antigo.
            try:
                intent.setAction(f"TT_EVENT_{notif_id}_{int(time.time()*1000)}")
            except Exception:
                pass
            try:
                intent.putExtra("tt_open_tab", "tab_char")
                intent.putExtra("tt_auto_search", True)
                if char_name:
                    intent.putExtra("tt_char_name", str(char_name))
                if event_type:
                    intent.putExtra("tt_event_type", str(event_type))
            except Exception:
                pass
            pi_flags = int(PendingIntent.FLAG_UPDATE_CURRENT)
            try:
                if int(VERSION.SDK_INT) >= 23:
                    # Em Android 12+ o sistema exige flag explícita; usamos IMMUTABLE.
                    pi_flags = pi_flags | int(PendingIntent.FLAG_IMMUTABLE)
            except Exception:
                pass
            pi = PendingIntent.getActivity(service, int(notif_id), intent, pi_flags)
            builder.setContentIntent(pi)
        except Exception:
            pass
        try:
            builder.setAutoCancel(True)
        except Exception:
            pass
        nm.notify(notif_id, builder.build())
    except Exception as e:
        _append_crash_log(f"notify fail: {e}")

def _android_start_foreground(title: str, text: str, notif_id: int = 1001):
    """Garante uma notificação fixa (foreground) com texto visível.
    Alguns devices mostram a notificação do serviço em branco se não chamarmos startForeground manualmente.
    """
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        PendingIntent = autoclass("android.app.PendingIntent")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        VERSION = autoclass("android.os.Build$VERSION")
        Context = autoclass("android.content.Context")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        NotificationManager = autoclass("android.app.NotificationManager")
        NotificationBuilder = autoclass("android.app.Notification$Builder")
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        nm = service.getSystemService(Context.NOTIFICATION_SERVICE)

        channel_id = "tibia_tools_watch_fg"
        if hasattr(nm, "createNotificationChannel"):
            # IMPORTANCE_MIN para não fazer barulho
            channel = NotificationChannel(channel_id, "Tibia Tools Monitor", NotificationManager.IMPORTANCE_MIN)
            nm.createNotificationChannel(channel)

        builder = NotificationBuilder(service, channel_id)
        builder.setContentTitle(title)
        builder.setContentText(text)
        builder.setSmallIcon(service.getApplicationInfo().icon)

        # Mantém o mesmo comportamento: abrir o app ao tocar
        try:
            # Usa o launch intent do pacote (mais robusto); fallback para PythonActivity.
            intent = None
            try:
                pm = service.getPackageManager()
                intent = pm.getLaunchIntentForPackage(service.getPackageName())
            except Exception:
                intent = None
            if intent is None:
                intent = Intent(service, PythonActivity)
            try:
                intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP)
            except Exception:
                pass

            # Abre direto na aba Char (sem char específico)
            try:
                intent.setAction(f"TT_FG_{notif_id}_{int(time.time()*1000)}")
            except Exception:
                pass
            try:
                intent.putExtra("tt_open_tab", "tab_char")
                intent.putExtra("tt_auto_search", False)
            except Exception:
                pass
            pi_flags = int(PendingIntent.FLAG_UPDATE_CURRENT)
            try:
                if int(VERSION.SDK_INT) >= 23:
                    pi_flags = pi_flags | int(PendingIntent.FLAG_IMMUTABLE)
            except Exception:
                pass
            pi = PendingIntent.getActivity(service, int(notif_id), intent, pi_flags)
            builder.setContentIntent(pi)
        except Exception:
            pass
        try:
            builder.setOngoing(True)
        except Exception:
            pass
        try:
            builder.setOnlyAlertOnce(True)
        except Exception:
            pass

        notif = builder.build()
        try:
            service.startForeground(notif_id, notif)
        except Exception:
            # fallback: postar como notificação normal
            nm.notify(notif_id, notif)
    except Exception as e:
        _append_crash_log(f"foreground notify fail: {e}")



def _android_get_service():
    """Retorna a instância do Android Service (PythonService.mService) ou None."""
    try:
        from jnius import autoclass
        PythonService = autoclass("org.kivy.android.PythonService")
        return PythonService.mService
    except Exception:
        return None

def _android_stop_self():
    try:
        svc = _android_get_service()
        if svc is not None:
            svc.stopSelf()
    except Exception:
        pass

def _lower_name(n: str) -> str:
    return str(n or "").strip().lower()

def _to_int(v):
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        s = str(v).strip()
        if s.isdigit():
            return int(s)
    except Exception:
        pass
    return None

def main():
    try:
        state_mod, tibia_mod, prefix = import_core_modules()
    except BaseException as e:
        msg = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        _append_crash_log("IMPORT FAIL:\n" + msg)
        return

    last_world_online_cache: Dict[str, Any] = {}  # world -> set(lower names)
    last_fg_text = None

    # Garante startForeground rápido (exigência do Android quando iniciado como foreground service).
    try:
        _android_start_foreground('Tibia Tools', 'Inicializando monitor...', notif_id=1001)
    except Exception:
        pass

    while True:
        try:
            data_dir = state_mod.default_data_dir_android()
            st = state_mod.load_state(data_dir)

            favorites = st.get("favorites", [])
            monitoring = bool(st.get("monitoring", False))
            interval = _to_int(st.get("interval_seconds")) or 30

            if not monitoring or not favorites:
                try:
                    _android_start_foreground('Tibia Tools', 'Monitor desativado/sem favoritos — serviço parado', notif_id=1001)
                except Exception:
                    pass
                try:
                    _android_stop_self()
                except Exception:
                    pass
                return

            # força notificação do serviço com texto visível (evita notificação em branco)
            try:
                fg_text = f"Monitorando {len(favorites)} favorito(s) — a cada {interval}s"
                if fg_text != last_fg_text:
                    _android_start_foreground("Tibia Tools", fg_text, notif_id=1001)
                    last_fg_text = fg_text
            except Exception:
                pass

            notify_online = bool(st.get("notify_fav_online", True))
            notify_death = bool(st.get("notify_fav_death", True))
            notify_level = bool(st.get("notify_fav_level", True))

            worlds_cache = st.get("worlds", {})
            if not isinstance(worlds_cache, dict):
                worlds_cache = {}
            last = st.get("last", {})
            if not isinstance(last, dict):
                last = {}

            # resolve world for each favorite (cache)
            favs = [str(x) for x in favorites[:10] if str(x).strip()]
            fav_world: Dict[str, Optional[str]] = {}
            for name in favs:
                ln = _lower_name(name)
                w = worlds_cache.get(ln)
                if not w:
                    w = tibia_mod.fetch_character_world(name, timeout=10)
                    if w:
                        worlds_cache[ln] = w
                fav_world[ln] = w or None

            # fetch online lists per world (one request per world)
            worlds = sorted({w for w in fav_world.values() if isinstance(w, str) and w.strip()})
            for w in worlds:
                online_set = tibia_mod.fetch_world_online_players(w, timeout=10)
                if online_set is None:
                    # keep last known if request fails
                    online_set = last_world_online_cache.get(w) or set()
                else:
                    last_world_online_cache[w] = online_set
                last_world_online_cache[w] = online_set

            # check each char
            changed = False
            for name in favs:
                ln = _lower_name(name)
                now_iso = datetime.utcnow().isoformat()
                snap = tibia_mod.fetch_character_snapshot(name, timeout=12)

                # prefer world-based online resolution
                w = fav_world.get(ln) or snap.get("world")
                online = False
                if isinstance(w, str) and w.strip():
                    osn = last_world_online_cache.get(w) or set()
                    online = (ln in osn) or (_lower_name(name) in osn)
                else:
                    online = bool(snap.get("online"))

                level = _to_int(snap.get("level"))
                deaths = snap.get("deaths") or []
                death_time = None
                try:
                    death_time = tibia_mod.newest_death_time(deaths)
                except Exception:
                    death_time = None

                prev = last.get(ln) if isinstance(last.get(ln), dict) else None
                prev_online = None
                prev_offline_since = None
                prev_last_seen_online = None
                try:
                    if isinstance(prev, dict):
                        prev_online = bool(prev.get("online", False))
                        prev_offline_since = prev.get("offline_since_iso")
                        prev_last_seen_online = prev.get("last_seen_online_iso")
                except Exception:
                    prev_online = None
                    prev_offline_since = None
                    prev_last_seen_online = None

                # ONLINE/OFFLINE duration tracking
                offline_since_iso = None
                last_seen_online_iso = None
                try:
                    if online:
                        # sempre que vemos online, limpamos o offline_since
                        last_seen_online_iso = now_iso
                        offline_since_iso = None
                    else:
                        # só define offline_since no momento exato em que detectamos a transição Online -> Offline
                        if prev_online is True:
                            offline_since_iso = now_iso
                        else:
                            offline_since_iso = prev_offline_since if isinstance(prev_offline_since, str) else None
                        last_seen_online_iso = prev_last_seen_online if isinstance(prev_last_seen_online, str) else None
                except Exception:
                    offline_since_iso = None
                    last_seen_online_iso = None

                # Notifications only if we already have previous state (avoid spam on first run)
                if isinstance(prev, dict):
                    prev_online = bool(prev.get("online", False))
                    prev_level = _to_int(prev.get("level"))
                    prev_death_time = prev.get("death_time")

                    if notify_online and (not prev_online) and online:
                        nid = 1000 + (abs(hash(f"online:{ln}")) % 50000)
                        _android_notify(
                            "Favorito online",
                            f"{name} está ONLINE",
                            notif_id=nid,
                            char_name=name,
                            event_type="online",
                        )

                    if notify_level and (prev_level is not None) and (level is not None) and level > prev_level:
                        nid = 1000 + (abs(hash(f"level:{ln}")) % 50000)
                        _android_notify(
                            "Level up",
                            f"{name} agora é level {level}",
                            notif_id=nid,
                            char_name=name,
                            event_type="level",
                        )

                    if notify_death and isinstance(death_time, str) and death_time and death_time != prev_death_time:
                        try:
                            summary = tibia_mod.death_summary(deaths)
                        except Exception:
                            summary = ""
                        msg = f"{name} morreu"
                        if summary:
                            msg += f" ({summary})"
                        nid = 1000 + (abs(hash(f"death:{ln}:{death_time}")) % 50000)
                        _android_notify(
                            "Morte",
                            msg,
                            notif_id=nid,
                            char_name=name,
                            event_type="death",
                        )

                # update persisted last state
                last[ln] = {
                    "online": bool(online),
                    "level": level,
                    "death_time": death_time,
                    # precisão: quando ficou OFF (logout detectado)
                    "offline_since_iso": offline_since_iso,
                    # utilitário: último instante em que vimos ONLINE
                    "last_seen_online_iso": last_seen_online_iso,
                    # utilitário: último check realizado pelo serviço
                    "last_checked_iso": now_iso,
                }
                changed = True

            if changed:
                st["worlds"] = worlds_cache
                st["last"] = last
                state_mod.save_state(data_dir, st)

            time.sleep(max(20, interval))
        except Exception as e:
            msg = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            _append_crash_log(msg)
            time.sleep(10)

if __name__ == "__main__":
    main()