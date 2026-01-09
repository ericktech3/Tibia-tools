from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List

import requests
from bs4 import BeautifulSoup


@dataclass
class ImbuementEntry:
    name: str
    basic: str
    intricate: str
    powerful: str


_FANDOM_PAGES = {
    "basic": "https://tibia.fandom.com/wiki/Basic_Imbuements",
    "intricate": "https://tibia.fandom.com/wiki/Intricate_Imbuements",
    "powerful": "https://tibia.fandom.com/wiki/Powerful_Imbuements",
}


def _clean(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()


def _strip_tier_prefix(name: str) -> str:
    # Remove prefix "Basic ", "Intricate ", "Powerful " quando existir
    return re.sub(r"^(Basic|Intricate|Powerful)\s+", "", name.strip(), flags=re.I)


def _pick_main_table(soup: BeautifulSoup):
    """Escolhe a tabela principal de lista de imbuements (Name/Category/Astral Sources/Slots/Effect)."""
    best = None
    best_score = 0
    for t in soup.find_all("table"):
        # header pode estar em <th> na primeira linha
        header_cells = [ _clean(th.get_text(" ", strip=True)).lower() for th in t.find_all("th")[:10] ]
        header = " ".join(header_cells)
        score = 0
        for key in ("name", "category", "astral", "sources", "slots", "effect"):
            if key in header:
                score += 1
        # também pontua pelo número de linhas
        rows = t.find_all("tr")
        if len(rows) >= 10:
            score += 2
        if score > best_score:
            best_score = score
            best = t
    return best


def _parse_fandom_list(url: str, headers: Dict[str, str]) -> Tuple[bool, Dict[str, str] | str]:
    """Retorna dict: base_name -> details."""
    try:
        resp = requests.get(url, headers=headers, timeout=25)
        if resp.status_code >= 400 or not resp.text:
            return False, f"HTTP {resp.status_code}"
        soup = BeautifulSoup(resp.text, "html.parser")
        table = _pick_main_table(soup)
        if not table:
            return False, "Tabela não encontrada"

        out: Dict[str, str] = {}
        rows = table.find_all("tr")
        for r in rows[1:]:
            cols = r.find_all(["td", "th"])
            if len(cols) < 5:
                continue

            name = _clean(cols[0].get_text(" ", strip=True))
            if not name:
                continue
            # ignora cabeçalhos repetidos
            if name.lower() in {"name", "imbuement", "imbuements"}:
                continue

            base = _strip_tier_prefix(name)

            category = _clean(cols[1].get_text(" ", strip=True))
            astral = _clean(cols[2].get_text(" ", strip=True))
            slots = _clean(cols[3].get_text(" ", strip=True))
            effect = _clean(cols[4].get_text(" ", strip=True))

            details_parts = []
            if category:
                details_parts.append(f"Category: {category}")
            if astral:
                details_parts.append(f"Astral Sources: {astral}")
            if slots:
                details_parts.append(f"Slots: {slots}")
            if effect:
                details_parts.append(f"Effect: {effect}")
            details = "\n".join(details_parts).strip()

            if base and details:
                out[base] = details

        if not out:
            return False, "Nenhuma linha válida extraída"
        return True, out
    except Exception as e:
        return False, str(e)


def fetch_imbuements_table():
    """Busca e monta a lista completa de imbuements (24+) juntando Basic/Intricate/Powerful.

    Fonte: TibiaWiki Fandom (páginas de lista):
      - Basic_Imbuements
      - Intricate_Imbuements
      - Powerful_Imbuements

    A UI do app lista por nome base (ex: Vampirism) e mostra detalhes por tier.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    ok_b, basic = _parse_fandom_list(_FANDOM_PAGES["basic"], headers)
    ok_i, intricate = _parse_fandom_list(_FANDOM_PAGES["intricate"], headers)
    ok_p, powerful = _parse_fandom_list(_FANDOM_PAGES["powerful"], headers)

    if not (ok_b or ok_i or ok_p):
        # devolve o erro mais útil
        err = ""
        for v in (basic, intricate, powerful):
            if isinstance(v, str) and v:
                err = v
                break
        return False, err or "Falha ao buscar listas de imbuements."

    # Normaliza tipos
    basic_map: Dict[str, str] = basic if isinstance(basic, dict) else {}
    intricate_map: Dict[str, str] = intricate if isinstance(intricate, dict) else {}
    powerful_map: Dict[str, str] = powerful if isinstance(powerful, dict) else {}

    names = set(basic_map.keys()) | set(intricate_map.keys()) | set(powerful_map.keys())
    entries: List[ImbuementEntry] = []
    for name in sorted(names, key=lambda s: s.lower()):
        entries.append(
            ImbuementEntry(
                name=name,
                basic=basic_map.get(name, "-"),
                intricate=intricate_map.get(name, "-"),
                powerful=powerful_map.get(name, "-"),
            )
        )

    return True, entries
