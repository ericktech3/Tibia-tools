# -*- coding: utf-8 -*-
"""
Tibia Tools (Android) - KivyMD app

Tabs: Char / Share XP / Favoritos / Mais
Mais -> telas internas: Bosses (ExevoPan), Boosted, Treino (Exercise), Imbuements, Hunt Analyzer
"""
from __future__ import annotations

import os
import sys
import json
import re
import threading
import time
import urllib.parse
import webbrowser
import traceback
import math
import requests
from datetime import datetime, timedelta, timezone
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
from kivy.uix.behaviors import ButtonBehavior

from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRectangleFlatIconButton
from kivymd.uix.list import (
    OneLineIconListItem,
    OneLineListItem,
    TwoLineIconListItem,
    IconLeftWidget,
)
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.behaviors import RectangularRippleBehavior
from kivymd.uix.scrollview import MDScrollView

# ---- IMPORTS DO CORE (com proteção para não “fechar sozinho” no Android) ----
_CORE_IMPORT_ERROR = None
try:
    from core.api import (
        fetch_character_tibiadata,
        fetch_worlds_tibiadata,
        is_character_online_tibiadata,
        is_character_online_tibia_com,
        fetch_guildstats_deaths_xp,
        fetch_guildstats_exp_changes,
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


# --------------------
# Crash logging (Android-friendly)
# --------------------
def _try_get_writable_dir() -> str:
    # Prefer android app storage; fallback to user_data_dir when app exists.
    try:
        from android.storage import app_storage_path  # type: ignore
        p = app_storage_path()
        if p:
            os.makedirs(p, exist_ok=True)
            return p
    except Exception:
        pass
    # best-effort fallback
    try:
        from kivy.app import App
        app = App.get_running_app()
        if app and getattr(app, "user_data_dir", None):
            p = str(app.user_data_dir)
            os.makedirs(p, exist_ok=True)
            return p
    except Exception:
        pass
    return os.getcwd()

_CRASH_FILE_NAME = "tibia_tools_crash.log"

def _write_crash_log(text: str) -> None:
    try:
        # tenta sempre recalcular um diretório gravável
        crash_dir = _try_get_writable_dir()
        os.makedirs(crash_dir, exist_ok=True)
        crash_file = os.path.join(crash_dir, _CRASH_FILE_NAME)
        with open(crash_file, "a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except Exception:
        pass

def _excepthook(exc_type, exc, tb):
    try:
        _write_crash_log("".join(traceback.format_exception(exc_type, exc, tb)))
    finally:
        # keep default behavior (logcat will show it too)
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

try:
    sys.excepthook = _excepthook
except Exception:
    pass



class RootSM(ScreenManager):
    pass


class MoreItem(OneLineIconListItem):
    icon = StringProperty("chevron-right")




class ClickableRow(RectangularRippleBehavior, ButtonBehavior, MDBoxLayout):
    """Linha clicável usada no Dashboard/Home."""
    pass


class TibiaToolsApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.favorites: List[str] = []

        # -----------------------------------------------------------------
        # Boosted fetch (ANTI-TRAVAMENTO)
        #
        # Havia um loop indireto:
        #   dashboard_refresh() -> update_boosted() -> _boosted_done() -> dashboard_refresh() -> ...
        # Isso gerava threads em cascata, uso alto de CPU/rede e UI “travando”,
        # principalmente após buscar personagem (que chama dashboard_refresh).
        #
        # Estes flags/lock evitam workers simultâneos e permitem throttling.
        # -----------------------------------------------------------------
        self._boosted_lock = threading.Lock()
        self._boosted_inflight = False
        self._boosted_last_fetch_mono = 0.0

        # Android background service handle (favorites monitor)
        self._bg_service = None

        # data dir (writable) – evita crash quando fallback cai em pasta sem permissão no Android
        self.data_dir = ""
        if _CORE_IMPORT_ERROR is None:
            try:
                self.data_dir = str(get_data_dir() or "")
            except Exception:
                self.data_dir = ""

        if not self.data_dir:
            # user_data_dir é o caminho mais confiável no Android
            try:
                self.data_dir = str(getattr(self, "user_data_dir", "") or "")
            except Exception:
                self.data_dir = ""

        if not self.data_dir:
            self.data_dir = os.getcwd()

        def _ensure_writable_dir(p: str) -> str:
            try:
                os.makedirs(p, exist_ok=True)
                test_path = os.path.join(p, ".tt_write_test")
                with open(test_path, "w", encoding="utf-8") as f:
                    f.write("ok")
                try:
                    os.remove(test_path)
                except Exception:
                    pass
                return p
            except Exception:
                return ""

        ok_dir = _ensure_writable_dir(self.data_dir)
        if not ok_dir:
            try:
                ok_dir = _ensure_writable_dir(str(getattr(self, "user_data_dir", "") or ""))
            except Exception:
                ok_dir = ""
        if not ok_dir:
            ok_dir = os.getcwd()
        self.data_dir = ok_dir

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

        # Char search history menu
        self._menu_char_history: Optional[MDDropdownMenu] = None

        # Favorites (chars) UI/status helpers
        self._fav_items = {}  # lower(char_name) -> list item
        self._fav_status_cache = {}  # lower(char_name) -> last known "online"/"offline"
        self._fav_world_cache = {}  # lower(char_name) -> cached world
        self._fav_last_login_cache = {}  # lower(char_name) -> last_login ISO (UTC)
        self._last_seen_online_cache = {}  # lower(char_name) -> last time we saw ONLINE (UTC ISO)
        self._fav_status_job_id = 0
        self._fav_refresh_event = None

        # Disk I/O debounce (evita travadas por salvar JSON a cada update)
        self._prefs_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._prefs_dirty = False
        self._cache_dirty = False
        self._disk_event = threading.Event()
        self._disk_stop = threading.Event()
        self._disk_thread = threading.Thread(target=self._disk_worker_loop, daemon=True)
        self._disk_thread.start()

        # Evita rebuild completo da lista de favoritos a cada refresh
        self._fav_rendered_signature = None
        self._fav_refreshing = False

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

        # Preferências (tema) antes de carregar o KV
        try:
            self._load_prefs_cache()
            style = str(self._prefs_get("theme_style", "Dark") or "Dark").strip().title()
            if style in ("Dark", "Light"):
                self.theme_cls.theme_style = style
        except Exception:
            pass

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
            Clock.schedule_once(lambda *_: self._safe_call(self._apply_settings_to_ui), 0)
            # (disabled) background monitor service auto-start for stability
            Clock.schedule_once(lambda *_: self._safe_call(self._set_initial_home_tab), 0)
            Clock.schedule_once(lambda *_: self._safe_call(self.dashboard_refresh), 0)

            Clock.schedule_once(lambda *_: self._safe_call(self.refresh_favorites_list, silent=True), 0)
            # Auto-atualização do status dos favoritos (não faz sentido ficar "travado")
            if self._fav_refresh_event is None:
                self._fav_refresh_event = Clock.schedule_interval(
                    lambda dt: self._safe_call(self.refresh_favorites_list, silent=True),
                    30,
                )
            Clock.schedule_once(lambda *_: self._safe_call(self.update_boosted), 0)

        return root

    def _safe_call(self, fn, *args, **kwargs):
        """Executa fn e captura exceções, evitando fechar o app no Android."""
        try:
            return fn(*args, **kwargs)
        except Exception:
            _write_crash_log(traceback.format_exc())
            # tenta mostrar uma mensagem simples na UI (sem quebrar se KV falhou)
            try:
                dlg = MDDialog(
                    title="Erro",
                    text="Ocorreu um erro e foi gravado em tibia_tools_crash.log.\nAbra o app novamente e me envie esse log.",
                    buttons=[MDFlatButton(text="OK", on_release=lambda *_: dlg.dismiss())],
                )
                dlg.open()
            except Exception:
                pass
            return None

    def on_pause(self):
        """Android: ao ir para o background, força flush de prefs/cache.

        Isso ajuda a não perder dados caso o sistema mate o processo.
        """
        try:
            self._flush_prefs_to_disk(force=True)
            self._flush_cache_to_disk(force=True)
        except Exception:
            pass
        # Garante que o monitor em segundo plano continue rodando mesmo com o app fechado.
        # (Alguns usuários abrem e fecham rápido; isso assegura que o serviço seja iniciado no background.)
        try:
            Clock.schedule_once(lambda *_: self._safe_call(self._maybe_start_fav_monitor_service), 0)
        except Exception:
            pass

        return True

    def on_stop(self):
        """Flush final e encerra o worker de disco."""
        try:
            try:
                self._disk_stop.set()
            except Exception:
                pass
            try:
                self._disk_event.set()
            except Exception:
                pass
            # flush final
            self._flush_prefs_to_disk(force=True)
            self._flush_cache_to_disk(force=True)
        except Exception:
            pass

    # --------------------
    # Deep-link / Notification click handling (Android)
    # --------------------
    def _handle_android_intent(self) -> None:
        """Se o app foi aberto por uma notificação do serviço, abre a aba Char e (opcionalmente) dispara a busca.

        O serviço envia extras no Intent:
        - tt_open_tab: "tab_char"
        - tt_char_name: nome do char (opcional)
        - tt_auto_search: bool
        - tt_event_type: "online"/"level"/"death" (opcional)
        """
        if not self._is_android():
            return
        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")

            act = PythonActivity.mActivity
            intent = act.getIntent()
            if intent is None:
                return

            open_tab = None
            char_name = None
            auto_search = False
            event_type = None
            try:
                open_tab = intent.getStringExtra("tt_open_tab")
            except Exception:
                open_tab = None
            try:
                char_name = intent.getStringExtra("tt_char_name")
            except Exception:
                char_name = None
            try:
                event_type = intent.getStringExtra("tt_event_type")
            except Exception:
                event_type = None
            try:
                auto_search = bool(intent.getBooleanExtra("tt_auto_search", False))
            except Exception:
                auto_search = False

            if not (open_tab or char_name or event_type):
                return

            sig = f"{open_tab}|{char_name}|{auto_search}|{event_type}"
            if getattr(self, "_last_intent_sig", None) == sig:
                return
            self._last_intent_sig = sig

            # Garante que estamos na Home e na aba Char
            try:
                self.go("home")
            except Exception:
                pass
            try:
                self.select_home_tab("tab_char")
            except Exception:
                pass

            def apply_and_search(*_):
                try:
                    home = self.root.get_screen("home")
                    if char_name and "char_name" in home.ids:
                        home.ids.char_name.text = str(char_name)
                    if auto_search and char_name:
                        # silencioso: não spammar toast ao tocar na notificação
                        self.search_character(silent=True)
                except Exception:
                    pass

            # Deixa a UI terminar de montar antes de mexer nos ids
            Clock.schedule_once(apply_and_search, 0.15)

            # Evita re-disparar ao voltar de background: limpa o Intent atual
            try:
                empty = Intent()
                try:
                    empty.setAction(f"TT_HANDLED_{int(time.time()*1000)}")
                except Exception:
                    pass
                act.setIntent(empty)
            except Exception:
                # fallback: remove extras
                try:
                    intent.removeExtra("tt_open_tab")
                    intent.removeExtra("tt_char_name")
                    intent.removeExtra("tt_auto_search")
                    intent.removeExtra("tt_event_type")
                except Exception:
                    pass
        except Exception:
            return

    # --------------------
    # Navigation
    # --------------------

    def on_start(self):
        # Startup: handle deep-link intents (if any) + request notification permission (Android 13+).
        try:
            Clock.schedule_once(lambda *_: self._handle_android_intent(), 0.6)
        except Exception:
            pass

        # Ask once on first run (Android 13+ requires POST_NOTIFICATIONS).
        try:
            Clock.schedule_once(lambda *_: self._ensure_post_notifications_permission(), 0.9)
        except Exception:
            pass

        # Start/stop background monitor according to current settings.
        # (Needs to run after the initial permission check on Android 13+.)
        try:
            Clock.schedule_once(lambda *_: self._safe_call(self._maybe_start_fav_monitor_service), 1.6)
        except Exception:
            pass

    def on_resume(self):
        # Quando o usuário toca na notificação com o app em background, isso garante o deep-link.
        try:
            Clock.schedule_once(lambda *_: self._handle_android_intent(), 0.2)
        except Exception:
            pass

        # Reconfere o estado do serviço ao voltar (alguns OEMs podem matar o processo do serviço).
        try:
            Clock.schedule_once(lambda *_: self._safe_call(self._maybe_start_fav_monitor_service), 0.8)
        except Exception:
            pass

    def go(self, screen_name: str):
        sm = self.root
        if isinstance(sm, ScreenManager) and screen_name in sm.screen_names:
            sm.current = screen_name

    def back_home(self, *_):
        self.go("home")


    def open_boosted_from_home(self, which: str = ""):
        """Abre a tela Boosted a partir do card da Home.

        which: "creature" | "boss" | "" (opcional, apenas para futuras melhorias).
        """
        try:
            self.root.current = "boosted"
        except Exception:
            return

        # garante que os dados estejam atualizados ao entrar
        try:
            self.update_boosted(silent=False)
        except Exception:
            pass


    def select_home_tab(self, tab_name: str):
        """Seleciona uma aba dentro da HomeScreen (BottomNavigation)."""
        try:
            home = self.root.get_screen("home")
            if "bottom_nav" in home.ids:
                home.ids.bottom_nav.switch_tab(tab_name)
        except Exception:
            pass

    def open_more_target(self, target: str):
        # Itens que abrem dialog/ações, não telas
        if target == "about":
            self.show_about()
            return
        if target == "changelog":
            self.show_changelog()
            return
        if target == "feedback":
            self.open_feedback()
            return

        self.go(target)
        if target == "bosses":
            self._bosses_refresh_worlds()
        elif target == "imbuements":
            self._imbuements_load()
        elif target == "training":
            self._ensure_training_menus()
        elif target == "settings":
            self._apply_settings_to_ui()

    def show_about(self):
        txt = (
            "Tibia Tools\n"
            "\n"
            "• Consulta de personagens (status, guild, houses, mortes)\n"
            "• Favoritos com monitoramento em background (online/morte/level)\n"
            "• Boosted / Bosses / Treino / Hunt Analyzer / Imbuements\n"
            "\n"
            "Observações:\n"
            "- Dados de status vêm de TibiaData e Tibia.com (quando necessário).\n"
            "- Histórico de XP (30 dias) usa um fansite como fonte auxiliar.\n"
            "\n"
            "Dica: toque em qualquer notificação de favorito para abrir a aba de personagem automaticamente."
        )
        self._show_text_dialog("Sobre", txt)

    def show_changelog(self):
        txt = (
            "Novidades\n\n"
            "- Notificações em background para Favoritos: ONLINE, MORTE e LEVEL UP\n"
            "- Toque na notificação abre o app na aba do personagem e já pesquisa o char\n"
            "- Histórico de busca de personagens (botão de relógio)\n"
            "- Card de XP feita: total 7d e 30d (quando disponível)\n"
            "- Configuração de tema claro/escuro"
        )
        self._show_text_dialog("Novidades", txt)

    def open_feedback(self):
        # Abre issues do GitHub se houver repo configurado; senão, abre o próprio repo.
        url = str(self._prefs_get("repo_url", "") or "").strip()
        if url and "github.com" in url.lower():
            if "/issues" not in url.lower():
                url = url.rstrip("/") + "/issues/new"
            try:
                webbrowser.open(url)
                return
            except Exception:
                pass
        self.toast("Defina a URL do repo nas Configurações para abrir o feedback.")

    # --------------------
    # Char tab helpers (history / clear)
    # --------------------
    def clear_char_search(self):
        try:
            home = self.root.get_screen("home")
            if "char_name" in home.ids:
                home.ids.char_name.text = ""
                home.ids.char_name.focus = True
        except Exception:
            pass

    def _get_char_history(self) -> list[str]:
        try:
            hist = self._prefs_get("char_history", []) or []
            if not isinstance(hist, list):
                return []
            out = []
            for x in hist:
                s = str(x or "").strip()
                if s:
                    out.append(s)
            return out
        except Exception:
            return []

    def _add_to_char_history(self, name: str) -> None:
        name = (name or "").strip()
        if not name:
            return
        try:
            hist = self._get_char_history()
            # remove duplicates (case-insensitive)
            hist = [h for h in hist if h.strip().lower() != name.lower()]
            hist.insert(0, name)
            hist = hist[:12]
            self._prefs_set("char_history", hist)
        except Exception:
            pass

    def open_char_history_menu(self):
        try:
            home = self.root.get_screen("home")
            anchor = home.ids.get("char_name")
        except Exception:
            return

        hist = self._get_char_history()
        if not hist:
            self.toast("Sem histórico ainda.")
            return

        def pick(n: str):
            try:
                home.ids.char_name.text = n
                # fecha menu e foca no campo
                try:
                    if self._menu_char_history:
                        self._menu_char_history.dismiss()
                except Exception:
                    pass
                home.ids.char_name.focus = True
            except Exception:
                pass

        menu_items = [
            {
                "viewclass": "OneLineListItem",
                "text": n,
                "on_release": (lambda x=n: pick(x)),
            }
            for n in hist
        ]

        try:
            if self._menu_char_history:
                self._menu_char_history.dismiss()
        except Exception:
            pass
        self._menu_char_history = MDDropdownMenu(
            caller=anchor,
            items=menu_items,
            width_mult=4,
            max_height=dp(320),
        )
        self._menu_char_history.open()

    
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
            if (not self._notifications_globally_enabled()) or (not self._channel_enabled("tibia_tools_watch_fg")) or (not self._channel_enabled("tibia_tools_events")):
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

    # --------------------
    # Background service (Favorites monitor)
    # --------------------
    def _start_fav_monitor_service(self):
        """Inicia o serviço em segundo plano (foreground service) para monitorar favoritos."""
        if not self._is_android():
            return

        # Em Android 13+ precisamos de POST_NOTIFICATIONS; sem isso o serviço pode falhar ao postar a notificação fixa do foreground.
        if self._android_sdk_int() >= 33:
            ok = self._ensure_post_notifications_permission(auto_open_settings=False)
            if not ok:
                try:
                    self._prompt_enable_notifications_dialog()
                except Exception:
                    pass
                return

        try:
            from jnius import autoclass  # type: ignore
            ServiceFavwatch = autoclass('org.erick.tibiatools.ServiceFavwatch')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            ctx = PythonActivity.mActivity
            # Usa overload com (icon, title, text, arg) quando disponível; senão cai no start(ctx, arg).
            try:
                ServiceFavwatch.start(ctx, '', 'Tibia Tools', 'Monitorando favoritos', '')
            except Exception:
                ServiceFavwatch.start(ctx, '')
            self._bg_service = True
        except Exception:
            _write_crash_log(traceback.format_exc())

    def _stop_fav_monitor_service(self):
        if not self._is_android():
            return
        try:
            from jnius import autoclass  # type: ignore
            ServiceFavwatch = autoclass('org.erick.tibiatools.ServiceFavwatch')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            ctx = PythonActivity.mActivity
            ServiceFavwatch.stop(ctx)
            self._bg_service = None
        except Exception:
            _write_crash_log(traceback.format_exc())

    def _maybe_start_fav_monitor_service(self):
        """Liga/desliga o serviço conforme Configurações + favoritos."""
        if not self._is_android():
            return
        try:
            st = fav_state.load_state(self.data_dir)
            monitoring = bool(st.get("monitoring", True))
            favs = st.get("favorites", [])
            has_favs = isinstance(favs, list) and any(str(x).strip() for x in favs)

            if monitoring and has_favs:
                self._start_fav_monitor_service()
            else:
                self._stop_fav_monitor_service()
        except Exception:
            _write_crash_log(traceback.format_exc())


    # --------------------
    # Shared state (Favorites monitor service)
    # --------------------
    def _load_fav_service_state_cached(self) -> dict:
        """Carrega favorites.json (compartilhado com o serviço) com TTL curto.

        Evita leituras de disco repetidas (Android pode ser caro).
        """
        try:
            now = time.time()
            c = getattr(self, "_svc_state_cache", None)
            if isinstance(c, dict) and (now - float(c.get("t", 0))) < 2.0:
                st = c.get("st")
                if isinstance(st, dict):
                    return st
        except Exception:
            pass

        try:
            st = fav_state.load_state(self.data_dir)
            if not isinstance(st, dict):
                st = {}
        except Exception:
            st = {}

        try:
            self._svc_state_cache = {"t": time.time(), "st": st}
        except Exception:
            pass
        return st

    def _get_service_last_entry(self, name: str) -> Optional[dict]:
        key = (name or "").strip().lower()
        if not key:
            return None
        try:
            st = self._load_fav_service_state_cached()
            last = st.get("last", {})
            if isinstance(last, dict):
                v = last.get(key)
                return v if isinstance(v, dict) else None
        except Exception:
            return None
        return None

    def _service_entry_is_fresh(self, entry: dict, max_age_s: int = 90) -> bool:
        try:
            ts = entry.get("last_checked_iso")
            if not ts:
                return False
            dt = datetime.fromisoformat(str(ts).strip())
            age = (datetime.utcnow() - dt).total_seconds()
            return age <= float(max_age_s)
        except Exception:
            return False

    def _sync_bg_monitor_state_from_ui(self):
        """Save background-monitor settings into favorites.json (shared with the service)."""
        try:
            scr = self.root.get_screen("settings")
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
            st = fav_state.load_state(self.data_dir)
            if not isinstance(st, dict):
                st = {}
            st["favorites"] = [str(x) for x in (self.favorites or [])]
            st["monitoring"] = monitoring
            st["notify_fav_online"] = notify_online
            st["notify_fav_level"] = notify_level
            st["notify_fav_death"] = notify_death
            st["autostart_on_boot"] = autostart
            st["interval_seconds"] = max(20, min(600, int(interval)))
            fav_state.save_state(self.data_dir, st)
        except Exception:
            pass

        # aplica o estado imediatamente
        try:
            self._maybe_start_fav_monitor_service()
        except Exception:
            pass

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
                ids.dash_boost_creature.text = (cached_boost.get('creature') or '-')
                ids.dash_boost_boss.text = (cached_boost.get('boss') or '-')
                # sprites no dashboard (quando disponíveis)
                if "dash_boost_creature_sprite" in ids:
                    ids.dash_boost_creature_sprite.source = cached_boost.get("creature_image") or ""
                if "dash_boost_boss_sprite" in ids:
                    ids.dash_boost_boss_sprite.source = cached_boost.get("boss_image") or ""
                ts = self.cache.get("boosted", {}).get("ts", "")
                ids.dash_boost_updated.text = f"Atualizado: {ts.split('T')[0] if ts else ''}"
            except Exception:
                pass
        else:
            try:
                ids.dash_boost_creature.text = "-"
                ids.dash_boost_boss.text = "-"
                if "dash_boost_creature_sprite" in ids:
                    ids.dash_boost_creature_sprite.source = ""
                if "dash_boost_boss_sprite" in ids:
                    ids.dash_boost_boss_sprite.source = ""
                ids.dash_boost_updated.text = "Sem cache ainda."
            except Exception:
                pass

        # Atualiza Boosted ao vivo (sem travar UI), mas com *throttling*.
        # Chamar isso a cada dashboard_refresh (ex: ao buscar personagem) cria
        # muita atividade de rede/CPU no Android. Atualizamos apenas se o cache
        # estiver ausente ou "velho" o suficiente.
        try:
            need_live = False
            ts = None
            try:
                ts = (self.cache.get("boosted") or {}).get("ts")
            except Exception:
                ts = None

            if not ts:
                need_live = True
            else:
                try:
                    dt = datetime.fromisoformat(str(ts))
                    age_s = (datetime.utcnow() - dt).total_seconds()
                    # Boosted muda 1x por dia; 6h é um bom equilíbrio.
                    if age_s > 6 * 3600:
                        need_live = True
                except Exception:
                    need_live = True

            if need_live:
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
        """Carrega prefs/cache do disco (1x) e mantém em memória."""
        prefs = safe_read_json(self.prefs_path, default={}) or {}
        if not isinstance(prefs, dict):
            prefs = {}
        cache = safe_read_json(self.cache_path, default={}) or {}
        if not isinstance(cache, dict):
            cache = {}

        # Evita race com o worker de flush
        try:
            with self._prefs_lock:
                self.prefs = prefs
                self._prefs_dirty = False
            with self._cache_lock:
                self.cache = cache
                self._cache_dirty = False
        except Exception:
            self.prefs = prefs
            self.cache = cache

    def _write_json_atomic(self, path: str, data, *, pretty: bool = False) -> bool:
        """Escreve JSON de forma atômica (tmp + replace).

        pretty=True  -> indentado (legível)
        pretty=False -> compacto (mais rápido/menor)
        """
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

    def _disk_worker_loop(self) -> None:
        """Thread dedicado para flush de prefs/cache em disco, com debounce.

        Isso evita travadas na UI quando o app atualiza muitos itens (ex: Favoritos)
        e chamava json.dump a cada update.
        """
        while True:
            try:
                if getattr(self, "_disk_stop", None) is not None and self._disk_stop.is_set():
                    break
                # espera alguma alteração (ou timeout para permitir sair)
                self._disk_event.wait(timeout=1.0)
                if getattr(self, "_disk_stop", None) is not None and self._disk_stop.is_set():
                    break

                # debounce: coalesce bursts
                time.sleep(0.4)
                try:
                    self._disk_event.clear()
                except Exception:
                    pass

                self._flush_prefs_to_disk()
                self._flush_cache_to_disk()
            except Exception:
                try:
                    _write_crash_log(traceback.format_exc())
                except Exception:
                    pass

    def _flush_prefs_to_disk(self, force: bool = False) -> None:
        """Salva prefs.json se houver alterações."""
        try:
            with self._prefs_lock:
                if (not force) and (not bool(getattr(self, "_prefs_dirty", False))):
                    return
                snapshot = dict(self.prefs) if isinstance(self.prefs, dict) else {}
                self._prefs_dirty = False
            ok = self._write_json_atomic(self.prefs_path, snapshot, pretty=True)
            if not ok:
                with self._prefs_lock:
                    self._prefs_dirty = True
        except Exception:
            try:
                with self._prefs_lock:
                    self._prefs_dirty = True
            except Exception:
                pass

    def _flush_cache_to_disk(self, force: bool = False) -> None:
        """Salva cache.json se houver alterações (compacto, para ser rápido)."""
        try:
            with self._cache_lock:
                if (not force) and (not bool(getattr(self, "_cache_dirty", False))):
                    return
                snapshot = dict(self.cache) if isinstance(self.cache, dict) else {}
                self._cache_dirty = False
            ok = self._write_json_atomic(self.cache_path, snapshot, pretty=False)
            if not ok:
                with self._cache_lock:
                    self._cache_dirty = True
        except Exception:
            try:
                with self._cache_lock:
                    self._cache_dirty = True
            except Exception:
                pass

    def _save_prefs(self):
        """Compat: salva imediatamente (evite chamar em hot paths)."""
        self._flush_prefs_to_disk(force=True)

    def _save_cache(self):
        """Compat: salva imediatamente (evite chamar em hot paths)."""
        self._flush_cache_to_disk(force=True)

    def _prefs_get(self, key: str, default=None):
        try:
            return self.prefs.get(key, default)
        except Exception:
            return default

    def _prefs_set(self, key: str, value):
        """Atualiza prefs em memória e agenda flush em background."""
        try:
            with self._prefs_lock:
                if not isinstance(self.prefs, dict):
                    self.prefs = {}
                self.prefs[key] = value
                self._prefs_dirty = True
            try:
                self._disk_event.set()
            except Exception:
                pass
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
        """Atualiza cache em memória e agenda flush em background."""
        try:
            with self._cache_lock:
                if not isinstance(self.cache, dict):
                    self.cache = {}
                self.cache[key] = {"ts": datetime.utcnow().isoformat(), "value": value}
                self._cache_dirty = True
            try:
                self._disk_event.set()
            except Exception:
                pass
        except Exception:
            pass

    def _cache_clear(self):
        try:
            with self._cache_lock:
                self.cache = {}
                self._cache_dirty = True
            try:
                self._disk_event.set()
            except Exception:
                pass
        except Exception:
            pass

    # --------------------
    # Offline duration helpers ("última vez online")
    # --------------------
    def _eu_dst_offset_hours(self, dt_local: datetime) -> int:
        """Retorna offset CET/CEST (horas) assumindo regra EU.

        Usado quando a API não informa timezone.
        """
        try:
            y = dt_local.year
            # last Sunday of March
            import calendar
            def last_sunday(year: int, month: int) -> datetime:
                last_day = calendar.monthrange(year, month)[1]
                d = datetime(year, month, last_day)
                # weekday: Monday=0 ... Sunday=6
                delta = (d.weekday() - 6) % 7
                return d - timedelta(days=delta)

            start = last_sunday(y, 3).replace(hour=2, minute=0, second=0, microsecond=0)  # 02:00 local
            end = last_sunday(y, 10).replace(hour=3, minute=0, second=0, microsecond=0)   # 03:00 local
            if start <= dt_local < end:
                return 2  # CEST
            return 1      # CET
        except Exception:
            # fallback simples
            try:
                return 2 if 4 <= int(dt_local.month) <= 9 else 1
            except Exception:
                return 1

    def _parse_tibia_datetime(self, raw: str) -> Optional[datetime]:
        """Tenta converter datas vindas do TibiaData/tibia.com para datetime UTC (naive)."""
        if not isinstance(raw, str):
            return None
        s = raw.strip()
        if not s or s.lower() in ("n/a", "none", "null"):
            return None

        # Normaliza alguns formatos
        s2 = s.replace("\u00a0", " ").strip()
        # ISO com Z
        if s2.endswith('Z'):
            try:
                dt = datetime.fromisoformat(s2[:-1] + '+00:00')
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

        # ISO (talvez com offset)
        try:
            dt = datetime.fromisoformat(s2)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            pass

        # Formatos comuns do TibiaData (sem tz)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d, %H:%M:%S", "%Y-%m-%d"):
            try:
                dt_local = datetime.strptime(s2, fmt)
                off = self._eu_dst_offset_hours(dt_local)
                return (dt_local - timedelta(hours=off))
            except Exception:
                continue

        # Formato típico do tibia.com: "Jan 22 2026, 10:42:00 CET"
        # Vamos remover o timezone e aplicar CET/CEST.
        import re
        m = re.match(r"^([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4}),\s*(\d{2}:\d{2}:\d{2})(?:\s+([A-Za-z]{2,5}))?$", s2)
        if m:
            mon, day, year, hhmmss, tz = m.groups()
            try:
                dt_local = datetime.strptime(f"{mon} {day} {year}, {hhmmss}", "%b %d %Y, %H:%M:%S")
            except Exception:
                dt_local = None
            if dt_local:
                tz_u = (tz or "").upper().strip()
                if tz_u == "CEST":
                    off = 2
                elif tz_u == "CET":
                    off = 1
                elif tz_u in ("UTC", "GMT"):
                    off = 0
                else:
                    off = self._eu_dst_offset_hours(dt_local)
                return dt_local - timedelta(hours=off)

        return None

    def _extract_last_login_dt_from_tibiadata(self, data: dict) -> Optional[datetime]:
        """Extrai o 'last_login' (ou equivalente) do JSON do TibiaData."""
        if not isinstance(data, dict):
            return None
        ch_wrap = data.get('character') or {}
        ch = None
        if isinstance(ch_wrap, dict):
            ch = ch_wrap.get('character') if isinstance(ch_wrap.get('character'), dict) else ch_wrap
        if not isinstance(ch, dict):
            return None

        # Possíveis chaves (variam por versão/API)
        candidates = [
            'last_login',
            'lastLogin',
            'last_logout',
            'lastLogout',
            'last_seen',
            'lastSeen',
            'last_online',
            'lastOnline',
        ]
        raw = None
        for k in candidates:
            if k in ch and ch.get(k):
                raw = ch.get(k)
                break

        # Às vezes vem como dict
        if isinstance(raw, dict):
            raw = raw.get('date') or raw.get('datetime') or raw.get('time')

        if isinstance(raw, str):
            return self._parse_tibia_datetime(raw)

        return None

    def _fetch_last_login_dt_tibia_com(self, name: str, timeout: int = 12) -> Optional[datetime]:
        """Fallback: tenta pegar o 'Last Login' direto do tibia.com."""
        try:
            from bs4 import BeautifulSoup  # type: ignore
        except Exception:
            return None

        try:
            safe = urllib.parse.quote_plus(str(name))
            url = f"https://www.tibia.com/community/?subtopic=characters&name={safe}"
            hdr = {
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 13; Mobile) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Mobile Safari/537.36"
                ),
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            r = requests.get(url, timeout=timeout, headers=hdr)
            if r.status_code != 200:
                return None
            html = r.text or ""
            if not html:
                return None

            soup = BeautifulSoup(html, "html.parser")
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                k = (tds[0].get_text(" ", strip=True) or "").strip().rstrip(":").strip().lower()
                if k not in ("last login", "last login time", "last login:") and not k.startswith("last login"):
                    continue
                v = (tds[1].get_text(" ", strip=True) or "").strip()
                dt = self._parse_tibia_datetime(v)
                if dt:
                    return dt
            return None
        except Exception:
            return None

    def _get_cached_fav_last_login_iso(self, name: str) -> Optional[str]:
        key = (name or "").strip().lower()
        if not key:
            return None
        try:
            if key in getattr(self, "_fav_last_login_cache", {}):
                v = self._fav_last_login_cache.get(key)
                return str(v) if v else None
        except Exception:
            pass
        cached = self._cache_get(f"fav_last_login:{key}")
        if isinstance(cached, str) and cached.strip():
            try:
                self._fav_last_login_cache[key] = cached.strip()
            except Exception:
                pass
            return cached.strip()
        return None

    def _set_cached_fav_last_login_iso(self, name: str, iso: Optional[str]) -> None:
        key = (name or "").strip().lower()
        if not key:
            return
        try:
            if iso and str(iso).strip():
                self._fav_last_login_cache[key] = str(iso).strip()
                self._cache_set(f"fav_last_login:{key}", str(iso).strip())
            else:
                self._fav_last_login_cache.pop(key, None)
                self._cache_set(f"fav_last_login:{key}", None)
        except Exception:
            pass



    def _get_cached_last_seen_online_iso(self, name: str) -> Optional[str]:
        """Instante (UTC ISO) em que o app viu o char ONLINE pela última vez.

        Tibia.com expõe "Last Login" (hora que entrou), não "Last Logout".
        Para mostrar "há quanto tempo ficou OFF", usamos o último instante em que o app confirmou o ONLINE.
        """
        key = (name or "").strip().lower()
        if not key:
            return None

        try:
            if key in getattr(self, "_last_seen_online_cache", {}):
                v = self._last_seen_online_cache.get(key)
                return str(v) if v else None
        except Exception:
            pass

        cached = self._cache_get(f"last_seen_online:{key}")
        if isinstance(cached, str) and cached.strip():
            try:
                self._last_seen_online_cache[key] = cached.strip()
            except Exception:
                pass
            return cached.strip()

        return None



    def _set_cached_last_seen_online_iso(self, name: str, iso: Optional[str]) -> None:
        key = (name or "").strip().lower()
        if not key:
            return
        try:
            if iso and str(iso).strip():
                self._last_seen_online_cache[key] = str(iso).strip()
                self._cache_set(f"last_seen_online:{key}", str(iso).strip())
            else:
                self._last_seen_online_cache.pop(key, None)
                self._cache_set(f"last_seen_online:{key}", None)
        except Exception:
            pass


    def _get_cached_offline_since_iso(self, name: str) -> Optional[str]:
        """Instante (UTC ISO) em que o app/serviço detectou a transição Online -> Offline.

        Esse é o mais próximo de "quando deslogou" que dá para medir automaticamente.
        """
        key = (name or "").strip().lower()
        if not key:
            return None
        try:
            if key in getattr(self, "_offline_since_cache", {}):
                v = self._offline_since_cache.get(key)
                return str(v) if v else None
        except Exception:
            pass
        cached = self._cache_get(f"offline_since:{key}")
        if isinstance(cached, str) and cached.strip():
            try:
                if not hasattr(self, "_offline_since_cache"):
                    self._offline_since_cache = {}
                self._offline_since_cache[key] = cached.strip()
            except Exception:
                pass
            return cached.strip()
        return None

    def _set_cached_offline_since_iso(self, name: str, iso: Optional[str]) -> None:
        key = (name or "").strip().lower()
        if not key:
            return
        try:
            if not hasattr(self, "_offline_since_cache"):
                self._offline_since_cache = {}
            if iso and str(iso).strip():
                self._offline_since_cache[key] = str(iso).strip()
                self._cache_set(f"offline_since:{key}", str(iso).strip())
            else:
                self._offline_since_cache.pop(key, None)
                self._cache_set(f"offline_since:{key}", None)
        except Exception:
            pass


    def _format_ago_short(self, dt_utc: datetime) -> str:
        try:
            now = datetime.utcnow()
            sec = max(0, int((now - dt_utc).total_seconds()))
            mins = sec // 60
            if mins < 60:
                return f"há {mins}m"
            hrs = mins // 60
            if hrs < 24:
                return f"há {hrs}h"
            days = hrs // 24
            if days < 30:
                return f"há {days}d"
            # meses aproximados
            months = days // 30
            return f"há {months}m"
        except Exception:
            return ""

    def _format_ago_long(self, dt_utc: datetime) -> str:
        try:
            now = datetime.utcnow()
            sec = max(0, int((now - dt_utc).total_seconds()))
            mins = sec // 60
            if mins < 60:
                n = mins
                return f"há {n} minuto" + ("s" if n != 1 else "")
            hrs = mins // 60
            if hrs < 24:
                n = hrs
                return f"há {n} hora" + ("s" if n != 1 else "")
            days = hrs // 24
            if days < 30:
                n = days
                return f"há {n} dia" + ("s" if n != 1 else "")
            months = days // 30
            n = months
            return f"há {n} mês" + ("es" if n != 1 else "")
        except Exception:
            return ""

    def _fetch_last_login_iso_for_char(self, name: str) -> Optional[str]:
        """Busca o last_login (UTC ISO) do char.

        1) tenta TibiaData /v4/character
        2) fallback tibia.com
        """
        try:
            data = fetch_character_tibiadata(name, timeout=12)
            dt = self._extract_last_login_dt_from_tibiadata(data)
            if dt:
                return dt.isoformat()
        except Exception:
            pass
        try:
            dt = self._fetch_last_login_dt_tibia_com(name, timeout=12)
            if dt:
                return dt.isoformat()
        except Exception:
            pass
        return None

    def _set_initial_home_tab(self, *_):
        # abre direto no Dashboard
        self.select_home_tab("tab_dashboard")


    def _apply_settings_to_ui(self):
        try:
            scr = self.root.get_screen("settings")
        except Exception:
            return
        try:
            # Tema
            try:
                style = str(self._prefs_get("theme_style", "Dark") or "Dark").strip().title()
                scr.ids.set_theme_light.active = (style == "Light")
            except Exception:
                pass
            scr.ids.set_notify_boosted.active = bool(self._prefs_get("notify_boosted", True))
            scr.ids.set_notify_boss_high.active = bool(self._prefs_get("notify_boss_high", True))
            scr.ids.set_repo_url.text = str(self._prefs_get("repo_url", "") or "")
        except Exception:
            pass

        # Background monitor (shared state file)
        try:
            st = fav_state.load_state(self.data_dir)
            scr.ids.set_bg_monitor.active = bool(st.get("monitoring", True))
            scr.ids.set_bg_notify_online.active = bool(st.get("notify_fav_online", True))
            scr.ids.set_bg_notify_level.active = bool(st.get("notify_fav_level", True))
            scr.ids.set_bg_notify_death.active = bool(st.get("notify_fav_death", True))
            scr.ids.set_bg_interval.text = str(int(st.get("interval_seconds", 30) or 30))
            scr.ids.set_bg_autostart.active = bool(st.get("autostart_on_boot", True))
        except Exception:
            pass


    def settings_save(self):
        try:
            scr = self.root.get_screen("settings")
            # Tema
            try:
                theme_style = "Light" if bool(scr.ids.set_theme_light.active) else "Dark"
                self._prefs_set("theme_style", theme_style)
                try:
                    self.theme_cls.theme_style = theme_style
                except Exception:
                    pass
            except Exception:
                pass
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

            # XP últimos 30 dias (GuildStats)
            if "char_xp_list" in home.ids:
                try:
                    home.ids.char_xp_total.text = "Carregando histórico de XP..."
                    home.ids.char_xp_total.theme_text_color = "Hint"
                except Exception:
                    pass
                try:
                    home.ids.char_xp_list.clear_widgets()
                    xitem = OneLineIconListItem(text="Buscando histórico de XP...")
                    xitem.add_widget(IconLeftWidget(icon="chart-line"))
                    home.ids.char_xp_list.add_widget(xitem)
                except Exception:
                    pass
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

            # XP card
            if "char_xp_list" in home.ids:
                try:
                    home.ids.char_xp_total.text = "—"
                    home.ids.char_xp_total.theme_text_color = "Hint"
                except Exception:
                    pass
                try:
                    home.ids.char_xp_list.clear_widgets()
                    xitem = OneLineIconListItem(text="Sem dados.")
                    xitem.add_widget(IconLeftWidget(icon="chart-line"))
                    home.ids.char_xp_list.add_widget(xitem)
                except Exception:
                    pass
            return

        if "char_status" in home.ids:
            home.ids.char_status.text = message

    def _char_show_result(self, home, payload: dict, *, side_effects: bool = True):
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

        # XP últimos 30 dias (GuildStats tab=9)
        exp_rows_30 = payload.get("exp_rows_30") or []
        exp_total_30 = payload.get("exp_total_30")
        try:
            home.char_xp_source_url = str(payload.get("gs_exp_url") or "")
        except Exception:
            pass

        try:
            home._last_char_payload = payload
        except Exception:
            pass

        # Side-effects (prefs/history/dashboard) apenas na primeira renderização do resultado.
        if side_effects:
            try:
                if title:
                    self._prefs_set("last_char", title)
                    self._add_to_char_history(title)
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
            # Se estiver OFFLINE, mostra há quanto tempo (se disponível)
            try:
                if st == "offline":
                    ago = str(payload.get("last_login_ago") or "").strip()
                    if ago:
                        add_two("Última vez online", ago, "clock-outline")
            except Exception:
                pass
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

            # ----------------------------
            # Card: XP últimos 30 dias
            # ----------------------------
            if "char_xp_list" in home.ids:
                def fmt_pt(n: int) -> str:
                    try:
                        s = f"{abs(int(n)):,}".replace(",", ".")
                    except Exception:
                        s = str(n)
                    return ("-" if int(n) < 0 else "+") + s

                try:
                    xlist = home.ids.char_xp_list
                    xlist.clear_widgets()

                    loading_gs = bool(payload.get("gs_exp_loading"))
                    rows = exp_rows_30 if isinstance(exp_rows_30, list) else []

                    if loading_gs and not rows:
                        home.ids.char_xp_total.text = "Carregando histórico de XP..."
                        home.ids.char_xp_total.theme_text_color = "Hint"
                    elif isinstance(exp_total_30, (int, float)) and rows:
                        # também calcula últimos 7 dias com base na data mais recente do histórico
                        total_7 = None
                        try:
                            ref_dates = []
                            for rr in rows:
                                ds0 = str(rr.get("date") or "").strip()
                                if not ds0:
                                    continue
                                try:
                                    ref_dates.append(datetime.fromisoformat(ds0).date())
                                except Exception:
                                    continue
                            ref = max(ref_dates) if ref_dates else datetime.utcnow().date()
                            cutoff7 = ref - timedelta(days=7)
                            s7 = 0
                            for rr in rows:
                                ds0 = str(rr.get("date") or "").strip()
                                if not ds0:
                                    continue
                                try:
                                    d0 = datetime.fromisoformat(ds0).date()
                                except Exception:
                                    continue
                                if d0 < cutoff7:
                                    continue
                                try:
                                    s7 += int(rr.get("exp_change_int") or 0)
                                except Exception:
                                    continue
                            total_7 = int(s7)
                        except Exception:
                            total_7 = None

                        if isinstance(total_7, int):
                            home.ids.char_xp_total.text = f"Total 7d: {fmt_pt(total_7)} XP • 30d: {fmt_pt(int(exp_total_30))} XP"
                        else:
                            home.ids.char_xp_total.text = f"Total 30d: {fmt_pt(int(exp_total_30))} XP"
                        home.ids.char_xp_total.theme_text_color = "Primary"
                    elif not loading_gs:
                        home.ids.char_xp_total.text = "Histórico de XP indisponível. Toque no ícone ↗ para conferir."
                        home.ids.char_xp_total.theme_text_color = "Hint"

                    if not rows:
                        it = OneLineIconListItem(text=("Buscando dados no GuildStats..." if loading_gs else "Sem dados."))
                        it.add_widget(IconLeftWidget(icon="chart-line"))
                        xlist.add_widget(it)
                    else:
                        # Mostra sempre os últimos 7 dias (consecutivos). Se o GuildStats não listar um dia,
                        # exibimos 0 para ficar claro que não houve ganho/perda (ou que não foi trackeado).
                        try:
                            # Determina a data mais recente do histórico.
                            ref_dates = []
                            for rr in rows:
                                ds0 = str(rr.get("date") or "").strip()
                                if not ds0:
                                    continue
                                try:
                                    ref_dates.append(datetime.fromisoformat(ds0).date())
                                except Exception:
                                    continue
                            ref = max(ref_dates) if ref_dates else datetime.utcnow().date()

                            day_map = {}
                            for rr in rows:
                                ds0 = str(rr.get("date") or "").strip()
                                if not ds0:
                                    continue
                                try:
                                    ev_i = int(rr.get("exp_change_int") or 0)
                                except Exception:
                                    continue
                                # Se houver duplicata por data, soma (mais seguro).
                                day_map[ds0] = int(day_map.get(ds0, 0)) + int(ev_i)

                            for i in range(0, 7):
                                d = ref - timedelta(days=i)
                                ds = d.isoformat()
                                ev_i = int(day_map.get(ds, 0))
                                sec = f"{fmt_pt(ev_i)} XP"
                                icon = "trending-up" if ev_i >= 0 else "trending-down"
                                item = TwoLineIconListItem(text=ds, secondary_text=sec)
                                item.add_widget(IconLeftWidget(icon=icon))
                                xlist.add_widget(item)
                        except Exception:
                            # fallback: mostra os 7 primeiros registros como antes
                            for r in rows[:7]:
                                ds = str(r.get("date") or "").strip()
                                ev = r.get("exp_change_int")
                                try:
                                    ev_i = int(ev)
                                except Exception:
                                    continue
                                sec = f"{fmt_pt(ev_i)} XP"
                                icon = "trending-up" if ev_i >= 0 else "trending-down"
                                item = TwoLineIconListItem(text=ds, secondary_text=sec)
                                item.add_widget(IconLeftWidget(icon=icon))
                                xlist.add_widget(item)
                except Exception:
                    pass

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
    def search_character(self, *, silent: bool = False):
        home = self.root.get_screen("home")
        name = (home.ids.char_name.text or "").strip()
        if not name:
            if not silent:
                self.toast("Digite o nome do char.")
            return
    
        # Marca como "buscando" imediatamente (UI responsiva).
        self._char_set_loading(home, name)
        home.char_last_url = ""
        try:
            home.char_xp_source_url = ""
        except Exception:
            pass
    
        # Token para evitar que resultados de buscas antigas sobrescrevam a busca atual.
        try:
            self._char_search_seq = int(getattr(self, "_char_search_seq", 0)) + 1
        except Exception:
            self._char_search_seq = int(time.time() * 1000)
        seq = self._char_search_seq
    
        def done_stage1(ok: bool, payload_or_msg, url: str):
            # Só aplica se ainda for a busca atual
            if getattr(self, "_char_search_seq", None) != seq:
                return
    
            home.char_last_url = url
            try:
                if ok and isinstance(payload_or_msg, dict):
                    home.char_xp_source_url = str(payload_or_msg.get("gs_exp_url") or "")
                else:
                    home.char_xp_source_url = ""
            except Exception:
                home.char_xp_source_url = ""
    
            if ok:
                self._char_show_result(home, payload_or_msg, side_effects=True)
    
                # cache do world para a aba Favoritos
                try:
                    w = str((payload_or_msg or {}).get("world") or "").strip()
                    t = str((payload_or_msg or {}).get("title") or "").strip()
                    if w and w.upper() != "N/A" and t:
                        self._cache_set(f"fav_world:{t.lower()}", w)
                except Exception:
                    pass
                # cache do last_seen_online (para mostrar "há quanto tempo off" em Favoritos/Char)
                try:
                    t = str((payload_or_msg or {}).get("title") or "").strip()
                    stx = str((payload_or_msg or {}).get("status") or "").strip().lower()
                    if t and stx == "online":
                        self._set_cached_last_seen_online_iso(t, datetime.utcnow().isoformat())
                except Exception:
                    pass
                # cache do last_login (para mostrar "há quanto tempo off" em Favoritos)
                try:
                    t = str((payload_or_msg or {}).get("title") or "").strip()
                    stx = str((payload_or_msg or {}).get("status") or "").strip().lower()
                    lli = (payload_or_msg or {}).get("last_login_iso")
                    if t and stx == "offline" and isinstance(lli, str) and lli.strip():
                        self._set_cached_fav_last_login_iso(t, lli.strip())
                    elif t and stx == "online":
                        self._set_cached_fav_last_login_iso(t, None)
                except Exception:
                    pass
    
                if not silent:
                    self.toast("Char encontrado.")
            else:
                self._char_show_error(home, str(payload_or_msg))
                if not silent:
                    self.toast(str(payload_or_msg))
    
        def done_stage2(payload: dict, url: str):
            # Só aplica se ainda for a busca atual e se o char exibido for o mesmo
            if getattr(self, "_char_search_seq", None) != seq:
                return
            try:
                cur = getattr(home, "_last_char_payload", None) or {}
                cur_title = str(cur.get("title") or "").strip().lower()
                new_title = str(payload.get("title") or "").strip().lower()
                if cur_title and new_title and cur_title != new_title:
                    return
            except Exception:
                pass
    
            home.char_last_url = url
            try:
                home.char_xp_source_url = str(payload.get("gs_exp_url") or "")
            except Exception:
                pass
    
            # Re-render sem side-effects (não mexe em prefs/histórico/dashboard de novo)
            self._char_show_result(home, payload, side_effects=False)
    
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
    
                # Status: prioriza TibiaData (rápido). Dados oficiais (tibia.com) ficam para o "enriquecimento".
                status_raw = str(character.get("status") or "").strip().lower()
                status = "online" if status_raw == "online" else "offline"

                # Correção: TibiaData/tibia.com podem dar falso OFF.
                # A lista oficial de players online por world costuma ser a fonte mais confiável.
                world_status_checked = False
                try:
                    w_clean = str(world or "").strip()
                    if w_clean and w_clean.upper() != "N/A":
                        online_set = self._fetch_world_online_players(w_clean, timeout=12)
                        if online_set is not None:
                            world_status_checked = True
                            status = "online" if (title or name).strip().lower() in online_set else "offline"
                except Exception:
                    world_status_checked = False
    
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
    
                # Fonte do XP 30 dias (GuildStats tab=9)
                gs_exp_url = f"https://guildstats.eu/character?nick={urllib.parse.quote((title or name), safe='')}&tab=9"
    
                # Fallback robusto imediato: estimativa local (não depende de scraping)
                # (A etapa 2 tenta sobrescrever com valores do GuildStats se disponíveis.)
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
                    "guild_line": guild_line,
                    "house_line": house_line,
                    "deaths": deaths,
    
                    # XP 30 dias (GuildStats) — carregado em background (stage 2)
                    "exp_rows_30": [],
                    "exp_total_30": None,
                    "gs_exp_url": gs_exp_url,
                    "gs_exp_loading": True,

                    "_world_status_checked": bool(world_status_checked),
                }
    
                # "Última vez online" (offline duration)
                try:
                    if status == "online":
                        # atualiza sempre o instante em que vimos ONLINE (útil para calcular o OFF depois)
                        try:
                            self._set_cached_last_seen_online_iso(title, datetime.utcnow().isoformat())
                        except Exception:
                            pass
                        payload["last_login_iso"] = None
                        payload["last_login_ago"] = None
                    else:
                        # Opção 1 (mais fiel): usa offline_since (detectado pelo monitor em background) quando disponível.
                        off_iso = None
                        try:
                            fav_set = {str(x).strip().lower() for x in (self.favorites or []) if str(x).strip()}
                            if (title or "").strip().lower() in fav_set:
                                ent = self._get_service_last_entry(title)
                                if ent and (not bool(ent.get("online"))):
                                    v = ent.get("offline_since_iso")
                                    if isinstance(v, str) and v.strip():
                                        off_iso = v.strip()
                        except Exception:
                            off_iso = None

                        if off_iso:
                            try:
                                dt = datetime.fromisoformat(off_iso)
                                payload["last_login_iso"] = off_iso
                                payload["last_login_ago"] = self._format_ago_long(dt)
                            except Exception:
                                payload["last_login_iso"] = None
                                payload["last_login_ago"] = None
                        else:
                            # Fallback: último instante em que vimos ONLINE (quando o app estava aberto)
                            seen_iso = self._get_cached_last_seen_online_iso(title)
                            if seen_iso:
                                try:
                                    dt = datetime.fromisoformat(str(seen_iso).strip())
                                    payload["last_login_iso"] = str(seen_iso).strip()
                                    payload["last_login_ago"] = self._format_ago_long(dt)
                                except Exception:
                                    payload["last_login_iso"] = None
                                    payload["last_login_ago"] = None
                            else:
                                # Último recurso (não é logout): TibiaData "Last Login".
                                last_dt = None
                                try:
                                    last_dt = self._extract_last_login_dt_from_tibiadata(data)
                                except Exception:
                                    last_dt = None
                                if last_dt:
                                    payload["last_login_iso"] = last_dt.isoformat()
                                    payload["last_login_ago"] = self._format_ago_long(last_dt)
                                else:
                                    payload["last_login_iso"] = None
                                    payload["last_login_ago"] = None
                except Exception:
                    payload["last_login_iso"] = None
                    payload["last_login_ago"] = None
    
                # Mostra o resultado básico imediatamente.
                Clock.schedule_once(lambda *_: done_stage1(True, payload, url), 0)
    
                # Se outra busca começou, não continua.
                if getattr(self, "_char_search_seq", None) != seq:
                    return
    
                # -----------------------------------------------------------
                # Stage 2: Enriquecimento (GuildStats + status oficial tibia.com)
                # - roda em background
                # - não bloqueia a exibição do resultado básico
                # -----------------------------------------------------------
                try:
                    # Status "oficial": tenta novamente via /v4/world (mais confiável) e evita sobrescrever se já checamos.
                    if not bool(payload.get("_world_status_checked")):
                        try:
                            w_clean2 = str(payload.get("world") or "").strip()
                            if w_clean2 and w_clean2.upper() != "N/A":
                                online_set2 = self._fetch_world_online_players(w_clean2, timeout=12)
                                if online_set2 is not None:
                                    payload["_world_status_checked"] = True
                                    payload["status"] = "online" if (title or name).strip().lower() in online_set2 else "offline"
                        except Exception:
                            pass

                    # Tibia.com apenas como fallback (pode dar falso OFF)
                    if not bool(payload.get("_world_status_checked")):
                        try:
                            online_web = is_character_online_tibia_com(title or name, world or "")
                        except Exception:
                            online_web = None
                        if online_web is True:
                            payload["status"] = "online"
                        elif online_web is False:
                            payload["status"] = "offline"
    
                    # Atualiza last_login_* com base no status refinado
                    try:
                        if payload.get("status") == "online":
                            try:
                                self._set_cached_last_seen_online_iso(title, datetime.utcnow().isoformat())
                            except Exception:
                                pass
                            payload["last_login_iso"] = None
                            payload["last_login_ago"] = None
                        else:
                            # se for favorito e o serviço marcou offline_since, usa isso
                            off_iso = None
                            try:
                                fav_set = {str(x).strip().lower() for x in (self.favorites or []) if str(x).strip()}
                                if (title or "").strip().lower() in fav_set:
                                    ent = self._get_service_last_entry(title)
                                    if ent and (not bool(ent.get("online"))):
                                        v = ent.get("offline_since_iso")
                                        if isinstance(v, str) and v.strip():
                                            off_iso = v.strip()
                            except Exception:
                                off_iso = None

                            if off_iso:
                                try:
                                    dt = datetime.fromisoformat(off_iso)
                                    payload["last_login_iso"] = off_iso
                                    payload["last_login_ago"] = self._format_ago_long(dt)
                                except Exception:
                                    pass
                            else:
                                seen_iso = self._get_cached_last_seen_online_iso(title)
                                if seen_iso:
                                    try:
                                        dt = datetime.fromisoformat(str(seen_iso).strip())
                                        payload["last_login_iso"] = str(seen_iso).strip()
                                        payload["last_login_ago"] = self._format_ago_long(dt)
                                    except Exception:
                                        pass
                    except Exception:
                        pass
    
                    # XP últimos ~30 dias (GuildStats tab=9)
                    exp_rows_30 = []
                    exp_total_30 = None
                    try:
                        key = f"gs_exp_rows:{(title or name).strip().lower()}"
                        rows = self._cache_get(key, ttl_seconds=10 * 60)
                        if rows is None:
                            rows = fetch_guildstats_exp_changes(title or name, light_only=self._is_android())
                            try:
                                self._cache_set(key, rows or [])
                            except Exception:
                                pass
    
                        if rows:
                            dates = []
                            for r in rows:
                                ds = str(r.get("date") or "")
                                try:
                                    dates.append(datetime.fromisoformat(ds).date())
                                except Exception:
                                    pass
                            ref = max(dates) if dates else datetime.utcnow().date()
                            cutoff = ref - timedelta(days=30)
    
                            for r in rows:
                                ds = str(r.get("date") or "")
                                try:
                                    d = datetime.fromisoformat(ds).date()
                                except Exception:
                                    continue
                                if d < cutoff:
                                    continue
                                exp_rows_30.append(r)
    
                            exp_rows_30.sort(key=lambda x: x.get("date", ""), reverse=True)
                            exp_total_30 = int(sum(int(r.get("exp_change_int") or 0) for r in exp_rows_30))
                    except Exception:
                        exp_rows_30 = []
                        exp_total_30 = None
    
                    payload["exp_rows_30"] = exp_rows_30
                    payload["exp_total_30"] = exp_total_30
                    payload["gs_exp_loading"] = False
    
                    # XP lost por morte (GuildStats tab=5) — tenta sobrescrever a estimativa
                    try:
                        deaths2 = payload.get("deaths") or []
                        xp_list = []
                        if deaths2:
                            key2 = f"gs_death_xp:{(title or name).strip().lower()}"
                            xp_list = self._cache_get(key2, ttl_seconds=6 * 3600)
                            if xp_list is None:
                                try:
                                    xp_list = fetch_guildstats_deaths_xp(title or name, light_only=self._is_android())
                                except Exception:
                                    xp_list = []
                                try:
                                    self._cache_set(key2, xp_list or [])
                                except Exception:
                                    pass
    
                        if xp_list:
                            for i, d in enumerate(deaths2):
                                if i >= len(xp_list):
                                    break
                                if isinstance(d, dict) and xp_list[i]:
                                    d["exp_lost"] = xp_list[i]
                            payload["deaths"] = deaths2
                    except Exception:
                        pass
    
                except Exception:
                    # não falha a busca básica por conta do enrichment
                    pass
    
                # Aplica o enrichment na UI (sem side-effects)
                if getattr(self, "_char_search_seq", None) == seq:
                    Clock.schedule_once(lambda *_: done_stage2(payload, url), 0)
    
            except Exception as e:
                Clock.schedule_once(lambda *_: done_stage1(False, f"Erro: {e}", ""), 0)
    
        threading.Thread(target=worker, daemon=True).start()
    
    
    def open_last_in_browser(self):
        home = self.root.get_screen("home")
        url = getattr(home, "char_last_url", "") or ""
        if not url:
            self.toast("Sem link ainda. Faça uma busca primeiro.")
            return
        webbrowser.open(url)

    def open_char_xp_source(self):
        """Abre a fonte do histórico de XP (GuildStats tab=9) no navegador."""
        home = self.root.get_screen("home")
        url = getattr(home, "char_xp_source_url", "") or ""
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
            # mantém serviço em sync
            try:
                self._maybe_start_fav_monitor_service()
            except Exception:
                pass
            self.refresh_favorites_list()
            self.toast("Adicionado aos favoritos.")
        else:
            self.toast("Já está nos favoritos.")

    # --------------------
    # Favorites tab
    # --------------------
    def refresh_favorites_list(self, silent: bool = False, force: bool = False):
        """Renderiza/atualiza a lista de Favoritos sem travar a UI.

        Otimizações importantes:
        - Evita `clear_widgets()` e rebuild completo a cada refresh silencioso.
        - Evita iniciar múltiplos workers simultâneos (threads em cascata).
        """
        try:
            home = self.root.get_screen("home")
            container = home.ids.fav_list
        except Exception:
            return

        # Normaliza lista + gera assinatura (para saber se precisa rebuild)
        names = [str(n) for n in (self.favorites or []) if str(n).strip()]
        signature = [n.strip().lower() for n in names]

        # Estado do serviço (compartilhado via favorites.json)
        service_last = {}
        try:
            st_svc = self._load_fav_service_state_cached()
            v = st_svc.get("last", {}) if isinstance(st_svc, dict) else {}
            service_last = v if isinstance(v, dict) else {}
        except Exception:
            service_last = {}

        need_rebuild = bool(force)
        try:
            if getattr(self, "_fav_rendered_signature", None) != signature:
                need_rebuild = True
            if not isinstance(getattr(self, "_fav_items", None), dict):
                need_rebuild = True
        except Exception:
            need_rebuild = True

        # Se não for rebuild, só garante que ainda temos todos os itens renderizados.
        if not need_rebuild:
            try:
                for n in names:
                    if (n or "").strip().lower() not in self._fav_items:
                        need_rebuild = True
                        break
            except Exception:
                need_rebuild = True

        if need_rebuild:
            try:
                container.clear_widgets()
            except Exception:
                pass
            self._fav_items = {}
            self._fav_rendered_signature = signature

            if not names:
                try:
                    item = OneLineIconListItem(text="Sem favoritos. Adicione no Char.")
                    item.add_widget(IconLeftWidget(icon="star-outline"))
                    container.add_widget(item)
                except Exception:
                    pass
                return

            # Render rápido com cache (sem fazer requests aqui)
            for name in names:
                key = (name or "").strip().lower()

                # Preferir estado do serviço se estiver "fresco"
                svc = service_last.get(key) if isinstance(service_last, dict) else None
                use_svc = bool(isinstance(svc, dict) and self._service_entry_is_fresh(svc, max_age_s=90))

                if use_svc:
                    is_on = bool(svc.get("online"))
                    state = "online" if is_on else "offline"
                    off_iso = None if is_on else (svc.get("offline_since_iso") if isinstance(svc.get("offline_since_iso"), str) else None)
                    seen_iso = (svc.get("last_seen_online_iso") if isinstance(svc.get("last_seen_online_iso"), str) else None)

                    # sincroniza caches locais
                    try:
                        if not hasattr(self, "_fav_status_cache"):
                            self._fav_status_cache = {}
                        self._fav_status_cache[key] = state
                        self._cache_set(f"fav_status:{key}", state)
                    except Exception:
                        pass
                    try:
                        if state == "online":
                            self._set_cached_offline_since_iso(name, None)
                        elif off_iso:
                            self._set_cached_offline_since_iso(name, off_iso)
                    except Exception:
                        pass
                    try:
                        if is_on and seen_iso:
                            self._set_cached_last_seen_online_iso(name, seen_iso)
                    except Exception:
                        pass
                else:
                    state = None if force else self._get_cached_fav_status(name)
                    off_iso = self._get_cached_offline_since_iso(name) if str(state).strip().lower() == "offline" else None
                    seen_iso = self._get_cached_last_seen_online_iso(name) if str(state).strip().lower() == "offline" else None

                secondary, color = self._fav_status_presentation(state, off_iso, seen_iso, None)

                try:
                    item = TwoLineIconListItem(text=name, secondary_text=secondary)
                    item.add_widget(IconLeftWidget(icon="account"))
                    item.secondary_theme_text_color = "Custom"
                    item.secondary_text_color = color
                    item.bind(on_release=lambda _item, n=name: self._fav_actions(n, _item))
                    self._fav_items[name.strip().lower()] = item
                    container.add_widget(item)
                except Exception:
                    pass
        else:
            # Sem rebuild: atualiza texto/cor baseado no cache atual (barato)
            for name in names:
                try:
                    key = (name or "").strip().lower()
                    item = self._fav_items.get(key)
                    if not item:
                        continue
                    svc = service_last.get(key) if isinstance(service_last, dict) else None
                    use_svc = bool(isinstance(svc, dict) and self._service_entry_is_fresh(svc, max_age_s=90))

                    if use_svc:
                        is_on = bool(svc.get("online"))
                        state = "online" if is_on else "offline"
                        off_iso = None if is_on else (svc.get("offline_since_iso") if isinstance(svc.get("offline_since_iso"), str) else None)
                        seen_iso = (svc.get("last_seen_online_iso") if isinstance(svc.get("last_seen_online_iso"), str) else None)
                        try:
                            if not hasattr(self, "_fav_status_cache"):
                                self._fav_status_cache = {}
                            self._fav_status_cache[key] = state
                            self._cache_set(f"fav_status:{key}", state)
                        except Exception:
                            pass
                        try:
                            if state == "online":
                                self._set_cached_offline_since_iso(name, None)
                            elif off_iso:
                                self._set_cached_offline_since_iso(name, off_iso)
                        except Exception:
                            pass
                        try:
                            if is_on and seen_iso:
                                self._set_cached_last_seen_online_iso(name, seen_iso)
                        except Exception:
                            pass
                    else:
                        state = None if force else self._get_cached_fav_status(name)
                        off_iso = self._get_cached_offline_since_iso(name) if str(state).strip().lower() == "offline" else None
                        seen_iso = self._get_cached_last_seen_online_iso(name) if str(state).strip().lower() == "offline" else None

                    secondary, color = self._fav_status_presentation(state, off_iso, seen_iso, None)
                    item.secondary_text = secondary
                    item.secondary_text_color = color
                except Exception:
                    pass

        # Decide quem precisa de refresh (TTL) e dispara worker em background
        names_to_check: list[str] = []
        for name in names:
            try:
                # Se o serviço acabou de atualizar, não precisamos refazer requests.
                k = (name or "").strip().lower()
                svc = service_last.get(k) if isinstance(service_last, dict) else None
                if isinstance(svc, dict) and self._service_entry_is_fresh(svc, max_age_s=90) and not force:
                    continue

                state = None if force else self._get_cached_fav_status(name)
                if force or state is None or self._fav_status_needs_refresh(name, ttl_seconds=45):
                    names_to_check.append(name)
            except Exception:
                names_to_check.append(name)

        if not silent and force:
            try:
                Snackbar(text="Atualizando favoritos...").open()
            except Exception:
                pass

        if not names_to_check:
            return

        # Evita empilhar threads em refresh automático.
        try:
            if bool(getattr(self, "_fav_refreshing", False)) and (not force):
                return
        except Exception:
            pass

        self._fav_status_job_id += 1
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
            safe_world = urllib.parse.quote(str(world).strip())
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
    def _fav_status_presentation(
        self,
        state,
        offline_since_iso: Optional[str] = None,
        last_seen_online_iso: Optional[str] = None,
        fallback_last_login_iso: Optional[str] = None,
    ) -> tuple[str, tuple]:
        s = str(state).strip().lower() if state is not None else ""
        if s == "online" or state is True:
            return "Online", (0.2, 0.75, 0.35, 1)
        if s == "offline" or state is False:
            extra = ""
            iso = offline_since_iso or last_seen_online_iso or fallback_last_login_iso
            if iso:
                try:
                    dt = datetime.fromisoformat(str(iso).strip())
                    ago = self._format_ago_short(dt)
                    if ago:
                        extra = f" • {ago}"
                except Exception:
                    extra = ""
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
        """Atualiza o status (Online/Offline) no item da lista de favoritos e no cache.

        Este método é chamado via Clock no thread principal.
        """
        try:
            key = (name or "").strip().lower()
            if not key:
                return

            st_low = str(state).strip().lower()

            # ONLINE: atualiza o "last seen online" e limpa o offline_since
            if st_low == "online":
                try:
                    now_iso = last_seen_online_iso or datetime.utcnow().isoformat()
                    self._set_cached_last_seen_online_iso(name, now_iso)
                except Exception:
                    pass

                try:
                    self._set_cached_offline_since_iso(name, None)
                except Exception:
                    pass

            # OFFLINE: usa offline_since se fornecido (preferível a "Last Login").
            if st_low == "offline" and offline_since_iso:
                try:
                    self._set_cached_offline_since_iso(name, str(offline_since_iso).strip())
                except Exception:
                    pass

            self._fav_status_cache[key] = state
            try:
                self._cache_set(f"fav_status:{key}", state)
            except Exception:
                pass

            item = self._fav_items.get(key)
            if not item:
                return

            off_since = offline_since_iso or self._get_cached_offline_since_iso(name)
            seen = last_seen_online_iso or self._get_cached_last_seen_online_iso(name)

            # Para Favoritos, evitamos usar "Last Login" como fallback porque não representa logout.
            label, color = self._fav_status_presentation(state, off_since, seen, None)
            item.secondary_text = label
            item.secondary_text_color = color
        except Exception:
            pass

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
                # mantém serviço em sync
                try:
                    self._maybe_start_fav_monitor_service()
                except Exception:
                    pass
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

    def _apply_fav_status_updates(self, updates, job_id: int) -> None:
        """Aplica vários updates de status de uma vez no thread principal.

        Isso evita `Clock.schedule_once` em loop (um por favorito), que pode engasgar a UI.
        """
        try:
            if job_id != self._fav_status_job_id:
                return
            if not updates:
                return
            for u in updates:
                try:
                    name, st, off_iso, seen_iso = u
                    self._set_fav_item_status(name, st, off_iso, seen_iso, None)
                except Exception:
                    continue
        except Exception:
            pass

    def _refresh_fav_statuses_worker(self, names: List[str], job_id: int):
        """Atualiza o status dos favoritos em background, minimizando chamadas e falsos OFF.

        Em vez de checar 1 a 1 (muito request e pode dar falso OFF), agrupamos por world e
        consultamos o /v4/world/{world} (lista de online players).

        Otimização: calcula tudo em background e aplica numa única chamada no thread principal.
        """
        try:
            # (name, status, offline_since_iso, last_seen_online_iso)
            updates: list[tuple[str, str, Optional[str], Optional[str]]] = []

            # 1) resolve world de cada char (cache -> TibiaData /v4/character)
            name_to_world: dict[str, str] = {}
            unknown: list[str] = []

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
            by_world: dict[str, list[str]] = {}
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

                    seen_iso: Optional[str] = None
                    off_iso: Optional[str] = None

                    if st == "online":
                        seen_iso = datetime.utcnow().isoformat()
                        off_iso = None
                    else:
                        seen_iso = self._get_cached_last_seen_online_iso(n)
                        off_iso = self._get_cached_offline_since_iso(n)
                        # Se antes estava ONLINE e agora OFFLINE, marca o instante do logout detectado.
                        try:
                            prev = str(self._get_cached_fav_status(n) or "").strip().lower()
                            if prev == "online" and not off_iso:
                                off_iso = datetime.utcnow().isoformat()
                        except Exception:
                            pass

                    updates.append((n, st, off_iso, seen_iso))

            # 4) fallback (se não conseguimos world): tenta método antigo (tibia.com / endpoint do char)
            for n in unknown:
                if job_id != self._fav_status_job_id:
                    return

                st = self._fetch_character_online_state(n)
                if st is None:
                    # mantém último estado se existir, senão offline
                    k = (n or "").strip().lower()
                    st = getattr(self, "_fav_status_cache", {}).get(k) or "offline"

                seen_iso: Optional[str] = None
                off_iso: Optional[str] = None
                if str(st).strip().lower() == "online":
                    seen_iso = datetime.utcnow().isoformat()
                    off_iso = None
                else:
                    seen_iso = self._get_cached_last_seen_online_iso(n)
                    off_iso = self._get_cached_offline_since_iso(n)
                    try:
                        prev = str(self._get_cached_fav_status(n) or "").strip().lower()
                        if prev == "online" and not off_iso:
                            off_iso = datetime.utcnow().isoformat()
                    except Exception:
                        pass

                updates.append((n, str(st), off_iso, seen_iso))

            # aplica tudo de uma vez no thread principal
            Clock.schedule_once(lambda _dt, ups=updates: self._apply_fav_status_updates(ups, job_id), 0)
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
        """Dialog de ações do boss (favoritar/copiar/abrir) com layout que não quebra em telas pequenas."""
        try:
            name = str(boss_dict.get("boss") or boss_dict.get("name") or "Boss").strip()
            chance = str(boss_dict.get("chance") or "").strip()
            status = str(boss_dict.get("status") or "").strip()
        except Exception:
            return

        url = self._boss_wiki_url(name)
        is_fav = self.boss_is_favorite(name)

        txt = "\n".join([x for x in [f"Chance: {chance}" if chance else "", status] if x]).strip() or " "

        # Conteúdo (texto + ações em lista) — evita estourar/ficar “fora” do dialog
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        lbl = MDLabel(text=txt, theme_text_color="Secondary", size_hint_y=None)
        lbl.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1] + dp(6)))
        content.add_widget(lbl)

        def close(*_):
            try:
                dlg.dismiss()
            except Exception:
                pass

        def toggle(*_):
            fav = self.boss_toggle_favorite(name)
            self.toast("Favoritado." if fav else "Removido dos favoritos.")
            close()
            self.bosses_apply_filters()
            self.dashboard_refresh()

        def copy(*_):
            try:
                Clipboard.copy(url)
                self.toast("Link copiado.")
            except Exception:
                self.toast("Não consegui copiar.")
            close()

        def open_url(*_):
            try:
                webbrowser.open(url)
            except Exception:
                self.toast("Não consegui abrir o navegador.")
            close()

        actions = [
            (("Remover dos favoritos" if is_fav else "Adicionar aos favoritos"), ("star" if is_fav else "star-outline"), toggle),
            ("Copiar link", "content-copy", copy),
            ("Abrir no navegador", "open-in-new", open_url),
        ]

        for label, icon, cb in actions:
            it = OneLineIconListItem(text=label)
            it.add_widget(IconLeftWidget(icon=icon))
            it.bind(on_release=cb)
            content.add_widget(it)

        dlg = MDDialog(
            title=name,
            type="custom",
            content_cls=content,
            buttons=[MDFlatButton(text="FECHAR", on_release=close)],
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
            """Update Bosses world list/menu on the main thread.

            Defensive: exceptions here can hard-crash some Android/Kivy builds.
            """
            try:
                if worlds is None:
                    worlds = []
                elif not isinstance(worlds, (list, tuple)):
                    try:
                        worlds = list(worlds)
                    except Exception:
                        worlds = []

                if "boss_status" in scr.ids:
                    scr.ids.boss_status.text = f"Worlds: {len(worlds)}"

                # Restore last selected world (if field exists)
                field = getattr(scr.ids, "world_field", None)
                try:
                    last = str(self._prefs_get("boss_last_world", "") or "").strip()
                    if field is not None and last:
                        field.text = last
                except Exception:
                    pass

                arrow = getattr(scr.ids, "world_drop", None)
                row = getattr(scr.ids, "world_row", None)
                caller = row or field or arrow
                if caller is None:
                    return

                # Build dropdown items (cap to avoid very tall/heavy menus)
                items = [
                    {"text": w, "on_release": (lambda x=w: self._select_world(x))}
                    for w in (worlds or [])[:400]
                ]

                # Recreate menu safely
                if getattr(self, "_menu_world", None):
                    try:
                        self._menu_world.dismiss()
                    except Exception:
                        pass

                from kivymd.uix.menu import MDDropdownMenu
                from kivy.metrics import dp

                base_w = getattr(caller, "width", 0) or dp(280)
                menu_w = max(dp(220), min(dp(360), base_w))

                # Build the dropdown menu. Some KivyMD builds differ in supported kwargs,
                # so we try the more complete config first and fall back if needed.
                try:
                    self._menu_world = MDDropdownMenu(
                        caller=caller,
                        items=items,
                        width=menu_w,
                        max_height=dp(420),
                        position="auto",
                        border_margin=dp(12),
                    )
                except TypeError:
                    self._menu_world = MDDropdownMenu(
                        caller=caller,
                        items=items,
                        width=menu_w,
                        max_height=dp(420),
                    )

                # Extra safety: force the menu to grow inside the screen when supported.
                try:
                    if hasattr(self._menu_world, "hor_growth"):
                        self._menu_world.hor_growth = "right"
                    if hasattr(self._menu_world, "ver_growth"):
                        self._menu_world.ver_growth = "down"
                except Exception:
                    pass

            except Exception:
                try:
                    from kivy.logger import Logger
                    Logger.exception("Bosses: failed to build worlds menu")
                except Exception:
                    pass
        def run():
            try:
                worlds = worker()
                Clock.schedule_once(lambda *_: done(worlds), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(scr.ids.boss_status, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()



    def open_world_menu(self):
        # Open the World dropdown and keep it inside screen bounds.
        try:
            from kivy.metrics import dp

            screen = self.root.get_screen("bosses")
            field = getattr(screen.ids, "world_field", None)
            arrow = getattr(screen.ids, "world_drop", None)
            row = getattr(screen.ids, "world_row", None)
            caller = row or field or arrow
            if not self._menu_world or not caller:
                return

            # Width: prefer the full row width (field + arrow), clamped to screen.
            w = getattr(caller, "width", 0) or 0
            if w <= 1 and field is not None:
                w = field.width
            w = max(dp(240), min(w, self.root.width - dp(32)))

            # Height: avoid going behind bottom bar.
            max_h = min(dp(360), max(dp(160), self.root.height - dp(260)))

            try:
                self._menu_world.caller = caller
                self._menu_world.width = w
                self._menu_world.max_height = max_h

                # Keep a margin from the screen edges.
                try:
                    if hasattr(self._menu_world, "border_margin"):
                        self._menu_world.border_margin = dp(12)
                except Exception:
                    pass

                # Force growth to the right to avoid negative X on some layouts.
                if hasattr(self._menu_world, "hor_growth"):
                    self._menu_world.hor_growth = "right"
                if hasattr(self._menu_world, "ver_growth"):
                    self._menu_world.ver_growth = "down"
                if hasattr(self._menu_world, "position"):
                    self._menu_world.position = "auto"
            except Exception:
                pass

            self._menu_world.open()

            # Final safety clamp (some Android devices ignore border_margin/hor_growth).
            try:
                from kivy.core.window import Window
                from kivy.clock import Clock

                def _clamp_menu_pos(*_a):
                    try:
                        margin = dp(8)
                        target = None
                        # KivyMD may expose the visible container as `menu`.
                        if hasattr(self._menu_world, "menu"):
                            target = self._menu_world.menu
                        elif hasattr(self._menu_world, "_menu"):
                            target = self._menu_world._menu
                        else:
                            target = self._menu_world

                        if not hasattr(target, "x") or not hasattr(target, "width"):
                            return
                        # Clamp X inside the window.
                        max_x = Window.width - target.width - margin
                        if max_x < margin:
                            return
                        target.x = max(margin, min(target.x, max_x))
                    except Exception:
                        pass

                Clock.schedule_once(_clamp_menu_pos, 0)
            except Exception:
                pass
        except Exception:
            pass

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
    def update_boosted(self, silent: bool = False, force: bool = False):
        """Atualiza Boosted Creature/Boss sem travar a UI.

        IMPORTANTE: em versões anteriores havia um loop de refresh que criava
        threads infinitas e deixava o app lento. Aqui adicionamos:
        - in-flight guard (não iniciar outro worker se já existe um rodando)
        - throttling (em updates silenciosos, não fazer fetch em sequência)
        """
        scr = self.root.get_screen("boosted")

        # Evita disparar vários downloads em cascata (principal causa do "travamento")
        now_mono = time.monotonic()
        min_interval = 90.0 if silent else 0.0  # silencioso: no máx. ~1x por 90s
        try:
            with self._boosted_lock:
                if self._boosted_inflight:
                    return
                if (not force) and min_interval and (now_mono - float(self._boosted_last_fetch_mono or 0.0) < min_interval):
                    return
                self._boosted_inflight = True
                self._boosted_last_fetch_mono = now_mono
        except Exception:
            # se por algum motivo o lock falhar, ainda tentamos seguir
            pass

        if not silent:
            scr.ids.boost_status.text = "Atualizando..."
        else:
            # não suja o status se for atualização usada pelo dashboard
            if not (scr.ids.boost_status.text or "").strip():
                scr.ids.boost_status.text = "Atualizando..."

        def run():
            data = None
            err = None
            try:
                data = fetch_boosted()
            except Exception as e:
                err = e

            def finish(*_):
                # libera o in-flight guard SEMPRE (sucesso ou erro)
                try:
                    with self._boosted_lock:
                        self._boosted_inflight = False
                except Exception:
                    pass

                if err is not None:
                    if not silent:
                        try:
                            scr.ids.boost_status.text = f"Erro: {err}"
                        except Exception:
                            pass
                    return

                self._boosted_done(data, silent=silent)

            Clock.schedule_once(finish, 0)

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

        # sprites (quando disponíveis)
        try:
            if "boost_creature_sprite" in scr.ids:
                scr.ids.boost_creature_sprite.source = data.get("creature_image") or ""
            if "boost_boss_sprite" in scr.ids:
                scr.ids.boost_boss_sprite.source = data.get("boss_image") or ""
        except Exception:
            pass

        # cache + histórico (7 dias)
        try:
            self._cache_set("boosted", data)
        except Exception:
            pass

        # também atualiza o card do Dashboard (Home)
        try:
            home = self.root.get_screen("home")
            hids = home.ids
            if "dash_boost_creature" in hids:
                hids.dash_boost_creature.text = data.get("creature", "-") or "-"
            if "dash_boost_boss" in hids:
                hids.dash_boost_boss.text = data.get("boss", "-") or "-"
            if "dash_boost_creature_sprite" in hids:
                hids.dash_boost_creature_sprite.source = data.get("creature_image") or ""
            if "dash_boost_boss_sprite" in hids:
                hids.dash_boost_boss_sprite.source = data.get("boss_image") or ""
            ts = self.cache.get("boosted", {}).get("ts", "")
            if "dash_boost_updated" in hids:
                hids.dash_boost_updated.text = f"Atualizado: {ts.split('T')[0] if ts else ''}"
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

        # NÃO chamar dashboard_refresh() aqui.
        # O _boosted_done já atualiza diretamente os widgets do Dashboard e chamar
        # dashboard_refresh() cria um ciclo indireto (e era a principal causa de
        # travamentos/threads em cascata em Android).

    # --------------------
    # Training (Exercise)
    # --------------------
    def _menu_fix_position(self, menu):
        """Tenta manter dropdown dentro da tela (KivyMD 1.2)."""
        try:
            # Se disponível, força crescimento horizontal para a esquerda.
            menu.hor_growth = "left"
        except Exception:
            pass
        try:
            menu.ver_growth = "down"
        except Exception:
            pass
        try:
            # Margem para evitar colar na borda.
            menu.border_margin = dp(16)
        except Exception:
            pass

    def _clamp_dropdown_to_window(self, menu, _tries: int = 3):
        """Garante que o dropdown não fique fora da tela (extra p/ Android)."""
        try:
            from kivy.core.window import Window
        except Exception:
            return

        try:
            w = float(getattr(menu, "width", 0) or 0)
            h = float(getattr(menu, "height", 0) or 0)
        except Exception:
            return

        # Em alguns devices o size ainda não está pronto no mesmo frame.
        if w <= 0 or h <= 0:
            if _tries > 0:
                Clock.schedule_once(lambda *_: self._clamp_dropdown_to_window(menu, _tries=_tries - 1), 0)
            return

        m = dp(8)
        try:
            menu.x = max(m, min(menu.x, Window.width - w - m))
        except Exception:
            pass
        try:
            menu.y = max(m, min(menu.y, Window.height - h - m))
        except Exception:
            pass

    def training_open_menu(self, which: str):
        """Abre menus do Treino sem deixar o menu/selection sair da tela."""
        scr = self.root.get_screen("training")
        self._ensure_training_menus()

        # Evita o menu de contexto do Android (Select All / Paste) em campos readonly.
        for _id in (
            "skill_field",
            "voc_field",
            "weapon_field",
            "from_level",
            "percent_left",
            "to_level",
            "loyalty",
        ):
            w = scr.ids.get(_id)
            if w is not None:
                try:
                    w.focus = False
                except Exception:
                    pass

        menu = None
        if which == "skill":
            menu = self._menu_skill
        elif which in ("voc", "vocation"):
            menu = self._menu_vocation
        elif which == "weapon":
            menu = self._menu_weapon

        if menu is None:
            return

        menu.open()
        # Ajusta posição no próximo frame (quando o tamanho do menu já foi calculado).
        Clock.schedule_once(lambda *_: self._clamp_dropdown_to_window(menu), 0)

    def _ensure_training_menus(self):
        scr = self.root.get_screen("training")

        # ⚠️ Em telas menores, o dropdown pode "vazar" para fora da tela.
        # Aqui o melhor caller é o botão de seta (menu-down) + hor_growth="left".
        # Assim o menu cresce para a esquerda e fica visível.
        skill_caller = scr.ids.get("skill_drop") or scr.ids.get("skill_field")
        voc_caller = scr.ids.get("voc_drop") or scr.ids.get("voc_field")
        weapon_caller = scr.ids.get("weapon_drop") or scr.ids.get("weapon_field")

        if self._menu_skill is None:
            skills = ["Sword", "Axe", "Club", "Distance", "Fist Fighting", "Shielding", "Magic Level"]
            self._menu_skill = MDDropdownMenu(
                caller=skill_caller,
                items=[{"text": s, "on_release": (lambda x=s: self._set_training_skill(x))} for s in skills],
                width_mult=4,
                max_height=dp(320),
                position="auto",
            )
            self._menu_fix_position(self._menu_skill)

        if 'voc_drop' in scr.ids and 'voc_field' in scr.ids:
            if self._menu_vocation is None:
                vocs = ["Knight", "Paladin", "Sorcerer", "Druid", "Monk", "None"]
                self._menu_vocation = MDDropdownMenu(
                    caller=voc_caller,
                    items=[{"text": v, "on_release": (lambda x=v: self._set_training_voc(x))} for v in vocs],
                    width_mult=4,
                    max_height=dp(260),
                    position="auto",
                )
                self._menu_fix_position(self._menu_vocation)

        if 'weapon_drop' in scr.ids and 'weapon_field' in scr.ids:
            if self._menu_weapon is None:
                weapons = ["Standard (500)", "Enhanced (1800)", "Lasting (14400)"]
                self._menu_weapon = MDDropdownMenu(
                    caller=weapon_caller,
                    items=[{"text": w, "on_release": (lambda x=w: self._set_training_weapon(x))} for w in weapons],
                    width_mult=4,
                    max_height=dp(260),
                    position="auto",
                )
                self._menu_fix_position(self._menu_weapon)

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
    try:
        TibiaToolsApp().run()
    except Exception:
        _write_crash_log(traceback.format_exc())
        raise