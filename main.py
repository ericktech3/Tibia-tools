# -*- coding: utf-8 -*-
"""
Tibia Tools (Android) - KivyMD app

Tabs: Char / Share XP / Favoritos / Mais
Mais -> telas internas: Bosses (ExevoPan), Boosted, Treino (Exercise), Imbuements, Hunt Analyzer
"""
from __future__ import annotations

import os
import json
import re
import threading
import time
import urllib.parse
import webbrowser
import traceback
import math
import requests
from datetime import datetime, timedelta
from urllib.parse import quote
from typing import List, Optional

from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.resources import resource_find
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.screenmanager import ScreenManager
from kivy.utils import platform

from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.list import (
    OneLineIconListItem,
    OneLineListItem,
    TwoLineIconListItem,
    IconLeftWidget,
)
from kivymd.uix.menu import MDDropdownMenu

# ---- IMPORTS DO CORE (com proteção para não “fechar sozinho” no Android) ----
_CORE_IMPORT_ERROR = None
try:
    from core.api import (
        fetch_character_tibiadata,
        fetch_worlds_tibiadata,
        is_character_online_tibiadata,
        is_character_online_tibia_com,
        fetch_guildstats_deaths_xp,
    )
    from core.exp_loss import estimate_death_exp_lost
    from core.storage import get_data_dir, safe_read_json, safe_write_json
    from core import state as fav_state
    from core.bosses import fetch_exevopan_bosses
    from core.boosted import fetch_boosted
    from core.training import TrainingInput, compute_training_plan
    from core.hunt import parse_hunt_session_text
    from core.imbuements import fetch_imbuements_table, fetch_imbuement_details, ImbuementEntry
    from core.stamina import parse_hm_text, compute_offline_regen, format_hm
except Exception:
    _CORE_IMPORT_ERROR = traceback.format_exc()

KV_FILE = "tibia_tools.kv"


class RootSM(ScreenManager):
    pass


class MoreItem(OneLineIconListItem):
    icon = StringProperty("chevron-right")


class TibiaToolsApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.favorites: List[str] = []

        self.data_dir = get_data_dir() if _CORE_IMPORT_ERROR is None else os.getcwd()
        os.makedirs(self.data_dir, exist_ok=True)
        self.fav_path = os.path.join(self.data_dir, "favorites.json")
        self.prefs_path = os.path.join(self.data_dir, "prefs.json")
        self.cache_path = os.path.join(self.data_dir, "cache.json")
        self.prefs = {}
        self.cache = {}
        self._bosses_filter_debounce_ev = None
        self._menu_boss_filter = None
        self._menu_boss_sort = None
        self._menu_imb_tier = None


        self._menu_world: Optional[MDDropdownMenu] = None
        self._menu_skill: Optional[MDDropdownMenu] = None
        self._menu_vocation: Optional[MDDropdownMenu] = None
        self._menu_weapon: Optional[MDDropdownMenu] = None

        # Favorites (chars) UI/status helpers
        self._fav_items = {}  # lower(char_name) -> list item
        self._fav_status_cache = {}  # lower(char_name) -> last known "online"/"offline"
        self._fav_world_cache = {}  # lower(char_name) -> cached world
        self._fav_status_job_id = 0
        self._fav_refresh_event = None

    def build(self):
        self.title = "Tibia Tools"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Dark"

        # Se algum import do core falhar no Android, mostre na tela em vez de fechar.
        if _CORE_IMPORT_ERROR is not None:
            print(_CORE_IMPORT_ERROR)
            from kivymd.uix.label import MDLabel
            return MDLabel(
                text="Erro ao importar módulos (core).\nVeja o logcat (Traceback).",
                halign="center",
            )

        kv_ok = False
        try:
            kv_path = resource_find(KV_FILE) or KV_FILE
            root = Builder.load_file(kv_path)
            kv_ok = True
        except Exception:
            traceback.print_exc()
            from kivymd.uix.label import MDLabel
            root = MDLabel(text="Erro ao iniciar. Veja o logcat (Traceback).", halign="center")

        # ✅ MUITO IMPORTANTE:
        # só agenda funções que usam telas/ids se o KV carregou de verdade.
        if kv_ok and isinstance(root, ScreenManager):
            self.load_favorites()
            self._load_prefs_cache()
            Clock.schedule_once(lambda *_: self._apply_settings_to_ui(), 0)
            Clock.schedule_once(lambda *_: self._maybe_start_fav_monitor_service(), 0.2)
            Clock.schedule_once(lambda *_: self._set_initial_home_tab(), 0)
            Clock.schedule_once(lambda *_: self.dashboard_refresh(), 0)

            Clock.schedule_once(lambda *_: self.refresh_favorites_list(silent=True), 0)
            # Auto-atualização do status dos favoritos (não faz sentido ficar "travado")
            if self._fav_refresh_event is None:
                self._fav_refresh_event = Clock.schedule_interval(
                    lambda dt: self.refresh_favorites_list(silent=True),
                    30,
                )
            Clock.schedule_once(lambda *_: self.update_boosted(), 0)

        return root

    # --------------------
    # Navigation
    # --------------------

    def on_start(self):
        """Android 13+ (SDK 33+) pode exigir permissão de notificação.

        Em vários devices, o helper `android.permissions` não dispara o popup e/ou falha silenciosamente.
        Aqui fazemos o check + request via Activity.requestPermissions (JNI), e re-tentamos com throttle.
        """
        try:
            # Se o app foi aberto por toque em uma notificação do service,
            # processa os extras e navega (Home/Favoritos/Char).
            Clock.schedule_once(self._handle_notification_intent, 0.6)
            Clock.schedule_once(self._handle_notification_intent, 1.4)

            if not self._is_android():
                return
            if self._android_sdk_int() < 33:
                return
            # throttle para evitar spam caso o usuário negue
            now = int(time.time())
            last = int(self._prefs_get("post_notif_last_req_ts", 0) or 0)
            if now - last < 60:
                return
            # Se já está concedido, ainda precisamos checar se o usuário bloqueou o app/canal.
            if self._post_notif_permission_granted():
                if (not self._notifications_globally_enabled()) or (not self._channel_enabled("tibia_tools_watch_fg")):
                    # aqui não existe popup, só Configurações
                    Clock.schedule_once(lambda *_: self._prompt_enable_notifications_dialog(), 0.2)
                return
            self._prefs_set("post_notif_last_req_ts", now)
            from kivy.clock import Clock
            Clock.schedule_once(lambda *_: self._ensure_post_notifications_permission(auto_open_settings=False), 0.8)
        except Exception:
            pass

    def on_resume(self):
        """Chamado quando o app volta para o foreground.

        Importante para quando o usuário toca uma notificação com o app já aberto.
        """
        try:
            Clock.schedule_once(self._handle_notification_intent, 0.2)
            Clock.schedule_once(self._handle_notification_intent, 0.8)
        except Exception:
            pass
        return True

    def go(self, screen_name: str):
        sm = self.root
        if isinstance(sm, ScreenManager) and screen_name in sm.screen_names:
            sm.current = screen_name

    def back_home(self, *_):
        self.go("home")


    def select_home_tab(self, tab_name: str):
        """Seleciona uma aba dentro da HomeScreen (BottomNavigation)."""
        try:
            home = self.root.get_screen("home")
            if "bottom_nav" in home.ids:
                home.ids.bottom_nav.switch_tab(tab_name)
        except Exception:
            pass

    # --------------------
    # Android: abrir tela ao tocar na notificação
    # --------------------
    def _handle_notification_intent(self, *_):
        """Se o app foi aberto via notificação do service, navega para a tela correta.

        Extras esperados:
          - tt_open: "fav" | "char"
          - tt_char: nome do personagem (opcional)
          - tt_event: "online" | "level" | "death" (opcional)
        """
        if not self._is_android():
            return
        try:
            from jnius import autoclass  # type: ignore

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            intent = activity.getIntent()
            if intent is None:
                return

            tt_open = intent.getStringExtra("tt_open")
            if not tt_open:
                return
            tt_open = str(tt_open)

            tt_char = intent.getStringExtra("tt_char")
            tt_char = str(tt_char) if tt_char else ""
            tt_event = intent.getStringExtra("tt_event")
            tt_event = str(tt_event) if tt_event else ""

            # Limpa para não reprocessar no próximo on_resume
            try:
                intent.removeExtra("tt_open")
                intent.removeExtra("tt_char")
                intent.removeExtra("tt_event")
                activity.setIntent(intent)
            except Exception:
                pass

            # Navegação
            self.go("home")
            if tt_open == "fav":
                self.select_home_tab("tab_fav")
            elif tt_open == "char":
                self.select_home_tab("tab_char")
                if tt_char:
                    try:
                        home = self.root.get_screen("home")
                        home.ids.char_name.text = tt_char
                    except Exception:
                        pass
                    # chama a busca após o tab/ids estarem prontos
                    Clock.schedule_once(lambda *_: self.search_character(), 0.2)

            # Feedback opcional
            if tt_event and tt_char:
                if tt_event == "online":
                    self.toast(f"{tt_char} ficou ONLINE")
                elif tt_event == "level":
                    self.toast(f"{tt_char} upou level")
                elif tt_event == "death":
                    self.toast(f"{tt_char} morreu")
        except Exception:
            pass

    def open_more_target(self, target: str):
        self.go(target)
        if target == "bosses":
            self._bosses_refresh_worlds()
        elif target == "imbuements":
            self._imbuements_load()
        elif target == "training":
            self._ensure_training_menus()
        elif target == "settings":
            self._apply_settings_to_ui()

    
    # --------------------
    # Dashboard (Home)
    # --------------------
    def _send_notification(self, title: str, message: str):
        # Notificação "best effort" (sem background)
        try:
            from plyer import notification  # type: ignore
            notification.notify(title=title, message=message, app_name="Tibia Tools")
            return
        except Exception:
            pass
        self.toast(f"{title}: {message}")


    # --------------------
    # Background service: monitor favorites even with the app closed
    # --------------------
    def _is_android(self) -> bool:
        return platform == "android"

    def _android_sdk_int(self) -> int:
        if not self._is_android():
            return 0
        try:
            from jnius import autoclass  # type: ignore
            VERSION = autoclass("android.os.Build$VERSION")
            return int(VERSION.SDK_INT)
        except Exception:
            return 0

    def _post_notif_permission_granted(self) -> bool:
        """Check via Activity.checkSelfPermission (não depende de android.permissions)."""
        if not self._is_android():
            return True
        if self._android_sdk_int() < 33:
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

    def _notifications_globally_enabled(self) -> bool:
        """Verifica se o usuário bloqueou notificações do app (toggle do sistema).

        Observação: isso é diferente do runtime permission (Android 13+).
        Em muitos aparelhos (MIUI/OneUI/etc.), o usuário pode ter notificações desligadas
        mesmo com a permissão concedida — e aí NÃO existe popup, só Configurações.
        """
        if not self._is_android():
            return True
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            nm = activity.getSystemService(Context.NOTIFICATION_SERVICE)
            # API 24+
            try:
                return bool(nm.areNotificationsEnabled())
            except Exception:
                return True
        except Exception:
            return True

    def _channel_enabled(self, channel_id: str) -> bool:
        if not self._is_android():
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

    def _prompt_enable_notifications_dialog(self):
        """Mostra um dialog com atalho para Configurações de notificação do app."""
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
                    MDFlatButton(text="ABRIR CONFIGURAÇÕES", on_release=lambda *_: (dlg.dismiss(), self._open_app_notification_settings())),
                ],
            )
            dlg.open()
        except Exception:
            # fallback
            try:
                self.toast("Ative as notificações nas Configurações do app")
            except Exception:
                pass
    def _ensure_post_notifications_permission(self, on_result=None, auto_open_settings: bool = True) -> bool:
        """Android 13+ exige POST_NOTIFICATIONS.

        Retorna True se já está OK (ou não precisa).
        Se precisar pedir, dispara o prompt e retorna False.
        Se `on_result` for passado, chama com (granted: bool) quando o usuário responder.

        `auto_open_settings`: se True e o usuário negar, abre a tela de notificações do app.
        """
        if not self._is_android():
            return True

        if self._android_sdk_int() < 33:
            return True

        # 1) check robusto
        if self._post_notif_permission_granted():
            # Mesmo com permissão, o usuário pode ter bloqueado notificações do app/canal.
            if (not self._notifications_globally_enabled()) or (not self._channel_enabled("tibia_tools_watch_fg")):
                try:
                    self.toast("Notificações desativadas no sistema")
                except Exception:
                    pass
                if auto_open_settings:
                    try:
                        self._open_app_notification_settings()
                    except Exception:
                        pass
                return False
            return True

        # 2) request robusto via Activity.requestPermissions
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            perm = "android.permission.POST_NOTIFICATIONS"
            req_code = 7331

            def _after_check(*_):
                granted = self._post_notif_permission_granted()
                if not granted:
                    try:
                        self.toast("Ative a permissão de notificações para o Tibia Tools")
                        if auto_open_settings:
                            self._open_app_notification_settings()
                    except Exception:
                        pass
                if on_result:
                    try:
                        on_result(granted)
                    except Exception:
                        pass

            # O popup só aparece se chamado na UI thread.
            try:
                from android.runnable import run_on_ui_thread  # type: ignore

                @run_on_ui_thread
                def _req():
                    try:
                        activity.requestPermissions([perm], req_code)
                    except Exception:
                        # fallback para versões antigas
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

            # Não temos callback direto aqui; checa depois.
            from kivy.clock import Clock
            Clock.schedule_once(_after_check, 1.2)
            Clock.schedule_once(_after_check, 2.5)
            return False
        except Exception:
            # Se não der pra pedir, guia o usuário para Configurações.
            try:
                self.toast("Não foi possível abrir o popup de permissão. Abra as Configurações do app e ative Notificações.")
                if auto_open_settings:
                    self._open_app_notification_settings()
            except Exception:
                pass
            if on_result:
                try:
                    on_result(False)
                except Exception:
                    pass
            return False


    def _open_app_notification_settings(self):
        """Abre a tela de notificações do app."""
        if not self._is_android():
            return
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            Uri = autoclass("android.net.Uri")
            activity = PythonActivity.mActivity
            pkg = activity.getPackageName()

            # Preferir tela específica de notificação (quando disponível)
            try:
                intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                intent.putExtra(Settings.EXTRA_APP_PACKAGE, pkg)
            except Exception:
                intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                intent.setData(Uri.parse("package:" + pkg))

            activity.startActivity(intent)
        except Exception:
            pass
    def _start_fav_monitor_service(self):
        if not self._is_android():
            return

        def _do_start():
            try:
                from jnius import autoclass  # type: ignore
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                PythonService = autoclass("org.kivy.android.PythonService")
                mActivity = PythonActivity.mActivity
                # Inicia o serviço (foreground notification será ajustada dentro do service/main.py)
                PythonService.start(mActivity, "Tibia Tools", "Monitorando favoritos")
                return
            except Exception:
                # Fallback (older API)
                try:
                    from android import AndroidService  # type: ignore
                    s = AndroidService("Tibia Tools", "Monitorando favoritos")
                    s.start("start")
                except Exception:
                    pass

        # Android 13+: só inicia depois da permissão
        ok = self._ensure_post_notifications_permission(on_result=lambda granted: _do_start() if granted else None, auto_open_settings=True)
        if ok:
            _do_start()


    def _stop_fav_monitor_service(self):
        if not self._is_android():
            return
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            PythonService = autoclass("org.kivy.android.PythonService")
            mActivity = PythonActivity.mActivity
            PythonService.stop(mActivity)
        except Exception:
            try:
                from android import AndroidService  # type: ignore
                s = AndroidService("Tibia Tools", "Monitorando favoritos")
                s.stop()
            except Exception:
                pass

    def _maybe_start_fav_monitor_service(self):
        if not self._is_android():
            return
        try:
            st = fav_state.load_state(self.data_dir)
            if bool(st.get("monitoring", False)):
                self._start_fav_monitor_service()
        except Exception:
            pass

    def _sync_bg_monitor_state_from_ui(self):
        """Save background-monitor settings into favorites.json (shared with the service)."""
        try:
            scr = self.root.get_screen("settings")
            monitoring = bool(scr.ids.set_bg_monitor.active)
            notify_online = bool(scr.ids.set_bg_notify_online.active)
            notify_level = bool(scr.ids.set_bg_notify_level.active)
            notify_death = bool(scr.ids.set_bg_notify_death.active)
            try:
                interval = int((scr.ids.set_bg_interval.text or "60").strip())
            except Exception:
                interval = 60
        except Exception:
            return

        try:
            st = fav_state.load_state(self.data_dir)
            if not isinstance(st, dict):
                st = {}
            st["favorites"] = [str(x) for x in (self.favorites or [])]
            st["monitoring"] = monitoring
            st["notify_fav_online"] = notify_online
            st["notify_fav_level"] = notify_level
            st["notify_fav_death"] = notify_death
            st["interval_seconds"] = max(20, min(600, int(interval)))
            fav_state.save_state(self.data_dir, st)
        except Exception:
            pass

        # start/stop service immediately
        if monitoring:
            self._start_fav_monitor_service()
        else:
            self._stop_fav_monitor_service()

    def dashboard_refresh(self, *_):
        """Atualiza o resumo do Dashboard usando cache e, se possível, dados ao vivo."""
        try:
            home = self.root.get_screen("home")
            ids = home.ids
        except Exception:
            return

        # último char
        last_char = str(self._prefs_get("last_char", "") or "")
        try:
            ids.dash_last_char.text = last_char if last_char else "-"
        except Exception:
            pass

        # boosted do cache (TTL 12h) e atualização ao vivo em background
        cached_boost = self._cache_get("boosted", ttl_seconds=12 * 3600) or {}
        if isinstance(cached_boost, dict) and cached_boost:
            try:
                ids.dash_boost_creature.text = f"Creature: {cached_boost.get('creature', '-')}"
                ids.dash_boost_boss.text = f"Boss: {cached_boost.get('boss', '-')}"
                ts = self.cache.get("boosted", {}).get("ts", "")
                ids.dash_boost_updated.text = f"Atualizado: {ts.split('T')[0] if ts else ''}"
            except Exception:
                pass
        else:
            try:
                ids.dash_boost_creature.text = "Creature: -"
                ids.dash_boost_boss.text = "Boss: -"
                ids.dash_boost_updated.text = "Sem cache ainda."
            except Exception:
                pass

        # atualiza boosted ao vivo (não trava UI)
        try:
            self.update_boosted(silent=True)
        except Exception:
            pass

        # bosses favoritos high (do cache do último world)
        try:
            ids.dash_boss_list.clear_widgets()
        except Exception:
            pass

        favs = self._prefs_get("boss_favorites", []) or []
        if not isinstance(favs, list):
            favs = []

        world = str(self._prefs_get("boss_last_world", "") or "")
        cache_key = f"bosses:{world.lower()}" if world else ""
        bosses = self._cache_get(cache_key, ttl_seconds=6 * 3600) if cache_key else None
        if not bosses:
            try:
                ids.dash_boss_hint.text = "Sem cache de bosses ainda. Abra Bosses e toque em Buscar."
            except Exception:
                pass
            return

        high = []
        for b in bosses:
            try:
                name = str(b.get("boss") or b.get("name") or "")
                if name not in favs:
                    continue
                score = self._boss_chance_score(str(b.get("chance") or ""))
                if score >= 70:
                    high.append((score, b))
            except Exception:
                continue

        high.sort(key=lambda t: t[0], reverse=True)
        if not high:
            try:
                ids.dash_boss_hint.text = f"Nenhum favorito High em {world}."
            except Exception:
                pass
            return

        try:
            ids.dash_boss_hint.text = f"World: {world}  •  High: {len(high)}"
        except Exception:
            pass

        for _, b in high[:6]:
            name = str(b.get("boss") or b.get("name") or "Boss")
            chance = str(b.get("chance") or "").strip()
            it = OneLineIconListItem(text=f"{name} ({chance})")
            it.add_widget(IconLeftWidget(icon="star"))
            it.bind(on_release=lambda _it, bb=b: self.bosses_open_dialog(bb))
            try:
                ids.dash_boss_list.add_widget(it)
            except Exception:
                pass

        # alerta (apenas ao abrir/app na frente) - best effort
        try:
            if bool(self._prefs_get("notify_boss_high", True)) and high:
                today = datetime.utcnow().date().isoformat()
                last = str(self._prefs_get("boss_high_notified_date", "") or "")
                if last != today:
                    self._prefs_set("boss_high_notified_date", today)
                    self._send_notification("Boss favorito HIGH", f"{high[0][1].get('boss','Boss')} está HIGH em {world}")
        except Exception:
            pass

    def dashboard_open_last_char(self):
        last_char = str(self._prefs_get("last_char", "") or "").strip()
        if not last_char:
            self.toast("Nenhum char salvo ainda.")
            return
        try:
            webbrowser.open(f"https://www.tibia.com/community/?subtopic=characters&name={last_char.replace(' ', '+')}")
        except Exception:
            self.toast("Não consegui abrir o navegador.")

    # --------------------
    # Clipboard / Share helpers
    # --------------------
    def copy_deaths_to_clipboard(self):
        try:
            home = self.root.get_screen("home")
            title = (home.ids.char_title.text or "").strip()
            payload = getattr(home, "_last_char_payload", None)
            deaths = []
            if isinstance(payload, dict):
                deaths = payload.get("deaths") or []
            lines = [f"Mortes - {title}"]
            for d in deaths[:30]:
                if not isinstance(d, dict):
                    continue
                when = str(d.get("time") or d.get("date") or "")
                lvl = str(d.get("level") or "")
                reason = str(d.get("reason") or "")
                xp = str(d.get("exp_lost") or "")
                parts = [p for p in [when, f"Level {lvl}" if lvl else "", xp, reason] if p]
                lines.append(" - ".join(parts))
            Clipboard.copy("\n".join(lines))
            self.toast("Copiado.")
        except Exception:
            self.toast("Não consegui copiar.")

    def hunt_copy(self):
        try:
            scr = self.root.get_screen("hunt")
            Clipboard.copy(scr.ids.hunt_output.text or "")
            self.toast("Copiado.")
        except Exception:
            self.toast("Nada para copiar.")

    def hunt_share(self):
        try:
            scr = self.root.get_screen("hunt")
            txt = (scr.ids.hunt_output.text or "").strip()
            if not txt:
                self.toast("Nada para compartilhar.")
                return
            try:
                from plyer import share  # type: ignore
                share.share(txt, title="Hunt Analyzer")
                return
            except Exception:
                Clipboard.copy(txt)
                self.toast("Copiado (share indisponível).")
        except Exception:
            self.toast("Falha ao compartilhar.")

