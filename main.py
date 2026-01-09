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

# ---- IMPORTS DO CORE (com proteção para não “fechar sozinho” no Android) ----
_CORE_IMPORT_ERROR = None
try:
    from core.api import fetch_character_tibiadata, fetch_worlds_tibiadata, is_character_online_tibiadata
    from core.storage import get_data_dir, safe_read_json, safe_write_json
    from core.bosses import fetch_exevopan_bosses
    from core.boosted import fetch_boosted
    from core.training import TrainingInput, compute_training_plan
    from core.hunt import parse_hunt_session_text
    from core.imbuements import fetch_imbuements_table, fetch_imbuement_details, ImbuementEntry
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

        self._menu_world: Optional[MDDropdownMenu] = None
        self._menu_skill: Optional[MDDropdownMenu] = None
        self._menu_vocation: Optional[MDDropdownMenu] = None
        self._menu_weapon: Optional[MDDropdownMenu] = None

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
            Clock.schedule_once(lambda *_: self.refresh_favorites_list(), 0)
            Clock.schedule_once(lambda *_: self.update_boosted(), 0)

        return root

    # --------------------
    # Navigation
    # --------------------
    def go(self, screen_name: str):
        sm = self.root
        if isinstance(sm, ScreenManager) and screen_name in sm.screen_names:
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
                character_wrapper = data.get("character", {})
                character = character_wrapper.get("character", character_wrapper) if isinstance(character_wrapper, dict) else {}
                url = f"https://www.tibia.com/community/?subtopic=characters&name={name.replace(' ', '+')}"
                voc = character.get("vocation", "N/A")
                level = character.get("level", "N/A")
                world = character.get("world", "N/A")

                status = character.get("status") or ""
                if not status or str(status).strip().upper() == "N/A":
                    online = is_character_online_tibiadata(name, world) if world and world != 'N/A' else None
                    if online is True:
                        status = "online"
                    elif online is False:
                        status = "offline"
                    else:
                        status = "N/A"

                guild = character.get("guild") or {}
                if isinstance(guild, dict) and guild.get("name"):
                    gname = str(guild.get("name") or "").strip()
                    grank = str(guild.get("rank") or guild.get("title") or "").strip()
                    guild_line = f"Guild: {gname}{(' (' + grank + ')') if grank else ''}"
                else:
                    guild_line = "Guild: N/A"

                houses = character.get("houses") or []
                if isinstance(houses, list):
                    if not houses:
                        house_line = "Houses: Nenhuma"
                    else:
                        parts = []
                        for h in houses[:3]:
                            if isinstance(h, dict):
                                hn = str(h.get("name") or h.get("house") or "").strip()
                                ht = str(h.get("town") or "").strip()
                                if hn and ht:
                                    parts.append(f"{hn} ({ht})")
                                elif hn:
                                    parts.append(hn)
                            elif isinstance(h, str):
                                parts.append(h.strip())
                        parts = [p for p in parts if p]
                        more = f" (+{len(houses) - len(parts)}...)" if len(houses) > len(parts) and parts else ""
                        house_line = "Houses: " + (", ".join(parts) + more if parts else f"{len(houses)}")
                else:
                    house_line = "Houses: N/A"

                deaths = (character.get('deaths') or character_wrapper.get('deaths') or data.get('deaths') or [])
                deaths_text = ""
                if isinstance(deaths, list) and deaths:
                    rows = []
                    for d in deaths[:5]:
                        if not isinstance(d, dict):
                            continue
                        time_s = str(d.get("time") or d.get("date") or "").strip()
                        lvl_s = str(d.get("level") or "").strip()
                        reason_s = str(d.get("reason") or d.get("description") or "").strip()
                        if reason_s:
                            if lvl_s:
                                rows.append(f"- {time_s} (lvl {lvl_s}): {reason_s}".strip())
                            else:
                                rows.append(f"- {time_s}: {reason_s}".strip())
                    if rows:
                        deaths_text = "\nÚltimas mortes:\n" + "\n".join(rows)

                result = (
                    f"Status: {status}\n"
                    f"Vocation: {voc}\n"
                    f"Level: {level}\n"
                    f"World: {world}\n"
                    f"{guild_line}\n"
                    f"{house_line}"
                    f"{deaths_text}"
                )
                return True, result, url
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
    # Shared XP tab
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

        min_level = int(math.ceil(level * 2.0 / 3.0))
        max_level = int(math.floor(level * 3.0 / 2.0))

        home.ids.share_result.text = (
            f"Seu level: {level}\n"
            f"Pode sharear com: {min_level} até {max_level}"
        )

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
        # Abre primeiro com placeholder e depois carrega os itens sob demanda.
        page = (getattr(ent, "page", "") or "").strip()
        title = ent.name

        dlg = MDDialog(
            title=title,
            text="Carregando detalhes do TibiaWiki...",
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda *_: dlg.dismiss())],
        )
        dlg.open()

        def run():
            try:
                # se não tiver página, tenta usar o próprio nome como title
                ok, data = fetch_imbuement_details(page or title.replace(" ", "_"))
                if not ok:
                    msg = f"Erro ao carregar detalhes:
{data}"
                    Clock.schedule_once(lambda *_: setattr(dlg, "text", msg), 0)
                    return

                tiers = data  # type: ignore[assignment]
                def fmt(tkey: str, label: str) -> str:
                    effect = str(tiers.get(tkey, {}).get("effect", "")).strip()
                    items = tiers.get(tkey, {}).get("items", []) or []
                    lines = []
                    if effect:
                        lines.append(f"Efeito: {effect}")
                    if items:
                        lines.append("Itens:")
                        for it in items[:50]:
                            lines.append(f"- {it}")
                    else:
                        lines.append("Itens: (não encontrado)")
                    return f"{label}:
" + "
".join(lines)

                text = (
                    fmt("basic", "Basic")
                    + "

"
                    + fmt("intricate", "Intricate")
                    + "

"
                    + fmt("powerful", "Powerful")
                    + "

(Fonte: TibiaWiki BR)"
                )
                Clock.schedule_once(lambda *_: setattr(dlg, "text", text), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(dlg, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    TibiaToolsApp().run()
