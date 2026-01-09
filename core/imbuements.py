from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import re
import requests
from bs4 import BeautifulSoup


@dataclass
class ImbuementEntry:
    # Nome exibido (ex: "Scorch", "Vampirism", "Capacity")
    name: str
    # Resumo/efeito por tier (ex: "3%"). Pode ficar vazio se o site mudar.
    basic: str
    intricate: str
    powerful: str
    # Página no TibiaWiki BR (title após /wiki/)
    page: str = ""


_TIBIAWIKI_BR_BASE = "https://www.tibiawiki.com.br"
_IMBUEMENTS_CATEGORY = _TIBIAWIKI_BR_BASE + "/wiki/Categoria:Imbuements"
_IMBUEMENTS_INDEX = _TIBIAWIKI_BR_BASE + "/wiki/Imbuements"


def _clean_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s*\[[^\]]*\]\s*$", "", s).strip()  # remove [1]
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _display_name_from_title(title: str) -> str:
    title = _clean_name(title)
    # remove tradução em parênteses no final: "Vampirism (Roubo de Vida)" -> "Vampirism"
    if "(" in title and title.endswith(")"):
        base = title.split("(", 1)[0].strip()
        if base:
            return base
    return title


def _page_from_href(href: str) -> str:
    href = (href or "").strip()
    m = re.search(r"/wiki/([^#?]+)", href)
    return m.group(1).strip() if m else ""


def _extract_effect(cell_text: str) -> str:
    t = (cell_text or "").replace(",", ".")
    m = re.search(r"(\d{1,3}(?:\.\d{1,2})?%)", t)
    return m.group(1) if m else (cell_text or "").strip()


