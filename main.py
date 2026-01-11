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
from datetime import datetime, timedelta
from urllib.parse import quote
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
from kivymd.uix.list import OneLineIconListItem, TwoLineIconListItem, IconLeftWidget
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
    from core.storage import get_data_dir, safe_read_json, safe_write_json
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

        st = status.strip().lower()
        if st == "online":
            badge = "[b][color=#2ecc71]ONLINE[/color][/b]"
            status_icon = "wifi"
        elif st == "offline":
            badge = "[b][color=#e74c3c]OFFLINE[/color][/b]"
            status_icon = "wifi-off"
        else:
            badge = "[b][color=#bdc3c7]N/A[/color][/b]"
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

            add_one(f"Status: {status}", status_icon)
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

                # Status: a API /v4/character pode ficar "atrasada".
                # Primeiro: tenta lista de online via TibiaData (/v4/world/{world}).
                # Se falhar (ou disser OFFLINE), tenta fallback no site oficial (tibia.com).
                status_raw = str(character.get("status") or "").strip().lower()

                online_td = (
                    is_character_online_tibiadata(name, world)
                    if world and str(world).strip().upper() != "N/A"
                    else None
                )

                online_web = None
                if (online_td is None or online_td is False) and world and str(world).strip().upper() != "N/A":
                    online_web = is_character_online_tibia_com(name, world)

                # Regra anti-falso-negative:
                # - ONLINE se qualquer fonte confirmar
                # - OFFLINE apenas se TODAS as fontes consultadas confirmarem
                # - senão, usamos o status bruto da TibiaData (pode ser "offline" quando está atrasado)
                if online_td is True or online_web is True:
                    status = "online"
                elif online_td is False and online_web is False:
                    status = "offline"
                elif status_raw:
                    status = status_raw
                else:
                    status = "N/A"

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

                # Complemento: XP lost por morte (fansite). Match por ordem (mais recente -> mais recente).
                try:
                    xp_list = fetch_guildstats_deaths_xp(title or name)
                except Exception:
                    xp_list = []
                if xp_list:
                    for i, d in enumerate(deaths):
                        if i >= len(xp_list):
                            break
                        if isinstance(d, dict) and "exp_lost" not in d:
                            d["exp_lost"] = xp_list[i]

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
            item.bind(on_release=lambda _item, n=title: self._boss_open_prompt(n))
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
        # Abre primeiro com placeholder e depois carrega os itens (sob demanda)
        title = (ent.name or "").strip()

        dlg = MDDialog(
            title=title,
            text="Carregando detalhes...",
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda *_: dlg.dismiss())
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
                Clock.schedule_once(lambda *_: setattr(dlg, "text", text), 0)
            except Exception as e:
                Clock.schedule_once(lambda *_: setattr(dlg, "text", f"Erro: {e}"), 0)

        threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    TibiaToolsApp().run()