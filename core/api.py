# core/api.py
# Small HTTP helpers + TibiaData endpoints

from __future__ import annotations

import json
from urllib.parse import quote

import requests

DEFAULT_TIMEOUT = 15
UA = "TibiaTools/1.0 (+https://github.com/ericktech3/Tibia-tools)"

def fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Fetch JSON from an URL. Raises requests exceptions on network errors."""
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch_worlds_tibiadata() -> dict:
    # https://api.tibiadata.com/v4/worlds
    return fetch_json("https://api.tibiadata.com/v4/worlds")

def fetch_character_tibiadata(name: str) -> dict:
    # TibiaData expects URL-encoded name. Keep '+' out; encode spaces as %20.
    safe = quote(name.strip(), safe="")
    return fetch_json(f"https://api.tibiadata.com/v4/character/{safe}")
