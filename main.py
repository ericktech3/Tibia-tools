from __future__ import annotations

import json
import os
import threading
import traceback
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import certifi
import requests
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import OneLineListItem

# Garante certificados HTTPS no Android (evita erro SSL silencioso)
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


# -----------------------------
# Tibia: Blessings (fórmula)
# -----------------------------
def blessing_price_per_bless(level: int) -> int:
    """
    Fórmula (5 blessings regulares):
    - até lvl 30: 2000 gp por blessing
    - 31..120: 2000 + 200*(lvl-30)
    - 120+: 20000 + 75*(lvl-120)  (patch 13.14)
    Fonte: TibiaWiki BR (patch) + cálculo rápido 30..120.
    """
    if level <= 0:
        return 0
    if level <= 30:
        return 2000
    if level <= 120:
        return 2000 + 200 * (level - 30)
    return 20000 + 75 * (level - 120)


def blessing_total_5(level: int) -> int:
    return blessing_price_per_bless(level) * 5


# -----------------------------
# TibiaData (character)
# -----------------------------
TIBIADATA_URL = "https://api.tibiadata.com/v4/character/{name}"


def fetch_character_tibiadata(name: str, timeout: int = 15) -> Dict[str, Any]:
    """
    Estrutura típica usada por exemplos públicos:
    data["character"]["character"]["level"], etc.
    :contentReference[oaicite:1]{index=1}
    """
    safe = name.strip().replace(" ", "%20")
    url = TIBIADATA_URL.format(name=safe)
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    # Protege contra mudanças de estrutura
    root = data.get("character", {})
    ch = root.get("character", {}) if isinstance(root, dict) else {}

    # Alguns campos podem não existir dependendo do char
    return {
        "name": ch.get("name", name.strip()),
        "level": ch.get("level"),
        "vocation": ch.get("vocation"),
        "world": ch.get("world"),
        "status": ch.get("status"),  # às vezes vem "online"/"offline"
        "last_login": ch.get("last_login"),
        "account_status": ch.get("account_status"),
        "url": f"https://www.tibia.com/community/?name={name.strip().replace(' ', '+')}",
        "raw": data,
    }


# -----------------------------
# Persistência simples (favoritos)
# -----------------------------
@dataclass
class Favorite:
    name: str
    world: str = ""
    level: Optional[int] = None
    vocation: str = ""
    status: str = ""  # online/offline/unknown


class State:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.base_dir / "state.json"
        self.favorites: List[Favorite] = []
        self.load()

    def load(self) -> None:
        if not self.file.exists():
            self.save()
            return
        try:
            obj = json.loads(self.file.read_text(encoding="utf-8"))
            favs = obj.get("favorites", [])
            self.favorites = [Favorite(**f) for f in favs if isinstance(f, dict)]
        except Exception:
            # se corromper, recria
            self.favorites = []
            self.save()

    def save(self) -> None:
        obj = {
            "favorites": [f.__dict__ for f in self.favorites],
        }
        self.file.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert_favorite(self, fav: Favorite) -> None:
        for i, f in enumerate(self.favorites):
            if f.name.lower() == fav.name.lower():
                self.favorites[i] = fav
                self.save()
                return
        self.favorites.append(fav)
        self.save()

    def remove_favorite(self, name: str) -> None:
        self.favorites = [f for f in self.favorites if f.name.lower() != name.lower()]
        self.save()


