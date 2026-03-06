from __future__ import annotations

import time
from datetime import datetime

from kivy.clock import Clock
from kivy.utils import platform
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog

from core import state as fav_state
from services.error_reporting import log_current_exception


class AndroidBridgeService:
    def __init__(self, app):
        self.app = app

    def is_android(self) -> bool:
        return platform == "android"

    def android_sdk_int(self) -> int:
        if not self.is_android():
            return 0
        try:
            from jnius import autoclass  # type: ignore
            VERSION = autoclass("android.os.Build$VERSION")
            return int(VERSION.SDK_INT)
        except Exception:
            return 0

    def post_notif_permission_granted(self) -> bool:
        if not self.is_android():
            return True
        if self.android_sdk_int() < 33:
            return True
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            PackageManager = autoclass("android.content.pm.PackageManager")
            activity = PythonActivity.mActivity
            perm = "android.permission.POST_NOTIFICATIONS"
            return activity.checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED
        except Exception:
            return False

    def notifications_globally_enabled(self) -> bool:
        if not self.is_android():
            return True
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            nm = activity.getSystemService(Context.NOTIFICATION_SERVICE)
            try:
                return bool(nm.areNotificationsEnabled())
            except Exception:
                return True
        except Exception:
            return True

    def channel_enabled(self, channel_id: str) -> bool:
        if not self.is_android():
            return True
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            NotificationManager = autoclass("android.app.NotificationManager")
            activity = PythonActivity.mActivity
            nm = activity.getSystemService(Context.NOTIFICATION_SERVICE)
            ch = nm.getNotificationChannel(channel_id)
            if ch is None:
                return True
            return int(ch.getImportance()) != int(NotificationManager.IMPORTANCE_NONE)
        except Exception:
            return True

    def prompt_enable_notifications_dialog(self):
        try:
            txt = (
                "As notificações do Tibia Tools estão desativadas no sistema.\n"
                "Toque em 'Abrir configurações' e ative Notificações."
            )
            dlg = MDDialog(
                title="Ativar notificações",
                text=txt,
                buttons=[
                    MDFlatButton(text="AGORA NÃO", on_release=lambda *_: dlg.dismiss()),
                    MDFlatButton(
                        text="ABRIR CONFIGURAÇÕES",
                        on_release=lambda *_: (dlg.dismiss(), self.open_app_notification_settings()),
                    ),
                ],
            )
            dlg.open()
        except Exception:
            try:
                self.app.toast("Ative as notificações nas Configurações do app")
            except Exception:
                pass

    def ensure_post_notifications_permission(self, on_result=None, auto_open_settings: bool = True) -> bool:
        if not self.is_android():
            return True
        if self.android_sdk_int() < 33:
            return True

        if self.post_notif_permission_granted():
            if (
                (not self.notifications_globally_enabled())
                or (not self.channel_enabled("tibia_tools_watch_fg"))
                or (not self.channel_enabled("tibia_tools_events"))
            ):
                try:
                    self.app.toast("Notificações desativadas no sistema")
                except Exception:
                    pass
                if auto_open_settings:
                    try:
                        self.open_app_notification_settings()
                    except Exception:
                        pass
                return False
            return True

        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            perm = "android.permission.POST_NOTIFICATIONS"
            req_code = 7331

            def _after_check(*_):
                granted = self.post_notif_permission_granted()
                if not granted:
                    try:
                        self.app.toast("Ative a permissão de notificações para o Tibia Tools")
                        if auto_open_settings:
                            self.open_app_notification_settings()
                    except Exception:
                        pass
                if on_result:
                    try:
                        on_result(granted)
                    except Exception:
                        pass

            try:
                from android.runnable import run_on_ui_thread  # type: ignore

                @run_on_ui_thread
                def _req():
                    try:
                        activity.requestPermissions([perm], req_code)
                    except Exception:
                        try:
                            ActivityCompat = autoclass("androidx.core.app.ActivityCompat")
                            ActivityCompat.requestPermissions(activity, [perm], req_code)
                        except Exception:
                            pass

                _req()
            except Exception:
                try:
                    activity.requestPermissions([perm], req_code)
                except Exception:
                    pass

            Clock.schedule_once(_after_check, 1.2)
            Clock.schedule_once(_after_check, 2.5)
            return False
        except Exception:
            try:
                self.app.toast(
                    "Não foi possível abrir o popup de permissão. Abra as Configurações do app e ative Notificações."
                )
                if auto_open_settings:
                    self.open_app_notification_settings()
            except Exception:
                pass
            if on_result:
                try:
                    on_result(False)
                except Exception:
                    pass
            return False

    def open_app_notification_settings(self):
        if not self.is_android():
            return
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            Uri = autoclass("android.net.Uri")
            activity = PythonActivity.mActivity
            pkg = activity.getPackageName()

            try:
                intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                intent.putExtra(Settings.EXTRA_APP_PACKAGE, pkg)
            except Exception:
                intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                intent.setData(Uri.parse("package:" + pkg))

            activity.startActivity(intent)
        except Exception:
            pass

    def start_fav_monitor_service(self):
        if not self.is_android():
            return

        if self.android_sdk_int() >= 33:
            ok = self.ensure_post_notifications_permission(auto_open_settings=False)
            if not ok:
                try:
                    self.prompt_enable_notifications_dialog()
                except Exception:
                    pass
                return

        try:
            from jnius import autoclass  # type: ignore
            ServiceFavwatch = autoclass('org.erick.tibiatools.ServiceFavwatch')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            ctx = PythonActivity.mActivity
            try:
                ServiceFavwatch.start(ctx, '', 'Tibia Tools', 'Monitorando favoritos', '')
            except Exception:
                ServiceFavwatch.start(ctx, '')
            self.app._bg_service = True
        except Exception:
            log_current_exception(prefix="AndroidBridgeService.start_fav_monitor_service")

    def stop_fav_monitor_service(self):
        if not self.is_android():
            return
        try:
            from jnius import autoclass  # type: ignore
            ServiceFavwatch = autoclass('org.erick.tibiatools.ServiceFavwatch')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            ctx = PythonActivity.mActivity
            ServiceFavwatch.stop(ctx)
            self.app._bg_service = None
        except Exception:
            log_current_exception(prefix="AndroidBridgeService.stop_fav_monitor_service")

    def maybe_start_fav_monitor_service(self):
        if not self.is_android():
            return
        try:
            st = fav_state.load_state(self.app.data_dir)
            monitoring = bool(st.get("monitoring", True))
            favs = st.get("favorites", [])
            has_favs = isinstance(favs, list) and any(str(x).strip() for x in favs)

            if monitoring and has_favs:
                self.start_fav_monitor_service()
            else:
                self.stop_fav_monitor_service()
        except Exception:
            log_current_exception(prefix="AndroidBridgeService.maybe_start_fav_monitor_service")

    def load_fav_service_state_cached(self) -> dict:
        try:
            now = time.time()
            c = getattr(self.app, "_svc_state_cache", None)
            if isinstance(c, dict) and (now - float(c.get("t", 0))) < 2.0:
                st = c.get("st")
                if isinstance(st, dict):
                    return st
        except Exception:
            pass

        try:
            st = fav_state.load_state(self.app.data_dir)
            if not isinstance(st, dict):
                st = {}
        except Exception:
            st = {}

        try:
            self.app._svc_state_cache = {"t": time.time(), "st": st}
        except Exception:
            pass
        return st

    def get_service_last_entry(self, name: str):
        key = (name or "").strip().lower()
        if not key:
            return None
        try:
            st = self.load_fav_service_state_cached()
            last = st.get("last", {})
            if isinstance(last, dict):
                v = last.get(key)
                return v if isinstance(v, dict) else None
        except Exception:
            return None
        return None

    def service_entry_is_fresh(self, entry: dict, max_age_s: int = 90) -> bool:
        try:
            ts = entry.get("last_checked_iso")
            if not ts:
                return False
            dt = datetime.fromisoformat(str(ts).strip())
            age = (datetime.now() - dt).total_seconds()
            return age <= float(max_age_s)
        except Exception:
            return False

    def sync_bg_monitor_state_from_ui(self):
        try:
            scr = self.app.root.get_screen("settings")
            monitoring = bool(scr.ids.set_bg_monitor.active)
            notify_online = bool(scr.ids.set_bg_notify_online.active)
            notify_level = bool(scr.ids.set_bg_notify_level.active)
            notify_death = bool(scr.ids.set_bg_notify_death.active)
            autostart = bool(scr.ids.set_bg_autostart.active) if 'set_bg_autostart' in scr.ids else True
            try:
                interval = int((scr.ids.set_bg_interval.text or "30").strip())
            except Exception:
                interval = 30
        except Exception:
            return

        try:
            st = fav_state.load_state(self.app.data_dir)
            if not isinstance(st, dict):
                st = {}
            st["favorites"] = [str(x) for x in (self.app.favorites or [])]
            st["monitoring"] = monitoring
            st["notify_fav_online"] = notify_online
            st["notify_fav_level"] = notify_level
            st["notify_fav_death"] = notify_death
            st["autostart_on_boot"] = autostart
            st["interval_seconds"] = max(20, min(600, int(interval)))
            fav_state.save_state(self.app.data_dir, st)
        except Exception:
            pass

        try:
            self.maybe_start_fav_monitor_service()
        except Exception:
            pass
