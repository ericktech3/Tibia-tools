import os
import sys
import time
import json
import traceback
import importlib
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

def _android_notify(title: str, text: str, notif_id: int = 1002):
    try:
        from jnius import autoclass
        Context = autoclass("android.content.Context")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        NotificationManager = autoclass("android.app.NotificationManager")
        NotificationBuilder = autoclass("android.app.Notification$Builder")
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        nm = service.getSystemService(Context.NOTIFICATION_SERVICE)

        channel_id = "tibia_tools_watch"
        if hasattr(nm, "createNotificationChannel"):
            channel = NotificationChannel(channel_id, "Tibia Tools", NotificationManager.IMPORTANCE_DEFAULT)
            nm.createNotificationChannel(channel)

        builder = NotificationBuilder(service, channel_id)
        builder.setContentTitle(title)
        builder.setContentText(text)
        builder.setSmallIcon(service.getApplicationInfo().icon)
        nm.notify(notif_id, builder.build())
    except Exception as e:
        _append_crash_log(f"notify fail: {e}")


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

    while True:
        try:
            data_dir = state_mod.default_data_dir_android()
            st = state_mod.load_state(data_dir)

            favorites = st.get("favorites", [])
            monitoring = bool(st.get("monitoring", False))
            interval = _to_int(st.get("interval_seconds")) or 60

            if not monitoring or not favorites:
                time.sleep(15)
                continue

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

                # Notifications only if we already have previous state (avoid spam on first run)
                if isinstance(prev, dict):
                    prev_online = bool(prev.get("online", False))
                    prev_level = _to_int(prev.get("level"))
                    prev_death_time = prev.get("death_time")

                    if notify_online and (not prev_online) and online:
                        nid = 1000 + (abs(hash(f"online:{ln}")) % 50000)
                        _android_notify("Favorito online", f"{name} está ONLINE", notif_id=nid)

                    if notify_level and (prev_level is not None) and (level is not None) and level > prev_level:
                        nid = 1000 + (abs(hash(f"level:{ln}")) % 50000)
                        _android_notify("Level up", f"{name} agora é level {level}", notif_id=nid)

                    if notify_death and isinstance(death_time, str) and death_time and death_time != prev_death_time:
                        try:
                            summary = tibia_mod.death_summary(deaths)
                        except Exception:
                            summary = ""
                        msg = f"{name} morreu"
                        if summary:
                            msg += f" ({summary})"
                        nid = 1000 + (abs(hash(f"death:{ln}:{death_time}")) % 50000)
                        _android_notify("Morte", msg, notif_id=nid)

                # update persisted last state
                last[ln] = {
                    "online": bool(online),
                    "level": level,
                    "death_time": death_time,
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
