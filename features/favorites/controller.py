from __future__ import annotations

import threading
import urllib.parse
import webbrowser
from datetime import datetime
from typing import List, Optional

from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.metrics import dp
from kivymd.uix.list import OneLineIconListItem, TwoLineIconListItem, IconLeftWidget
from kivymd.uix.menu import MDDropdownMenu

from integrations.tibiadata import fetch_character_tibiadata, is_character_online_tibiadata
from integrations.tibia_com import fetch_world_online_players, is_character_online_tibia_com
from services.error_reporting import log_current_exception


class FavoritesControllerMixin:
    def _get_home_screen(self):
        root = getattr(self, "root", None)
        if root is None:
            return None
        get_screen = getattr(root, "get_screen", None)
        if not callable(get_screen):
            return None
        try:
            return get_screen("home")
        except Exception:
            return None

    def _get_home_ids(self, home):
        ids = getattr(home, "ids", None)
        return ids if ids is not None else {}

    def _get_favorites_container(self):
        home = self._get_home_screen()
        if home is None:
            return None, None
        ids = self._get_home_ids(home)
        container = ids.get("fav_list") if hasattr(ids, "get") else None
        return home, container

    def _favorite_names(self) -> list[str]:
        return [str(n).strip() for n in (getattr(self, "favorites", []) or []) if str(n).strip()]

    def _service_last_snapshot(self) -> dict:
        state = self._load_fav_service_state_cached()
        if not isinstance(state, dict):
            return {}
        last = state.get("last", {})
        return last if isinstance(last, dict) else {}

    def _ensure_fav_status_cache(self) -> dict:
        cache = getattr(self, "_fav_status_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._fav_status_cache = cache
        return cache

    def _ensure_fav_world_cache(self) -> dict:
        cache = getattr(self, "_fav_world_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._fav_world_cache = cache
        return cache

    def _sync_service_entry_to_cache(self, name: str, key: str, svc: dict) -> tuple[str, Optional[str], Optional[str]]:
        is_on = bool(svc.get("online"))
        state = "online" if is_on else "offline"
        off_iso = None if is_on else (svc.get("offline_since_iso") if isinstance(svc.get("offline_since_iso"), str) else None)
        seen_iso = svc.get("last_seen_online_iso") if isinstance(svc.get("last_seen_online_iso"), str) else None

        self._ensure_fav_status_cache()[key] = state
        self._cache_set(f"fav_status:{key}", state)
        if state == "online":
            self._set_cached_offline_since_iso(name, None)
        elif off_iso:
            self._set_cached_offline_since_iso(name, off_iso)
        if is_on and seen_iso:
            self._set_cached_last_seen_online_iso(name, seen_iso)
        return state, off_iso, seen_iso

    def _fallback_state_from_cache(self, name: str, force: bool) -> tuple[Optional[str], Optional[str], Optional[str]]:
        state = None if force else self._get_cached_fav_status(name)
        state_label = str(state).strip().lower()
        off_iso = self._get_cached_offline_since_iso(name) if state_label == "offline" else None
        seen_iso = self._get_cached_last_seen_online_iso(name) if state_label == "offline" else None
        return state, off_iso, seen_iso

    def _build_fav_item(self, name: str, secondary: str, color):
        item = TwoLineIconListItem(text=name, secondary_text=secondary)
        item.add_widget(IconLeftWidget(icon="account"))
        item.secondary_theme_text_color = "Custom"
        item.secondary_text_color = color
        item.bind(on_release=lambda _item, n=name: self._fav_actions(n, _item))
        return item

    def _update_existing_fav_item(self, item, secondary: str, color) -> None:
        item.secondary_text = secondary
        item.secondary_text_color = color

    def _needs_fav_rebuild(self, signature: list[str], names: list[str], force: bool) -> bool:
        if force:
            return True
        items = getattr(self, "_fav_items", None)
        if not isinstance(items, dict):
            return True
        if getattr(self, "_fav_rendered_signature", None) != signature:
            return True
        return any((name or "").strip().lower() not in items for name in names)

    def _needs_status_check(self, name: str, service_last: dict, force: bool) -> bool:
        key = (name or "").strip().lower()
        svc = service_last.get(key) if isinstance(service_last, dict) else None
        if isinstance(svc, dict) and self._service_entry_is_fresh(svc, max_age_s=90) and not force:
            return False
        state = None if force else self._get_cached_fav_status(name)
        return bool(force or state is None or self._fav_status_needs_refresh(name, ttl_seconds=45))

    def refresh_favorites_list(self, silent: bool = False, force: bool = False):
        """Renderiza/atualiza a lista de Favoritos sem travar a UI."""
        _home, container = self._get_favorites_container()
        if container is None:
            return

        names = self._favorite_names()
        signature = [n.lower() for n in names]
        try:
            service_last = self._service_last_snapshot()
        except Exception:
            service_last = {}
            log_current_exception(prefix="[fav] snapshot do serviço falhou")

        need_rebuild = self._needs_fav_rebuild(signature, names, force)

        if need_rebuild:
            try:
                container.clear_widgets()
            except AttributeError:
                return
            self._fav_items = {}
            self._fav_rendered_signature = signature

            if not names:
                try:
                    item = OneLineIconListItem(text="Sem favoritos. Adicione no Char.")
                    item.add_widget(IconLeftWidget(icon="star-outline"))
                    container.add_widget(item)
                except Exception:
                    log_current_exception(prefix="[fav] falha ao renderizar estado vazio")
                return

            for name in names:
                key = name.lower()
                svc = service_last.get(key) if isinstance(service_last, dict) else None
                use_svc = isinstance(svc, dict) and self._service_entry_is_fresh(svc, max_age_s=90)
                try:
                    if use_svc:
                        state, off_iso, seen_iso = self._sync_service_entry_to_cache(name, key, svc)
                    else:
                        state, off_iso, seen_iso = self._fallback_state_from_cache(name, force)
                    secondary, color = self._fav_status_presentation(state, off_iso, seen_iso, None)
                    item = self._build_fav_item(name, secondary, color)
                    self._fav_items[key] = item
                    container.add_widget(item)
                except Exception:
                    log_current_exception(prefix=f"[fav] falha ao renderizar favorito: {name}")
        else:
            for name in names:
                key = name.lower()
                item = getattr(self, "_fav_items", {}).get(key)
                if item is None:
                    continue
                svc = service_last.get(key) if isinstance(service_last, dict) else None
                use_svc = isinstance(svc, dict) and self._service_entry_is_fresh(svc, max_age_s=90)
                try:
                    if use_svc:
                        state, off_iso, seen_iso = self._sync_service_entry_to_cache(name, key, svc)
                    else:
                        state, off_iso, seen_iso = self._fallback_state_from_cache(name, force)
                    secondary, color = self._fav_status_presentation(state, off_iso, seen_iso, None)
                    self._update_existing_fav_item(item, secondary, color)
                except Exception:
                    log_current_exception(prefix=f"[fav] falha ao atualizar favorito: {name}")

        names_to_check = [name for name in names if self._needs_status_check(name, service_last, force)]

        if not silent and force:
            self.toast("Atualizando favoritos...")

        if not names_to_check:
            return

        if bool(getattr(self, "_fav_refreshing", False)) and not force:
            return

        self._fav_status_job_id = int(getattr(self, "_fav_status_job_id", 0)) + 1
        job_id = self._fav_status_job_id
        self._fav_refreshing = True
        threading.Thread(
            target=self._refresh_fav_statuses_worker,
            args=(names_to_check, job_id),
            daemon=True,
        ).start()

    def _get_cached_fav_status(self, name: str) -> Optional[str]:
        key_clean = (name or "").strip().lower()
        if not key_clean:
            return None

        cache = self._ensure_fav_status_cache()
        if key_clean in cache:
            cached_value = cache.get(key_clean)
            return str(cached_value) if isinstance(cached_value, str) else cached_value

        cached = self._cache_get(f"fav_status:{key_clean}", ttl_seconds=120)
        return cached if isinstance(cached, str) else None

    def _fav_status_needs_refresh(self, name: str, ttl_seconds: int = 45) -> bool:
        key_clean = (name or "").strip().lower()
        if not key_clean:
            return True
        cache_store = getattr(self, "cache", None)
        if not isinstance(cache_store, dict):
            return True
        item = cache_store.get(f"fav_status:{key_clean}")
        if not isinstance(item, dict):
            return True
        ts = item.get("ts")
        if not isinstance(ts, str) or not ts.strip():
            return True
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return True
        age = (datetime.utcnow() - dt).total_seconds()
        return age > ttl_seconds

    def _get_cached_fav_world(self, name: str) -> Optional[str]:
        key_clean = (name or "").strip().lower()
        if not key_clean:
            return None

        world_cache = self._ensure_fav_world_cache()
        if key_clean in world_cache:
            world = world_cache.get(key_clean)
            return str(world).strip() if world else None

        cached = self._cache_get(f"fav_world:{key_clean}", ttl_seconds=30 * 24 * 3600)
        if isinstance(cached, str) and cached.strip():
            world = cached.strip()
            world_cache[key_clean] = world
            return world
        return None

    def _set_cached_fav_world(self, name: str, world: str) -> None:
        key_clean = (name or "").strip().lower()
        world_clean = (world or "").strip()
        if not key_clean or not world_clean:
            return
        self._ensure_fav_world_cache()[key_clean] = world_clean
        self._cache_set(f"fav_world:{key_clean}", world_clean)

    def _fetch_character_world(self, name: str) -> Optional[str]:
        try:
            data = fetch_character_tibiadata(name, timeout=12)
        except Exception:
            log_current_exception(prefix=f"[fav] TibiaData falhou ao buscar world: {name}")
            return None
        wrapper = data.get("character", {}) if isinstance(data, dict) else {}
        character = wrapper.get("character", wrapper) if isinstance(wrapper, dict) else {}
        world = str((character or {}).get("world") or "").strip()
        if world and world.upper() != "N/A":
            self._set_cached_fav_world(name, world)
            return world
        return None

    def _fetch_world_online_players(self, world: str, timeout: int = 12) -> Optional[set]:
        try:
            return fetch_world_online_players(world, timeout=timeout)
        except Exception:
            log_current_exception(prefix=f"[fav] falha ao buscar online players: {world}")
            return None

    def _fav_status_presentation(
        self,
        state,
        offline_since_iso: Optional[str] = None,
        last_seen_online_iso: Optional[str] = None,
        fallback_last_login_iso: Optional[str] = None,
    ) -> tuple[str, tuple]:
        state_label = str(state).strip().lower() if state is not None else ""
        if state_label == "online" or state is True:
            return "Online", (0.2, 0.75, 0.35, 1)
        if state_label == "offline" or state is False:
            extra = ""
            iso = offline_since_iso or last_seen_online_iso or fallback_last_login_iso
            if iso:
                try:
                    ago = self._format_ago_short(datetime.fromisoformat(str(iso).strip()))
                except ValueError:
                    ago = ""
                if ago:
                    extra = f" • {ago}"
            return f"Offline{extra}", (0.95, 0.3, 0.3, 1)
        return "Atualizando...", (0.7, 0.7, 0.7, 1)

    def _set_fav_item_status(
        self,
        name: str,
        state,
        offline_since_iso: Optional[str] = None,
        last_seen_online_iso: Optional[str] = None,
        fallback_last_login_iso: Optional[str] = None,
    ) -> None:
        key = (name or "").strip().lower()
        if not key:
            return

        state_label = str(state).strip().lower()
        if state_label == "online":
            now_iso = last_seen_online_iso or datetime.utcnow().isoformat()
            self._set_cached_last_seen_online_iso(name, now_iso)
            self._set_cached_offline_since_iso(name, None)
        elif state_label == "offline" and offline_since_iso:
            self._set_cached_offline_since_iso(name, str(offline_since_iso).strip())

        self._ensure_fav_status_cache()[key] = state
        self._cache_set(f"fav_status:{key}", state)

        item = getattr(self, "_fav_items", {}).get(key)
        if item is None:
            return

        off_since = offline_since_iso or self._get_cached_offline_since_iso(name)
        seen = last_seen_online_iso or self._get_cached_last_seen_online_iso(name)
        label, color = self._fav_status_presentation(state, off_since, seen, fallback_last_login_iso)
        self._update_existing_fav_item(item, label, color)

    def _dismiss_fav_menu(self) -> None:
        menu = getattr(self, "_fav_menu", None)
        if menu is None:
            return
        try:
            menu.dismiss()
        except Exception:
            log_current_exception(prefix="[fav] falha ao fechar menu")
        self._fav_menu = None

    def _open_fav_in_app(self, name: str) -> None:
        self._dismiss_fav_menu()
        home = self._get_home_screen()
        if home is None:
            return
        ids = self._get_home_ids(home)
        nav = ids.get("bottom_nav") if hasattr(ids, "get") else None
        if nav is not None:
            try:
                if hasattr(nav, "switch_tab"):
                    nav.switch_tab("tab_char")
                else:
                    nav.current = "tab_char"
            except Exception:
                log_current_exception(prefix="[fav] falha ao trocar para aba Char")
        char_name = ids.get("char_name") if hasattr(ids, "get") else None
        if char_name is not None:
            char_name.text = name
        Clock.schedule_once(lambda _dt: self.search_character(), 0.05)

    def _open_fav_on_site(self, name: str) -> None:
        self._dismiss_fav_menu()
        url = (
            "https://www.tibia.com/community/?subtopic=characters&name="
            + urllib.parse.quote_plus(str(name or ""))
        )
        webbrowser.open(url)

    def _remove_favorite(self, name: str) -> None:
        self._dismiss_fav_menu()
        key = (name or "").strip().lower()
        if not key:
            return

        current = list(getattr(self, "favorites", []) or [])
        new_favorites = [n for n in current if (n or "").strip().lower() != key]
        if len(new_favorites) == len(current):
            return

        self.favorites = new_favorites
        self.save_favorites()
        try:
            self._maybe_start_fav_monitor_service()
        except Exception:
            log_current_exception(prefix="[fav] falha ao sincronizar serviço após remover favorito")
        self._cache_set(f"fav_status:{key}", None)
        self._ensure_fav_status_cache().pop(key, None)
        self.refresh_favorites_list()
        self.toast("Removido dos favoritos.")

    def _apply_fav_status_updates(self, updates, job_id: int) -> None:
        if job_id != getattr(self, "_fav_status_job_id", None):
            return
        if not updates:
            return
        for name, state, off_iso, seen_iso in updates:
            self._set_fav_item_status(name, state, off_iso, seen_iso, None)

    def _status_transition_metadata(self, name: str, state: str) -> tuple[Optional[str], Optional[str]]:
        state_label = str(state).strip().lower()
        if state_label == "online":
            return None, datetime.utcnow().isoformat()
        seen_iso = self._get_cached_last_seen_online_iso(name)
        off_iso = self._get_cached_offline_since_iso(name)
        prev = str(self._get_cached_fav_status(name) or "").strip().lower()
        if prev == "online" and not off_iso:
            off_iso = datetime.utcnow().isoformat()
        return off_iso, seen_iso

    def _refresh_fav_statuses_worker(self, names: List[str], job_id: int):
        try:
            updates: list[tuple[str, str, Optional[str], Optional[str]]] = []
            name_to_world: dict[str, str] = {}
            unknown: list[str] = []

            for name in names:
                if job_id != getattr(self, "_fav_status_job_id", None):
                    return
                world = self._get_cached_fav_world(name) or self._fetch_character_world(name)
                if world:
                    name_to_world[name] = world
                else:
                    unknown.append(name)

            by_world: dict[str, list[str]] = {}
            for name, world in name_to_world.items():
                by_world.setdefault(world, []).append(name)

            for world, world_names in by_world.items():
                if job_id != getattr(self, "_fav_status_job_id", None):
                    return
                online_set = self._fetch_world_online_players(world, timeout=12) or set()
                for name in world_names:
                    if job_id != getattr(self, "_fav_status_job_id", None):
                        return
                    is_online = name.strip().lower() in online_set
                    state = "online" if is_online else "offline"
                    off_iso, seen_iso = self._status_transition_metadata(name, state)
                    if state == "online":
                        off_iso = None
                    updates.append((name, state, off_iso, seen_iso))

            for name in unknown:
                if job_id != getattr(self, "_fav_status_job_id", None):
                    return
                state = self._fetch_character_online_state(name)
                if state is None:
                    key = (name or "").strip().lower()
                    state = getattr(self, "_fav_status_cache", {}).get(key) or "offline"
                off_iso, seen_iso = self._status_transition_metadata(name, str(state))
                if str(state).strip().lower() == "online":
                    off_iso = None
                updates.append((name, str(state), off_iso, seen_iso))

            Clock.schedule_once(lambda _dt, ups=updates: self._apply_fav_status_updates(ups, job_id), 0)
        except Exception:
            log_current_exception(prefix="[fav] worker de refresh falhou")
        finally:
            Clock.schedule_once(lambda _dt: setattr(self, "_fav_refreshing", False), 0)

    def _fetch_character_online_state(self, name: str) -> Optional[str]:
        try:
            online = is_character_online_tibia_com(name, world="", timeout=12)
        except Exception:
            online = None
        if online is not None:
            return "online" if online else "offline"

        try:
            online = is_character_online_tibiadata(name, world=None, timeout=12)
        except Exception:
            online = None
        if online is not None:
            return "online" if online else "offline"
        return None

    def _run_fav_action(self, fn) -> None:
        self._dismiss_fav_menu()
        try:
            fn()
        except Exception:
            log_current_exception(prefix="[fav] ação do menu falhou")
            self.show_snackbar("Erro ao executar ação.")

    def _fav_actions(self, name: str, caller=None):
        caller = caller or getattr(self, "root", None)
        if caller is None:
            return
        self._dismiss_fav_menu()

        menu_items = [
            {
                "viewclass": "OneLineListItem",
                "text": "Ver no app",
                "height": dp(48),
                "on_release": lambda *_: self._run_fav_action(lambda: self._open_fav_in_app(name)),
            },
            {
                "viewclass": "OneLineListItem",
                "text": "Abrir no site",
                "height": dp(48),
                "on_release": lambda *_: self._run_fav_action(lambda: self._open_fav_on_site(name)),
            },
            {
                "viewclass": "OneLineListItem",
                "text": "Copiar nome",
                "height": dp(48),
                "on_release": lambda *_: self._run_fav_action(lambda: self._copy_fav_name(name)),
            },
            {
                "viewclass": "OneLineListItem",
                "text": "Remover dos favoritos",
                "height": dp(48),
                "on_release": lambda *_: self._run_fav_action(lambda: self._remove_favorite(name)),
            },
        ]

        try:
            self._fav_menu = MDDropdownMenu(
                caller=caller,
                items=menu_items,
                width_mult=4,
                max_height=dp(240),
            )
            self._fav_menu.open()
        except Exception:
            log_current_exception(prefix="[fav] falha ao abrir menu")
            self.show_snackbar("Erro ao abrir opções.")

    def show_snackbar(self, message: str):
        self.toast(message)

    def _copy_fav_name(self, name: str):
        self._dismiss_fav_menu()
        try:
            Clipboard.copy(str(name or ""))
        except Exception:
            self.toast("Não consegui copiar o nome.")
            return
        self.toast("Nome copiado.")
