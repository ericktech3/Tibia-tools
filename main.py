# -*- coding: utf-8 -*-
"""
Tibia Tools (Android) - KivyMD app

Tabs: Char / Bless / Favoritos / Mais
Mais -> telas internas: Bosses (ExevoPan), Boosted, Treino (Exercise), Imbuements, Hunt Analyzer
"""
from __future__ import annotations

import os
import threading
import webbrowser
from typing import List, Optional

from kivy.lang import Builder
from kivy.resources import resource_find
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.screenmanager import ScreenManager

from kivymd.app import MDApp
from kivymd.uix.snackbar import Snackbar
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.list import OneLineIconListItem, IconLeftWidget
from kivymd.uix.menu import MDDropdownMenu

from core.api import fetch_character_tibiadata, fetch_worlds_tibiadata
from core.utilities import calc_blessings_cost
from core.storage import get_data_dir, safe_read_json, safe_write_json
from core.bosses import fetch_exevopan_bosses
from core.boosted import fetch_boosted
from core.training import TrainingInput, compute_training_plan
from core.hunt import parse_hunt_session_text
from core.imbuements import fetch_imbuements_table, Imbuem

KV_FILE = "tibia_tools.kv"
FAV_FILE = "favorites.json"


class MoreItem(OneLineIconListItem):
    icon = StringProperty("chevron-right")


class TibiaToolsApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.favorites: List[str] = []
        self._dialog: Optional[MDDialog] = None
        self._menu_world: Optional[MDDropdownMenu] = None
        self._menu_skill: Optional[MDDropdownMenu] = None
        self._menu_vocation: Optional[MDDropdownMenu] = None
        self._menu_weapon: Optional[MDDropdownMenu] = None

    def build(self):
        self.title = "Tibia Tools"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Dark"

        # ✅ Android-safe: encontra o KV empacotado também
        kv_path = resource_find(KV_FILE) or KV_FILE
        root = Builder.load_file(kv_path)

        self.load_favorites()
        Clock.schedule_once(lambda *_: self.refresh_favorites_list(), 0)
        Clock.schedule_once(lambda *_: self.update_boosted(), 0)
        return root

    # ---------------- Navigation ----------------
    def go(self, screen_name: str):
        sm = self.root.ids.screen_manager  # type: ignore
        sm.current = screen_name

    def on_tab_switch(self, instance_tabs, instance_tab, instance_tab_label, tab_text):
        # Placeholder (se quiser tratar troca de tabs)
        pass

    # ---------------- Favorites ----------------
    def _fav_path(self) -> str:
        data_dir = get_data_dir("tibia_tools")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, FAV_FILE)

    def load_favorites(self):
        data = safe_read_json(self._fav_path(), default={"favorites": []})
        self.favorites = list(data.get("favorites", []))

        # Atualiza campo da Home (Char) com último favorito, se existir
        try:
            if self.favorites:
                home = self.root.ids.tabs.get_tab_list()[0].content  # type: ignore
                # Em KV usamos root.char_last no HomeScreen@MDScreen, mas aqui o root é ScreenManager.
                # Então só guardamos para usar no fetch automático se quiser no futuro.
        except Exception:
            pass

    def save_favorites(self):
        safe_write_json(self._fav_path(), {"favorites": self.favorites})

    def add_favorite(self):
        name = (self.root.ids.tabs.get_tab_list()[2].content.ids.fav_name.text or "").strip()  # type: ignore
        if not name:
            Snackbar(text="Digite um nome.").open()
            return
        if name in self.favorites:
            Snackbar(text="Já está nos favoritos.").open()
            return
        self.favorites.append(name)
        self.save_favorites()
        self.refresh_favorites_list()
        Snackbar(text="Favorito adicionado!").open()
        self.root.ids.tabs.get_tab_list()[2].content.ids.fav_name.text = ""  # type: ignore

    def remove_favorite(self, name: str):
        if name in self.favorites:
            self.favorites.remove(name)
            self.save_favorites()
            self.refresh_favorites_list()
            Snackbar(text="Removido.").open()

    def refresh_favorites_list(self):
        lst = self.root.ids.tabs.get_tab_list()[2].content.ids.favorites_list  # type: ignore
        lst.clear_widgets()
        for name in self.favorites:
            item = OneLineIconListItem(text=name)
            item.bind(on_release=lambda inst, n=name: self.fetch_character(n))
            lst.add_widget(item)

    # ---------------- Character ----------------
    def fetch_character(self, name: Optional[str] = None):
        tab_char = self.root.ids.tabs.get_tab_list()[0].content  # type: ignore
        if name is None:
            name = (tab_char.ids.char_name.text or "").strip()
        if not name:
            Snackbar(text="Digite o nome do personagem.").open()
            return

        tab_char.ids.char_result.text = "Buscando..."
        def worker():
            try:
                data = fetch_character_tibiadata(name)
                Clock.schedule_once(lambda *_: self._render_char(data), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: self._set_char_error(str(e)), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _set_char_error(self, msg: str):
        tab_char = self.root.ids.tabs.get_tab_list()[0].content  # type: ignore
        tab_char.ids.char_result.text = f"Erro: {msg}"

    def _render_char(self, data: dict):
        tab_char = self.root.ids.tabs.get_tab_list()[0].content  # type: ignore
        if not data:
            tab_char.ids.char_result.text = "Sem dados."
            return

        # Ajuste conforme o retorno do seu core/api.py
        lines = []
        try:
            c = data.get("character", data)
            lines.append(f"Nome: {c.get('name','')}")
            lines.append(f"World: {c.get('world','')}")
            lines.append(f"Level: {c.get('level','')}")
            lines.append(f"Vocation: {c.get('vocation','')}")
        except Exception:
            lines.append(str(data))

        tab_char.ids.char_result.text = "\n".join(lines)

    # ---------------- Blessings ----------------
    def calc_blessings(self):
        tab = self.root.ids.tabs.get_tab_list()[1].content  # type: ignore
        lv_txt = (tab.ids.bless_level.text or "").strip()
        if not lv_txt.isdigit():
            Snackbar(text="Digite um level válido.").open()
            return

        level = int(lv_txt)
        cost = calc_blessings_cost(level)
        tab.ids.bless_result.text = f"Custo (aprox): {cost:,}".replace(",", ".")

    # ---------------- Bosses ----------------
    def update_bosses(self):
        screen = self.root.get_screen("bosses")  # type: ignore
        screen.ids.bosses_list.clear_widgets()
        screen.ids.bosses_list.add_widget(OneLineIconListItem(text="Buscando..."))

        def worker():
            try:
                bosses = fetch_exevopan_bosses()
                Clock.schedule_once(lambda *_: self._render_bosses(bosses), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: self._render_bosses_error(str(e)), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _render_bosses_error(self, msg: str):
        screen = self.root.get_screen("bosses")  # type: ignore
        screen.ids.bosses_list.clear_widgets()
        screen.ids.bosses_list.add_widget(OneLineIconListItem(text=f"Erro: {msg}"))

    def _render_bosses(self, bosses):
        screen = self.root.get_screen("bosses")  # type: ignore
        screen.ids.bosses_list.clear_widgets()

        if not bosses:
            screen.ids.bosses_list.add_widget(OneLineIconListItem(text="Sem dados."))
            return

        for b in bosses:
            # Ajuste conforme estrutura retornada
            text = str(b)
            screen.ids.bosses_list.add_widget(OneLineIconListItem(text=text))

    # ---------------- Boosted ----------------
    def update_boosted(self):
        screen = self.root.get_screen("boosted")  # type: ignore
        screen.ids.boosted_label.text = "Buscando..."

        def worker():
            try:
                data = fetch_boosted()
                Clock.schedule_once(lambda *_: self._render_boosted(data), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: self._render_boosted_error(str(e)), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _render_boosted_error(self, msg: str):
        screen = self.root.get_screen("boosted")  # type: ignore
        screen.ids.boosted_label.text = f"Erro: {msg}"

    def _render_boosted(self, data):
        screen = self.root.get_screen("boosted")  # type: ignore
        if not data:
            screen.ids.boosted_label.text = "Sem dados."
            return
        screen.ids.boosted_label.text = str(data)

    # ---------------- Training ----------------
    def compute_training(self):
        screen = self.root.get_screen("training")  # type: ignore
        from_txt = (screen.ids.training_from.text or "").strip()
        to_txt = (screen.ids.training_to.text or "").strip()
        ml_txt = (screen.ids.training_ml.text or "").strip()

        if not from_txt.isdigit() or not to_txt.isdigit():
            Snackbar(text="Preencha skill atual e alvo (números).").open()
            return

        skill_from = int(from_txt)
        skill_to = int(to_txt)
        ml = int(ml_txt) if ml_txt.isdigit() else None

        try:
            inp = TrainingInput(skill_from=skill_from, skill_to=skill_to, magic_level=ml)
            out = compute_training_plan(inp)
            screen.ids.training_result.text = str(out)
        except Exception as e:
            screen.ids.training_result.text = f"Erro: {e}"

    # ---------------- Imbuements ----------------
    def update_imbuements(self):
        screen = self.root.get_screen("imbuements")  # type: ignore
        screen.ids.imbuements_list.clear_widgets()
        screen.ids.imbuements_list.add_widget(OneLineIconListItem(text="Buscando..."))

        def worker():
            try:
                table = fetch_imbuements_table()
                Clock.schedule_once(lambda *_: self._render_imbuements(table), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: self._render_imbuements_error(str(e)), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _render_imbuements_error(self, msg: str):
        screen = self.root.get_screen("imbuements")  # type: ignore
        screen.ids.imbuements_list.clear_widgets()
        screen.ids.imbuements_list.add_widget(OneLineIconListItem(text=f"Erro: {msg}"))

    def _render_imbuements(self, table):
        screen = self.root.get_screen("imbuements")  # type: ignore
        screen.ids.imbuements_list.clear_widgets()

        if not table:
            screen.ids.imbuements_list.add_widget(OneLineIconListItem(text="Sem dados."))
            return

        for row in table:
            screen.ids.imbuements_list.add_widget(OneLineIconListItem(text=str(row)))

    # ---------------- Hunt Analyzer ----------------
    def parse_hunt(self):
        screen = self.root.get_screen("hunt")  # type: ignore
        txt = (screen.ids.hunt_text.text or "").strip()
        if not txt:
            Snackbar(text="Cole o texto do hunt.").open()
            return
        try:
            result = parse_hunt_session_text(txt)
            screen.ids.hunt_result.text = str(result)
        except Exception as e:
            screen.ids.hunt_result.text = f"Erro: {e}"


if __name__ == "__main__":
    TibiaToolsApp().run()
