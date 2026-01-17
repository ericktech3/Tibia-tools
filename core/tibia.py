from typing import Dict, Any, Optional, Set, List, Tuple
import requests
from urllib.parse import quote

TIBIADATA_CHAR = "https://api.tibiadata.com/v4/character/{name}"
TIBIADATA_WORLD = "https://api.tibiadata.com/v4/world/{world}"

_UA = {"User-Agent": "TibiaToolsAndroid/0.3"}

def fetch_character_raw(name: str, timeout: int = 12) -> Dict[str, Any]:
    url = TIBIADATA_CHAR.format(name=quote(str(name)))
    r = requests.get(url, timeout=timeout, headers=_UA)
    r.raise_for_status()
    return r.json() if r.text else {}

def fetch_character_world(name: str, timeout: int = 12) -> Optional[str]:
    """Best-effort: discover the character's world."""
    try:
        data = fetch_character_raw(name, timeout=timeout)
        ch = (data.get("character") or {}).get("character") or {}
        world = ch.get("world") or ch.get("server")
        if isinstance(world, str) and world.strip():
            return world.strip()
    except Exception:
        return None
    return None

def fetch_world_online_players(world: str, timeout: int = 12) -> Optional[Set[str]]:
    """Returns a set of lowercase names currently online on a world."""
    try:
        safe_world = quote(str(world).strip())
        url = TIBIADATA_WORLD.format(world=safe_world)
        r = requests.get(url, timeout=timeout, headers=_UA)
        r.raise_for_status()
        data = r.json() if r.text else {}
        wb = (data or {}).get("world", {}) if isinstance(data, dict) else {}
        players = None
        if isinstance(wb, dict):
            players = wb.get("online_players") or wb.get("players_online") or wb.get("players")
            if isinstance(players, dict):
                players = (
                    players.get("online_players")
                    or players.get("players")
                    or players.get("online")
                    or players.get("data")
                )
        if not isinstance(players, list):
            return set()
        out: Set[str] = set()
        for p in players:
            if isinstance(p, dict):
                n = p.get("name")
            else:
                n = p
            if isinstance(n, str) and n.strip():
                out.add(n.strip().lower())
        return out
    except Exception:
        return None

def _extract_deaths(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    chblk = (data.get("character") or {})
    deaths = chblk.get("deaths")
    if deaths is None:
        ch = chblk.get("character") or {}
        deaths = ch.get("deaths")
    return deaths if isinstance(deaths, list) else []

def fetch_character_snapshot(name: str, timeout: int = 12) -> Dict[str, Any]:
    """
    Snapshot mínimo para monitor:
    - level
    - world
    - deaths (lista bruta)
    """
    data = fetch_character_raw(name, timeout=timeout)
    ch = (data.get("character") or {}).get("character") or {}
    deaths = _extract_deaths(data)
    level = ch.get("level")
    world = ch.get("world") or ch.get("server")
    # 'online' on char endpoint sometimes lags; prefer world-check outside when possible
    online = ch.get("online")
    status = ch.get("status")
    if online is None and isinstance(status, str):
        online = (status.lower() == "online")
    return {"name": name, "level": level, "world": world, "online": online, "deaths": deaths}

def newest_death_time(deaths: List[Dict[str, Any]]) -> Optional[str]:
    """Returns the most recent death timestamp string if present."""
    if not deaths:
        return None
    d0 = deaths[0]
    if isinstance(d0, dict):
        t = d0.get("time") or d0.get("date")
        if isinstance(t, str) and t.strip():
            return t.strip()
    return None

def death_summary(deaths: List[Dict[str, Any]], max_killers: int = 2) -> str:
    if not deaths:
        return ""
    d0 = deaths[0] if isinstance(deaths[0], dict) else {}
    level = d0.get("level")
    killers = d0.get("killers") or d0.get("involved") or []
    names: List[str] = []
    if isinstance(killers, list):
        for k in killers[:max_killers]:
            if isinstance(k, dict):
                n = k.get("name")
            else:
                n = k
            if isinstance(n, str) and n.strip():
                names.append(n.strip())
    parts = []
    if level:
        parts.append(f"lvl {level}")
    if names:
        parts.append("por " + ", ".join(names))
    return " ".join(parts).strip()