def _fetch_category_list(timeout: int) -> Tuple[bool, List[ImbuementEntry] | str]:
    """Lista os 24 imbuements pela categoria do TibiaWiki BR."""
    try:
        resp = requests.get(_IMBUEMENTS_CATEGORY, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        entries: List[ImbuementEntry] = []
        # MediaWiki: links ficam na área de categoria
        cat = soup.find(class_=re.compile(r"mw-category"))
        scope = cat if cat else soup

        seen = set()
        for a in scope.find_all("a", href=True):
            href = a["href"]
            page = _page_from_href(href)
            if not page:
                continue

            # ignora links internos da wiki que não sejam páginas de imbuement (heurística)
            # A categoria costuma listar apenas as 24 páginas.
            title = a.get_text(" ", strip=True)
            title = _clean_name(title)
            if not title or title.lower().startswith(("ajuda", "categoria", "especial", "ficheiro", "arquivo", "file")):
                continue

            disp = _display_name_from_title(title)
            key = page.lower()
            if key in seen:
                continue
            seen.add(key)

            entries.append(ImbuementEntry(name=disp, basic="", intricate="", powerful="", page=page))

        # a categoria “Imbuements” do TibiaWiki BR tem exatamente 24 páginas
        if len(entries) >= 20:
            entries.sort(key=lambda e: e.name.lower())
            return True, entries

        return False, f"Categoria retornou poucos itens ({len(entries)})."
    except Exception as e:
        return False, str(e)


def _fetch_index_table(timeout: int) -> Tuple[bool, List[ImbuementEntry] | str]:
    """Fallback antigo: tenta achar tabela Basic/Intricate/Powerful na página /wiki/Imbuements (se existir)."""
    try:
        resp = requests.get(_IMBUEMENTS_INDEX, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        rows: List[ImbuementEntry] = []
        for table in soup.find_all("table"):
            table_text = table.get_text(" ", strip=True).lower()
            if "basic" not in table_text or "intricate" not in table_text or "powerful" not in table_text:
                continue

            for tr in table.find_all("tr"):
                cells = tr.find_all(["th", "td"])
                if len(cells) < 4:
                    continue

                name_cell = cells[0]
                name_text = _clean_name(name_cell.get_text(" ", strip=True))
                if not name_text:
                    continue
                # ignora cabeçalhos
                if name_text.lower() in {"name", "imbuement", "imbuements"}:
                    continue

                a = name_cell.find("a", href=True)
                page = _page_from_href(a["href"]) if a else ""

                basic = _extract_effect(cells[1].get_text(" ", strip=True))
                intricate = _extract_effect(cells[2].get_text(" ", strip=True))
                powerful = _extract_effect(cells[3].get_text(" ", strip=True))

                disp = _display_name_from_title(name_text)
                rows.append(ImbuementEntry(disp, basic, intricate, powerful, page=page))

        # dedupe
        uniq: Dict[str, ImbuementEntry] = {}
        for e in rows:
            k = e.page.lower() if e.page else e.name.lower()
            if k not in uniq:
                uniq[k] = e

        out = sorted(uniq.values(), key=lambda e: e.name.lower())
        if len(out) >= 20:
            return True, out
        return False, f"Index retornou poucos itens ({len(out)})."
    except Exception as e:
        return False, str(e)


def fetch_imbuements_table(timeout: int = 20):
    """
    Retorna (ok, data):
      ok=True  -> data é List[ImbuementEntry] (~24)
      ok=False -> data é string de erro
    """
    ok, data = _fetch_category_list(timeout)
    if ok:
        return ok, data
    # fallback
    ok2, data2 = _fetch_index_table(timeout)
    if ok2:
        return ok2, data2
    return False, f"{data} | {data2}"


# --------------------------------------------------------------------
# Detalhes (itens necessários) - carregado sob demanda ao clicar
# --------------------------------------------------------------------
def fetch_imbuement_details(page: str, timeout: int = 20):
    """
    Retorna (ok, data):
      ok=True -> data = {
          "basic": {"effect": "...", "items": ["25x ...", ...]},
          "intricate": {...},
          "powerful": {...}
      }
      ok=False -> data = string erro
    """
    page = (page or "").strip()
    if not page:
        return False, "Página inválida."

    url = f"{_TIBIAWIKI_BR_BASE}/wiki/{page}"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        tiers: Dict[str, Dict[str, object]] = {
            "basic": {"effect": "", "items": []},
            "intricate": {"effect": "", "items": []},
            "powerful": {"effect": "", "items": []},
        }

        def add_items(tier_key: str, txt: str):
            txt = (txt or "").strip()
            if not txt:
                return
            for ln in re.split(r"[\n\r]+", txt):
                ln = _clean_name(ln)
                if not ln:
                    continue
                if ln.lower() in {"basic", "intricate", "powerful", "itens", "items", "fontes astrais"}:
                    continue
                # normaliza "25 Vampire Teeth" -> "25x Vampire Teeth"
                m = re.match(r"^(\d+)\s*x?\s*(.+)$", ln)
                if m:
                    qty = m.group(1)
                    item = _clean_name(m.group(2))
                    if item:
                        tiers[tier_key]["items"].append(f"{qty}x {item}")
                else:
                    tiers[tier_key]["items"].append(ln)

        # 1) Tenta encontrar listas "Fontes Astrais" (é o padrão das páginas do TibiaWiki BR)
        raw = soup.get_text("\n", strip=True)
        raw = re.sub(r"[ \t]+", " ", raw)

        for key, label in [("basic", "Basic"), ("intricate", "Intricate"), ("powerful", "Powerful")]:
            # efeito (procura perto do label)
            if not tiers[key]["effect"]:
                m_eff = re.search(label + r".{0,120}?(\d{1,3}(?:[.,]\d{1,2})?%)", raw, flags=re.I | re.S)
                if m_eff:
                    tiers[key]["effect"] = m_eff.group(1).replace(",", ".")

            # itens: pega trecho após "Basic:" etc e coleta linhas com números
            m_blk = re.search(label + r":\s*(?:\n| )(.{0,600})", raw, flags=re.I | re.S)
            if m_blk:
                chunk = m_blk.group(1)
                # pega itens com quantidade: "25 Vampire Teeth"
                lines = re.findall(r"\b\d+\s*x?\s*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' -]{2,}\b", chunk)
                add_items(key, "\n".join(lines))

        # 2) Se ainda não achou itens, tenta por tabelas com linhas Basic/Intricate/Powerful
        if all(not tiers[k]["items"] for k in tiers):
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                present = set()
                for tr in rows:
                    cells = tr.find_all(["th", "td"])
                    if not cells:
                        continue
                    first = _clean_name(cells[0].get_text(" ", strip=True)).lower()
                    if first in tiers:
                        present.add(first)
                if len(present) >= 2:
                    for tr in rows:
                        cells = tr.find_all(["th", "td"])
                        if len(cells) < 2:
                            continue
                        tier = _clean_name(cells[0].get_text(" ", strip=True)).lower()
                        if tier not in tiers:
                            continue

                        row_text = tr.get_text(" ", strip=True).replace(",", ".")
                        if not tiers[tier]["effect"]:
                            m = re.search(r"(\d{1,3}(?:\.\d{1,2})?%)", row_text)
                            if m:
                                tiers[tier]["effect"] = m.group(1)

                        rest = "\n".join(c.get_text("\n", strip=True) for c in cells[1:])
                        rest = re.sub(r"\d{1,3}(?:[.,]\d{1,2})?%", "", rest)
                        add_items(tier, rest)

        return True, tiers
    except Exception as e:
        return False, str(e)
