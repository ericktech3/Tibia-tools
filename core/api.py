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
import requests


# TibiaData v4
WORLDS_URL = "https://api.tibiadata.com/v4/worlds"
CHAR_URL = "https://api.tibiadata.com/v4/character/{name}"
WORLD_URL = "https://api.tibiadata.com/v4/world/{world}"

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
    try:
        safe_world = requests.utils.quote(world)
        data = _get_json(WORLD_URL.format(world=safe_world), timeout)
        # v4: {"world": {"name": ..., "online_players": [...]}, "information": {...}}
        # Alguns wrappers antigos (ou cópias) podem vir como {"world": {"world": {...}}}
        world_obj = data.get("world", {})
        if isinstance(world_obj, dict) and isinstance(world_obj.get("world"), dict):
            world_obj = world_obj.get("world")  # type: ignore[assignment]

        players = []
        if isinstance(world_obj, dict):
            players = world_obj.get("online_players", []) or []

        if not isinstance(players, list):
            players = []

        target = (name or "").strip().lower()
        for p in players:
            if isinstance(p, dict) and (p.get("name") or "").strip().lower() == target:
                return True
        return False
    except Exception:
        return None


__all__ = [
    "fetch_worlds",
    "fetch_worlds_tibiadata",
    "fetch_character_snapshot",
    "fetch_character_tibiadata",
    "is_character_online_tibiadata",
]
