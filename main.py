# main.py
__version__ = "0.2.1"

import json
from datetime import datetime, timezone

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import StringProperty, BooleanProperty, NumericProperty, ListProperty
from kivy.utils import platform

from core.state import (
    load_state,
    save_state,
    add_favorite,
    remove_favorite,
    MAX_FAVORITES,
)
from core.utilities import (
    BlessConfig,
    calc_blessings,
    rashid_today,
    next_server_save_utc,
    to_cet,
    calc_stamina_offline,
)

KV = r"""
#:import dp kivy.metrics.dp

<NavBtn@Button>:
    size_hint_y: None
    height: dp(44)

<FavoriteRow@BoxLayout>:
    name: ""
    size_hint_y: None
    height: dp(44)
    spacing: dp(8)
    Label:
        text: root.name
        halign: "left"
        valign: "middle"
        text_size: self.size
    Button:
        text: "Remover"
        size_hint_x: None
        width: dp(95)
        on_release: app.on_remove_favorite(root.name)

BoxLayout:
    orientation: "horizontal"

    # Sidebar
    BoxLayout:
        size_hint_x: None
        width: dp(170)
        orientation: "vertical"
        padding: dp(10)
        spacing: dp(10)

        Label:
            text: "[b]Tibia Tools[/b]\\nAndroid"
            markup: True
            font_size: "18sp"
            size_hint_y: None
            height: dp(60)

        Label:
            text: app.status_text
            color: (0.2, 0.7, 0.2, 1) if "ON" in app.status_text else (0.8, 0.3, 0.3, 1)
            size_hint_y: None
            height: dp(24)

        NavBtn:
            text: "Favoritos"
            on_release: app.go("favorites")

        NavBtn:
            text: "Utilidades"
            on_release: app.go("utilities")

        Widget:

        Label:
            text: "v" + app.version_text
            font_size: "12sp"
            size_hint_y: None
            height: dp(20)

    # Content
    ScreenManager:
        id: sm

        Screen:
            name: "favorites"
            BoxLayout:
                orientation: "vertical"
                padding: dp(12)
                spacing: dp(12)

                Label:
                    text: "[b]Favoritos[/b] (máx. %d)" % app.max_favs
                    markup: True
                    font_size: "18sp"
                    size_hint_y: None
                    height: dp(28)

                BoxLayout:
                    size_hint_y: None
                    height: dp(44)
                    spacing: dp(8)

                    TextInput:
                        id: fav_in
                        hint_text: "Nome do personagem..."
                        multiline: False
                        on_text_validate: app.on_add_favorite(self.text)

                    Button:
                        text: "Adicionar"
                        size_hint_x: None
                        width: dp(110)
                        on_release: app.on_add_favorite(fav_in.text)

                BoxLayout:
                    size_hint_y: None
                    height: dp(44)
                    spacing: dp(8)

                    Label:
                        text: "Intervalo (s):"
                        size_hint_x: None
                        width: dp(100)

                    TextInput:
                        id: interval_in
                        text: str(int(app.interval_seconds))
                        input_filter: "int"
                        multiline: False

                    Button:
                        text: "Salvar"
                        size_hint_x: None
                        width: dp(90)
                        on_release: app.on_save_interval(interval_in.text)

                BoxLayout:
                    size_hint_y: None
                    height: dp(44)
                    spacing: dp(8)

                    Button:
                        text: "Iniciar monitor"
                        on_release: app.set_monitor(True)

                    Button:
                        text: "Parar"
                        on_release: app.set_monitor(False)

                Label:
                    text: app.info_text
                    font_size: "12sp"
                    size_hint_y: None
                    height: dp(18)

                ScrollView:
                    do_scroll_x: False
                    GridLayout:
                        id: fav_list
                        cols: 1
                        spacing: dp(6)
                        size_hint_y: None
                        height: self.minimum_height

        Screen:
            name: "utilities"
            BoxLayout:
                orientation: "vertical"
                padding: dp(12)
                spacing: dp(12)

                Label:
                    text: "[b]Utilidades[/b]"
                    markup: True
                    font_size: "18sp"
                    size_hint_y: None
                    height: dp(28)

                # Blessings
                BoxLayout:
                    orientation: "vertical"
                    size_hint_y: None
                    height: dp(220)
                    spacing: dp(8)

                    Label:
                        text: "[b]Calculadora de Blessings[/b]"
                        markup: True
                        size_hint_y: None
                        height: dp(24)

                    BoxLayout:
                        size_hint_y: None
                        height: dp(40)
                        spacing: dp(8)
                        Label:
                            text: "Level:"
                            size_hint_x: None
                            width: dp(70)
                        TextInput:
                            id: bless_level
                            text: "100"
                            input_filter: "int"
                            multiline: False

                    BoxLayout:
                        size_hint_y: None
                        height: dp(40)
                        spacing: dp(8)
                        Label:
                            text: "Bless (0-5):"
                            size_hint_x: None
                            width: dp(110)
                        TextInput:
                            id: bless_reg
                            text: "5"
                            input_filter: "int"
                            multiline: False

                    BoxLayout:
                        size_hint_y: None
                        height: dp(40)
                        spacing: dp(8)
                        Label:
                            text: "Novas (0-2):"
                            size_hint_x: None
                            width: dp(110)
                        TextInput:
                            id: bless_enh
                            text: "2"
                            input_filter: "int"
                            multiline: False

                    BoxLayout:
                        size_hint_y: None
                        height: dp(40)
                        spacing: dp(8)
                        ToggleButton:
                            id: inq
                            text: "Desconto Inq"
                            state: "down"
                        ToggleButton:
                            id: twist
                            text: "Twist of Fate"
                            state: "down"

                    Button:
                        text: "Calcular"
                        size_hint_y: None
                        height: dp(44)
                        on_release: app.on_calc_bless(bless_level.text, bless_reg.text, bless_enh.text, inq.state, twist.state)

                    Label:
                        id: bless_out
                        text: app.bless_text
                        font_size: "12sp"

                # Rashid + Server Save
                BoxLayout:
                    orientation: "vertical"
                    size_hint_y: None
                    height: dp(120)
                    spacing: dp(6)

                    Label:
                        text: "[b]Rashid + Server Save[/b]"
                        markup: True
                        size_hint_y: None
                        height: dp(24)

                    Label:
                        text: app.rashid_text
                        font_size: "12sp"

                    Label:
                        text: app.ss_text
                        font_size: "12sp"

                # Stamina
                BoxLayout:
                    orientation: "vertical"
                    size_hint_y: None
                    height: dp(160)
                    spacing: dp(6)

                    Label:
                        text: "[b]Calculadora de Stamina[/b]"
                        markup: True
                        size_hint_y: None
                        height: dp(24)

                    BoxLayout:
                        size_hint_y: None
                        height: dp(40)
                        spacing: dp(8)
                        Label:
                            text: "Stamina atual (HH:MM):"
                            size_hint_x: None
                            width: dp(170)
                        TextInput:
                            id: stam_in
                            text: "38:45"
                            multiline: False

                    Button:
                        text: "Calcular"
                        size_hint_y: None
                        height: dp(44)
                        on_release: app.on_calc_stamina(stam_in.text)

                    Label:
                        text: app.stamina_text
                        font_size: "12sp"
"""


