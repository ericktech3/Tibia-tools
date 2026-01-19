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

def main():
    try:
        state_mod, tibia_mod, prefix = import_core_modules()
    except BaseException as e:
        msg = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        _append_crash_log("IMPORT FAIL:\n" + msg)
        return

    # loop simples: checa favoritos e notifica mudanças (online/offline/level/deaths)
    last_snap: Dict[str, Dict[str, Any]] = {}

    while True:
        try:
            st = state_mod.load_state(state_mod.default_data_dir_android())
            favorites = st.get("favorites", [])
            monitoring = bool(st.get("monitoring", False))
            interval = int(st.get("interval_seconds", 60))
            if not monitoring or not favorites:
                time.sleep(5)
                continue

            for name in favorites[:10]:
                snap = tibia_mod.fetch_character_snapshot(name)
                prev = last_snap.get(name)
                if prev:
                    # online change
                    if bool(prev.get("online")) != bool(snap.get("online")):
                        _android_notify("Status", f"{name} está {'ONLINE' if snap.get('online') else 'OFFLINE'}")
                    # level change
                    if prev.get("level") and snap.get("level") and int(prev["level"]) != int(snap["level"]):
                        _android_notify("Level up", f"{name} agora está level {snap['level']}")
                last_snap[name] = snap

            time.sleep(max(10, interval))
        except Exception as e:
            msg = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            _append_crash_log(msg)
            time.sleep(10)

if __name__ == "__main__":
    main()
