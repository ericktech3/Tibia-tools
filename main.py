# Tibia Tools (Android) - main.py
# Hotfix: evita "abre e fecha" no Android com:
# - imports preguiçosos (core/Core) + tela de erro
# - log de crash em arquivo
# - Portrait/Vertical (via buildozer.spec)

from __future__ import annotations

import os
import sys
import time
import traceback
import importlib
from typing import Any, Dict, Optional, Tuple

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView


def _try_get_storage_dir() -> str:
    """
    Melhor esforço para achar um diretório gravável no Android.
    Se não der, usa o diretório atual.
    """
    # Android (python-for-android) geralmente tem android.storage
    try:
        from android.storage import app_storage_path  # type: ignore
        p = app_storage_path()
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass

    # user home / cwd
    for p in (os.path.expanduser("~"), os.getcwd()):
        try:
            os.makedirs(p, exist_ok=True)
            test = os.path.join(p, ".writable_test")
            with open(test, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test)
            return p
        except Exception:
            continue
    return os.getcwd()


_CRASH_DIR = _try_get_storage_dir()
_CRASH_FILE = os.path.join(_CRASH_DIR, "tibia_tools_crash.log")


def _append_crash_log(text: str) -> None:
    try:
        os.makedirs(os.path.dirname(_CRASH_FILE), exist_ok=True)
        with open(_CRASH_FILE, "a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except Exception:
        # último recurso: stderr
        try:
            sys.stderr.write(text + "\n")
        except Exception:
            pass


def _excepthook(exctype, value, tb):
    msg = "".join(traceback.format_exception(exctype, value, tb))
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_crash_log(f"\n[{stamp}] Uncaught exception:\n{msg}\n")
    # mantém comportamento padrão
    try:
        sys.__excepthook__(exctype, value, tb)
    except Exception:
        pass


sys.excepthook = _excepthook


def import_core_modules():
    """
    Importa os módulos do pacote `core` (minúsculo).

    Importante: no Android/Linux o filesystem é *case-sensitive*.
    Então 'Core' e 'core' são coisas diferentes. Padronize tudo em 'core/'.
    """
    try:
        from core import state as state_mod
        from core import tibia as tibia_mod
        from core import utilities as util_mod
        return tibia_mod, state_mod, util_mod
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "Não achei o pacote 'core'. Confirme que existe a pasta 'core/' na raiz do projeto "
            "(tudo minúsculo) e que ela contém '__init__.py'."
        ) from e

class FavoriteRow(RecycleDataViewBehavior, BoxLayout):
    """
    View do RecycleView para favoritos.
    IMPORTANTE: propriedades precisam existir para evitar crash em alguns Androids.
    """
    name = StringProperty("")
    index = NumericProperty(0)


