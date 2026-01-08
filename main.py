# -*- coding: utf-8 -*-
"""
Tibia Tools (Android) - KivyMD app

Tabs: Char / Share XP / Favoritos / Mais
Mais -> telas internas: Bosses (ExevoPan), Boosted, Treino (Exercise), Imbuements, Hunt Analyzer
"""
from __future__ import annotations

import os
import threading
import webbrowser
import traceback
import math
from typing import List, Optional

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.resources import resource_find
from kivy.metrics import dp
from kivy.core.window import Window

from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.list import OneLineIconListItem, IconLeftWidget
from kivymd.uix.menu import MDDropdownMenu

from core.api import fetch_character_tibiadata, fetch_worlds_tibiadata, is_character_online_tibiadata
from core.storage import get_data_dir, safe_read_json, safe_write_json
from core.bosses import fetch_exevopan_bosses
from core.boosted import fetch_boosted
from core.training import TrainingInput, compute_training_plan
from core.hunt import parse_hunt_session_text
from core.imbuements import ImbuementEntry, search_imbuements

KV_FILE = "tibia_tools.kv"
FAV_FILE = "favorites.json"


class MoreItem(OneLineIconListItem):
    icon: str = "chevron-right"


class TibiaToolsApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dialog: Optional[MDDialog] = None
        self.favorites: List[str] = []
        self.fav_path = os.path.join(get_data_dir(), FAV_FILE)

        self._boost_cache = None  # type: ignore

    def build(self):
        self.title = "Tibia Tools"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Dark"

        kv_ok = False

        try:
            kv_path = resource_find(KV_FILE) or KV_FILE
            root = Builder.load_file(kv_path)
            kv_ok = True
        except Exception:
            # Vai aparecer no logcat como Python traceback
            traceback.print_exc()
            # Mostra o erro na tela em vez de fechar sem explicar
            from kivymd.uix.label import MDLabel
            root = MDLabel(text="Erro ao iniciar. Veja o logcat (Traceback).", halign="center")

        if kv_ok:
            self.load_favorites()
            Clock.schedule_once(lambda *_: self.refresh_favorites_list(), 0)
            Clock.schedule_once(lambda *_: self.update_boosted(), 0)

        return root

    # --------------------
    # Navigation
    # --------------------
    def open_more_target(self, target: str):
        try:
            self.root.current = target
        except Exception:
            self.toast("Não foi possível abrir a tela.")

    def go_home(self):
        try:
            self.root.current = "home"
        except Exception:
            pass

    # --------------------
    # Character (tibiadata)
    # --------------------
    def search_character(self):
        home = self.root.get_screen("home")
        name = (home.ids.char_name.text or "").strip()
        if not name:
            self.toast("Digite o nome do personagem.")
            return

        home.ids.char_status.text = "Buscando..."
        home.char_last_url = ""

        def run():
            try:
                data = fetch_character_tibiadata(name)
                if not data:
                    Clock.schedule_once(lambda *_: self._set_char_status("Não encontrado."), 0)
                    return

                url = data.get("url") or ""
                status_lines = []

                # online?
                online = False
                try:
                    online = is_character_online_tibiadata(data)
                except Exception:
                    online = False

                status_lines.append(f"Nome: {data.get('name','')}")
                status_lines.append(f"Level: {data.get('level','')}")
                status_lines.append(f"Vocation: {data.get('vocation','')}")
                status_lines.append(f"World: {data.get('world','')}")
                status_lines.append(f"Status: {'Online' if online else 'Offline'}")

                guild = data.get("guild")
                if guild:
                    status_lines.append(f"Guild: {guild}")

                acc_status = data.get("account_status")
                if acc_status:
                    status_lines.append(f"Account: {acc_status}")

                if url:
                    home.char_last_url = url

                text = "\n".join(status_lines)
                Clock.schedule_once(lambda *_: self._set_char_status(text), 0)
            except Exception:
                traceback.print_exc()
                Clock.schedule_once(lambda *_: self._set_char_status("Erro ao buscar. Veja o logcat."), 0)

        threading.Thread(target=run, daemon=True).start()

    def _set_char_status(self, text: str):
        try:
            home = self.root.get_screen("home")
            home.ids.char_status.text = text
        except Exception:
            pass

    def open_last_in_browser(self):
        home = self.root.get_screen("home")
        url = (home.char_last_url or "").strip()
        if not url:
            self.toast("Faça uma busca primeiro.")
            return
        try:
            webbrowser.open(url)
        except Exception:
            self.toast("Não foi possível abrir o navegador.")

    def add_current_to_favorites(self):
        home = self.root.get_screen("home")
        name = (home.ids.char_name.text or "").strip()
        if not name:
            self.toast("Digite o nome do personagem.")
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
    def refresh_favorites_list(self):
        home = self.root.get_screen("home")
        container = home.ids.fav_list
        container.clear_widgets()

        if not self.favorites:
            item = OneLineIconListItem(text="Sem favoritos ainda.")
            item.add_widget(IconLeftWidget(icon="star-outline"))
            container.add_widget(item)
            return

        for name in self.favorites:
            item = OneLineIconListItem(text=name)
            item.add_widget(IconLeftWidget(icon="account"))
            item.bind(on_release=lambda _item, n=name: self._fav_actions(n))
            container.add_widget(item)

    def _fav_actions(self, name: str):
        def remove(*_):
            if name in self.favorites:
                self.favorites.remove(name)
                self.save_favorites()
                self.refresh_favorites_list()
                self.toast("Removido.")
            dlg.dismiss()

        def open_char(*_):
            try:
                home = self.root.get_screen("home")
                home.ids.char_name.text = name
                self.root.current = "home"
                dlg.dismiss()
            except Exception:
                dlg.dismiss()

        dlg = MDDialog(
            title=name,
            text="O que deseja fazer?",
            buttons=[
                MDFlatButton(text="ABRIR", on_release=open_char),
                MDFlatButton(text="REMOVER", on_release=remove),
                MDFlatButton(text="CANCELAR", on_release=lambda *_: dlg.dismiss()),
            ],
        )
        dlg.open()

    # --------------------
    # Shared XP
    # --------------------
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

        # Regra do Tibia (party shared XP):
        # Se você é level L, pode sharear com levels entre:
        #   ceil(2/3 * L)  e  floor(3/2 * L)
        min_level = int(math.ceil(level * 2.0 / 3.0))
        max_level = int(math.floor(level * 3.0 / 2.0))

        home.ids.share_result.text = (
            f"Seu level: {level}\n"
            f"Pode sharear com: {min_level} até {max_level}"
        )

    # --------------------
    # Bosses (ExevoPan)
    # --------------------
    def load_bosses(self):
        scr = self.root.get_screen("bosses")
        scr.ids.boss_status.text = "Carregando..."
        scr.ids.boss_list.clear_widgets()

        def run():
            try:
                bosses = fetch_exevopan_bosses()
                Clock.schedule_once(lambda *_: self._render_bosses(bosses), 0)
            except Exception:
                traceback.print_exc()
                Clock.schedule_once(lambda *_: self._set_boss_status("Erro ao carregar."), 0)

        threading.Thread(target=run, daemon=True).start()

    def _set_boss_status(self, text: str):
        try:
            scr = self.root.get_screen("bosses")
            scr.ids.boss_status.text = text
        except Exception:
            pass

    def _render_bosses(self, bosses):
        scr = self.root.get_screen("bosses")
        scr.ids.boss_list.clear_widgets()
        if not bosses:
            scr.ids.boss_status.text = "Sem dados."
            return

        scr.ids.boss_status.text = f"{len(bosses)} bosses"
        for b in bosses:
            name = b.get("name", "")
            status = b.get("status", "")
            when = b.get("when", "")
            txt = f"{name} — {status} {when}".strip()
            item = OneLineIconListItem(text=txt)
            item.add_widget(IconLeftWidget(icon="skull"))
            scr.ids.boss_list.add_widget(item)

    # --------------------
    # Boosted
    # --------------------
    def update_boosted(self):
        scr = self.root.get_screen("boosted")
        scr.ids.boost_status.text = "Carregando..."

        def run():
            try:
                data = fetch_boosted()
                self._boost_cache = data
                Clock.schedule_once(lambda *_: self._render_boosted(data), 0)
            except Exception:
                traceback.print_exc()
                Clock.schedule_once(lambda *_: self._set_boost_status("Erro ao carregar."), 0)

        threading.Thread(target=run, daemon=True).start()

    def _set_boost_status(self, text: str):
        try:
            scr = self.root.get_screen("boosted")
            scr.ids.boost_status.text = text
        except Exception:
            pass

    def _render_boosted(self, data):
        scr = self.root.get_screen("boosted")
        if not data:
            scr.ids.boost_status.text = "Sem dados."
            scr.ids.boost_creature.text = ""
            scr.ids.boost_boss.text = ""
            return

        scr.ids.boost_status.text = "OK"
        scr.ids.boost_creature.text = f"Creature: {data.get('creature','')}"
        scr.ids.boost_boss.text = f"Boss: {data.get('boss','')}"

    # --------------------
    # Training
    # --------------------
    def init_training_dropdowns(self):
        scr = self.root.get_screen("training")

        worlds = []
        try:
            worlds = fetch_worlds_tibiadata() or []
        except Exception:
            worlds = []

        if worlds:
            scr.ids.world_field.text = worlds[0]

        # Voc
        vocs = ["Knight", "Paladin", "Sorcerer", "Druid"]
        scr.ids.voc_drop.text = vocs[0]
        voc_items = [{"text": v, "on_release": lambda x=v: self._set_dropdown(scr.ids.voc_drop, x)} for v in vocs]
        scr.ids.voc_menu = MDDropdownMenu(caller=scr.ids.voc_drop, items=voc_items, width_mult=3)

        # Skill
        skills = ["Sword", "Axe", "Club", "Distance", "Magic"]
        scr.ids.skill_drop.text = skills[0]
        skill_items = [{"text": s, "on_release": lambda x=s: self._set_dropdown(scr.ids.skill_drop, x)} for s in skills]
        scr.ids.skill_menu = MDDropdownMenu(caller=scr.ids.skill_drop, items=skill_items, width_mult=3)

        # Weapon
        weapons = ["Exercise Weapon", "Exercise Dummy"]
        scr.ids.weapon_drop.text = weapons[0]
        weapon_items = [{"text": w, "on_release": lambda x=w: self._set_dropdown(scr.ids.weapon_drop, x)} for w in weapons]
        scr.ids.weapon_menu = MDDropdownMenu(caller=scr.ids.weapon_drop, items=weapon_items, width_mult=3)

    def _set_dropdown(self, widget, value):
        widget.text = value
        try:
            if hasattr(widget, "menu"):
                widget.menu.dismiss()
        except Exception:
            pass

    def open_dropdown(self, menu_attr: str):
        scr = self.root.get_screen("training")
        menu = getattr(scr.ids, menu_attr, None)
        if menu:
            menu.open()

    def calc_training(self):
        scr = self.root.get_screen("training")

        try:
            from_level = int((scr.ids.from_level.text or "0").strip())
            to_level = int((scr.ids.to_level.text or "0").strip())
        except ValueError:
            self.toast("Levels inválidos.")
            return

        if from_level <= 0 or to_level <= 0 or to_level <= from_level:
            self.toast("Informe levels válidos (to > from).")
            return

        loyalty = 0
        try:
            loyalty = int((scr.ids.loyalty.text or "0").strip())
        except Exception:
            loyalty = 0

        world = (scr.ids.world_field.text or "").strip()
        voc = (scr.ids.voc_drop.text or "").strip()
        skill = (scr.ids.skill_drop.text or "").strip()
        weapon = (scr.ids.weapon_drop.text or "").strip()

        inp = TrainingInput(
            world=world,
            vocation=voc,
            skill=skill,
            from_level=from_level,
            to_level=to_level,
            weapon_kind=weapon,
            loyalty_percent=loyalty,
            private_dummy=scr.ids.private_dummy.active,
            double_event=scr.ids.double_event.active,
        )

        scr.ids.train_status.text = "Calculando..."
        scr.ids.train_result.text = ""

        def run():
            try:
                plan = compute_training_plan(inp)
                Clock.schedule_once(lambda *_: self._render_training(plan), 0)
            except Exception:
                traceback.print_exc()
                Clock.schedule_once(lambda *_: self._set_training_error(), 0)

        threading.Thread(target=run, daemon=True).start()

    def _set_training_error(self):
        scr = self.root.get_screen("training")
        scr.ids.train_status.text = "Erro ao calcular."
        scr.ids.train_result.text = "Veja o logcat (Traceback)."

    def _render_training(self, plan):
        scr = self.root.get_screen("training")
        if not plan:
            scr.ids.train_status.text = "Sem resultado."
            return

        scr.ids.train_status.text = "OK"
        scr.ids.train_result.text = plan

    # --------------------
    # Hunt Analyzer
    # --------------------
    def analyze_hunt(self):
        scr = self.root.get_screen("hunt")
        text = (scr.ids.hunt_input.text or "").strip()
        if not text:
            self.toast("Cole o texto do analisador (session).")
            return

        scr.ids.hunt_status.text = "Analisando..."
        scr.ids.hunt_output.text = ""

        def run():
            try:
                out = parse_hunt_session_text(text)
                Clock.schedule_once(lambda *_: self._render_hunt(out), 0)
            except Exception:
                traceback.print_exc()
                Clock.schedule_once(lambda *_: self._hunt_error(), 0)

        threading.Thread(target=run, daemon=True).start()

    def _hunt_error(self):
        scr = self.root.get_screen("hunt")
        scr.ids.hunt_status.text = "Erro ao analisar."
        scr.ids.hunt_output.text = "Veja o logcat (Traceback)."

    def _render_hunt(self, out: str):
        scr = self.root.get_screen("hunt")
        scr.ids.hunt_status.text = "OK"
        scr.ids.hunt_output.text = out or ""

    # --------------------
    # Imbuements
    # --------------------
    def imbu_search(self):
        scr = self.root.get_screen("imbuements")
        query = (scr.ids.imb_search.text or "").strip()
        if not query:
            self.toast("Digite algo para buscar.")
            return

        scr.ids.imb_status.text = "Buscando..."
        scr.ids.imb_list.clear_widgets()

        def run():
            try:
                results = search_imbuements(query)
                Clock.schedule_once(lambda *_: self._render_imbu(results), 0)
            except Exception:
                traceback.print_exc()
                Clock.schedule_once(lambda *_: self._imbu_error(), 0)

        threading.Thread(target=run, daemon=True).start()

    def _imbu_error(self):
        scr = self.root.get_screen("imbuements")
        scr.ids.imb_status.text = "Erro ao buscar."
        scr.ids.imb_list.clear_widgets()

    def _render_imbu(self, items: List[ImbuementEntry]):
        scr = self.root.get_screen("imbuements")
        scr.ids.imb_list.clear_widgets()

        if not items:
            scr.ids.imb_status.text = "Nada encontrado."
            return

        scr.ids.imb_status.text = f"{len(items)} resultados"
        for ent in items:
            item = OneLineIconListItem(text=ent.name)
            item.add_widget(IconLeftWidget(icon="flash"))
            item.bind(on_release=lambda _item, e=ent: self._imbu_show(e))
            scr.ids.imb_list.add_widget(item)

    def _imbu_show(self, ent: ImbuementEntry):
        text = f"Basic:\n{ent.basic}\n\nIntricate:\n{ent.intricate}\n\nPowerful:\n{ent.powerful}\n\n(Fonte: TibiaWiki)"
        dlg = MDDialog(
            title=ent.name,
            text=text,
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda *_: dlg.dismiss())],
        )
        dlg.open()

    # --------------------
    # Storage
    # --------------------
    def load_favorites(self):
        data = safe_read_json(self.fav_path)
        if isinstance(data, list):
            self.favorites = [str(x) for x in data]
        else:
            self.favorites = []

    def save_favorites(self):
        safe_write_json(self.fav_path, self.favorites)

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
            try:
                MDSnackbar(MDSnackbarText(text=message)).open()
                return
            except Exception:
                pass
        except Exception:
            pass

        # fallback: imprime no console
        print(message)


if __name__ == "__main__":
    TibiaToolsApp().run()
