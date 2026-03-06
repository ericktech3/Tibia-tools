from __future__ import annotations

import math
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timedelta

import requests
from kivy.clock import Clock
from kivy.metrics import dp
from kivymd.uix.list import OneLineIconListItem, TwoLineIconListItem, IconLeftWidget
from kivymd.uix.menu import MDDropdownMenu

from integrations.tibiadata import (
    fetch_character_tibiadata,
    fetch_guildstats_deaths_xp,
    fetch_guildstats_exp_changes,
)
from integrations.tibia_com import is_character_online_tibia_com
from core.exp_loss import estimate_death_exp_lost
from services.error_reporting import log_current_exception


class CharControllerMixin:
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

    def _safe_menu_dismiss(self, attr_name: str) -> None:
        menu = getattr(self, attr_name, None)
        if menu is None:
            return
        try:
            menu.dismiss()
        except Exception:
            log_current_exception(prefix=f"[char] falha ao fechar menu {attr_name}")
        setattr(self, attr_name, None)

    def _safe_parse_iso_datetime(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).strip())
        except ValueError:
            return None

    def _safe_parse_iso_date(self, value):
        dt = self._safe_parse_iso_datetime(value)
        return dt.date() if dt else None

    def _safe_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _favorite_names_set(self) -> set[str]:
        return {str(x).strip().lower() for x in (getattr(self, "favorites", []) or []) if str(x).strip()}

    def clear_char_search(self):
        home = self._get_home_screen()
        ids = getattr(home, "ids", None) if home is not None else None
        char_name = ids.get("char_name") if hasattr(ids, "get") else None
        if char_name is None:
            return
        char_name.text = ""
        try:
            char_name.focus = True
        except Exception:
            log_current_exception(prefix="[char] falha ao focar campo de busca")

    def open_char_from_account_list(self, name: str):
        """Abre (pesquisa) um personagem a partir da lista 'Outros chars na conta'."""
        nm = (name or "").strip()
        if not nm:
            return
        home = self._get_home_screen()
        ids = getattr(home, "ids", None) if home is not None else None
        char_name = ids.get("char_name") if hasattr(ids, "get") else None
        if char_name is not None:
            char_name.text = nm
            try:
                char_name.focus = False
            except Exception:
                log_current_exception(prefix="[char] falha ao desfocar campo de busca")
        try:
            self.search_character()
        except Exception:
            log_current_exception(prefix="[char] falha ao abrir personagem da conta")

    def _get_char_history(self) -> list[str]:
        hist = self._prefs_get("char_history", []) or []
        if not isinstance(hist, list):
            return []
        out = []
        for value in hist:
            item = str(value or "").strip()
            if item:
                out.append(item)
        return out

    def _add_to_char_history(self, name: str) -> None:
        name = (name or "").strip()
        if not name:
            return
        try:
            hist = [h for h in self._get_char_history() if h.strip().lower() != name.lower()]
            hist.insert(0, name)
            self._prefs_set("char_history", hist[:12])
        except Exception:
            log_current_exception(prefix=f"[char] falha ao salvar histórico: {name}")

    def open_char_history_menu(self):
        home = self._get_home_screen()
        ids = getattr(home, "ids", None) if home is not None else None
        anchor = ids.get("char_name") if hasattr(ids, "get") else None
        if anchor is None:
            return

        hist = self._get_char_history()
        if not hist:
            self.toast("Sem histórico ainda.")
            return

        def pick(selected: str):
            char_name = ids.get("char_name") if hasattr(ids, "get") else None
            if char_name is None:
                return
            char_name.text = selected
            self._safe_menu_dismiss("_menu_char_history")
            try:
                char_name.focus = True
            except Exception:
                log_current_exception(prefix="[char] falha ao focar histórico")

        menu_items = [
            {
                "viewclass": "OneLineListItem",
                "text": item,
                "on_release": (lambda selected=item: pick(selected)),
            }
            for item in hist
        ]

        self._safe_menu_dismiss("_menu_char_history")
        self._menu_char_history = MDDropdownMenu(
            caller=anchor,
            items=menu_items,
            width_mult=4,
            max_height=dp(320),
        )
        self._menu_char_history.open()

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
        ids = getattr(home, "ids", None)
        if ids is None:
            return

        if "char_title" in ids and "char_details_list" in ids and "char_deaths_list" in ids:
            ids.char_title.text = name
            ids.char_badge.text = ""
            ids.char_details_list.clear_widgets()

            item = OneLineIconListItem(text="Buscando informações...")
            item.add_widget(IconLeftWidget(icon="cloud-search"))
            ids.char_details_list.add_widget(item)

            ids.char_deaths_list.clear_widgets()
            death_item = OneLineIconListItem(text="Aguardando...")
            death_item.add_widget(IconLeftWidget(icon="skull-outline"))
            ids.char_deaths_list.add_widget(death_item)

            xp_total = ids.get("char_xp_total") if hasattr(ids, "get") else None
            xp_list = ids.get("char_xp_list") if hasattr(ids, "get") else None
            if xp_total is not None:
                xp_total.text = "Carregando histórico de XP..."
                xp_total.theme_text_color = "Hint"
            if xp_list is not None:
                xp_list.clear_widgets()
                xp_item = OneLineIconListItem(text="Buscando histórico de XP...")
                xp_item.add_widget(IconLeftWidget(icon="chart-line"))
                xp_list.add_widget(xp_item)

            account_list = ids.get("char_account_list") if hasattr(ids, "get") else None
            if account_list is not None:
                account_list.clear_widgets()
                acc_item = OneLineIconListItem(text="Aguardando...")
                acc_item.add_widget(IconLeftWidget(icon="account-multiple"))
                account_list.add_widget(acc_item)
            return

        char_status = ids.get("char_status") if hasattr(ids, "get") else None
        if char_status is not None:
            char_status.text = "Buscando..."

    def _char_show_error(self, home, message: str):
        ids = getattr(home, "ids", None)
        if ids is None:
            return

        if "char_title" in ids and "char_details_list" in ids and "char_deaths_list" in ids:
            ids.char_title.text = "Erro"
            ids.char_badge.text = ""
            ids.char_details_list.clear_widgets()

            item = OneLineIconListItem(text=message)
            item.add_widget(IconLeftWidget(icon="alert-circle-outline"))
            ids.char_details_list.add_widget(item)

            ids.char_deaths_list.clear_widgets()
            death_item = OneLineIconListItem(text="—")
            death_item.add_widget(IconLeftWidget(icon="skull-outline"))
            ids.char_deaths_list.add_widget(death_item)

            xp_total = ids.get("char_xp_total") if hasattr(ids, "get") else None
            xp_list = ids.get("char_xp_list") if hasattr(ids, "get") else None
            if xp_total is not None:
                xp_total.text = "—"
                xp_total.theme_text_color = "Hint"
            if xp_list is not None:
                xp_list.clear_widgets()
                xp_item = OneLineIconListItem(text="Sem dados.")
                xp_item.add_widget(IconLeftWidget(icon="chart-line"))
                xp_list.add_widget(xp_item)

            account_list = ids.get("char_account_list") if hasattr(ids, "get") else None
            if account_list is not None:
                account_list.clear_widgets()
                acc_item = OneLineIconListItem(text="—")
                acc_item.add_widget(IconLeftWidget(icon="account-multiple"))
                account_list.add_widget(acc_item)
            return

        char_status = ids.get("char_status") if hasattr(ids, "get") else None
        if char_status is not None:
            char_status.text = message

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
        setattr(home, "char_xp_source_url", str(payload.get("gs_exp_url") or ""))
        setattr(home, "_last_char_payload", payload)

        # Side-effects (prefs/history/dashboard) apenas na primeira renderização do resultado.
        if side_effects:
            if title:
                try:
                    self._prefs_set("last_char", title)
                    self._add_to_char_history(title)
                except Exception:
                    log_current_exception(prefix=f"[char] falha ao persistir resultado: {title}")
            try:
                self.dashboard_refresh()
            except Exception:
                log_current_exception(prefix="[char] dashboard_refresh falhou")

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

            # ----------------------------
            # Card: Outros chars na conta
            # ----------------------------
            if "char_account_list" in home.ids:
                try:
                    alist = home.ids.char_account_list
                    alist.clear_widgets()

                    others = payload.get("other_characters")
                    if others is None:
                        others = payload.get("other_chars")
                    if not isinstance(others, list):
                        others = []

                    # remove o próprio char, se vier na lista
                    cur_l = (title or "").strip().lower()
                    cleaned = []
                    for oc in others:
                        if not isinstance(oc, dict):
                            continue
                        nm = str(oc.get("name") or oc.get("title") or "").strip()
                        if not nm:
                            continue
                        if cur_l and nm.strip().lower() == cur_l:
                            continue
                        cleaned.append({
                            "name": nm,
                            "world": str(oc.get("world") or "").strip(),
                            "status": str(oc.get("status") or "").strip().lower(),
                        })

                    if not cleaned:
                        aitem = OneLineIconListItem(text="Nenhum outro personagem visível na conta.")
                        aitem.add_widget(IconLeftWidget(icon="account-multiple"))
                        alist.add_widget(aitem)
                    else:
                        # ordena por nome
                        cleaned.sort(key=lambda x: x.get("name", "").lower())
                        for oc in cleaned:
                            nm = oc.get("name") or ""
                            ww = oc.get("world") or ""
                            st2 = oc.get("status") or ""

                            # Se tivermos status, mostra junto; senão só o world.
                            sec = ww if ww else " "
                            if st2 in ("online", "offline"):
                                sec = (sec + (" • " if sec.strip() else "") + st2.capitalize()).strip()

                            icon = "wifi" if st2 == "online" else "wifi-off" if st2 == "offline" else "account"
                            it = TwoLineIconListItem(text=nm, secondary_text=sec or " ")
                            it.add_widget(IconLeftWidget(icon=icon))
                            it.bind(on_release=lambda *_ , nn=nm: self.open_char_from_account_list(nn))
                            alist.add_widget(it)
                except Exception:
                    pass
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
    def search_character(self, *, silent: bool = False):
        home = self._get_home_screen()
        ids = getattr(home, "ids", None) if home is not None else None
        char_name = ids.get("char_name") if hasattr(ids, "get") else None
        name = (getattr(char_name, "text", "") or "").strip()
        if not name:
            if not silent:
                self.toast("Digite o nome do char.")
            return

        # Marca como "buscando" imediatamente (UI responsiva).
        self._char_set_loading(home, name)
        home.char_last_url = ""
        home.char_xp_source_url = ""

        # Token para evitar que resultados de buscas antigas sobrescrevam a busca atual.
        try:
            self._char_search_seq = int(getattr(self, "_char_search_seq", 0)) + 1
        except (TypeError, ValueError):
            self._char_search_seq = int(time.time() * 1000)
        seq = self._char_search_seq

        def done_stage1(ok: bool, payload_or_msg, url: str):
            if getattr(self, "_char_search_seq", None) != seq:
                return

            home.char_last_url = url
            if ok and isinstance(payload_or_msg, dict):
                home.char_xp_source_url = str(payload_or_msg.get("gs_exp_url") or "")
            else:
                home.char_xp_source_url = ""

            if ok:
                self._char_show_result(home, payload_or_msg, side_effects=True)

                title = str((payload_or_msg or {}).get("title") or "").strip()
                world = str((payload_or_msg or {}).get("world") or "").strip()
                status_label = str((payload_or_msg or {}).get("status") or "").strip().lower()
                last_login_iso = (payload_or_msg or {}).get("last_login_iso")

                if title and world and world.upper() != "N/A":
                    try:
                        self._cache_set(f"fav_world:{title.lower()}", world)
                    except Exception:
                        log_current_exception(prefix=f"[char] falha ao cachear world: {title}")
                if title and status_label == "online":
                    try:
                        self._set_cached_last_seen_online_iso(title, datetime.utcnow().isoformat())
                    except Exception:
                        log_current_exception(prefix=f"[char] falha ao salvar last_seen: {title}")
                if title:
                    try:
                        if status_label == "offline" and isinstance(last_login_iso, str) and last_login_iso.strip():
                            self._set_cached_fav_last_login_iso(title, last_login_iso.strip())
                        elif status_label == "online":
                            self._set_cached_fav_last_login_iso(title, None)
                    except Exception:
                        log_current_exception(prefix=f"[char] falha ao salvar last_login: {title}")

                if not silent:
                    self.toast("Char encontrado.")
            else:
                self._char_show_error(home, str(payload_or_msg))
                if not silent:
                    self.toast(str(payload_or_msg))

        def done_stage2(payload: dict, url: str):
            if getattr(self, "_char_search_seq", None) != seq:
                return
            current = getattr(home, "_last_char_payload", None) or {}
            cur_title = str(current.get("title") or "").strip().lower() if isinstance(current, dict) else ""
            new_title = str(payload.get("title") or "").strip().lower()
            if cur_title and new_title and cur_title != new_title:
                return

            home.char_last_url = url
            home.char_xp_source_url = str(payload.get("gs_exp_url") or "")
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

                # Outros personagens visíveis na conta (TibiaData)
                def _find_other_chars(obj):
                    try:
                        if isinstance(obj, dict):
                            if "other_characters" in obj:
                                return obj.get("other_characters")
                            # alguns wrappers mudam o formato
                            for vv in obj.values():
                                r = _find_other_chars(vv)
                                if r is not None:
                                    return r
                        elif isinstance(obj, list):
                            for vv in obj:
                                r = _find_other_chars(vv)
                                if r is not None:
                                    return r
                    except Exception:
                        return None
                    return None

                other_raw = None
                try:
                    other_raw = character.get("other_characters")
                except Exception:
                    other_raw = None
                if other_raw is None:
                    try:
                        other_raw = character_wrapper.get("other_characters")
                    except Exception:
                        other_raw = None
                if other_raw is None:
                    other_raw = _find_other_chars(data)

                other_chars = []
                try:
                    if isinstance(other_raw, dict) and "other_characters" in other_raw:
                        other_raw = other_raw.get("other_characters")
                    if isinstance(other_raw, list):
                        for oc in other_raw:
                            if isinstance(oc, dict):
                                nm = str(oc.get("name") or oc.get("character") or oc.get("title") or "").strip()
                                if not nm:
                                    continue
                                other_chars.append({
                                    "name": nm,
                                    "world": str(oc.get("world") or "").strip(),
                                    "status": str(oc.get("status") or "").strip().lower(),
                                })
                            elif isinstance(oc, str) and oc.strip():
                                other_chars.append({"name": oc.strip(), "world": "", "status": ""})
                except Exception:
                    other_chars = []
    
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

                    "other_characters": other_chars,

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

                    # Outros chars: tenta refinar o status via /v4/world/{world}
                    try:
                        others = payload.get("other_characters")
                        if isinstance(others, list) and others:
                            # agrupa worlds para evitar chamadas duplicadas
                            worlds_map = {}
                            for oc in others:
                                if not isinstance(oc, dict):
                                    continue
                                ww = str(oc.get("world") or "").strip()
                                if not ww or ww.upper() == "N/A":
                                    continue
                                worlds_map.setdefault(ww, []).append(oc)

                            # limita para não abusar de rede
                            for i, (ww, lst) in enumerate(list(worlds_map.items())):
                                if i >= 5:
                                    break
                                try:
                                    online_setw = self._fetch_world_online_players(ww, timeout=10)
                                except Exception:
                                    online_setw = None
                                if online_setw is None:
                                    continue
                                for oc in lst:
                                    nm_l = str(oc.get("name") or "").strip().lower()
                                    if not nm_l:
                                        continue
                                    oc["status"] = "online" if nm_l in online_setw else "offline"
                            payload["other_characters"] = others
                    except Exception:
                        pass
    
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