class TibiaToolsApp(App):
    version_text = StringProperty(__version__)
    status_text = StringProperty("MONITOR: OFF")
    info_text = StringProperty("")
    bless_text = StringProperty("")
    rashid_text = StringProperty("")
    ss_text = StringProperty("")
    stamina_text = StringProperty("")

    favorites = ListProperty([])
    monitoring = BooleanProperty(False)
    interval_seconds = NumericProperty(60)
    max_favs = NumericProperty(MAX_FAVORITES)

    def build(self):
        self.title = "Tibia Tools"
        self._service_ref = None

        self.state = load_state(self.user_data_dir)
        self.favorites = list(self.state.get("favorites", []))[:MAX_FAVORITES]
        self.monitoring = bool(self.state.get("monitoring", False))
        self.interval_seconds = int(self.state.get("interval_seconds", 60))

        root = Builder.load_string(KV)
        self.root = root
        self._refresh_fav_list()
        self._sync_status()

        self._update_rashid_and_ss()
        Clock.schedule_interval(lambda *_: self._update_rashid_and_ss(), 1)

        if platform == "android":
            self._request_android_permissions()

        return root

    def _request_android_permissions(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.POST_NOTIFICATIONS])
        except Exception:
            pass

    def go(self, screen_name: str):
        self.root.ids.sm.current = screen_name

    # ---------------- Favorites ----------------
   def _refresh_fav_list(self):
    container = self.root.ids.fav_list
    container.clear_widgets()

    for name in self.favorites:
        w = Factory.FavoriteRow(name=name)
        container.add_widget(w)

    self.info_text = f"{len(self.favorites)}/{MAX_FAVORITES} favoritos"

    def _sync_status(self):
        self.status_text = "MONITOR: ON" if self.monitoring else "MONITOR: OFF"

    def on_add_favorite(self, name: str):
        name = (name or "").strip()
        if not name:
            self.info_text = "Digite um nome."
            return

        ok, msg, favs = add_favorite(self.user_data_dir, name)
        self.state = load_state(self.user_data_dir)
        self.favorites = list(favs)[:MAX_FAVORITES]
        self._refresh_fav_list()
        self.info_text = msg

    def on_remove_favorite(self, name: str):
        ok, msg, favs = remove_favorite(self.user_data_dir, name)
        self.state = load_state(self.user_data_dir)
        self.favorites = list(favs)[:MAX_FAVORITES]
        self._refresh_fav_list()
        self.info_text = msg

    def on_save_interval(self, txt: str):
        try:
            val = int(txt)
            val = max(10, min(3600, val))
        except Exception:
            self.info_text = "Intervalo inválido."
            return

        self.interval_seconds = val
        st = load_state(self.user_data_dir)
        st["interval_seconds"] = int(val)
        save_state(self.user_data_dir, st)
        self.info_text = f"Intervalo salvo: {val}s"

    # ---------------- Service control ----------------
    def set_monitor(self, enable: bool):
        enable = bool(enable)
        self.monitoring = enable
        st = load_state(self.user_data_dir)
        st["monitoring"] = enable
        st["interval_seconds"] = int(self.interval_seconds)
        save_state(self.user_data_dir, st)
        self._sync_status()

        if platform != "android":
            self.info_text = "Monitor funciona só no Android."
            return

        try:
            from jnius import autoclass
            ServiceWatcher = autoclass("org.erick.tibiatools.ServiceWatcher")
            mActivity = autoclass("org.kivy.android.PythonActivity").mActivity

            payload = json.dumps(
                {"user_data_dir": self.user_data_dir, "interval": int(self.interval_seconds)},
                ensure_ascii=False,
            )

            if enable:
                ServiceWatcher.start(mActivity, payload)
                self.info_text = "Monitor iniciado."
            else:
                ServiceWatcher.stop(mActivity)
                self.info_text = "Monitor parado."
        except Exception as e:
            self.info_text = f"Falha ao controlar service: {e}"

    # ---------------- Utilities ----------------
    def on_calc_bless(self, level_txt: str, reg_txt: str, enh_txt: str, inq_state: str, twist_state: str):
        try:
            level = int(level_txt)
            reg = int(reg_txt)
            enh = int(enh_txt)
        except Exception:
            self.bless_text = "Valores inválidos."
            return

        cfg_dict = (load_state(self.user_data_dir).get("bless_cfg") or {})
        cfg = BlessConfig(**cfg_dict)

        res = calc_blessings(
            level=level,
            regular_count=reg,
            enhanced_count=enh,
            include_twist=(twist_state == "down"),
            inq_discount=(inq_state == "down"),
            cfg=cfg,
        )

        self.bless_text = (
            f"Total: {res['total']:,} gp\n"
            f"Regular (cada): {res['regular_each']:,} | Novas (cada): {res['enhanced_each']:,}\n"
            f"Quebra: regular={res['breakdown']['regular']:,} / novas={res['breakdown']['enhanced']:,} / twist={res['breakdown']['twist']:,}\n"
            f"Desconto: {res['discount_amt']:,} gp"
        )

    def _update_rashid_and_ss(self):
        utc_now = datetime.now(timezone.utc)
        r = rashid_today(utc_now)
        self.rashid_text = f"Rashid hoje: {r['city']} — {r['where']}"

        nxt = next_server_save_utc(utc_now)
        diff = int((nxt - utc_now).total_seconds())
        if diff < 0:
            diff = 0
        hh = diff // 3600
        mm = (diff % 3600) // 60
        ss = diff % 60
        cet = to_cet(utc_now)
        self.ss_text = f"Server Save em: {hh:02d}:{mm:02d}:{ss:02d} (agora CET: {cet.strftime('%H:%M:%S')})"

    def on_calc_stamina(self, cur_txt: str):
        try:
            res = calc_stamina_offline(cur_txt, "42:00", add_delay_10min=True)
            self.stamina_text = (
                f"Atual: {res['current']} → alvo {res['target']}\n"
                f"Offline p/ 39:00: {res['offline_to_39']}\n"
                f"Offline p/ 42:00: {res['offline_to_42']}\n"
                f"{res['note']}"
            )
        except Exception as e:
            self.stamina_text = f"Erro: {e}"


if __name__ == "__main__":
    TibiaToolsApp().run()
