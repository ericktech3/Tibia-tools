"""HTTP helpers + aliases de compatibilidade.

Este módulo existe para evitar que mudanças de nome quebrem o app no Android.
A UI (main.py) usa principalmente:
- fetch_character_tibiadata  -> JSON completo da TibiaData v4
- fetch_worlds_tibiadata     -> JSON completo da lista de mundos

Também expomos:
- fetch_character_snapshot   -> snapshot leve (para service/monitor)
- is_character_online_tibiadata -> fallback para status Online/Offline via /v4/world/{world}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import re

import requests
from bs4 import BeautifulSoup


# TibiaData v4
WORLDS_URL = "https://api.tibiadata.com/v4/worlds"
CHAR_URL = "https://api.tibiadata.com/v4/character/{name}"
WORLD_URL = "https://api.tibiadata.com/v4/world/{world}"

# GuildStats (fansite) – usado apenas para complementar informações (ex: xp lost em mortes)
GUILDSTATS_DEATHS_URL = "https://guildstats.eu/character?nick={name}&tab=5"

# Tibia.com (oficial) – fallback extra para detectar ONLINE
TIBIA_WORLD_URL = "https://www.tibia.com/community/?subtopic=worlds&world={world}"

# Alguns sites (principalmente fansites) podem bloquear user-agent genérico.
# Usamos um UA de navegador comum para reduzir falsos negativos.
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _get_json(url: str, timeout: int) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout, headers=UA)
    r.raise_for_status()
    return r.json()


def fetch_worlds_tibiadata(timeout: int = 12) -> Dict[str, Any]:
    """JSON completo do endpoint /v4/worlds."""
    return _get_json(WORLDS_URL, timeout)


# Compat: alguns lugares antigos chamavam fetch_worlds()
def fetch_worlds(timeout: int = 12) -> List[str]:
    """Lista simples de nomes de worlds (compat)."""
    data = fetch_worlds_tibiadata(timeout=timeout)
    worlds = data.get("worlds", {}).get("regular_worlds", []) or []
    out: List[str] = []
    for w in worlds:
        if isinstance(w, dict) and w.get("name"):
            out.append(str(w["name"]))
    return out


def fetch_character_tibiadata(name: str, timeout: int = 12) -> Dict[str, Any]:
    """JSON completo do endpoint /v4/character/{name}."""
    safe_name = requests.utils.quote(name)
    return _get_json(CHAR_URL.format(name=safe_name), timeout)


def fetch_character_snapshot(name: str, timeout: int = 12) -> Dict[str, Any]:
    """Snapshot leve (compat).

    Mantemos a assinatura para evitar quebrar código antigo. Hoje, retorna um
    subconjunto do /v4/character.
    """
    data = fetch_character_tibiadata(name=name, timeout=timeout)
    ch = (
        data.get("character", {})
        .get("character", {})
        or {}
    )
    return {
        "name": ch.get("name"),
        "world": ch.get("world"),
        "level": ch.get("level"),
        "vocation": ch.get("vocation"),
        "status": ch.get("status"),
        "url": f"https://www.tibia.com/community/?subtopic=characters&name={requests.utils.quote(name)}",
    }


def is_character_online_tibiadata(name: str, world: str, timeout: int = 12) -> Optional[bool]:
    """Retorna True/False se o char aparece na lista de online do world.

    Se houver erro (world inválido / indisponível), retorna None.
    """
    def _looks_like_player_list(v: Any) -> bool:
        if not isinstance(v, list) or not v:
            return False
        # heurística: lista de dicts com pelo menos 'name'
        ok = 0
        for it in v[:25]:
            if isinstance(it, dict) and isinstance(it.get("name"), str):
                ok += 1
        return ok >= max(1, min(3, len(v)))

    def _find_best_player_list(obj: Any, depth: int = 0) -> Optional[List[Dict[str, Any]]]:
        if depth > 6:
            return None

        best: Optional[List[Dict[str, Any]]] = None

        if isinstance(obj, dict):
            for v in obj.values():
                if _looks_like_player_list(v):
                    cand = [x for x in v if isinstance(x, dict)]
                    if best is None or len(cand) > len(best):
                        best = cand
                else:
                    nested = _find_best_player_list(v, depth + 1)
                    if nested and (best is None or len(nested) > len(best)):
                        best = nested

        elif isinstance(obj, list):
            for v in obj:
                nested = _find_best_player_list(v, depth + 1)
                if nested and (best is None or len(nested) > len(best)):
                    best = nested

        return best

    try:
        safe_world = requests.utils.quote(str(world))
        data = _get_json(WORLD_URL.format(world=safe_world), timeout)

        # v4 típico: {"world": {"name": ..., "online_players": [...]}, "information": {...}}
        # Alguns wrappers antigos (ou cópias) podem vir como {"world": {"world": {...}}}
        world_obj: Any = data.get("world", {})
        if isinstance(world_obj, dict) and isinstance(world_obj.get("world"), dict):
            world_obj = world_obj.get("world")

        players = None
        if isinstance(world_obj, dict) and isinstance(world_obj.get("online_players"), list):
            players = [x for x in (world_obj.get("online_players") or []) if isinstance(x, dict)]
        else:
            # fallback: procura recursivamente uma lista "parecida" com online players
            players = _find_best_player_list(world_obj)

        # Se não conseguimos achar a lista, devolvemos None (desconhecido) — para não forçar OFFLINE errado.
        if not players:
            return None

        target = (name or "").strip().lower()
        for p in players:
            if (p.get("name") or "").strip().lower() == target:
                return True
        return False
    except Exception:
        return None


def is_character_online_tibia_com(name: str, world: str, timeout: int = 12) -> Optional[bool]:
    """Fallback extra usando o site oficial (tibia.com) para checar se o char está online.

    Isso costuma ser mais confiável quando a TibiaData está atrasada/indisponível.

    Retorna:
    - True/False se conseguimos checar
    - None se houve erro/parsing falhou
    """
    try:
        safe_world = requests.utils.quote(str(world))
        url = TIBIA_WORLD_URL.format(world=safe_world)
        r = requests.get(url, timeout=timeout, headers=UA)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        target = (name or "").strip().lower()
        if not target:
            return None

        # No site oficial, a lista de online tem links para o character.
        for a in soup.find_all("a", href=True):
            href = a.get("href") or ""
            if "subtopic=characters" not in href:
                continue
            txt = a.get_text(" ", strip=True).strip().lower()
            if txt == target:
                return True
        return False
    except Exception:
        return None


def fetch_guildstats_deaths_xp(name: str, timeout: int = 12) -> List[str]:
    """Retorna a lista de 'Exp lost' (strings) do GuildStats, em ordem (mais recente primeiro).

    Observação: é um complemento (fansite). Se falhar, devolve lista vazia.
    """
    try:
        # Em query-string, preferimos + para espaços.
        safe = requests.utils.quote_plus(name)
        base_url = GUILDSTATS_DEATHS_URL.format(name=safe)

        def fetch_html(u: str) -> str:
            try:
                r = requests.get(u, timeout=timeout, headers=UA)
                if r.status_code != 200:
                    return ""
                return r.text or ""
            except Exception:
                return ""

        # Alguns ambientes/rotas podem variar por linguagem; tentamos algumas opções.
        html = ""
        for u in (base_url, base_url + "&lang=pt", base_url + "&lang=en"):
            html = fetch_html(u)
            if html:
                break
        if not html:
            return []

        # Alguns chars não têm a lista atualizada (GuildStats mostra uma mensagem e não renderiza tabela).
        if "death list is not updated" in html.lower():
            return []

        soup = BeautifulSoup(html, "html.parser")

        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "").strip()).lower()

        # Procurar a tabela correta de forma robusta:
        # - achar uma linha de header (<tr> com <th>) que tenha uma coluna contendo "Exp lost"
        # - capturar o índice dessa coluna
        best = None  # (table, exp_idx, score)
        for table in soup.find_all("table"):
            header_tr = None
            for tr in table.find_all("tr"):
                ths = tr.find_all("th")
                if ths:
                    header_tr = tr
                    break
            if not header_tr:
                continue

            headers = [norm(th.get_text(" ", strip=True)) for th in header_tr.find_all("th")]
            if not headers:
                continue

            exp_idx = None
            for i, h in enumerate(headers):
                if "exp" in h and "lost" in h:
                    exp_idx = i
                    break
            if exp_idx is None:
                continue

            # heurística extra: a tabela de mortes também tem "lvl" e/ou "morto"/"killed"/"when"
            score = 0
            joined = " ".join(headers)
            if "lvl" in joined or "level" in joined:
                score += 1
            if "quando" in joined or "when" in joined:
                score += 1
            if "morto" in joined or "killed" in joined:
                score += 1

            if best is None or score > best[2]:
                best = (table, exp_idx, score)

        if not best:
            return []

        table, exp_idx, _score = best

        out: List[str] = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            if exp_idx >= len(tds):
                continue
            xp = tds[exp_idx].get_text(" ", strip=True)
            xp = re.sub(r"\s+", " ", xp).strip()
            # filtra linhas que não parecem valor (cabeçalhos/colunas vazias)
            if not xp:
                continue
            out.append(xp)

        # Normalmente a primeira linha é a mais recente; mantemos a ordem.
        return out
    except Exception:
        return []


__all__ = [
    "fetch_worlds",
    "fetch_worlds_tibiadata",
    "fetch_character_snapshot",
    "fetch_character_tibiadata",
    "is_character_online_tibiadata",
    "is_character_online_tibia_com",
    "fetch_guildstats_deaths_xp",
]