# --------------------
    # Storage
    # --------------------

    def load_favorites(self):
        # favorites.json is now a shared state file used by the background service.
        # We still keep self.favorites as a simple list for the UI.
        try:
            st = fav_state.load_state(self.data_dir)
            fav = st.get("favorites", []) if isinstance(st, dict) else []
            if isinstance(fav, list):
                self.favorites = [str(x) for x in fav]
            else:
                self.favorites = []
        except Exception:
            # legacy fallback (list)
            data = safe_read_json(self.fav_path, default=[])
            if isinstance(data, list):
                self.favorites = [str(x) for x in data]
            else:
                self.favorites = []


    def save_favorites(self):
        # persist using shared state format (dict) to keep the background service in sync
        try:
            st = fav_state.load_state(self.data_dir)
            if not isinstance(st, dict):
                st = {}
            st["favorites"] = [str(x) for x in (self.favorites or [])]
            fav_state.save_state(self.data_dir, st)
        except Exception:
            # fallback: old format
            safe_write_json(self.fav_path, self.favorites)

    def _load_prefs_cache(self):
        self.prefs = safe_read_json(self.prefs_path, default={}) or {}
        if not isinstance(self.prefs, dict):
            self.prefs = {}
        self.cache = safe_read_json(self.cache_path, default={}) or {}
        if not isinstance(self.cache, dict):
            self.cache = {}

    def _save_prefs(self):
        if isinstance(self.prefs, dict):
            safe_write_json(self.prefs_path, self.prefs)

    def _save_cache(self):
        if isinstance(self.cache, dict):
            safe_write_json(self.cache_path, self.cache)

    def _prefs_get(self, key: str, default=None):
        try:
            return self.prefs.get(key, default)
        except Exception:
            return default

    def _prefs_set(self, key: str, value):
        try:
            self.prefs[key] = value
            self._save_prefs()
        except Exception:
            pass

    def _cache_get(self, key: str, ttl_seconds: int | None = None):
        try:
            item = self.cache.get(key)
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
            age = (datetime.utcnow() - dt).total_seconds()
            if age > ttl_seconds:
                return None
            return val
        except Exception:
            return None

    def _cache_set(self, key: str, value):
        try:
            self.cache[key] = {"ts": datetime.utcnow().isoformat(), "value": value}
            self._save_cache()
        except Exception:
            pass

    def _cache_clear(self):
        try:
            self.cache = {}
            self._save_cache()
        except Exception:
            pass

    def _set_initial_home_tab(self, *_):
        # abre direto no Dashboard
        self.select_home_tab("tab_dashboard")


    def _apply_settings_to_ui(self):
        try:
            scr = self.root.get_screen("settings")
        except Exception:
            return
        try:
            scr.ids.set_notify_boosted.active = bool(self._prefs_get("notify_boosted", True))
            scr.ids.set_notify_boss_high.active = bool(self._prefs_get("notify_boss_high", True))
            scr.ids.set_repo_url.text = str(self._prefs_get("repo_url", "") or "")
        except Exception:
            pass

        # Background monitor (shared state file)
        try:
            st = fav_state.load_state(self.data_dir)
            scr.ids.set_bg_monitor.active = bool(st.get("monitoring", False))
            scr.ids.set_bg_notify_online.active = bool(st.get("notify_fav_online", True))
            scr.ids.set_bg_notify_level.active = bool(st.get("notify_fav_level", True))
            scr.ids.set_bg_notify_death.active = bool(st.get("notify_fav_death", True))
            scr.ids.set_bg_interval.text = str(int(st.get("interval_seconds", 60) or 60))
        except Exception:
            pass


    def settings_save(self):
        try:
            scr = self.root.get_screen("settings")
            self._prefs_set("notify_boosted", bool(scr.ids.set_notify_boosted.active))
            self._prefs_set("notify_boss_high", bool(scr.ids.set_notify_boss_high.active))
            self._prefs_set("repo_url", (scr.ids.set_repo_url.text or "").strip())

            # Background monitor settings (favorites online/death/level)
            self._sync_bg_monitor_state_from_ui()

            scr.ids.set_status.text = "Salvo."
            self.toast("Configurações salvas.")
        except Exception:
            self.toast("Não consegui salvar as configurações.")

    def _parse_github_repo(self, url: str):
        url = (url or "").strip()
        m = re.search(r"github\.com/([^/]+)/([^/#?]+)", url, re.I)
        if not m:
            return None
        owner = m.group(1)
        repo = m.group(2).replace(".git", "")
        return owner, repo

    def settings_open_releases(self):
        url = str(self._prefs_get("repo_url", "") or "").strip()
        if not url:
            self.toast("Defina a URL do repo nas configurações.")
            return
        if "github.com" in url.lower() and "/releases" not in url.lower():
            url = url.rstrip("/") + "/releases"
        webbrowser.open(url)

    def settings_check_updates(self):
        scr = self.root.get_screen("settings")
        url = str(self._prefs_get("repo_url", "") or "").strip()
        parsed = self._parse_github_repo(url)
        if not parsed:
            self.toast("URL do GitHub inválida.")
            return

        owner, repo = parsed
        scr.ids.set_status.text = "Checando..."
        api = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

        def run():
            try:
                r = requests.get(api, timeout=15, headers={"User-Agent": "TibiaToolsApp"})
                if r.status_code != 200:
                    raise ValueError(f"HTTP {r.status_code}")
                j = r.json()
                tag = str(j.get("tag_name") or j.get("name") or "").strip() or "?"
                html_url = str(j.get("html_url") or (url.rstrip("/") + "/releases") )
                last_seen = str(self._prefs_get("last_release", "") or "")
                Clock.schedule_once(lambda *_: self._updates_done(tag, html_url, last_seen), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(scr.ids.set_status, "text", f"Erro ao checar: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()

    def _updates_done(self, tag: str, html_url: str, last_seen: str):
        scr = self.root.get_screen("settings")
        self._prefs_set("last_release", tag)
        if last_seen and tag != last_seen:
            scr.ids.set_status.text = f"Nova versão: {tag}"
            self._show_text_dialog("Update disponível", f"Nova versão encontrada: {tag}\n\nAbrir releases?")
            try:
                webbrowser.open(html_url)
            except Exception:
                pass
        else:
            scr.ids.set_status.text = f"Última versão: {tag}"
            self.toast("Sem updates (ou já visto).")

    def settings_clear_cache(self):
        self._cache_clear()
        try:
            self.root.get_screen("settings").ids.set_status.text = "Cache limpo."
        except Exception:
            pass
        self.toast("Cache limpo.")

    def toast(self, message: str):
        """Mostra uma mensagem rápida sem derrubar o app."""
        try:
            from kivymd.uix.snackbar import Snackbar  # type: ignore
            try:
                Snackbar(text=message).open()
                return
            except Exception:
                pass
        except Exception:
            pass

        try:
            from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText  # type: ignore
            sb = MDSnackbar(MDSnackbarText(text=message))
            sb.open()
            return
        except Exception:
            pass

        print(f"[TOAST] {message}")

    def _show_text_dialog(self, title: str, text: str):
        """Abre um dialog simples para mostrar textos longos (sem cortar com '...')."""
        try:
            if getattr(self, "_active_dialog", None):
                self._active_dialog.dismiss()
        except Exception:
            pass

        dialog = MDDialog(
            title=title,
            text=text,
            buttons=[
                MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss()),
            ],
        )
        self._active_dialog = dialog
        dialog.open()

    def _shorten_death_reason(self, reason: str) -> str:
        """Deixa o texto da morte mais legível no card (o completo pode abrir no dialog)."""
        r = (reason or "").strip()
        if not r:
            return ""

        # Tenta reduzir listas enormes de killers: "... by A, B, C and D"
        low = r.lower()
        if " by " in low:
            idx = low.find(" by ")
            prefix = r[:idx].strip().rstrip(".")
            killers = r[idx + 4 :].strip().rstrip(".")

            # normaliza separadores
            killers_norm = killers.replace(" and ", ", ")
            parts = [p.strip() for p in killers_norm.split(",") if p.strip()]
            if parts:
                first = parts[0]
                extra = len(parts) - 1

                # compacta "Slain/Died at Level X" -> "Slain"/"Died"
                event = prefix
                if prefix.lower().startswith("slain"):
                    event = "Slain"
                elif prefix.lower().startswith("died"):
                    event = "Died"

                return f"{event} by {first}" + (f" +{extra}" if extra > 0 else "")

        # fallback: corta com bom senso (sem '...')
        return r[:80] + ("" if len(r) <= 80 else "…")

    def _char_set_loading(self, home, name: str):
        if not hasattr(home, "ids"):
            return

        # Layout novo (cards + listas)
        if "char_title" in home.ids and "char_details_list" in home.ids and "char_deaths_list" in home.ids:
            home.ids.char_title.text = name
            home.ids.char_badge.text = ""
            home.ids.char_details_list.clear_widgets()

            item = OneLineIconListItem(text="Buscando informações...")
            item.add_widget(IconLeftWidget(icon="cloud-search"))
            home.ids.char_details_list.add_widget(item)

            home.ids.char_deaths_list.clear_widgets()
            ditem = OneLineIconListItem(text="Aguardando...")
            ditem.add_widget(IconLeftWidget(icon="skull-outline"))
            home.ids.char_deaths_list.add_widget(ditem)
            return

        # Fallback antigo
        if "char_status" in home.ids:
            home.ids.char_status.text = "Buscando..."

    def _char_show_error(self, home, message: str):
        if not hasattr(home, "ids"):
            return

        if "char_title" in home.ids and "char_details_list" in home.ids and "char_deaths_list" in home.ids:
            home.ids.char_title.text = "Erro"
            home.ids.char_badge.text = ""
            home.ids.char_details_list.clear_widgets()

            item = OneLineIconListItem(text=message)
            item.add_widget(IconLeftWidget(icon="alert-circle-outline"))
            home.ids.char_details_list.add_widget(item)

            home.ids.char_deaths_list.clear_widgets()
            ditem = OneLineIconListItem(text="—")
            ditem.add_widget(IconLeftWidget(icon="skull-outline"))
            home.ids.char_deaths_list.add_widget(ditem)
            return

        if "char_status" in home.ids:
            home.ids.char_status.text = message

    def _char_show_result(self, home, payload: dict):
        status = str(payload.get("status", "N/A"))
        title = str(payload.get("title", ""))
        voc = str(payload.get("voc", "N/A"))
        level = str(payload.get("level", "N/A"))
        world = str(payload.get("world", "N/A"))
        guild_line = str(payload.get("guild_line", "Guild: N/A"))
        house_line = str(payload.get("house_line", "Houses: N/A"))
        guild = payload.get("guild") or {}
        houses = payload.get("houses") or []
        deaths = payload.get("deaths", [])

        try:
            home._last_char_payload = payload
        except Exception:
            pass
        try:
            if title:
                self._prefs_set("last_char", title)
        except Exception:
            pass
        try:
            self.dashboard_refresh()
        except Exception:
            pass

        st = status.strip().lower()
        if st == "online":
            badge = "[b][color=#2ecc71]ONLINE[/color][/b]"
            status_icon = "wifi"
        elif st == "offline":
            badge = "[b][color=#e74c3c]OFFLINE[/color][/b]"
            status_icon = "wifi-off"
        else:
            badge = "[b][color=#e74c3c]OFFLINE[/color][/b]"
            status_icon = "help-circle-outline"

        # Layout novo (cards + listas)
        if hasattr(home, "ids") and "char_title" in home.ids and "char_details_list" in home.ids and "char_deaths_list" in home.ids:
            home.ids.char_title.text = title or "Resultado"
            home.ids.char_badge.text = badge

            dl = home.ids.char_details_list
            dl.clear_widgets()

            def add_one(text: str, icon: str, dialog_title: str = "", dialog_text: str = ""):
                item = OneLineIconListItem(text=text)
                item.add_widget(IconLeftWidget(icon=icon))
                if dialog_text:
                    item.bind(on_release=lambda *_: self._show_text_dialog(dialog_title or "Detalhes", dialog_text))
                dl.add_widget(item)

            def add_two(text: str, secondary: str, icon: str, dialog_title: str = "", dialog_text: str = ""):
                item = TwoLineIconListItem(text=text, secondary_text=secondary or " ")
                item.add_widget(IconLeftWidget(icon=icon))
                if dialog_text:
                    item.bind(on_release=lambda *_: self._show_text_dialog(dialog_title or "Detalhes", dialog_text))
                dl.add_widget(item)

            # Usuário pediu para mostrar apenas ONLINE/OFFLINE (sem "Status:")
            add_one((st if st in ("online", "offline") else "offline").capitalize(), status_icon)
            add_one(f"Vocation: {voc}", "account")
            add_one(f"Level: {level}", "signal")
            add_one(f"World: {world}", "earth")

            # Guild (evita cortar demais; toque para ver completo)
            gname = str(guild.get("name") or "").strip() if isinstance(guild, dict) else ""
            grank = str(guild.get("rank") or "").strip() if isinstance(guild, dict) else ""
            if gname:
                full = f"{gname}{(' (' + grank + ')') if grank else ''}".strip()
                if grank:
                    add_two(f"Guild: {gname}", grank, "account-group", "Guild", full)
                else:
                    add_one(f"Guild: {gname}", "account-group", "Guild", full)
            else:
                add_one(guild_line, "account-group")

            # Houses (se for mais de 1, mostra quantidade e abre dialog com a lista)
            houses_list = [str(x).strip() for x in houses if str(x).strip()] if isinstance(houses, list) else []
            if not houses_list:
                add_one("Houses: Nenhuma", "home")
            elif len(houses_list) == 1:
                add_one(f"Houses: {houses_list[0]}", "home", "Houses", houses_list[0])
            else:
                full_h = "\n".join(houses_list)
                add_two("Houses", f"{len(houses_list)} casas", "home", "Houses", full_h)

            dlist = home.ids.char_deaths_list
            dlist.clear_widgets()

            deaths_list = [d for d in deaths if isinstance(d, dict)] if isinstance(deaths, list) else []
            for d in deaths_list[:6]:
                time_s = str(d.get("time") or d.get("date") or "").strip()
                lvl_s = str(d.get("level") or "").strip()
                xp_s = str(d.get("exp_lost") or d.get("xp_lost") or "").strip()
                reason_s = str(d.get("reason") or d.get("description") or "").strip()
                if not reason_s:
                    continue

                meta = time_s
                if lvl_s:
                    meta = (meta + f" • lvl {lvl_s}").strip(" •")
                if xp_s:
                    meta = (meta + f" • xp {xp_s}").strip(" •")

                short_reason = self._shorten_death_reason(reason_s)
                it = TwoLineIconListItem(text=short_reason or reason_s, secondary_text=meta or " ")
                it.add_widget(IconLeftWidget(icon="skull"))
                it.bind(on_release=lambda *_ , rr=reason_s, mm=meta: self._show_text_dialog("Morte", f"{rr}\n\n{mm}".strip()))
                dlist.add_widget(it)

            if len(dlist.children) == 0:
                ditem = OneLineIconListItem(text="Sem mortes recentes (ou sem dados).")
                ditem.add_widget(IconLeftWidget(icon="skull-outline"))
                dlist.add_widget(ditem)
            return

        # Fallback antigo (se ainda existir)
        if "char_status" in home.ids:
            home.ids.char_status.text = (
                f"Status: {status}\n"
                f"Vocation: {voc}\n"
                f"Level: {level}\n"
                f"World: {world}\n"
                f"{guild_line}\n"
                f"{house_line}"
            )


    # --------------------
    # Char tab
    # --------------------
    def search_character(self):
        home = self.root.get_screen("home")
        name = (home.ids.char_name.text or "").strip()
        if not name:
            self.toast("Digite o nome do char.")
            return

        self._char_set_loading(home, name)
        home.char_last_url = ""

        def worker():
            try:
                data = fetch_character_tibiadata(name)
                if not data:
                    raise ValueError("Sem resposta da API.")
                character_wrapper = data.get("character", {})
                character = character_wrapper.get("character", character_wrapper) if isinstance(character_wrapper, dict) else {}
                url = f"https://www.tibia.com/community/?subtopic=characters&name={name.replace(' ', '+')}"
                title = str(character.get("name") or name)

                voc = character.get("vocation", "N/A")
                level = character.get("level", "N/A")
                world = character.get("world", "N/A")

                # Status (sem "unknown")
                # A /v4/character às vezes atrasa; o mais confiável é o status na página do tibia.com.
                status_raw = str(character.get("status") or "").strip().lower()

                # 1) tenta tibia.com (não depende de world)
                online_web = is_character_online_tibia_com(name, world or "")
                if online_web is True:
                    status = "online"
                elif online_web is False:
                    status = "offline"
                else:
                    # 2) fallback TibiaData
                    online_td = (
                        is_character_online_tibiadata(name, world)
                        if world and str(world).strip().upper() != "N/A"
                        else None
                    )
                    if online_td is True:
                        status = "online"
                    else:
                        status = "online" if status_raw == "online" else "offline"

                guild = character.get("guild") or {}
                guild_name = ""
                guild_rank = ""
                if isinstance(guild, dict) and guild.get("name"):
                    guild_name = str(guild.get("name") or "").strip()
                    guild_rank = str(guild.get("rank") or guild.get("title") or "").strip()

                guild_line = (
                    f"Guild: {guild_name}{(' (' + guild_rank + ')') if guild_rank else ''}"
                    if guild_name
                    else "Guild: N/A"
                )

                houses = character.get("houses") or []
                houses_list = []
                if isinstance(houses, list):
                    for h in houses:
                        if isinstance(h, dict):
                            hn = str(h.get("name") or h.get("house") or "").strip()
                            ht = str(h.get("town") or "").strip()
                            if hn and ht:
                                houses_list.append(f"{hn} ({ht})")
                            elif hn:
                                houses_list.append(hn)
                        elif isinstance(h, str) and h.strip():
                            houses_list.append(h.strip())

                if houses_list:
                    if len(houses_list) == 1:
                        house_line = f"Houses: {houses_list[0]}"
                    else:
                        house_line = f"Houses: {len(houses_list)} (toque para ver)"
                else:
                    house_line = "Houses: Nenhuma"

                deaths = (character.get('deaths') or character_wrapper.get('deaths') or data.get('deaths') or [])
                if not isinstance(deaths, list):
                    deaths = []

                # XP lost por morte:
                # 1) tenta GuildStats (fansite) por ordem (mais recente -> mais recente)
                # 2) se falhar/bloquear, calcula a estimativa offline (igual GuildStats: promoted + 7 blessings)
                xp_list = []
                try:
                    xp_list = fetch_guildstats_deaths_xp(title or name)
                except Exception:
                    xp_list = []

                if xp_list:
                    for i, d in enumerate(deaths):
                        if i >= len(xp_list):
                            break
                        if isinstance(d, dict) and not d.get("exp_lost"):
                            d["exp_lost"] = xp_list[i]

                # Fallback robusto: estimativa local (não depende de scraping)
                for d in deaths:
                    if not isinstance(d, dict):
                        continue
                    if d.get("exp_lost"):
                        continue
                    lvl = d.get("level")
                    try:
                        lvl_int = int(lvl)
                    except Exception:
                        continue
                    exp_lost = estimate_death_exp_lost(lvl_int, blessings=7, promoted=True, retro_hardcore=False)
                    if exp_lost:
                        d["exp_lost"] = f"-{exp_lost:,}"

                payload = {
                    "title": title,
                    "status": status,
                    "voc": voc,
                    "level": level,
                    "world": world,
                    "guild": {"name": guild_name, "rank": guild_rank} if guild_name else None,
                    "houses": houses_list,
                    # Mantemos as strings por compat (fallback antigo / outros pontos)
                    "guild_line": guild_line,
                    "house_line": house_line,
                    "deaths": deaths,
                }
                return True, payload, url
            except Exception as e:
                return False, f"Erro: {e}", ""

        def done(res):
            ok, payload_or_msg, url = res
            home.char_last_url = url

            if ok:
                self._char_show_result(home, payload_or_msg)
                # cache do world para a aba Favoritos
                try:
                    w = str((payload_or_msg or {}).get("world") or "").strip()
                    t = str((payload_or_msg or {}).get("title") or "").strip()
                    if w and w.upper() != "N/A" and t:
                        self._cache_set(f"fav_world:{t.lower()}", w)
                except Exception:
                    pass
                self.toast("Char encontrado.")
            else:
                self._char_show_error(home, str(payload_or_msg))

        def run():
            res = worker()
            Clock.schedule_once(lambda *_: done(res), 0)

        threading.Thread(target=run, daemon=True).start()

    def open_last_in_browser(self):
        home = self.root.get_screen("home")
        url = getattr(home, "char_last_url", "") or ""
        if not url:
            self.toast("Sem link ainda. Faça uma busca primeiro.")
            return
        webbrowser.open(url)

    def add_current_to_favorites(self):
        home = self.root.get_screen("home")
        name = (home.ids.char_name.text or "").strip()
        if not name:
            self.toast("Digite o nome do char.")
            return
        if name not in self.favorites:
            self.favorites.append(name)
            self.favorites.sort(key=lambda s: s.lower())
            self.save_favorites()
            self.refresh_favorites_list()
            self.toast("Adicionado aos favoritos.")
        else:
            self.toast("Já está nos favoritos.")

    # --------------------
    # Favorites tab
    # --------------------
    def refresh_favorites_list(self, silent: bool = False, force: bool = False):
        home = self.root.get_screen("home")
        container = home.ids.fav_list
        container.clear_widgets()

        # Each refresh spawns a new status job. Older jobs stop automatically.
        self._fav_status_job_id += 1
        job_id = self._fav_status_job_id
        self._fav_items = {}

        if not self.favorites:
            item = OneLineIconListItem(text="Sem favoritos. Adicione no Char.")
            item.add_widget(IconLeftWidget(icon="star-outline"))
            container.add_widget(item)
            return

        # Render quickly with cached status (if available), then refresh in background.
        names_to_check: list[str] = []
        names = list(self.favorites)
        for name in names:
            state = None if force else self._get_cached_fav_status(name)
            secondary, color = self._fav_status_presentation(state)

            item = TwoLineIconListItem(text=name, secondary_text=secondary)
            item.add_widget(IconLeftWidget(icon="account"))
            item.secondary_theme_text_color = "Custom"
            item.secondary_text_color = color
            item.bind(on_release=lambda _item, n=name: self._fav_actions(n, _item))

            self._fav_items[name.strip().lower()] = item
            container.add_widget(item)

            if force or state is None or self._fav_status_needs_refresh(name, ttl_seconds=45):
                names_to_check.append(name)

        if not silent and force:
            try:
                Snackbar(text="Atualizando favoritos...").open()
            except Exception:
                pass

        if names_to_check:
            threading.Thread(
                target=self._refresh_fav_statuses_worker,
                args=(names_to_check, job_id),
                daemon=True,
            ).start()

    def _get_cached_fav_status(self, name: str) -> Optional[str]:
        key_clean = (name or "").strip().lower()
        if not key_clean:
            return None

        # 1) cache em memória (não expira enquanto o app está aberto)
        try:
            if key_clean in getattr(self, "_fav_status_cache", {}):
                return self._fav_status_cache.get(key_clean)
        except Exception:
            pass

        # 2) cache persistente (TTL moderado)
        cached = self._cache_get(f"fav_status:{key_clean}", ttl_seconds=120)  # 2 min
        if isinstance(cached, str):
            return cached
        return None

    def _fav_status_needs_refresh(self, name: str, ttl_seconds: int = 45) -> bool:
        """Decide se vale atualizar o status novamente.

        Usamos o timestamp do cache persistente (self.cache), não o cache em memória.
        """
        try:
            key_clean = (name or "").strip().lower()
            if not key_clean:
                return True
            item = self.cache.get(f"fav_status:{key_clean}")
            if not isinstance(item, dict):
                return True
            ts = item.get("ts")
            if not ts:
                return True
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                return True
            age = (datetime.utcnow() - dt).total_seconds()
            return age > ttl_seconds
        except Exception:
            return True

    def _get_cached_fav_world(self, name: str) -> Optional[str]:
        key_clean = (name or "").strip().lower()
        if not key_clean:
            return None

        try:
            if key_clean in getattr(self, "_fav_world_cache", {}):
                w = self._fav_world_cache.get(key_clean)
                return str(w).strip() if w else None
        except Exception:
            pass

        cached = self._cache_get(f"fav_world:{key_clean}", ttl_seconds=30 * 24 * 3600)  # 30 dias
        if isinstance(cached, str) and cached.strip():
            try:
                self._fav_world_cache[key_clean] = cached.strip()
            except Exception:
                pass
            return cached.strip()
        return None

    def _set_cached_fav_world(self, name: str, world: str) -> None:
        key_clean = (name or "").strip().lower()
        w = (world or "").strip()
        if not key_clean or not w:
            return
        try:
            self._fav_world_cache[key_clean] = w
        except Exception:
            pass
        try:
            self._cache_set(f"fav_world:{key_clean}", w)
        except Exception:
            pass

    def _fetch_character_world(self, name: str) -> Optional[str]:
        """Busca o world do char via TibiaData e cacheia."""
        try:
            data = fetch_character_tibiadata(name, timeout=12)
            cw = data.get("character", {}) if isinstance(data, dict) else {}
            ch = cw.get("character", cw) if isinstance(cw, dict) else {}
            world = str((ch or {}).get("world") or "").strip()
            if world and world.upper() != "N/A":
                self._set_cached_fav_world(name, world)
                return world
        except Exception:
            pass
        return None

    def _fetch_world_online_players(self, world: str, timeout: int = 12) -> Optional[set]:
        """Retorna um set (lowercase) com os nomes online no world (TibiaData /v4/world/{world})."""
        try:
            safe_world = requests.utils.quote(str(world).strip())
            url = f"https://api.tibiadata.com/v4/world/{safe_world}"
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "TibiaToolsApp"})
            r.raise_for_status()
            data = r.json() if r.text else {}
            wb = (data or {}).get("world", {}) if isinstance(data, dict) else {}
            players = None
            if isinstance(wb, dict):
                players = wb.get("online_players") or wb.get("players_online") or wb.get("players")
                if isinstance(players, dict):
                    players = players.get("online_players") or players.get("players") or players.get("data")
            if not isinstance(players, list):
                return set()
            out = set()
            for p in players:
                pname = None
                if isinstance(p, dict):
                    pname = p.get("name") or p.get("player_name")
                else:
                    pname = p
                if isinstance(pname, str) and pname.strip():
                    out.add(pname.strip().lower())
            return out
        except Exception:
            return None
    def _fav_status_presentation(self, state) -> tuple[str, tuple]:
        s = str(state).strip().lower() if state is not None else ""
        if s == "online" or state is True:
            return "Online", (0.2, 0.75, 0.35, 1)
        if s == "offline" or state is False:
            return "Offline", (0.95, 0.3, 0.3, 1)
        return "Atualizando...", (0.7, 0.7, 0.7, 1)


    def _set_fav_item_status(self, name: str, state) -> None:
        """Atualiza o status (Online/Offline) no item da lista de favoritos e no cache.

        Este método é chamado via Clock no thread principal.
        """
        try:
            key = (name or "").strip().lower()
            if not key:
                return

            # atualiza cache em memória + cache persistente simples
            self._fav_status_cache[key] = state
            try:
                self._cache_set(f"fav_status:{key}", state)
            except Exception:
                pass

            item = self._fav_items.get(key)
            if not item:
                return

            label, color = self._fav_status_presentation(state)
            item.secondary_text = label
            item.secondary_text_color = color
        except Exception as e:
            print(f"[FAV] Erro ao atualizar status de '{name}': {e}")

    def _dismiss_fav_menu(self) -> None:
        try:
            if getattr(self, "_fav_menu", None):
                self._fav_menu.dismiss()
        except Exception:
            pass
        self._fav_menu = None

    def _open_fav_in_app(self, name: str) -> None:
        """Abre o char no app (aba Char) e executa a busca."""
        self._dismiss_fav_menu()
        try:
            home = self.root.get_screen("home")
            # troca para a aba Char
            nav = home.ids.get("bottom_nav")
            if nav is not None:
                try:
                    if hasattr(nav, "switch_tab"):
                        nav.switch_tab("tab_char")
                    else:
                        nav.current = "tab_char"
                except Exception:
                    pass

            # preenche o nome e busca
            if "char_name" in home.ids:
                home.ids.char_name.text = name
            Clock.schedule_once(lambda dt: self.search_character(), 0.05)
        except Exception as e:
            print(f"[FAV] Erro ao abrir no app: {e}")

    def _open_fav_on_site(self, name: str) -> None:
        """Abre o char no site oficial do Tibia."""
        self._dismiss_fav_menu()
        try:
            url = (
                "https://www.tibia.com/community/?subtopic=characters&name="
                + urllib.parse.quote_plus(name)
            )
            webbrowser.open(url)
        except Exception as e:
            print(f"[FAV] Erro ao abrir no site: {e}")

    def _remove_favorite(self, name: str) -> None:
        """Remove o char dos favoritos."""
        self._dismiss_fav_menu()
        try:
            key = (name or "").strip().lower()
            if not key:
                return

            before = len(self.favorites)
            self.favorites = [n for n in self.favorites if (n or "").strip().lower() != key]

            if len(self.favorites) != before:
                self.save_favorites()
                # limpa cache relacionado (opcional)
                try:
                    self._cache_set(f"fav_status:{key}", None)
                except Exception:
                    pass
                self._fav_status_cache.pop(key, None)

                self.refresh_favorites_list()
                try:
                    Snackbar(text="Removido dos favoritos.").open()
                except Exception:
                    pass
        except Exception as e:
            print(f"[FAV] Erro ao remover favorito: {e}")

    def _refresh_fav_statuses_worker(self, names: List[str], job_id: int):
        """Atualiza o status dos favoritos em background, minimizando chamadas e falsos OFF.

        Em vez de checar 1 a 1 (muito request e pode dar falso OFF),
        agrupamos por world e consultamos o /v4/world/{world} (lista de online players).
        """
        try:
            # 1) resolve world de cada char (cache -> TibiaData /v4/character)
            name_to_world = {}
            unknown = []

            for n in names:
                if job_id != self._fav_status_job_id:
                    return
                w = self._get_cached_fav_world(n)
                if not w:
                    w = self._fetch_character_world(n)
                if w:
                    name_to_world[n] = w
                else:
                    unknown.append(n)

            # 2) agrupa por world
            by_world = {}
            for n, w in name_to_world.items():
                by_world.setdefault(w, []).append(n)

            # 3) para cada world, pega o set de online players 1x
            for w, ns in by_world.items():
                if job_id != self._fav_status_job_id:
                    return
                online_set = self._fetch_world_online_players(w, timeout=12)
                if online_set is None:
                    online_set = set()

                for n in ns:
                    if job_id != self._fav_status_job_id:
                        return
                    is_on = (n or "").strip().lower() in online_set
                    st = "online" if is_on else "offline"
                    Clock.schedule_once(lambda dt, nn=n, stt=st: self._set_fav_item_status(nn, stt), 0)

            # 4) fallback (se não conseguimos world): tenta método antigo (tibia.com / endpoint do char)
            for n in unknown:
                if job_id != self._fav_status_job_id:
                    return
                st = self._fetch_character_online_state(n)
                if st is None:
                    # mantém último estado se existir, senão offline
                    k = (n or "").strip().lower()
                    st = getattr(self, "_fav_status_cache", {}).get(k) or "offline"
                Clock.schedule_once(lambda dt, nn=n, stt=st: self._set_fav_item_status(nn, stt), 0)
        finally:
            Clock.schedule_once(lambda _dt: setattr(self, "_fav_refreshing", False), 0)

    def _fetch_character_online_state(self, name: str) -> Optional[str]:
        """Fallback (1 a 1) para descobrir online/offline.

        Usado apenas quando não conseguimos resolver o world para usar o /v4/world/{world}.
        """
        try:
            tc = is_character_online_tibia_com(name, world="", timeout=12)
            if tc is not None:
                return "online" if tc else "offline"
        except Exception:
            pass

        try:
            td = is_character_online_tibiadata(name, world=None, timeout=12)
            if td is not None:
                return "online" if td else "offline"
        except Exception:
            pass

        return None

    def _fav_actions(self, name: str, caller=None):
        """Menu de ações para um favorito.

        Em algumas versões do KivyMD, usar MDDialog(type="simple", items=[OneLineListItem...])
        pode causar crash (KeyError: _left_container). Para evitar isso, usamos MDDropdownMenu.
        """
        try:
            if caller is None:
                caller = self.root

            # Fecha menu anterior, se existir
            if getattr(self, "_fav_menu", None):
                try:
                    self._fav_menu.dismiss()
                except Exception:
                    pass
                self._fav_menu = None

            def _wrap(fn):
                def _inner(*_args):
                    self._dismiss_fav_menu()
                    try:
                        fn()
                    except Exception as e:
                        self.show_snackbar(f"Erro: {e}")
                return _inner

            menu_items = [
                {
                    "viewclass": "OneLineListItem",
                    "text": "Ver no app",
                    "height": dp(48),
                    "on_release": _wrap(lambda: self._open_fav_in_app(name)),
                },
                {
                    "viewclass": "OneLineListItem",
                    "text": "Abrir no site",
                    "height": dp(48),
                    "on_release": _wrap(lambda: self._open_fav_on_site(name)),
                },
                {
                    "viewclass": "OneLineListItem",
                    "text": "Copiar nome",
                    "height": dp(48),
                    "on_release": _wrap(lambda: self._copy_fav_name(name)),
                },
                {
                    "viewclass": "OneLineListItem",
                    "text": "Remover dos favoritos",
                    "height": dp(48),
                    "on_release": _wrap(lambda: self._remove_favorite(name)),
                },
            ]

            self._fav_menu = MDDropdownMenu(
                caller=caller,
                items=menu_items,
                width_mult=4,
                max_height=dp(240),
            )
            self._fav_menu.open()
        except Exception as e:
            self.show_snackbar(f"Erro ao abrir opções: {e}")

    def calc_shared_xp(self):
        home = self.root.get_screen("home")
        try:
            level = int((home.ids.share_level.text or "0").strip())
        except ValueError:
            self.toast("Digite um level válido.")
            return

        if level <= 0:
            self.toast("Digite um level maior que 0.")
            return

        min_level = int(math.ceil(level * 2.0 / 3.0))
        max_level = int(math.floor(level * 3.0 / 2.0))

        home.ids.share_result.text = (
            f"Seu level: {level}\n"
            f"Pode sharear com: {min_level} até {max_level}"
        )

    # --------------------
    # Stamina (offline)
    # --------------------
    def stamina_calculate(self):
        """Calcula quanto tempo ficar offline para atingir a stamina desejada.

        Regra usada:
        - a regeneração começa 10 minutos após deslogar;
        - até 39:00: 1 min stamina / 3 min offline;
        - de 39:00 a 42:00: 1 min stamina / 6 min offline.
        """
        scr = self.root.get_screen("stamina")

        try:
            cur_min = parse_hm_text(scr.ids.stam_cur_h.text, scr.ids.stam_cur_m.text)
            tgt_min = parse_hm_text(scr.ids.stam_tgt_h.text, scr.ids.stam_tgt_m.text)
        except Exception as e:
            self.toast(str(e))
            return

        res = compute_offline_regen(cur_min, tgt_min)
        now = datetime.now()

        if res.offline_needed_min <= 0:
            scr.ids.stam_result.text = (
                f"Stamina atual: {format_hm(res.current_min)}\n"
                f"Stamina alvo: {format_hm(res.target_min)}\n\n"
                "Você já está no alvo."
            )
            return

        offline_total = res.offline_needed_min
        offline_h = offline_total // 60
        offline_m = offline_total % 60

        regen_only = res.regen_offline_only_min
        regen_h = regen_only // 60
        regen_m = regen_only % 60

        reached_at = now + timedelta(minutes=offline_total)

        scr.ids.stam_result.text = (
            f"Stamina atual: {format_hm(res.current_min)}\n"
            f"Stamina alvo: {format_hm(res.target_min)}\n\n"
            f"Tempo offline necessário: {offline_h}h {offline_m:02d}min\n"
            f"(Regeneração: {regen_h}h {regen_m:02d}min + 10min iniciais)\n\n"
            f"Você terá {format_hm(res.target_min)} em: {reached_at.strftime('%d/%m %H:%M')}\n"
            "(considerando que você desloga agora)"
        )

    # --------------------
    # Bosses (ExevoPan)
    # --------------------

    def _boss_wiki_url(self, boss_name: str) -> str:
        """Gera URL do boss no TibiaWiki (BR)."""
        title = (boss_name or "").strip().replace(" ", "_")
        # index.php?title=... é o formato mais estável do MediaWiki.
        return f"https://tibiawiki.com.br/index.php?title={quote(title)}"

    def _boss_open_prompt(self, boss_name: str) -> None:
        """Pergunta ao usuário se quer abrir a página do boss."""
        boss_name = (boss_name or "").strip()
        if not boss_name:
            return

        def go(*_):
            try:
                webbrowser.open(self._boss_wiki_url(boss_name))
            finally:
                dlg.dismiss()

        dlg = MDDialog(
            title=boss_name,
            text="Quer abrir a página desse boss para ver os detalhes?",
            buttons=[
                MDFlatButton(text="ABRIR", on_release=go),
                MDFlatButton(text="CANCELAR", on_release=lambda *_: dlg.dismiss()),
            ],
        )
        dlg.open()


    def _boss_chance_score(self, chance: str) -> float:
        c = (chance or "").strip().lower()
        if not c:
            return 0.0
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", c)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except Exception:
                return 0.0
        if "no chance" in c or "sem chance" in c:
            return 0.0
        if "unknown" in c or "desconhecido" in c:
            return 0.0
        if "very low" in c:
            return 10.0
        if "low chance" in c or c == "low":
            return 25.0
        if "medium chance" in c or c == "medium":
            return 50.0
        if "high chance" in c or c == "high":
            return 75.0
        return 0.0

    def boss_is_favorite(self, boss_name: str) -> bool:
        favs = self._prefs_get("boss_favorites", []) or []
        if not isinstance(favs, list):
            favs = []
        return (boss_name or "").strip() in favs

    def boss_toggle_favorite(self, boss_name: str) -> bool:
        boss_name = (boss_name or "").strip()
        favs = self._prefs_get("boss_favorites", []) or []
        if not isinstance(favs, list):
            favs = []
        if boss_name in favs:
            favs.remove(boss_name)
            self._prefs_set("boss_favorites", favs)
            return False
        favs.append(boss_name)
        # remove duplicados mantendo ordem
        seen = set()
        out = []
        for x in favs:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        self._prefs_set("boss_favorites", out)
        return True

    def bosses_toggle_fav_only(self):
        cur = bool(self._prefs_get("boss_fav_only", False))
        cur = not cur
        self._prefs_set("boss_fav_only", cur)
        try:
            scr = self.root.get_screen("bosses")
            if "boss_fav_toggle" in scr.ids:
                scr.ids.boss_fav_toggle.icon = "star" if cur else "star-outline"
        except Exception:
            pass
        self.bosses_apply_filters()

    def bosses_apply_filters_debounced(self):
        try:
            if self._bosses_filter_debounce_ev:
                self._bosses_filter_debounce_ev.cancel()
        except Exception:
            pass
        self._bosses_filter_debounce_ev = Clock.schedule_once(lambda *_: self.bosses_apply_filters(), 0.15)

    def open_boss_filter_menu(self):
        scr = self.root.get_screen("bosses")
        caller = scr.ids.get("boss_filter_btn")
        if caller is None:
            return
        options = ["All", "High", "Medium+", "Low+", "No chance", "Unknown"]
        items = [{"text": opt, "on_release": (lambda x=opt: self._set_boss_filter(x))} for opt in options]
        if self._menu_boss_filter:
            self._menu_boss_filter.dismiss()
        self._menu_boss_filter = MDDropdownMenu(caller=caller, items=items, width_mult=4, max_height=dp(320))
        self._menu_boss_filter.open()

    def _set_boss_filter(self, value: str):
        self._prefs_set("boss_filter", value)
        try:
            scr = self.root.get_screen("bosses")
            if "boss_filter_label" in scr.ids:
                scr.ids.boss_filter_label.text = value
        except Exception:
            pass
        if self._menu_boss_filter:
            self._menu_boss_filter.dismiss()
        self.bosses_apply_filters()

    def open_boss_sort_menu(self):
        scr = self.root.get_screen("bosses")
        caller = scr.ids.get("boss_sort_btn")
        if caller is None:
            return
        options = ["Chance", "Name", "Favorites first"]
        items = [{"text": opt, "on_release": (lambda x=opt: self._set_boss_sort(x))} for opt in options]
        if self._menu_boss_sort:
            self._menu_boss_sort.dismiss()
        self._menu_boss_sort = MDDropdownMenu(caller=caller, items=items, width_mult=4, max_height=dp(260))
        self._menu_boss_sort.open()

    def _set_boss_sort(self, value: str):
        self._prefs_set("boss_sort", value)
        try:
            scr = self.root.get_screen("bosses")
            if "boss_sort_label" in scr.ids:
                scr.ids.boss_sort_label.text = value
        except Exception:
            pass
        if self._menu_boss_sort:
            self._menu_boss_sort.dismiss()
        self.bosses_apply_filters()

    def open_boss_favorites(self):
        self.go("boss_favorites")
        self.boss_favorites_refresh()

    def bosses_open_dialog(self, boss_dict):
        try:
            name = str(boss_dict.get("boss") or boss_dict.get("name") or "Boss").strip()
            chance = str(boss_dict.get("chance") or "").strip()
            status = str(boss_dict.get("status") or "").strip()
        except Exception:
            return

        url = self._boss_wiki_url(name)

        def toggle(*_):
            fav = self.boss_toggle_favorite(name)
            self.toast("Favoritado." if fav else "Removido dos favoritos.")
            try:
                dlg.dismiss()
            except Exception:
                pass
            self.bosses_apply_filters()
            self.dashboard_refresh()

        def copy(*_):
            try:
                Clipboard.copy(url)
                self.toast("Link copiado.")
            except Exception:
                self.toast("Não consegui copiar.")
            try:
                dlg.dismiss()
            except Exception:
                pass

        def open_url(*_):
            try:
                webbrowser.open(url)
            except Exception:
                self.toast("Não consegui abrir o navegador.")
            try:
                dlg.dismiss()
            except Exception:
                pass

        star = "REMOVER ⭐" if self.boss_is_favorite(name) else "FAVORITAR ⭐"
        txt = "\n".join([x for x in [f"Chance: {chance}" if chance else "", status] if x]).strip() or " "
        dlg = MDDialog(
            title=name,
            text=txt,
            buttons=[
                MDFlatButton(text=star, on_release=toggle),
                MDFlatButton(text="COPIAR LINK", on_release=copy),
                MDFlatButton(text="ABRIR", on_release=open_url),
                MDFlatButton(text="FECHAR", on_release=lambda *_: dlg.dismiss()),
            ],
        )
        dlg.open()

    def bosses_apply_filters(self):
        scr = self.root.get_screen("bosses")
        bosses = getattr(scr, "bosses_raw", []) or []
        if not isinstance(bosses, list):
            bosses = []

        q = ""
        if "boss_search" in scr.ids:
            q = (scr.ids.boss_search.text or "").strip().lower()

        bf = str(self._prefs_get("boss_filter", "All") or "All")
        bs = str(self._prefs_get("boss_sort", "Chance") or "Chance")
        fav_only = bool(self._prefs_get("boss_fav_only", False))
        favs = self._prefs_get("boss_favorites", []) or []
        if not isinstance(favs, list):
            favs = []

        def match(b: dict) -> bool:
            name = str(b.get("boss") or b.get("name") or "")
            if q and q not in name.lower():
                return False
            if fav_only and name not in favs:
                return False

            chance = str(b.get("chance") or "")
            score = self._boss_chance_score(chance)
            lowc = chance.lower()

            if bf == "High":
                return score >= 70.0
            if bf == "Medium+":
                return score >= 40.0
            if bf == "Low+":
                return score >= 10.0
            if bf == "No chance":
                return ("no chance" in lowc) or ("sem chance" in lowc)
            if bf == "Unknown":
                return score == 0.0 and ("unknown" in lowc or "desconhecido" in lowc or (not chance))
            return True

        filtered = [b for b in bosses if isinstance(b, dict) and match(b)]

        if bs == "Name":
            filtered.sort(key=lambda b: str(b.get("boss") or b.get("name") or "").lower())
        elif bs == "Favorites first":
            def key(b):
                nm = str(b.get("boss") or b.get("name") or "")
                return (0 if nm in favs else 1, -self._boss_chance_score(str(b.get("chance") or "")), nm.lower())
            filtered.sort(key=key)
        else:
            filtered.sort(key=lambda b: self._boss_chance_score(str(b.get("chance") or "")), reverse=True)

        scr.ids.boss_list.clear_widgets()
        scr.ids.boss_status.text = f"Bosses: {len(filtered)} (de {len(bosses)})"

        if not filtered:
            item = OneLineIconListItem(text="Nada encontrado com esses filtros.")
            item.add_widget(IconLeftWidget(icon="magnify"))
            scr.ids.boss_list.add_widget(item)
            return

        for b in filtered[:200]:
            name = str(b.get("boss") or b.get("name") or "Boss")
            chance = str(b.get("chance") or "").strip()
            status = str(b.get("status") or "").strip()
            sec = " • ".join([x for x in [chance, status] if x]) or " "
            item = TwoLineIconListItem(text=name, secondary_text=sec)
            icon = "star" if self.boss_is_favorite(name) else "skull"
            item.add_widget(IconLeftWidget(icon=icon))
            item.bind(on_release=lambda _it, bb=b: self.bosses_open_dialog(bb))
            scr.ids.boss_list.add_widget(item)

    def boss_favorites_refresh(self):
        scr = self.root.get_screen("boss_favorites")
        favs = self._prefs_get("boss_favorites", []) or []
        if not isinstance(favs, list):
            favs = []
        scr.ids.boss_fav_list.clear_widgets()
        if not favs:
            scr.ids.boss_fav_status.text = "Sem favoritos. Favorite bosses na tela Bosses."
            it = OneLineIconListItem(text="Sem favoritos ainda.")
            it.add_widget(IconLeftWidget(icon="star-outline"))
            scr.ids.boss_fav_list.add_widget(it)
            return

        world = str(self._prefs_get("boss_last_world", "") or "")
        cache_key = f"bosses:{world.lower()}" if world else ""
        bosses = self._cache_get(cache_key, ttl_seconds=6 * 3600) if cache_key else None

        scr.ids.boss_fav_status.text = f"Favoritos: {len(favs)}" + (f" • World: {world}" if world else "")
        for name in favs[:200]:
            chance_txt = ""
            if isinstance(bosses, list):
                for b in bosses:
                    if str(b.get("boss") or b.get("name") or "") == name:
                        chance_txt = str(b.get("chance") or "").strip()
                        break
            item = OneLineIconListItem(text=f"{name}{(' ('+chance_txt+')') if chance_txt else ''}")
            item.add_widget(IconLeftWidget(icon="star"))
            item.bind(on_release=lambda _it, n=name: self.bosses_open_dialog({"boss": n, "chance": chance_txt}))
            scr.ids.boss_fav_list.add_widget(item)

    def _bosses_refresh_worlds(self):
        scr = self.root.get_screen("bosses")
        scr.ids.boss_status.text = "Carregando worlds..."

        def worker():
            data = fetch_worlds_tibiadata()
            return sorted([w.get("name") for w in data.get("worlds", {}).get("regular_worlds", []) if w.get("name")])

        def done(worlds):
            scr.ids.boss_status.text = f"Worlds: {len(worlds)}"
            # restaura último world
            try:
                last = str(self._prefs_get("boss_last_world", "") or "").strip()
                if last:
                    scr.ids.world_field.text = last
            except Exception:
                pass
            items = [{"text": w, "on_release": (lambda x=w: self._select_world(x))} for w in worlds[:400]]
            if self._menu_world:
                self._menu_world.dismiss()
            self._menu_world = MDDropdownMenu(caller=scr.ids.world_drop, items=items, width_mult=4, max_height=dp(420))

        def run():
            try:
                worlds = worker()
                Clock.schedule_once(lambda *_: done(worlds), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(scr.ids.boss_status, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()

    def _select_world(self, world: str):
        scr = self.root.get_screen("bosses")
        scr.ids.world_field.text = world
        try:
            self._prefs_set("boss_last_world", world)
        except Exception:
            pass
        if self._menu_world:
            self._menu_world.dismiss()

    def bosses_fetch(self):
        scr = self.root.get_screen("bosses")
        world = (scr.ids.world_field.text or "").strip()
        if not world:
            self.toast("Digite o world.")
            return

        try:
            self._prefs_set("boss_last_world", world)
        except Exception:
            pass
        scr.ids.boss_status.text = "Buscando bosses..."
        scr.ids.boss_list.clear_widgets()
        for _ in range(6):
            it = OneLineIconListItem(text="Carregando...")
            it.add_widget(IconLeftWidget(icon="cloud-download"))
            scr.ids.boss_list.add_widget(it)


        def run():
            try:
                bosses = fetch_exevopan_bosses(world)
                Clock.schedule_once(lambda *_: self._bosses_done(bosses), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(scr.ids.boss_status, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()

    def _bosses_done(self, bosses):
        scr = self.root.get_screen("bosses")
        if not bosses:
            scr.ids.boss_list.clear_widgets()
            scr.ids.boss_status.text = "Nada encontrado (ou ExevoPan indisponível)."
            return

        # guarda raw para filtros e salva cache (TTL 6h)
        scr.bosses_raw = bosses
        world = (scr.ids.world_field.text or "").strip()
        if world:
            self._cache_set(f"bosses:{world.lower()}", bosses)

        # aplica prefs e UI labels
        try:
            if "boss_filter_label" in scr.ids:
                scr.ids.boss_filter_label.text = str(self._prefs_get("boss_filter", "All") or "All")
            if "boss_sort_label" in scr.ids:
                scr.ids.boss_sort_label.text = str(self._prefs_get("boss_sort", "Chance") or "Chance")
            if "boss_fav_toggle" in scr.ids:
                scr.ids.boss_fav_toggle.icon = "star" if bool(self._prefs_get("boss_fav_only", False)) else "star-outline"
        except Exception:
            pass

        self.bosses_apply_filters()
        self.dashboard_refresh()

    # --------------------
    # Boosted

    # --------------------
    def update_boosted(self, silent: bool = False):
        scr = self.root.get_screen("boosted")
        if not silent:
            scr.ids.boost_status.text = "Atualizando..."
        else:
            # não suja o status se for atualização usada pelo dashboard
            if not (scr.ids.boost_status.text or "").strip():
                scr.ids.boost_status.text = "Atualizando..."

        def run():
            try:
                data = fetch_boosted()
                Clock.schedule_once(lambda *_: self._boosted_done(data, silent=silent), 0)
            except Exception as e:
                if not silent:
                    Clock.schedule_once(lambda *_: setattr(scr.ids.boost_status, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()

    def _boosted_done(self, data, silent: bool = False):
        scr = self.root.get_screen("boosted")
        if not data:
            if not silent:
                scr.ids.boost_status.text = "Falha ao buscar Boosted."
            return
        scr.ids.boost_status.text = "OK"
        scr.ids.boost_creature.text = data.get("creature", "N/A")
        scr.ids.boost_boss.text = data.get("boss", "N/A")

        # cache + histórico (7 dias)
        try:
            self._cache_set("boosted", data)
        except Exception:
            pass

        try:
            hist = self._prefs_get("boosted_history", []) or []
            if not isinstance(hist, list):
                hist = []
            today = datetime.utcnow().date().isoformat()
            entry = {"date": today, "creature": data.get("creature"), "boss": data.get("boss")}
            # remove do mesmo dia e reinsere no topo
            hist = [h for h in hist if isinstance(h, dict) and h.get("date") != today]
            hist.insert(0, entry)
            hist = hist[:7]
            self._prefs_set("boosted_history", hist)
        except Exception:
            pass

        # UI: histórico
        try:
            if "boost_hist_list" in scr.ids:
                scr.ids.boost_hist_list.clear_widgets()
                hist = self._prefs_get("boosted_history", []) or []
                if isinstance(hist, list) and hist:
                    for h in hist:
                        if not isinstance(h, dict):
                            continue
                        dt = str(h.get("date") or "")
                        cr = str(h.get("creature") or "-")
                        bb = str(h.get("boss") or "-")
                        it = TwoLineIconListItem(text=f"{dt}", secondary_text=f"{cr} • {bb}")
                        it.add_widget(IconLeftWidget(icon="history"))
                        scr.ids.boost_hist_list.add_widget(it)
        except Exception:
            pass

        # notificação 1x ao dia se mudou
        try:
            if bool(self._prefs_get("notify_boosted", True)):
                today = datetime.utcnow().date().isoformat()
                last_date = str(self._prefs_get("boosted_notified_date", "") or "")
                last_seen = self._prefs_get("boosted_last_seen", {}) or {}
                changed = (isinstance(last_seen, dict) and (last_seen.get("creature") != data.get("creature") or last_seen.get("boss") != data.get("boss")))
                if changed and last_date != today:
                    self._prefs_set("boosted_notified_date", today)
                    self._send_notification("Boosted mudou", f"{data.get('creature','-')} • {data.get('boss','-')}")
                self._prefs_set("boosted_last_seen", data)
        except Exception:
            pass

        # atualiza dashboard
        try:
            self.dashboard_refresh()
        except Exception:
            pass

    # --------------------
    # Training (Exercise)
    # --------------------
    def _ensure_training_menus(self):
        scr = self.root.get_screen("training")

        if self._menu_skill is None:
            skills = ["Sword", "Axe", "Club", "Distance", "Fist Fighting", "Shielding", "Magic Level"]
            self._menu_skill = MDDropdownMenu(
                caller=scr.ids.skill_drop,
                items=[{"text": s, "on_release": (lambda x=s: self._set_training_skill(x))} for s in skills],
                width_mult=4,
                max_height=dp(320),
            )

        if 'voc_drop' in scr.ids and 'voc_field' in scr.ids:
            if self._menu_vocation is None:
                vocs = ["Knight", "Paladin", "Sorcerer", "Druid", "Monk", "None"]
                self._menu_vocation = MDDropdownMenu(
                    caller=scr.ids.voc_drop,
                    items=[{"text": v, "on_release": (lambda x=v: self._set_training_voc(x))} for v in vocs],
                    width_mult=4,
                    max_height=dp(260),
                )

        if 'weapon_drop' in scr.ids and 'weapon_field' in scr.ids:
            if self._menu_weapon is None:
                weapons = ["Standard (500)", "Enhanced (1800)", "Lasting (14400)"]
                self._menu_weapon = MDDropdownMenu(
                    caller=scr.ids.weapon_drop,
                    items=[{"text": w, "on_release": (lambda x=w: self._set_training_weapon(x))} for w in weapons],
                    width_mult=4,
                    max_height=dp(260),
                )

    def _set_training_skill(self, skill: str):
        scr = self.root.get_screen("training")
        scr.ids.skill_field.text = skill
        if self._menu_skill:
            self._menu_skill.dismiss()

    def _set_training_voc(self, voc: str):
        scr = self.root.get_screen("training")
        w = scr.ids.get("voc_field")
        if w is not None:
            w.text = voc
        if self._menu_vocation:
            self._menu_vocation.dismiss()

    def _set_training_weapon(self, weapon: str):
        scr = self.root.get_screen("training")
        w = scr.ids.get("weapon_field")
        if w is not None:
            w.text = weapon
        if self._menu_weapon:
            self._menu_weapon.dismiss()

    def training_calculate(self):
        scr = self.root.get_screen("training")
        try:
            frm = int((scr.ids.from_level.text or "").strip())
            to = int((scr.ids.to_level.text or "").strip())
            pct_w = scr.ids.get("percent_left")
            pct = float(((pct_w.text if pct_w else "100") or "100").replace(",", ".").strip() or 100)
            loyalty = float((scr.ids.loyalty.text or "0").replace(",", ".").strip() or 0)
        except ValueError:
            self.toast("Verifique os campos numéricos.")
            return

        skill = (scr.ids.skill_field.text or "Sword").strip()
        voc_w = scr.ids.get("voc_field")
        weapon_w = scr.ids.get("weapon_field")
        voc = ((voc_w.text if voc_w else "") or "Knight").strip()
        weapon = ((weapon_w.text if weapon_w else "") or "Enhanced (1800)").strip()

        if "voc_field" not in scr.ids:
            if skill == "Magic Level":
                voc = "Sorcerer"
            elif skill == "Distance":
                voc = "Paladin"
            else:
                voc = "Knight"

        inp = TrainingInput(
            skill=skill,
            vocation=voc,
            from_level=frm,
            to_level=to,
            weapon_kind=weapon,
            percent_left=pct,
            loyalty_percent=loyalty,
            private_dummy=scr.ids.private_dummy.active,
            double_event=scr.ids.double_event.active,
        )

        scr.ids.train_status.text = "Calculando..."
        scr.ids.train_result.text = ""

        def run():
            plan = compute_training_plan(inp)
            Clock.schedule_once(lambda *_: self._training_done(plan), 0)

        threading.Thread(target=run, daemon=True).start()

    def _training_done(self, plan):
        scr = self.root.get_screen("training")
        if not plan.ok:
            scr.ids.train_status.text = plan.error or "Erro"
            return
        scr.ids.train_status.text = "OK"
        scr.ids.train_result.text = (
            f"Weapons: {plan.weapons}\n"
            f"Charges necessárias: {plan.total_charges:,}\n"
            f"Tempo: {plan.hours:.2f} h\n"
            f"Custo total: {plan.total_cost_gp:,} gp\n"
        ).replace(",", ".")

    # --------------------
    # Hunt Analyzer
    # --------------------
    def hunt_parse(self):
        scr = self.root.get_screen("hunt")
        raw = (scr.ids.hunt_input.text or "").strip()
        if not raw:
            self.toast("Cole o texto do Session Data.")
            return
        scr.ids.hunt_status.text = "Analisando..."
        scr.ids.hunt_output.text = ""

        def run():
            res = parse_hunt_session_text(raw)
            Clock.schedule_once(lambda *_: self._hunt_done(res), 0)

        threading.Thread(target=run, daemon=True).start()

    def _hunt_done(self, res):
        scr = self.root.get_screen("hunt")
        if not res.ok:
            scr.ids.hunt_status.text = res.error or "Erro"
            scr.ids.hunt_output.text = ""
            return
        scr.ids.hunt_status.text = "OK"
        scr.ids.hunt_output.text = res.pretty

    # --------------------
    # Imbuements
    # --------------------

    def imbuement_is_favorite(self, name: str) -> bool:
        favs = self._prefs_get("imb_favorites", []) or []
        if not isinstance(favs, list):
            favs = []
        return (name or "").strip() in favs

    def imbuement_toggle_favorite(self, name: str) -> bool:
        name = (name or "").strip()
        favs = self._prefs_get("imb_favorites", []) or []
        if not isinstance(favs, list):
            favs = []
        if name in favs:
            favs.remove(name)
            self._prefs_set("imb_favorites", favs)
            return False
        favs.append(name)
        self._prefs_set("imb_favorites", favs)
        return True

    def open_imb_tier_menu(self):
        scr = self.root.get_screen("imbuements")
        caller = scr.ids.get("imb_tier_btn")
        if caller is None:
            return
        options = ["All", "Basic", "Intricate", "Powerful"]
        items = [{"text": opt, "on_release": (lambda x=opt: self._set_imb_tier(x))} for opt in options]
        if self._menu_imb_tier:
            self._menu_imb_tier.dismiss()
        self._menu_imb_tier = MDDropdownMenu(caller=caller, items=items, width_mult=4, max_height=dp(220))
        self._menu_imb_tier.open()

    def _set_imb_tier(self, value: str):
        self._prefs_set("imb_tier", value)
        try:
            scr = self.root.get_screen("imbuements")
            scr.ids.imb_tier_label.text = value
        except Exception:
            pass
        if self._menu_imb_tier:
            self._menu_imb_tier.dismiss()
        self.imbuements_refresh_list()

    def imbuements_toggle_fav_only(self):
        cur = bool(self._prefs_get("imb_fav_only", False))
        cur = not cur
        self._prefs_set("imb_fav_only", cur)
        try:
            scr = self.root.get_screen("imbuements")
            scr.ids.imb_fav_toggle.icon = "star" if cur else "star-outline"
        except Exception:
            pass
        self.imbuements_refresh_list()

    def imbuements_copy_selected_hint(self):
        self.toast("Abra um imbuement e use o botão COPIAR no dialog.")

    def _imbuements_load(self):
        scr = self.root.get_screen("imbuements")
        scr.entries = []
        scr.ids.imb_status.text = "Carregando (offline)..."
        scr.ids.imb_list.clear_widgets()

        def run():
            ok, data = fetch_imbuements_table()
            Clock.schedule_once(lambda *_: self._imbuements_done(ok, data), 0)

        threading.Thread(target=run, daemon=True).start()

    def _imbuements_done(self, ok: bool, data):
        scr = self.root.get_screen("imbuements")
        if not ok:
            scr.ids.imb_status.text = f"Erro: {data}"
            return
        scr.entries = data
        scr.ids.imb_status.text = f"Imbuements: {len(data)}"
        try:
            scr.ids.imb_tier_label.text = str(self._prefs_get("imb_tier", "All") or "All")
            scr.ids.imb_fav_toggle.icon = "star" if bool(self._prefs_get("imb_fav_only", False)) else "star-outline"
        except Exception:
            pass
        self.imbuements_refresh_list()

    def imbuements_refresh_list(self):
        scr = self.root.get_screen("imbuements")
        q = (scr.ids.imb_search.text or "").strip().lower()
        tier = str(self._prefs_get("imb_tier", "All") or "All")
        fav_only = bool(self._prefs_get("imb_fav_only", False))
        favs = self._prefs_get("imb_favorites", []) or []
        if not isinstance(favs, list):
            favs = []

        scr.ids.imb_list.clear_widgets()
        entries: List[ImbuementEntry] = getattr(scr, "entries", [])

        def matches(ent: ImbuementEntry) -> bool:
            if q and q not in ent.name.lower():
                return False
            if fav_only and ent.name not in favs:
                return False
            if tier == "Basic" and not (ent.basic or "").strip():
                return False
            if tier == "Intricate" and not (ent.intricate or "").strip():
                return False
            if tier == "Powerful" and not (ent.powerful or "").strip():
                return False
            return True

        filtered = [e for e in entries if matches(e)]
        scr.ids.imb_status.text = f"Imbuements: {len(filtered)}"

        for e in filtered[:200]:
            icon = "star" if self.imbuement_is_favorite(e.name) else "flash"
            item = OneLineIconListItem(text=e.name)
            item.add_widget(IconLeftWidget(icon=icon))
            item.bind(on_release=lambda _item, ent=e: self._imbu_show(ent))
            scr.ids.imb_list.add_widget(item)

    def _imbu_show(self, ent: ImbuementEntry):
        # Abre primeiro com placeholder e depois carrega os itens (sob demanda)
        title = (ent.name or "").strip()

        def copy_now(*_):
            try:
                Clipboard.copy(getattr(dlg, "_last_text", "") or "")
                self.toast("Copiado.")
            except Exception:
                self.toast("Ainda não carregou.")

        def toggle_fav(*_):
            fav = self.imbuement_toggle_favorite(title)
            self.toast("Favoritado." if fav else "Removido dos favoritos.")
            try:
                dlg.dismiss()
            except Exception:
                pass
            self.imbuements_refresh_list()

        fav_txt = "REMOVER ⭐" if self.imbuement_is_favorite(title) else "FAVORITAR ⭐"

        dlg = MDDialog(
            title=title,
            text="Carregando detalhes...",
            buttons=[
                MDFlatButton(text=fav_txt, on_release=toggle_fav),
                MDFlatButton(text="COPIAR", on_release=copy_now),
                MDFlatButton(text="FECHAR", on_release=lambda *_: dlg.dismiss()),
            ],
        )
        dlg.open()

        def run():
            try:
                page = (ent.page or "").strip()
                if not page:
                    page = title.replace(" ", "_")

                ok, data = fetch_imbuement_details(page)
                if not ok:
                    msg = f"Erro ao carregar detalhes:\n{data}"
                    Clock.schedule_once(lambda *_: setattr(dlg, "text", msg), 0)
                    return

                tiers = data  # dict com basic/intricate/powerful

                def fmt(tkey: str, label: str) -> str:
                    tier = tiers.get(tkey, {}) if isinstance(tiers, dict) else {}

                    def clean(s: str) -> str:
                        # Converte sequências literais (ex.: "\\n") em quebras de linha reais
                        return (s or "").replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t").strip()

                    effect = clean(str(tier.get("effect", "")))
                    items = tier.get("items", []) or []

                    out_lines = [f"{label}:"]
                    if effect:
                        out_lines.append(f"Efeito: {effect}")
                    if items:
                        out_lines.append("Itens:")
                        for it in items[:50]:
                            out_lines.append(f"• {clean(str(it))}")
                    else:
                        out_lines.append("Itens: (não encontrado)")
                    return "\n".join(out_lines)

                text = (
                    fmt("basic", "Basic")
                    + "\n\n"
                    + fmt("intricate", "Intricate")
                    + "\n\n"
                    + fmt("powerful", "Powerful")
                    + "\n\n(Fonte: TibiaWiki BR)"
                )
                def _set_text(*_):
                    setattr(dlg, "text", text)
                    setattr(dlg, "_last_text", text)
                Clock.schedule_once(_set_text, 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(dlg, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    TibiaToolsApp().run()