# -----------------------------
# App
# -----------------------------
class TibiaToolsApp(MDApp):
    result_title = StringProperty("Pronto.")
    result_body = StringProperty("Digite um nome e toque em Buscar.")
    last_character_name: str = ""
    last_character_url: str = ""

    bless_result = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dialog: Optional[MDDialog] = None
        self.state: Optional[State] = None

    def build(self):
        self.title = "Tibia Tools"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Dark"

        # Carrega KV
        Builder.load_file("tibia_tools.kv")

        # user_data_dir é o lugar certo no Android (sem permissão extra)
        self.state = State(Path(self.user_data_dir))
        root = Builder.load_string("RootWidget:\n")  # placeholder (Root real vem do kv)
        return Builder.load_file("tibia_tools.kv")

    # ---------- UI helpers ----------
    def show_error(self, title: str, msg: str) -> None:
        if self.dialog:
            self.dialog.dismiss()
        self.dialog = MDDialog(title=title, text=msg, buttons=[])
        self.dialog.open()

    def safe_set_result(self, title: str, body: str) -> None:
        self.result_title = title
        self.result_body = body

    # ---------- Actions ----------
    def search_character(self, name: str) -> None:
        name = (name or "").strip()
        if not name:
            self.show_error("Erro", "Digite o nome do personagem.")
            return

        self.safe_set_result("Buscando...", "Aguarde.")
        self.last_character_name = ""
        self.last_character_url = ""

        def worker():
            try:
                info = fetch_character_tibiadata(name)
                # Monta texto
                level = info.get("level")
                world = info.get("world") or ""
                voc = info.get("vocation") or ""
                status = info.get("status") or "unknown"
                last_login = info.get("last_login") or ""
                acc = info.get("account_status") or ""

                title = info.get("name", name)
                body_lines = [
                    f"World: {world}",
                    f"Level: {level}",
                    f"Vocation: {voc}",
                    f"Status: {status}",
                ]
                if last_login:
                    body_lines.append(f"Last login: {last_login}")
                if acc:
                    body_lines.append(f"Account: {acc}")

                url = info.get("url", "")
                def ui(_dt):
                    self.last_character_name = title
                    self.last_character_url = url
                    self.safe_set_result(title, "\n".join(body_lines))
                Clock.schedule_once(ui, 0)

            except Exception as e:
                tb = traceback.format_exc()
                def ui(_dt):
                    self.safe_set_result("Falha", "Não foi possível buscar o personagem.")
                    self.show_error("Erro na busca", f"{e}\n\nDetalhes:\n{tb}")
                Clock.schedule_once(ui, 0)

        threading.Thread(target=worker, daemon=True).start()

    def open_last_in_browser(self) -> None:
        if self.last_character_url:
            webbrowser.open(self.last_character_url)

    def add_last_to_favorites(self) -> None:
        if not self.state or not self.last_character_name:
            return

        # tenta extrair alguns campos do texto atual
        world = ""
        level = None
        voc = ""
        status = ""
        try:
            for line in self.result_body.splitlines():
                if line.lower().startswith("world:"):
                    world = line.split(":", 1)[1].strip()
                elif line.lower().startswith("level:"):
                    v = line.split(":", 1)[1].strip()
                    level = int(v) if v.isdigit() else None
                elif line.lower().startswith("vocation:"):
                    voc = line.split(":", 1)[1].strip()
                elif line.lower().startswith("status:"):
                    status = line.split(":", 1)[1].strip()
        except Exception:
            pass

        self.state.upsert_favorite(Favorite(
            name=self.last_character_name,
            world=world,
            level=level,
            vocation=voc,
            status=status,
        ))
        self.refresh_favorites_list()

    def remove_favorite(self, name: str) -> None:
        if not self.state:
            return
        self.state.remove_favorite(name)
        self.refresh_favorites_list()

    def refresh_favorites_list(self) -> None:
        if not self.state:
            return
        root = self.root
        fav_list = root.ids.get("fav_list")
        if not fav_list:
            return

        fav_list.clear_widgets()
        if not self.state.favorites:
            fav_list.add_widget(OneLineListItem(text="Nenhum favorito ainda."))
            return

        for fav in self.state.favorites:
            item = OneLineListItem(
                text=f"{fav.name}  ({fav.world})  Lvl {fav.level or '?'}  [{fav.status or 'unknown'}]"
            )
            # clique = remover (simples e impossível de errar)
            item.on_release = lambda n=fav.name: self.remove_favorite(n)
            fav_list.add_widget(item)

    def calc_blessings(self, level_text: str) -> None:
        level_text = (level_text or "").strip()
        if not level_text.isdigit():
            self.bless_result = "Digite um level válido (número)."
            return
        lvl = int(level_text)
        per = blessing_price_per_bless(lvl)
        total = blessing_total_5(lvl)
        # fórmula rápida 30..120: total = (lvl-20)*1000, bate com a wiki
        # 
        self.bless_result = (
            f"Level {lvl}\n"
            f"Preço por bênção: {per:,} gp\n"
            f"Total (5 bênçãos): {total:,} gp"
        ).replace(",", ".")

    def on_start(self):
        # preenche lista ao abrir
        Clock.schedule_once(lambda _dt: self.refresh_favorites_list(), 0)


if __name__ == "__main__":
    TibiaToolsApp().run()
