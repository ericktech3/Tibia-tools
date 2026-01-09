from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import re

import requests
from bs4 import BeautifulSoup


@dataclass
class ImbuementEntry:
    name: str
    basic: str
    intricate: str
    powerful: str


# URLs (primário = TibiaWiki BR; fallback = Fandom)
_IMB_URL = "https://www.tibiawiki.com.br/wiki/Imbuements"
_IMB_ALT_URL = "https://tibia.fandom.com/wiki/Imbuements"

_TIER_WORDS = ("basic", "intricate", "powerful")
_EDIT_TAIL_RE = re.compile(r"\[\s*edit\s*\]$", re.I)


def _clean_text(el) -> str:
    if el is None:
        return ""
    # preserva quebras de linha dentro da célula (fica melhor no dialog)
    txt = el.get_text("\n", strip=True)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    return txt.strip()


def _normalize_heading(text: str) -> str:
    t = (text or "").strip()
    t = _EDIT_TAIL_RE.sub("", t).strip()
    # remove notas como (Imbuement) etc, mas mantém se fizer parte do nome
    return t


def _guess_indices_from_header(th_texts: List[str]) -> Tuple[int, Optional[int], Optional[int], Optional[int]]:
    """
    Retorna: (idx_name, idx_basic, idx_intricate, idx_powerful)
    """
    lower = [t.lower() for t in th_texts]
    # nome
    idx_name = 0
    for i, t in enumerate(lower):
        if "imbu" in t or t in ("name", "nome"):
            idx_name = i
            break

    def find_col(keys: Tuple[str, ...]) -> Optional[int]:
        for i, t in enumerate(lower):
            if any(k in t for k in keys):
                return i
        return None

    idx_basic = find_col(("basic", "básico", "basico"))
    idx_intr = find_col(("intricate", "intricado"))
    idx_pow = find_col(("powerful", "poderoso", "poderosa"))
    return idx_name, idx_basic, idx_intr, idx_pow


def _parse_big_table(table) -> List[ImbuementEntry]:
    """
    Tabela "grande": uma linha por imbuement e colunas Basic/Intricate/Powerful.
    Essa é a melhor forma quando existe na página.
    """
    out: List[ImbuementEntry] = []
    header_row = table.find("tr")
    if not header_row:
        return out

    ths = header_row.find_all(["th", "td"])
    th_texts = [_clean_text(th) for th in ths]
    if not th_texts:
        return out

    header_join = " ".join(th_texts).lower()
    if not all(w in header_join for w in _TIER_WORDS):
        return out

    idx_name, idx_basic, idx_intr, idx_pow = _guess_indices_from_header(th_texts)
    # se não encontrou colunas de tier, aborta
    if idx_basic is None or idx_intr is None or idx_pow is None:
        return out

    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all(["td", "th"])
        if not tds or len(tds) <= max(idx_name, idx_basic, idx_intr, idx_pow):
            continue

        name = _clean_text(tds[idx_name])
        if not name:
            continue
        name_l = name.strip().lower()
        if name_l in {"imbuement", "imbuements", "name", "nome"}:
            continue

        basic = _clean_text(tds[idx_basic])
        intr = _clean_text(tds[idx_intr])
        powr = _clean_text(tds[idx_pow])

        # evita entradas "vazias"
        if not (basic or intr or powr):
            continue

        out.append(ImbuementEntry(name.strip(), basic or "N/A", intr or "N/A", powr or "N/A"))
    return out


def _find_previous_heading(table) -> str:
    # procura um heading logo antes da tabela (h2/h3/h4)
    node = table
    for _ in range(60):
        node = node.previous_element
        if node is None:
            break
        if getattr(node, "name", None) in ("h2", "h3", "h4"):
            text = _normalize_heading(_clean_text(node))
            if text:
                return text
    return ""


def _parse_tier_table(table) -> Optional[ImbuementEntry]:
    """
    Tabela por imbuement: geralmente 3 linhas (Basic/Intricate/Powerful).
    """
    rows = table.find_all("tr")
    if len(rows) < 2:
        return None

    tiers: Dict[str, str] = {"basic": "", "intricate": "", "powerful": ""}

    # detecta se a primeira coluna tem "Basic/Intricate/Powerful"
    matches = 0
    for tr in rows:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        left = _clean_text(cells[0]).lower()
        if "basic" in left or "básico" in left or "basico" in left:
            matches += 1
        elif "intricate" in left or "intricado" in left:
            matches += 1
        elif "powerful" in left or "poderoso" in left or "poderosa" in left:
            matches += 1

    if matches < 2:
        return None

    name = _find_previous_heading(table)
    if not name:
        return None

    for tr in rows:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        tier_raw = _clean_text(cells[0]).lower()
        value = _clean_text(cells[1])

        if not value:
            continue

        if "basic" in tier_raw or "básico" in tier_raw or "basico" in tier_raw:
            tiers["basic"] = value
        elif "intricate" in tier_raw or "intricado" in tier_raw:
            tiers["intricate"] = value
        elif "powerful" in tier_raw or "poderoso" in tier_raw or "poderosa" in tier_raw:
            tiers["powerful"] = value

    if not any(tiers.values()):
        return None

    return ImbuementEntry(
        name=name,
        basic=tiers["basic"] or "N/A",
        intricate=tiers["intricate"] or "N/A",
        powerful=tiers["powerful"] or "N/A",
    )


def fetch_imbuements_table():
    """
    Busca imbuements (lista completa) e retorna:
      (True, List[ImbuementEntry]) ou (False, "mensagem de erro")

    Estruturas suportadas:
    - tabela grande com colunas Basic/Intricate/Powerful
    - várias tabelas por imbuement (3 linhas Basic/Intricate/Powerful)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    try:
        # 1) tenta TibiaWiki BR
        resp = requests.get(_IMB_URL, headers=headers, timeout=20)
        html = resp.text or ""
        if resp.status_code >= 400 or len(html) < 2000:
            # 2) fallback Fandom
            resp2 = requests.get(_IMB_ALT_URL, headers=headers, timeout=20)
            html = resp2.text or ""

        if not html or len(html) < 1000:
            return False, "Resposta vazia do site."

        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")

        # A) tenta achar uma tabela grande (mais comum e melhor)
        merged: List[ImbuementEntry] = []
        for t in tables:
            merged.extend(_parse_big_table(t))

        # se achou bastante, retorna
        if len(merged) >= 10:
            # dedupe por nome
            by_name: Dict[str, ImbuementEntry] = {}
            for e in merged:
                by_name[e.name.lower()] = e
            out = list(by_name.values())
            out.sort(key=lambda x: x.name.lower())
            return True, out

        # B) fallback: várias tabelas por imbuement
        items: List[ImbuementEntry] = []
        for t in tables:
            e = _parse_tier_table(t)
            if e:
                items.append(e)

        if items:
            by_name: Dict[str, ImbuementEntry] = {}
            for e in items:
                by_name[e.name.lower()] = e
            out = list(by_name.values())
            out.sort(key=lambda x: x.name.lower())
            return True, out

        return False, "Não foi possível extrair a lista completa de imbuements."
    except Exception as e:
        # aqui caía o erro 're' não definido se alguém usava re sem importar;
        # agora re está importado, mas mantemos o try/except para mostrar a mensagem no app.
        return False, str(e)
