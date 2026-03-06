from __future__ import annotations

import json
import os
import time
from datetime import datetime

from core.storage import safe_read_json
from services.error_reporting import log_current_exception


class PersistenceService:
    def __init__(self, app):
        self.app = app

    def load_prefs_cache(self):
        prefs = safe_read_json(self.app.prefs_path, default={}) or {}
        if not isinstance(prefs, dict):
            prefs = {}
        cache = safe_read_json(self.app.cache_path, default={}) or {}
        if not isinstance(cache, dict):
            cache = {}

        try:
            with self.app._prefs_lock:
                self.app.prefs = prefs
                self.app._prefs_dirty = False
            with self.app._cache_lock:
                self.app.cache = cache
                self.app._cache_dirty = False
        except Exception:
            self.app.prefs = prefs
            self.app.cache = cache

    def write_json_atomic(self, path: str, data, *, pretty: bool = False) -> bool:
        try:
            base = os.path.dirname(path) or "."
            os.makedirs(base, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                if pretty:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                else:
                    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
            return True
        except Exception:
            return False

    def disk_worker_loop(self) -> None:
        while True:
            try:
                if getattr(self.app, "_disk_stop", None) is not None and self.app._disk_stop.is_set():
                    break
                self.app._disk_event.wait(timeout=1.0)
                if getattr(self.app, "_disk_stop", None) is not None and self.app._disk_stop.is_set():
                    break

                time.sleep(0.4)
                try:
                    self.app._disk_event.clear()
                except Exception:
                    pass

                self.flush_prefs_to_disk()
                self.flush_cache_to_disk()
            except Exception:
                log_current_exception(prefix="PersistenceService.disk_worker_loop")

    def flush_prefs_to_disk(self, force: bool = False) -> None:
        try:
            with self.app._prefs_lock:
                if (not force) and (not bool(getattr(self.app, "_prefs_dirty", False))):
                    return
                snapshot = dict(self.app.prefs) if isinstance(self.app.prefs, dict) else {}
                self.app._prefs_dirty = False
            ok = self.write_json_atomic(self.app.prefs_path, snapshot, pretty=True)
            if not ok:
                with self.app._prefs_lock:
                    self.app._prefs_dirty = True
        except Exception:
            try:
                with self.app._prefs_lock:
                    self.app._prefs_dirty = True
            except Exception:
                pass

    def flush_cache_to_disk(self, force: bool = False) -> None:
        try:
            with self.app._cache_lock:
                if (not force) and (not bool(getattr(self.app, "_cache_dirty", False))):
                    return
                snapshot = dict(self.app.cache) if isinstance(self.app.cache, dict) else {}
                self.app._cache_dirty = False
            ok = self.write_json_atomic(self.app.cache_path, snapshot, pretty=False)
            if not ok:
                with self.app._cache_lock:
                    self.app._cache_dirty = True
        except Exception:
            try:
                with self.app._cache_lock:
                    self.app._cache_dirty = True
            except Exception:
                pass

    def save_prefs(self):
        self.flush_prefs_to_disk(force=True)

    def save_cache(self):
        self.flush_cache_to_disk(force=True)

    def prefs_get(self, key: str, default=None):
        try:
            return self.app.prefs.get(key, default)
        except Exception:
            return default

    def prefs_set(self, key: str, value):
        try:
            with self.app._prefs_lock:
                if not isinstance(self.app.prefs, dict):
                    self.app.prefs = {}
                self.app.prefs[key] = value
                self.app._prefs_dirty = True
            try:
                self.app._disk_event.set()
            except Exception:
                pass
        except Exception:
            pass

    def cache_get(self, key: str, ttl_seconds: int | None = None):
        try:
            item = self.app.cache.get(key)
            if not isinstance(item, dict):
                return None
            ts = item.get("ts")
            val = item.get("value")
            if ttl_seconds is None:
                return val
            if not ts:
                return None
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                return None
            age = (datetime.now() - dt).total_seconds()
            if age > ttl_seconds:
                return None
            return val
        except Exception:
            return None

    def cache_set(self, key: str, value):
        try:
            with self.app._cache_lock:
                if not isinstance(self.app.cache, dict):
                    self.app.cache = {}
                self.app.cache[key] = {"ts": datetime.now().isoformat(), "value": value}
                self.app._cache_dirty = True
            try:
                self.app._disk_event.set()
            except Exception:
                pass
        except Exception:
            pass

    def cache_clear(self):
        try:
            with self.app._cache_lock:
                self.app.cache = {}
                self.app._cache_dirty = True
            try:
                self.app._disk_event.set()
            except Exception:
                pass
        except Exception:
            pass
