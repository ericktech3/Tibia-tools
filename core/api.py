"""HTTP helpers + aliases de compatibilidade.

Este módulo existe para evitar que mudanças de nome quebrem o app no Android.
A UI (main.py) usa principalmente:
- fetch_character_tibiadata  -> deve retornar o JSON completo da TibiaData v4
- fetch_worlds_tibiadata     -> JSON completo da lista de mundos

Também expomos:
- fetch_character_snapshot   -> snapshot leve (para service/monitor)
"""

from __future__ import annotations

from typing import Dict
import requests

from .tibia import fetch_character_snapshot as _fetch_character_snapshot

WORLDS_URL = "https://api.tibiadata.com/v4/worlds"
CHAR_URL = "https://api.tibiadata.com/v4/character/{name}"


def fetch_worlds(timeout: int = 12) -> Dict:
    """Lista de mundos via TibiaData v4."""
    r = requests.get(WORLDS_URL, timeout=timeout, headers={"User-Agent": "TibiaToolsAndroid/1.0"})
    r.raise_for_status()
    return r.json()


def fetch_worlds_tibiadata(timeout: int = 12) -> Dict:
    """Alias compatível com versões antigas da UI."""
    return fetch_worlds(timeout=timeout)


def fetch_character_snapshot(name: str, timeout: int = 12) -> Dict:
    """Snapshot leve (mantido para o service)."""
    return _fetch_character_snapshot(name, timeout=timeout)


def fetch_character_tibiadata(name: str, timeout: int = 12) -> Dict:
    """Retorna o JSON completo do endpoint /v4/character/{name}."""
    url = CHAR_URL.format(name=requests.utils.quote(name))
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "TibiaToolsAndroid/1.0"})
    r.raise_for_status()
    return r.json()


__all__ = [
    "fetch_worlds",
    "fetch_worlds_tibiadata",
    "fetch_character_snapshot",
    "fetch_character_tibiadata",
]
