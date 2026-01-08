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
from typing import List, Optional

from kivy.core.window import Window
from kivy.lang import Builder
from kivy.resources import resource_find
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.screenmanager import ScreenManager

from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.list import OneLineIconListItem, IconLeftWidget
from kivymd.uix.menu import MDDropdownMenu

CORE_IMPORT_ERROR = None
try:
    from core.api import fetch_character_tibiadata, fetch_worlds_tibiadata, is_character_online_tibiadata
    from core.storage import get_data_dir, safe_read_json, safe_write_json
    from core.bosses import fetch_exevopan_bosses
    from core.boosted import fetch_boosted
    from core.training import TrainingInput, compute_training_plan
    from core.hunt import parse_hunt_session_text
    from core.imbuements import fetch_imbuements_table, ImbuementEntry
except Exception:
    CORE_IMPORT_ERROR = traceback.format_exc()


KV_FILE = "tibia_tools.kv"


class RootSM(ScreenManager):
    pass


class MoreItem(OneLineIconListItem):
    icon = StringProperty("chevron-right")


class TibiaToolsApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.favorites: List[str] = []

        self.data_dir = get_data_dir()
        os.makedirs(self.data_dir, exist_ok=True)
        self.fav_path = os.path.join(self.data_dir, "favorites.json")

        self._menu_world: Optional[MDDropdownMenu] = None
        self._menu_skill: Optional[MDDropdownMenu] = None
        self._menu_vocation: Optional[MDDropdownMenu] = None
        self._menu_weapon: Optional[MDDropdownMenu] = None

    def build(self):
        if CORE_IMPORT_ERROR:
            from kivymd.uix.label import MDLabel
            # Mostra o erro na tela (sem precisar de logcat)
            txt = CORE_IMPORT_ERROR[-2000:]
            return MDLabel(text="Erro de dependência/import:\n\n"+txt, halign="left")

        Window.softinput_mode = "below_target"
        self.icon = "assets/icon.png"
        self.title = "Tibia Tools"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Dark"

        try:
            kv_path = resource_find(KV_FILE) or KV_FILE
            root = Builder.load_file(kv_path)
        except Exception:
            # Vai aparecer no logcat como Python traceback
            traceback.print_exc()
            # Mostra o erro na tela em vez de fechar sem explicar
            from kivymd.uix.label import MDLabel
            root = MDLabel(text="Erro ao iniciar. Veja o logcat (Traceback).", halign="center")
        self.load_favorites()
        Clock.schedule_once(lambda *_: self.refresh_favorites_list(), 0)
        Clock.schedule_once(lambda *_: self.update_boosted(), 0)
        return root

    # --------------------
    # Navigation
    # --------------------
    def go(self, screen_name: str):
        sm: RootSM = self.root
        if screen_name in sm.screen_names:
            sm.current = screen_name

    def back_home(self, *_):
        self.go("home")

    def open_more_target(self, target: str):
        self.go(target)
        if target == "bosses":
            self._bosses_refresh_worlds()
        elif target == "imbuements":
            self._imbuements_load()
        elif target == "training":
            self._ensure_training_menus()

    # --------------------
    # Storage
    # --------------------
    def load_favorites(self):
        data = safe_read_json(self.fav_path, default=[])
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
            sb = MDSnackbar(MDSnackbarText(text=message))
            sb.open()
            return
        except Exception:
            pass

        print(f"[TOAST] {message}")


    # --------------------
    # Char tab
    # --------------------

