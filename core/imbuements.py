from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List, Tuple, Optional
from urllib.parse import urljoin, unquote

import requests
from bs4 import BeautifulSoup


_TIBIAWIKI_BASE = "https://www.tibiawiki.com.br"
_IMBUEMENTS_LIST_URL = f"{_TIBIAWIKI_BASE}/wiki/Imbuements"
_FANDOM_FALLBACK_URL = "https://tibia.fandom.com/wiki/Imbuements"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


@dataclass
class ImbuementEntry:
    # Nome “limpo” (sem artefatos tipo [])
    name: str
    # Efeito/resumo por tier (na página lista geralmente é algo curto como 3%, 8%, 15% etc.)
    basic: str
    intricate: str
    powerful: str
    # Caminho/título da página no TibiaWiki BR (ex.: /wiki/Electrify_(Dano_de_Energia))
    page: str


def _clean_name(s: str) -> str:
    s = (s or "").strip()
    # Remove artefatos comuns que aparecem no HTML (ex.: "Capacity []")
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_page_href(cell) -> str:
    a = cell.find("a", href=True)
    if not a:
        return ""
    href = a.get("href", "") or ""
    # No TibiaWiki BR costuma ser /wiki/...
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return href
    # fallback
    return "/" + href


def fetch_imbuements_table() -> Tuple[bool, List[ImbuementEntry] | str]:
    """Busca e parseia a lista de Imbuements.

    Retorna lista com 24 tipos (normalmente), contendo o nome e um resumo do efeito por tier.
    A lista NÃO traz os itens necessários; isso é buscado sob demanda (clique no imbuement).
    """
    try:
        url = _IMBUEMENTS_LIST_URL
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code >= 400 or not r.text:
            # fallback fandom (mantém app funcionando se o BR estiver fora)
            r = requests.get(_FANDOM_FALLBACK_URL, headers=_HEADERS, timeout=20)

        if r.status_code >= 400 or not r.text:
            return False, f"Falha ao acessar a página ({r.status_code})."

        soup = BeautifulSoup(r.text, "html.parser")

        # Procura uma tabela que tenha as colunas Basic/Intricate/Powerful
        target = None
        for t in soup.find_all("table"):
            header_txt = t.get_text(" ", strip=True).lower()
            if "basic" in header_txt and "intricate" in header_txt and "powerful" in header_txt:
                target = t
                break

        if not target:
            return False, "Tabela de imbuements não encontrada."

        out: List[ImbuementEntry] = []
        rows = target.find_all("tr")
        for r in rows[1:]:
            cols = r.find_all(["td", "th"])
            if len(cols) < 4:
                continue

            # Nome + link (se existir)
            a = cols[0].find("a")
            name = a.get_text(" ", strip=True) if a else cols[0].get_text(" ", strip=True)
            name = _clean_name(name)

            basic = cols[1].get_text(" ", strip=True)
            intricate = cols[2].get_text(" ", strip=True)
            powerful = cols[3].get_text(" ", strip=True)

            if not name:
                continue
            if name.strip().lower() in {"imbuement", "name", "imbuements"}:
                continue

            page = _extract_page_href(cols[0])

            out.append(ImbuementEntry(name=name, basic=basic, intricate=intricate, powerful=powerful, page=page))

        # Dedup por nome (algumas páginas podem repetir cabeçalhos/linhas)
        uniq: List[ImbuementEntry] = []
        seen = set()
        for e in out:
            key = e.name.lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(e)

        if not uniq:
            return False, "Não foi possível extrair linhas da tabela."
        return True, uniq
    except Exception as e:
        return False, str(e)


def _normalize_tier_label(s: str) -> Optional[str]:
    s = (s or "").strip().lower().replace(":", "")
    if s in {"basic", "básico", "basico"}:
        return "Basic"
    if s in {"intricate", "intrincado"}:
        return "Intricate"
    if s in {"powerful", "poderoso"}:
        return "Powerful"
    return None


def _clean_li_text(s: str) -> str:
    s = (s or "").strip()
    # remove trechos de imagem/ícones que aparecem no texto
    s = re.sub(r"\bImage:.*$", "", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_sources_items(soup: BeautifulSoup) -> Dict[str, List[str]]:
    """Extrai os itens (Fontes Astrais) por tier a partir da página individual do imbuement."""
    out: Dict[str, List[str]] = {"Basic": [], "Intricate": [], "Powerful": []}

    # Encontra o ponto onde começa "Fontes Astrais"
    start = soup.find(string=re.compile(r"Fontes\s+Astrais", re.I))
    if not start:
        return out

    node = start.parent

    current: Optional[str] = None

    # Caminha a partir desse ponto, procurando títulos Basic/Intricate/Powerful e <li> subsequentes
    for el in node.next_elements:
        # texto de controle para parar
        if hasattr(el, "get_text"):
            txt = el.get_text(" ", strip=True)
            if re.search(r"\bTabela de Custos\b|\bNotas\b|\bVeja Também\b|\bCategorias\b|Disponível em", txt, re.I):
                break

            tier = _normalize_tier_label(txt)
            if tier:
                current = tier
                continue

        # captura itens
        if getattr(el, "name", None) == "li" and current:
            li_txt = _clean_li_text(el.get_text(" ", strip=True))
            if not li_txt:
                continue
            # normaliza "25 Rorc Feather" -> "25x Rorc Feather"
            m = re.match(r"^(\d+)\s+(.+)$", li_txt)
            if m:
                qty = m.group(1)
                item = m.group(2).strip()
                out[current].append(f"{qty}x {item}")
            else:
                out[current].append(li_txt)

    return out


def fetch_imbuement_details(page: str) -> Tuple[bool, Dict[str, List[str]] | str]:
    """Busca detalhes do imbuement (itens necessários por tier) na página do TibiaWiki BR.

    Retorna um dict:
      {"Basic": ["25x Item A", ...], "Intricate": [...], "Powerful": [...]}
    """
    try:
        if not page:
            return False, "Página do imbuement não encontrada."

        # Monta URL
        if page.startswith("http"):
            url = page
        elif page.startswith("/"):
            url = urljoin(_TIBIAWIKI_BASE, page)
        else:
            url = urljoin(_TIBIAWIKI_BASE, "/wiki/" + page)

        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code >= 400 or not r.text:
            return False, f"Falha ao acessar o TibiaWiki ({r.status_code})."

        soup = BeautifulSoup(r.text, "html.parser")
        items = _extract_sources_items(soup)

        # Se veio tudo vazio, ainda assim devolve (UI mostra "não encontrado")
        return True, items
    except Exception as e:
        return False, str(e)
