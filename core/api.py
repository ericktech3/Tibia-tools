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

UA = {"User-Agent": "TibiaToolsAndroid/1.0 (+kivy)"}


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
        safe = requests.utils.quote(name)
        url = GUILDSTATS_DEATHS_URL.format(name=safe)
        r = requests.get(url, timeout=timeout, headers=UA)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # acha a tabela que contém o header "Exp lost"
        th = soup.find(lambda t: t.name in ("th", "td") and "Exp lost" in t.get_text(" ", strip=True))
        if not th:
            return []
        table = th.find_parent("table")
        if not table:
            return []

        out: List[str] = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            xp = tds[4].get_text(" ", strip=True)
            xp = re.sub(r"\s+", " ", xp).strip()
            if xp:
                out.append(xp)
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