def search_character(self):
    home = self.root.get_screen("home")
    name = (home.ids.char_name.text or "").strip()
    if not name:
        self.toast("Digite o nome do char.")
        return

    home.ids.char_status.text = "Buscando..."
    home.char_last_url = ""

    def worker():
        try:
            data = fetch_character_tibiadata(name)
            if not data:
                raise ValueError("Sem resposta da API.")

            cw = data.get("character", {}) or {}
            c = cw.get("character", {}) or {}

            url = c.get("url") or ""

            voc = c.get("vocation") or "N/A"
            level = c.get("level") if c.get("level") is not None else "N/A"
            world = c.get("world") or "N/A"

            # Status pode vir direto do endpoint, mas nem sempre vem preenchido
            status_raw = (c.get("status") or "").strip().lower()
            if status_raw in ("online", "offline"):
                status = status_raw
            else:
                online = None
                if world and world != "N/A":
                    online = is_character_online_tibiadata(name, world)
                if online is True:
                    status = "online"
                elif online is False:
                    status = "offline"
                else:
                    status = "N/A"

            # Guild
            guild_txt = ""
            g = c.get("guild")
            if isinstance(g, dict):
                gname = (g.get("name") or "").strip()
                grank = (g.get("rank") or "").strip()
                if gname and grank:
                    guild_txt = f"{gname} ({grank})"
                elif gname:
                    guild_txt = gname

            # Houses
            houses_txt = ""
            houses = c.get("houses") or []
            if isinstance(houses, list) and houses:
                parts = []
                for h in houses:
                    if not isinstance(h, dict):
                        continue
                    hname = (h.get("name") or "").strip()
                    htown = (h.get("town") or h.get("location") or "").strip()
                    if hname and htown:
                        parts.append(f"{hname} ({htown})")
                    elif hname:
                        parts.append(hname)
                if parts:
                    houses_txt = "; ".join(parts)

            # Últimas mortes
            deaths = cw.get("deaths") or c.get("deaths") or data.get("deaths") or []
            death_lines = []
            if isinstance(deaths, list) and deaths:
                for d in deaths[:5]:
                    if not isinstance(d, dict):
                        continue
                    when = (d.get("time") or d.get("date") or "").strip()
                    lvl = d.get("level")
                    lvl_txt = f"lvl {lvl}" if lvl is not None else ""
                    reason = (d.get("reason") or d.get("description") or "").strip()

                    involved = d.get("involved") or []
                    killers = []
                    if isinstance(involved, list):
                        for inv in involved:
                            if isinstance(inv, dict) and inv.get("name"):
                                killers.append(inv["name"])
                            elif isinstance(inv, str):
                                killers.append(inv)
                    if killers and reason and "by" not in reason.lower():
                        reason = f"{reason} (by {', '.join(killers)})"

                    line = f"- {when} {lvl_txt} {reason}".strip()
                    death_lines.append(line)

            result_lines = [
                f"Status: {status}",
                f"Vocation: {voc}",
                f"Level: {level}",
                f"World: {world}",
            ]
            if guild_txt:
                result_lines.append(f"Guild: {guild_txt}")
            if houses_txt:
                result_lines.append(f"Houses: {houses_txt}")
            if death_lines:
                result_lines.append("Últimas mortes:")
                result_lines.extend(death_lines)

            return True, "\n".join(result_lines), url
        except Exception as e:
            return False, f"Erro: {e}", ""

    def done(res):
        ok, text, url = res
        home.ids.char_status.text = text
        home.char_last_url = url
        if ok:
            self.toast("Char encontrado.")

    def run():
        res = worker()
        Clock.schedule_once(lambda *_: done(res), 0)

    threading.Thread(target=run, daemon=True).start()

