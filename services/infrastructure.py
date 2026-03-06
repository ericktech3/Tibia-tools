from __future__ import annotations

from datetime import datetime
from typing import Optional

from repositories.favorites_repo import load_favorites as repo_load_favorites, save_favorites as repo_save_favorites


class InfrastructureMixin:
    def load_favorites(self):
        self.favorites = repo_load_favorites(self.data_dir, self.fav_path)

    def save_favorites(self):
        repo_save_favorites(self.data_dir, self.fav_path, [str(x) for x in (self.favorites or [])])

    def _load_prefs_cache(self):
        self.persistence.load_prefs_cache()

    def _write_json_atomic(self, path: str, data, *, pretty: bool = False) -> bool:
        return self.persistence.write_json_atomic(path, data, pretty=pretty)

    def _disk_worker_loop(self) -> None:
        return self.persistence.disk_worker_loop()

    def _flush_prefs_to_disk(self, force: bool = False) -> None:
        return self.persistence.flush_prefs_to_disk(force=force)

    def _flush_cache_to_disk(self, force: bool = False) -> None:
        return self.persistence.flush_cache_to_disk(force=force)

    def _save_prefs(self):
        return self.persistence.save_prefs()

    def _save_cache(self):
        return self.persistence.save_cache()

    def _prefs_get(self, key: str, default=None):
        return self.persistence.prefs_get(key, default)

    def _prefs_set(self, key: str, value):
        return self.persistence.prefs_set(key, value)

    def _cache_get(self, key: str, ttl_seconds: int | None = None):
        return self.persistence.cache_get(key, ttl_seconds=ttl_seconds)

    def _cache_set(self, key: str, value):
        return self.persistence.cache_set(key, value)

    def _cache_clear(self):
        return self.persistence.cache_clear()

    def _send_notification(self, title: str, message: str):
        try:
            from plyer import notification  # type: ignore
            notification.notify(title=title, message=message, app_name="Tibia Tools")
            return
        except Exception:
            pass
        self.toast(f"{title}: {message}")

    def _is_android(self) -> bool:
        return self.android_bridge.is_android()

    def _android_sdk_int(self) -> int:
        return self.android_bridge.android_sdk_int()

    def _post_notif_permission_granted(self) -> bool:
        return self.android_bridge.post_notif_permission_granted()

    def _notifications_globally_enabled(self) -> bool:
        return self.android_bridge.notifications_globally_enabled()

    def _channel_enabled(self, channel_id: str) -> bool:
        return self.android_bridge.channel_enabled(channel_id)

    def _prompt_enable_notifications_dialog(self):
        return self.android_bridge.prompt_enable_notifications_dialog()

    def _ensure_post_notifications_permission(self, on_result=None, auto_open_settings: bool = True) -> bool:
        return self.android_bridge.ensure_post_notifications_permission(on_result=on_result, auto_open_settings=auto_open_settings)

    def _open_app_notification_settings(self):
        return self.android_bridge.open_app_notification_settings()

    def _start_fav_monitor_service(self):
        return self.android_bridge.start_fav_monitor_service()

    def _stop_fav_monitor_service(self):
        return self.android_bridge.stop_fav_monitor_service()

    def _maybe_start_fav_monitor_service(self):
        return self.android_bridge.maybe_start_fav_monitor_service()

    def _load_fav_service_state_cached(self) -> dict:
        return self.android_bridge.load_fav_service_state_cached()

    def _get_service_last_entry(self, name: str):
        return self.android_bridge.get_service_last_entry(name)

    def _service_entry_is_fresh(self, entry: dict, max_age_s: int = 90) -> bool:
        return self.android_bridge.service_entry_is_fresh(entry, max_age_s=max_age_s)

    def _sync_bg_monitor_state_from_ui(self):
        return self.android_bridge.sync_bg_monitor_state_from_ui()