KV = r"""
#:import dp kivy.metrics.dp

<FavoriteRow>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(44)
    padding: dp(10), dp(8)
    spacing: dp(10)
    canvas.before:
        Color:
            rgba: (0.12, 0.12, 0.14, 1) if self.index % 2 == 0 else (0.10, 0.10, 0.12, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10),]
    Button:
        text: root.name
        background_normal: ""
        background_color: (0.18, 0.47, 0.86, 1)
        color: (1,1,1,1)
        on_release: app.on_select_favorite(root.name)
    Button:
        text: "✖"
        size_hint_x: None
        width: dp(52)
        background_normal: ""
        background_color: (0.8, 0.2, 0.2, 1)
        color: (1,1,1,1)
        on_release: app.on_remove_favorite(root.name)

<HeaderBar@BoxLayout>:
    size_hint_y: None
    height: dp(56)
    padding: dp(12), dp(10)
    spacing: dp(10)
    canvas.before:
        Color:
            rgba: (0.10, 0.10, 0.12, 1)
        Rectangle:
            pos: self.pos
            size: self.size
    Label:
        text: "Tibia Tools"
        bold: True
        font_size: "20sp"
        color: (1,1,1,1)
        size_hint_x: 1
        halign: "left"
        valign: "middle"
        text_size: self.size
    Button:
        text: "Diagnóstico"
        size_hint_x: None
        width: dp(120)
        background_normal: ""
        background_color: (0.2, 0.6, 0.2, 1)
        color: (1,1,1,1)
        on_release: app.show_diagnostics()

<ErrorPanel@BoxLayout>:
    orientation: "vertical"
    padding: dp(14)
    spacing: dp(10)
    canvas.before:
        Color:
            rgba: (0.08, 0.08, 0.10, 1)
        Rectangle:
            pos: self.pos
            size: self.size
    Label:
        text: "Falha ao iniciar"
        bold: True
        font_size: "20sp"
        color: (1,1,1,1)
        size_hint_y: None
        height: dp(34)
    ScrollView:
        do_scroll_x: False
        Label:
            id: err_text
            text: ""
            color: (1,1,1,1)
            text_size: self.width, None
            size_hint_y: None
            height: self.texture_size[1] + dp(20)
    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(10)
        Button:
            text: "Copiar erro"
            background_normal: ""
            background_color: (0.5, 0.5, 0.5, 1)
            on_release: app.copy_error()
        Button:
            text: "Ver arquivo log"
            background_normal: ""
            background_color: (0.2, 0.4, 0.7, 1)
            on_release: app.copy_log_path()

<MainPanel@BoxLayout>:
    orientation: "vertical"

    HeaderBar:

    BoxLayout:
        orientation: "vertical"
        padding: dp(14)
        spacing: dp(10)

        Label:
            text: "Personagem"
            bold: True
            font_size: "18sp"
            size_hint_y: None
            height: dp(28)
            halign: "left"
            valign: "middle"
            text_size: self.size

        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(10)

            TextInput:
                id: char_input
                hint_text: "Nome do personagem"
                multiline: False

            Button:
                text: "Buscar"
                size_hint_x: None
                width: dp(110)
                background_normal: ""
                background_color: (0.18, 0.47, 0.86, 1)
                color: (1,1,1,1)
                on_release: app.on_search_char()

        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(10)

            Button:
                text: "Adicionar aos favoritos"
                background_normal: ""
                background_color: (0.35, 0.35, 0.35, 1)
                color: (1,1,1,1)
                on_release: app.on_add_favorite()

            ToggleButton:
                id: monitor_btn
                text: "Monitor: OFF"
                background_normal: ""
                background_color: (0.2, 0.2, 0.2, 1)
                on_state: app.set_monitor(self.state == "down")

        Label:
            id: status_lbl
            text: ""
            color: (0.9,0.9,0.9,1)
            size_hint_y: None
            height: self.texture_size[1] + dp(10)

        Label:
            text: "Favoritos (máx. 10)"
            bold: True
            font_size: "18sp"
            size_hint_y: None
            height: dp(28)
            halign: "left"
            valign: "middle"
            text_size: self.size

        RecycleView:
            id: fav_rv
            viewclass: "FavoriteRow"
            scroll_type: ["bars", "content"]
            bar_width: dp(6)
            do_scroll_x: False
            RecycleBoxLayout:
                default_size: None, dp(44)
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                orientation: "vertical"

        Label:
            text: "Utilidades"
            bold: True
            font_size: "18sp"
            size_hint_y: None
            height: dp(28)
            halign: "left"
            valign: "middle"
            text_size: self.size

        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(10)
            Button:
                text: "Calcular Bless"
                background_normal: ""
                background_color: (0.5, 0.5, 0.5, 1)
                on_release: app.on_bless_calc()
            Button:
                text: "Calcular Stamina"
                background_normal: ""
                background_color: (0.5, 0.5, 0.5, 1)
                on_release: app.on_stamina_calc()
            Button:
                text: "Rashid/SS"
                background_normal: ""
                background_color: (0.5, 0.5, 0.5, 1)
                on_release: app.update_rashid_and_ss()

        ScrollView:
            do_scroll_x: False
            Label:
                id: out_text
                text: ""
                color: (1,1,1,1)
                text_size: self.width, None
                size_hint_y: None
                height: self.texture_size[1] + dp(20)

BoxLayout:
    id: root_box
    orientation: "vertical"
"""


