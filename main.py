# main.py — Safe Boot (portrait + lazy imports + erro visível)
from __future__ import annotations
import os, traceback, time
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.lang import Builder
from kivy.utils import platform

KV = """
#:import dp kivy.metrics.dp

<Root@BoxLayout>:
    orientation: "vertical"
    padding: dp(14)
    spacing: dp(10)

    BoxLayout:
        size_hint_y: None
        height: dp(44)
        Label:
            text: "[b]Tibia Tools (Android)[/b]"
            markup: True
            color: (1,1,1,1)
        Label:
            id: status
            text: app.status_text
            color: (0.75,0.8,0.9,1)

    BoxLayout:
        size_hint_y: None
        height: dp(48)
        spacing: dp(10)
        TextInput:
            id: name_in
            hint_text: "Nome do personagem"
            multiline: False
            on_text_validate: app.search_character(self.text)
        Button:
            text: "Buscar"
            size_hint_x: None
            width: dp(110)
            on_release: app.search_character(name_in.text)
        Button:
            text: "Favoritar"
            size_hint_x: None
            width: dp(120)
            on_release: app.add_current_to_favorites()

    Label:
        id: out
        text: "Pronto."
        color: (0.9,0.92,0.95,1)
        text_size: self.width, None
        valign: "top"
"""

class TibiaToolsApp(App):
    status_text = "Iniciando…"

    # — utilidades internas —
    def _crash_path(self):
        try: os.makedirs(self.user_data_dir, exist_ok=True)
        except Exception: pass
        return os.path.join(self.user_data_dir, "tibia_tools_crash.log")

    def _log_crash(self, exc: BaseException):
        try:
            with open(self._crash_path(), "a", encoding="utf-8") as f:
                f.write("\n" + "="*72 + "\n")
                f.write(datetime.now().isoformat(timespec="seconds") + "  Uncaught Exception\n")
                f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        except Exception:
            pass

    def _error_screen(self, exc: BaseException):
        root = BoxLayout(orientation="vertical", padding=16, spacing=8)
        root.add_widget(Label(text="[b]Falha ao iniciar[/b]", markup=True, size_hint_y=None, height=28))
        root.add_widget(Label(text=f"Log salvo em:\n{self._crash_path()}", size_hint_y=None, height=48))
        sv = ScrollView()
        lbl = Label(text="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                    size_hint_y=None, color=(1,1,1,1))
        lbl.bind(texture_size=lambda i, ts: setattr(i, "height", ts[1]))
        sv.add_widget(lbl)
        root.add_widget(sv)
        return root

    def on_start(self):
        # força retrato no Android (caso o spec seja ignorado)
        if platform == "android":
            try:
                from jnius import autoclass
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                ActivityInfo = autoclass("android.content.pm.ActivityInfo")
                PythonActivity.mActivity.setRequestedOrientation(
                    ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                )
            except Exception:
                pass

        # inicialização preguiçosa depois que a janela existe
        Clock.schedule_once(self._safe_boot, 0.05)

    def build(self):
        # tela mínima para evitar “preto”
        box = BoxLayout(orientation="vertical", padding=16, spacing=8)
        box.add_widget(Label(text="[b]Tibia Tools[/b]", markup=True, size_hint_y=None, height=30, color=(1,1,1,1)))
        box.add_widget(Label(text="Carregando UI…", color=(0.9,0.92,0.95,1)))
        return box

    def _safe_boot(self, *_):
        try:
            # imports preguiçosos (evita travar antes da janela)
            try:
                from core import api, state, utilities
            except Exception:
                # tenta com maiúsculas (repo vindo do Windows às vezes tem casing)
                from Core import api, state, utilities  # type: ignore

            self.m_api = api
            self.m_state = state
            self.m_util = utilities

            # carrega KV principal
            root = Builder.load_string(KV)
            self.root.clear_widgets()
            self.root.add_widget(root)

            # estado
            self._st = self.m_state.load_state(self.user_data_dir)
            self.status_text = "Pronto."
            self.root.ids.out.text = "Faça uma busca."

            # permissões Android 13+ (notificações)
            if platform == "android":
                try:
                    from android.permissions import request_permissions, Permission
                    request_permissions([Permission.POST_NOTIFICATIONS])
                except Exception:
                    pass

        except Exception as e:
            self._log_crash(e)
            self.root.clear_widgets()
            self.root.add_widget(self._error_screen(e))

    # -------- AÇÕES BÁSICAS (usam módulos lazy) ----------
    def search_character(self, name: str):
        try:
            name = (name or "").strip()
            if not name:
                self.status_text = "Digite um nome."
                return
            self.status_text = "Buscando…"

            def _do(*_):
                try:
                    data = self.m_api.fetch_character(name, timeout=12)
                    if not data:
                        raise RuntimeError("Sem dados do personagem.")
                    char = data.get("character", {})
                    world = char.get("world", "-") or "-"
                    online = bool(char.get("online", False))
                    level = char.get("level", "-")
                    voc = char.get("vocation", "-")
                    res = char.get("residence", "-")

                    self.root.ids.out.text = (
                        f"[b]{name}[/b]\n"
                        f"Mundo: {world}\n"
                        f"Online: {'sim' if online else 'não'}\n"
                        f"Level: {level}\n"
                        f"Vocação: {voc}\n"
                        f"Residência: {res}"
                    )
                    self.root.ids.out.markup = True
                    self.status_text = "OK."
                except Exception as e:
                    self.status_text = f"Erro: {e}"
            Clock.schedule_once(_do, 0)

        except Exception as e:
            self._log_crash(e)
            self.status_text = f"Falha: {e}"

    def add_current_to_favorites(self):
        try:
            txt = getattr(self.root.ids, "out").text or ""
            # extrai nome entre [b]...[/b]
            name = txt.split("[b]")[1].split("[/b]")[0] if "[b]" in txt else ""
            if not name:
                self.status_text = "Busque um personagem antes."
                return
            st = self._st
            if name in st.favorites:
                self.status_text = "Já está nos favoritos."
                return
            if len(st.favorites) >= 10:
                self.status_text = "Limite de 10 favoritos."
                return
            self.m_state.add_favorite(st, name)
            self.m_state.save_state(self.user_data_dir, st)
            self.status_text = f"Favoritado: {name}"
        except Exception as e:
            self._log_crash(e)
            self.status_text = f"Falha: {e}"


if __name__ == "__main__":
    TibiaToolsApp().run()
