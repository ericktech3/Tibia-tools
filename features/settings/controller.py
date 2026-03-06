from __future__ import annotations

import threading
import webbrowser

from kivy.clock import Clock

from core import state as fav_state
from services.error_reporting import log_current_exception
from services.release_service import (
    GithubReleaseLookupError,
    InvalidGithubRepoUrl,
    build_releases_url,
    fetch_latest_release_for_repo_url,
    has_unseen_release,
)


class SettingsControllerMixin:
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
        url = str(self._prefs_get("repo_url", "") or "").strip()
        if url and "github.com" in url.lower():
            if "/issues" not in url.lower():
                url = url.rstrip("/") + "/issues/new"
            try:
                webbrowser.open(url)
                return
            except Exception:
                log_current_exception(prefix="[settings] falha ao abrir feedback")
        self.toast("Defina a URL do repo nas Configurações para abrir o feedback.")

    def _apply_settings_to_ui(self):
        try:
            scr = self.root.get_screen("settings")
        except Exception:
            return
        try:
            style = str(self._prefs_get("theme_style", "Dark") or "Dark").strip().title()
            scr.ids.set_theme_light.active = (style == "Light")
        except Exception:
            log_current_exception(prefix="[settings] falha ao carregar tema")

        try:
            scr.ids.set_notify_boosted.active = bool(self._prefs_get("notify_boosted", True))
            scr.ids.set_notify_boss_high.active = bool(self._prefs_get("notify_boss_high", True))
            scr.ids.set_repo_url.text = str(self._prefs_get("repo_url", "") or "")
        except Exception:
            log_current_exception(prefix="[settings] falha ao carregar preferências")

        try:
            st = fav_state.load_state(self.data_dir)
            scr.ids.set_bg_monitor.active = bool(st.get("monitoring", True))
            scr.ids.set_bg_notify_online.active = bool(st.get("notify_fav_online", True))
            scr.ids.set_bg_notify_level.active = bool(st.get("notify_fav_level", True))
            scr.ids.set_bg_notify_death.active = bool(st.get("notify_fav_death", True))
            scr.ids.set_bg_interval.text = str(int(st.get("interval_seconds", 30) or 30))
            scr.ids.set_bg_autostart.active = bool(st.get("autostart_on_boot", True))
        except Exception:
            log_current_exception(prefix="[settings] falha ao aplicar estado do monitor")

    def settings_save(self):
        try:
            scr = self.root.get_screen("settings")
        except Exception:
            self.toast("Não consegui abrir as configurações.")
            return

        try:
            theme_style = "Light" if bool(scr.ids.set_theme_light.active) else "Dark"
            self._prefs_set("theme_style", theme_style)
            try:
                self.theme_cls.theme_style = theme_style
            except Exception:
                log_current_exception(prefix="[settings] falha ao aplicar tema")

            self._prefs_set("notify_boosted", bool(scr.ids.set_notify_boosted.active))
            self._prefs_set("notify_boss_high", bool(scr.ids.set_notify_boss_high.active))
            self._prefs_set("repo_url", (scr.ids.set_repo_url.text or "").strip())
            self._sync_bg_monitor_state_from_ui()
            scr.ids.set_status.text = "Salvo."
            self.toast("Configurações salvas.")
        except Exception:
            log_current_exception(prefix="[settings] falha ao salvar configurações")
            self.toast("Não consegui salvar as configurações.")

    def settings_open_releases(self):
        url = str(self._prefs_get("repo_url", "") or "").strip()
        if not url:
            self.toast("Defina a URL do repo nas configurações.")
            return
        try:
            webbrowser.open(build_releases_url(url))
        except InvalidGithubRepoUrl:
            self.toast("URL do GitHub inválida.")
        except Exception:
            log_current_exception(prefix="[settings] falha ao abrir releases")
            self.toast("Não consegui abrir as releases.")

    def settings_check_updates(self):
        try:
            scr = self.root.get_screen("settings")
        except Exception:
            self.toast("Não consegui abrir as configurações.")
            return

        url = str(self._prefs_get("repo_url", "") or "").strip()
        if not url:
            self.toast("Defina a URL do repo nas configurações.")
            return

        try:
            build_releases_url(url)
        except InvalidGithubRepoUrl:
            self.toast("URL do GitHub inválida.")
            return

        scr.ids.set_status.text = "Checando..."

        def run():
            try:
                result = fetch_latest_release_for_repo_url(url, timeout=15)
                last_seen = str(self._prefs_get("last_release", "") or "")
                Clock.schedule_once(
                    lambda *_: self._updates_done(result.tag, result.html_url, last_seen),
                    0,
                )
            except GithubReleaseLookupError as exc:
                Clock.schedule_once(
                    lambda *_: setattr(scr.ids.set_status, "text", str(exc)),
                    0,
                )
            except Exception:
                log_current_exception(prefix="[settings] falha ao checar updates")
                Clock.schedule_once(
                    lambda *_: setattr(scr.ids.set_status, "text", "Erro ao checar releases."),
                    0,
                )

        threading.Thread(target=run, daemon=True).start()

    def _updates_done(self, tag: str, html_url: str, last_seen: str):
        try:
            scr = self.root.get_screen("settings")
        except Exception:
            return
        self._prefs_set("last_release", tag)
        if has_unseen_release(last_seen, tag):
            scr.ids.set_status.text = f"Nova versão: {tag}"
            self._show_text_dialog("Update disponível", f"Nova versão encontrada: {tag}\n\nAbrir releases?")
            try:
                webbrowser.open(html_url)
            except Exception:
                log_current_exception(prefix="[settings] falha ao abrir release encontrada")
        else:
            scr.ids.set_status.text = f"Última versão: {tag}"
            self.toast("Sem updates (ou já visto).")

    def settings_clear_cache(self):
        self._cache_clear()
        try:
            self.root.get_screen("settings").ids.set_status.text = "Cache limpo."
        except Exception:
            log_current_exception(prefix="[settings] falha ao atualizar status após limpar cache")
        self.toast("Cache limpo.")
