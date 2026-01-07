"""API helpers used by the UI.

Important: Keep these functions *robust* on Android (never crash the UI thread).
"""

from typing import Any, Dict, List
from urllib.parse import quote

import requests

from .tibia import fetch_character_full


API_BASE = "https://api.tibiadata.com/v4"


def fetch_character_tibiadata(name: str, timeout: int = 20) -> Dict[str, Any]:
    """Return the *full* TibiaData v4 payload for a character."""
    return fetch_character_full(name, timeout=timeout)


def fetch_worlds_tibiadata(timeout: int = 20) -> Dict[str, Any]:
    r = requests.get(f"{API_BASE}/worlds", timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_world_overview(world: str, timeout: int = 20) -> Dict[str, Any]:
    world = (world or "").strip()
    if not world:
        raise ValueError("World vazio.")
    r = requests.get(f"{API_BASE}/world/{quote(world)}", timeout=timeout)
    r.raise_for_status()
    return r.json()
