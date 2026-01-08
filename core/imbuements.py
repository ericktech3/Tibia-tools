from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup


@dataclass
class ImbuementEntry:
    name: str
    basic: str
    intricate: str
    powerful: str


def _parse_table(html: str) -> List[ImbuementEntry]:
    soup = BeautifulSoup(html, "html.parser")

    # Procura uma tabela que contenha as colunas Basic/Intricate/Powerful
    tables = soup.find_all("table")
    target = None
    for t in tables:
        head_txt = t.get_text(" ", strip=True).lower()
        if "basic" in head_txt and "intricate" in head_txt and "powerful" in head_txt:
            target = t
            break

    if not target:
        return []

    out: List[ImbuementEntry] = []
    rows = target.find_all("tr")
    for r in rows:
        cols = r.find_all(["th", "td"])
        if len(cols) < 4:
            continue

        name = cols[0].get_text(" ", strip=True)
        if not name:
            continue
        if name.lower() in ("imbuement", "imbuements", "nome", "name"):
            continue

        basic = cols[1].get_text(" ", strip=True)
        intricate = cols[2].get_text(" ", strip=True)
        powerful = cols[3].get_text(" ", strip=True)

        out.append(ImbuementEntry(name=name, basic=basic, intricate=intricate, powerful=powerful))

    return out


def fetch_imbuements_table() -> Tuple[bool, List[ImbuementEntry]]:
    """
    Retorna uma lista com os imbuements (Basic/Intricate/Powerful).
    Faz scraping em sites públicos. Se falhar, retorna uma lista mínima (fallback),
    para o app não ficar vazio.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Android; Mobile) TibiaTools/1.0",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    urls = [
        # Fandom costuma ser mais estável para scraping
        "https://tibia.fandom.com/wiki/Imbuing",
        # Alternativa
        "https://www.tibiawiki.com.br/wiki/Imbuements",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=25)
            resp.raise_for_status()
            entries = _parse_table(resp.text)
            if entries:
                return True, entries
        except Exception:
            continue

    # Fallback bem simples (se os sites bloquearem / mudarem o HTML)
    fallback = [
        ImbuementEntry("Vampirism", "—", "—", "—"),
        ImbuementEntry("Void", "—", "—", "—"),
        ImbuementEntry("Strike", "—", "—", "—"),
        ImbuementEntry("Chop", "—", "—", "—"),
        ImbuementEntry("Slash", "—", "—", "—"),
        ImbuementEntry("Bash", "—", "—", "—"),
        ImbuementEntry("Precision", "—", "—", "—"),
        ImbuementEntry("Swiftness", "—", "—", "—"),
        ImbuementEntry("Featherweight", "—", "—", "—"),
        ImbuementEntry("Dragon Hide", "—", "—", "—"),
    ]
    return True, fallback