def calc_shared_xp(self):
    home = self.root.get_screen("home")
    txt = (home.ids.share_level.text or "").strip()
    if not txt:
        home.ids.share_result.text = "Digite um level."
        return
    try:
        lvl = int(txt)
        if lvl <= 0:
            raise ValueError
    except Exception:
        home.ids.share_result.text = "Level inválido."
        return

    # Regra oficial: menor >= 2/3 do maior
    # Para um level L, a faixa que consegue sharear é:
    # ceil(L*2/3) até floor(L*3/2)
    import math
    min_lvl = math.ceil(lvl * 2 / 3)
    max_lvl = math.floor(lvl * 3 / 2)

    home.ids.share_result.text = (
        f"Para o level {lvl}, dá para sharear com levels\n"
        f"de {min_lvl} até {max_lvl}."
    )

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
    def refresh_favorites_list(self):
        home = self.root.get_screen("home")
        container = home.ids.fav_list
        container.clear_widgets()

        if not self.favorites:
            item = OneLineIconListItem(text="Sem favoritos. Adicione no Char.")
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
            webbrowser.open(f"https://www.tibia.com/community/?subtopic=characters&name={name.replace(' ', '+')}")
            dlg.dismiss()

        dlg = MDDialog(
            title=name,
            text="O que você quer fazer?",
            buttons=[
                MDFlatButton(text="ABRIR", on_release=open_char),
                MDFlatButton(text="REMOVER", on_release=remove),
                MDFlatButton(text="FECHAR", on_release=lambda *_: dlg.dismiss()),
            ],
        )
        dlg.open()

    # --------------------


    # --------------------
    # Bosses (ExevoPan)
    # --------------------
    def _bosses_refresh_worlds(self):
        scr = self.root.get_screen("bosses")
        scr.ids.boss_status.text = "Carregando worlds..."

        def worker():
            data = fetch_worlds_tibiadata()
            return sorted([w.get("name") for w in data.get("worlds", {}).get("regular_worlds", []) if w.get("name")])

        def done(worlds):
            scr.ids.boss_status.text = f"Worlds: {len(worlds)}"
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
        if self._menu_world:
            self._menu_world.dismiss()

    def bosses_fetch(self):
        scr = self.root.get_screen("bosses")
        world = (scr.ids.world_field.text or "").strip()
        if not world:
            self.toast("Digite o world.")
            return

        scr.ids.boss_status.text = "Buscando bosses..."
        scr.ids.boss_list.clear_widgets()

        def run():
            try:
                bosses = fetch_exevopan_bosses(world)
                Clock.schedule_once(lambda *_: self._bosses_done(bosses), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(scr.ids.boss_status, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()

    def _bosses_done(self, bosses):
        scr = self.root.get_screen("bosses")
        scr.ids.boss_list.clear_widgets()
        if not bosses:
            scr.ids.boss_status.text = "Nada encontrado (ou ExevoPan indisponível)."
            return
        scr.ids.boss_status.text = f"Encontrado(s): {len(bosses)}"
        for b in bosses[:200]:
            title = b.get("boss") or b.get("name") or "Boss"
            chance = b.get("chance") or ""
            status = b.get("status") or ""
            extra = " | ".join([x for x in [chance, status] if x])
            item = OneLineIconListItem(text=f"{title}{(' - ' + extra) if extra else ''}")
            item.add_widget(IconLeftWidget(icon="skull"))
            scr.ids.boss_list.add_widget(item)

    # --------------------
    # Boosted
    # --------------------
    def update_boosted(self):
        scr = self.root.get_screen("boosted")
        scr.ids.boost_status.text = "Atualizando..."

        def run():
            try:
                data = fetch_boosted()
                Clock.schedule_once(lambda *_: self._boosted_done(data), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(scr.ids.boost_status, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()

    def _boosted_done(self, data):
        scr = self.root.get_screen("boosted")
        if not data:
            scr.ids.boost_status.text = "Falha ao buscar Boosted."
            return
        scr.ids.boost_status.text = "OK"
        scr.ids.boost_creature.text = data.get("creature", "N/A")
        scr.ids.boost_boss.text = data.get("boss", "N/A")

    # --------------------
    # Training (Exercise)
    # --------------------
    def _ensure_training_menus(self):
        scr = self.root.get_screen("training")

        if self._menu_skill is None:
            skills = ["Sword", "Axe", "Club", "Distance", "Shielding", "Magic Level", "Fist Fighting"]
            self._menu_skill = MDDropdownMenu(
                caller=scr.ids.skill_drop,
                items=[{"text": s, "on_release": (lambda x=s: self._set_training_skill(x))} for s in skills],
                width_mult=4,
                max_height=dp(320),
            )
        # Menus de vocation/weapon só existem em algumas versões do KV.
        if 'voc_drop' in scr.ids and 'voc_field' in scr.ids:
            if self._menu_vocation is None:
                            vocs = ["Knight", "Paladin", "Druid/Sorcerer", "None"]
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
            loyalty = float((scr.ids.loyalty.text or "0").replace(",", ".").strip() or 0)
        except ValueError:
            self.toast("Verifique os campos numéricos.")
            return

        skill = (scr.ids.skill_field.text or "Sword").strip()
        voc_w = scr.ids.get("voc_field")
        weapon_w = scr.ids.get("weapon_field")
        voc = ((voc_w.text if voc_w else "") or "Knight").strip()
        weapon = ((weapon_w.text if weapon_w else "") or "Enhanced (1800)").strip()
        # inferência simples se não houver campo de vocation
        if "voc_field" not in scr.ids:
            if skill == "Magic Level":
                voc = "Mage"
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
    def _imbuements_load(self):
        scr = self.root.get_screen("imbuements")
        scr.entries = []
        scr.ids.imb_status.text = "Carregando (TibiaWiki)..."
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
        self.imbuements_refresh_list()

    def imbuements_refresh_list(self):
        scr = self.root.get_screen("imbuements")
        q = (scr.ids.imb_search.text or "").strip().lower()
        scr.ids.imb_list.clear_widgets()
        entries: List[ImbuementEntry] = getattr(scr, "entries", [])
        filtered = [e for e in entries if q in e.name.lower()] if q else entries

        for e in filtered[:200]:
            item = OneLineIconListItem(text=e.name)
            item.add_widget(IconLeftWidget(icon="flash"))
            item.bind(on_release=lambda _item, ent=e: self._imbu_show(ent))
            scr.ids.imb_list.add_widget(item)

    def _imbu_show(self, ent: ImbuementEntry):
        text = f"Basic:\n{ent.basic}\n\nIntricate:\n{ent.intricate}\n\nPowerful:\n{ent.powerful}\n\n(Fonte: TibiaWiki)"
        dlg = MDDialog(
            title=ent.name,
            text=text,
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda *_: dlg.dismiss())],
        )
        dlg.open()


if __name__ == "__main__":
    TibiaToolsApp().run()