class TibiaToolsApp(App):
    favorites = ListProperty([])
    monitoring = BooleanProperty(False)
    status_text = StringProperty("")
    last_error = StringProperty("")
    interval_seconds = NumericProperty(60)

    # Bless config
    bless_cfg_threshold = NumericProperty(120)
    bless_cfg_regular_base = NumericProperty(20000)
    bless_cfg_regular_step = NumericProperty(75)
    bless_cfg_enhanced_base = NumericProperty(26000)
    bless_cfg_enhanced_step = NumericProperty(100)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._core_state = None
        self._core_tibia = None
        self._core_util = None
        self._prefix = None
        self._root = None
        self._main_panel = None
        self._error_panel = None

    def build(self):
        # Construir UI base SEM depender do core.*
        root = Builder.load_string(KV)
        self._root = root

        # tenta importar core depois da UI estar de pé
        try:
            st_mod, tb_mod, util_mod, prefix = import_core_modules()
            self._core_state, self._core_tibia, self._core_util, self._prefix = st_mod, tb_mod, util_mod, prefix
        except BaseException as e:
            msg = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self._show_fatal_error("Falha ao importar módulos do projeto (core/Core).", msg)
            return root

        # inicializa dados persistidos
        try:
            st = self._core_state.load_state(self.user_data_dir)
            self.favorites = st.get("favorites", [])
            self.interval_seconds = int(st.get("interval_seconds", 60))
            self.monitoring = bool(st.get("monitoring", False))
            cfg = st.get("bless_cfg", {})
            self.bless_cfg_threshold = int(cfg.get("threshold_level", 120))
            self.bless_cfg_regular_base = int(cfg.get("regular_base", 20000))
            self.bless_cfg_regular_step = int(cfg.get("regular_step", 75))
            self.bless_cfg_enhanced_base = int(cfg.get("enhanced_base", 26000))
            self.bless_cfg_enhanced_step = int(cfg.get("enhanced_step", 100))
        except BaseException as e:
            msg = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self._show_fatal_error("Falha ao ler o estado/salvos.", msg)
            return root

        Clock.schedule_once(lambda *_: self._refresh_list(), 0)
        Clock.schedule_interval(lambda dt: self._tick_monitor(dt), 2.5)
        Clock.schedule_interval(lambda dt: self._tick_rashid(dt), 1.0)
        Clock.schedule_once(lambda *_: self.update_rashid_and_ss(), 0)
        Clock.schedule_once(lambda *_: self._update_monitor_button(), 0)

        # pedir permissão de notificação (Android 13+)
        try:
            if sys.platform == "android":
                from android.permissions import request_permissions, Permission  # type: ignore
                request_permissions([Permission.POST_NOTIFICATIONS])
        except Exception:
            pass

        # outputs iniciais
        self.status_text = "Pronto."
        self._set_status(self.status_text)
        self.on_bless_calc()
        self.on_stamina_calc()
        return root

    # ----------------------------
    # UI helpers
    # ----------------------------
    def _find(self, wid: str):
        if not self._root:
            return None
        try:
            return self._root.ids.get(wid)
        except Exception:
            return None

    def _set_status(self, text: str):
        self.status_text = text
        lbl = self._find("status_lbl")
        if lbl is not None:
            lbl.text = text

    def _append_output(self, text: str):
        out = self._find("out_text")
        if out is not None:
            out.text = text

    def _update_monitor_button(self):
        btn = self._find("monitor_btn")
        if btn is not None:
            btn.text = "Monitor: ON" if self.monitoring else "Monitor: OFF"
            btn.state = "down" if self.monitoring else "normal"

    def _show_fatal_error(self, title: str, details: str):
        full = f"{title}\n\n{details}\n\nLog: {_CRASH_FILE}"
        self.last_error = full
        _append_crash_log(full)
        # troca UI para painel de erro
        root_box = self._find("root_box")
        if root_box is None:
            return
        root_box.clear_widgets()

        panel = Builder.load_string("ErrorPanel:")
        self._error_panel = panel
        # set text
        try:
            panel.ids.err_text.text = full
        except Exception:
            pass
        root_box.add_widget(panel)

    def show_diagnostics(self):
        info = [
            f"package: {self.__class__.__name__}",
            f"user_data_dir: {self.user_data_dir}",
            f"crash_log: {_CRASH_FILE}",
            f"core_prefix: {self._prefix}",
            f"favorites: {len(self.favorites)}",
            f"monitoring: {self.monitoring} (interval={self.interval_seconds}s)",
        ]
        self._append_output("DIAGNÓSTICO\n" + "\n".join(info))

    def copy_error(self):
        if self.last_error:
            Clipboard.copy(self.last_error)

    def copy_log_path(self):
        Clipboard.copy(_CRASH_FILE)
        self._append_output(f"Caminho do log copiado:\n{_CRASH_FILE}")

    # ----------------------------
    # Favorites
    # ----------------------------
    def _save_state(self):
        try:
            self._core_state.save_state(
                self.user_data_dir,
                {
                    "favorites": list(self.favorites),
                    "interval_seconds": int(self.interval_seconds),
                    "monitoring": bool(self.monitoring),
                    "bless_cfg": {
                        "threshold_level": int(self.bless_cfg_threshold),
                        "regular_base": int(self.bless_cfg_regular_base),
                        "regular_step": int(self.bless_cfg_regular_step),
                        "enhanced_base": int(self.bless_cfg_enhanced_base),
                        "enhanced_step": int(self.bless_cfg_enhanced_step),
                    },
                },
            )
        except Exception as e:
            self._set_status(f"Falha ao salvar estado: {e}")

    def _refresh_list(self):
        rv = self._find("fav_rv")
        if rv is not None:
            rv.data = [{"name": n, "index": i} for i, n in enumerate(self.favorites)]

    def on_select_favorite(self, name: str):
        ti = self._find("char_input")
        if ti is not None:
            ti.text = name
        self._set_status(f"Selecionado: {name}")

    def on_remove_favorite(self, name: str):
        if name in self.favorites:
            self.favorites.remove(name)
            self._save_state()
            self._refresh_list()
            self._set_status(f"Removido dos favoritos: {name}")

    def on_add_favorite(self):
        ti = self._find("char_input")
        if ti is None:
            return
        name = ti.text.strip()
        if not name:
            self._set_status("Digite um nome para favoritar.")
            return
        if name in self.favorites:
            self._set_status("Já está nos favoritos.")
            return
        if len(self.favorites) >= 10:
            self._set_status("Limite de 10 favoritos.")
            return
        self.favorites.append(name)
        self._save_state()
        self._refresh_list()
        self._set_status(f"Favoritado: {name}")

    def set_monitor(self, enabled: bool):
        self.monitoring = bool(enabled)
        self._update_monitor_button()
        self._save_state()
        self._set_status("Monitor ligado." if self.monitoring else "Monitor desligado.")

    # ----------------------------
    # Char search
    # ----------------------------
    def on_search_char(self):
        ti = self._find("char_input")
        if ti is None:
            return
        name = ti.text.strip()
        if not name:
            self._set_status("Digite o nome do personagem.")
            return
        try:
            snap = self._core_tibia.fetch_character_snapshot(name)
            lines = []
            if snap.get("error"):
                lines.append(f"ERRO: {snap['error']}")
            else:
                lines.append(f"Nome: {snap.get('name','-')}")
                lines.append(f"Mundo: {snap.get('world','-')}")
                lines.append(f"Level: {snap.get('level','-')}  Voc: {snap.get('vocation','-')}")
                lines.append(f"Status: {'online' if snap.get('online') else 'offline'}")
                if snap.get("last_login"):
                    lines.append(f"Last login: {snap.get('last_login')}")
            self._append_output("\n".join(lines))
            self._set_status("Busca OK.")
        except Exception as e:
            msg = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            _append_crash_log(msg)
            self._set_status(f"Falha na busca: {e}")

    # ----------------------------
    # Monitor (notificações via serviço)
    # ----------------------------
    def _tick_monitor(self, dt):
        # este app controla estado; serviço faz o monitoramento real.
        if not self.monitoring:
            return
        # Só atualiza texto (mínimo). Você pode iniciar o serviço aqui quando quiser.
        self._set_status(f"Monitor: ON (intervalo {int(self.interval_seconds)}s)")

    # ----------------------------
    # Utilities
    # ----------------------------
    def on_bless_calc(self):
        """
        Calcula custo estimado das blessings (modelo simples ajustável).
        """
        # nível do campo atual (se for número), senão usa 120
        lvl = 120
        ti = self._find("char_input")
        if ti is not None:
            txt = ti.text.strip()
            # permite "120" como input rápido
            if txt.isdigit():
                lvl = int(txt)

        try:
            calc = self._core_util.calc_bless_cost(
                level=lvl,
                threshold_level=int(self.bless_cfg_threshold),
                regular_base=int(self.bless_cfg_regular_base),
                regular_step=int(self.bless_cfg_regular_step),
                enhanced_base=int(self.bless_cfg_enhanced_base),
                enhanced_step=int(self.bless_cfg_enhanced_step),
            )
            self._append_output(
                "BLESS\n"
                f"Level: {lvl}\n"
                f"Regular (5): {calc['regular_5']:,}\n"
                f"Enhanced (2): {calc['enhanced_2']:,}\n"
                f"Total (7): {calc['total_7']:,}\n"
            )
        except Exception as e:
            self._append_output(f"BLESS: erro: {e}")

    def on_stamina_calc(self):
        """
        Stamina: input "HH:MM" no campo do personagem, ex: 38:45
        """
        ti = self._find("char_input")
        if ti is None:
            return
        txt = ti.text.strip()
        try:
            h, m = txt.split(":")
            cur = int(h) * 60 + int(m)
            need = self._core_util.minutes_to_full_stamina(cur)
            self._append_output(
                "STAMINA\n"
                f"Atual: {txt}\n"
                f"Falta offline: {need//60}h {need%60:02d}m para 42:00\n"
            )
        except Exception:
            self._append_output("STAMINA\nDigite no campo: HH:MM (ex: 38:45) para calcular.")

    def _tick_rashid(self, dt):
        # atualiza rótulo de status periodicamente (sem spam)
        pass

    def update_rashid_and_ss(self):
        try:
            info = self._core_util.rashid_and_serversave_info()
            self._append_output(
                "RASHID / SERVER SAVE\n"
                f"Rashid hoje: {info['rashid_city']}\n"
                f"Server Save (CET/CEST): {info['serversave_eta']}\n"
            )
        except Exception as e:
            self._append_output(f"RASHID: erro: {e}")


if __name__ == "__main__":
    TibiaToolsApp().run()