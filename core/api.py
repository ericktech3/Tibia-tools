"""HTTP helpers + aliases de compatibilidade.

Motivo: em algumas refatorações, os nomes das funções mudaram.
No Android, um `ImportError` na inicialização faz o app abrir e fechar.

A UI atual (main.py) usa:
- fetch_character_tibiadata
- fetch_worlds_tibiadata

Este módulo garante esses nomes (e também expõe os nomes "novos").
"""

from __future__ import annotations

from typing import Dict

import requests

from .tibia import fetch_character_snapshot as _fetch_character_snapshot

WORLDS_URL = "https://api.tibiadata.com/v4/worlds"


def fetch_worlds(timeout: int = 10) -> Dict:
    """Lista de mundos via TibiaData."""
    r = requests.get(WORLDS_URL, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_worlds_tibiadata(timeout: int = 10) -> Dict:
    """Alias compatível com versões antigas da UI."""
    return fetch_worlds(timeout=timeout)


def fetch_character_snapshot(name: str, timeout: int = 10) -> Dict:
    """Nome "novo" (mantido)."""
    return _fetch_character_snapshot(name, timeout=timeout)


def fetch_character_tibiadata(name: str, timeout: int = 10) -> Dict:
    """Alias compatível com versões antigas da UI."""
    return fetch_character_snapshot(name, timeout=timeout)


__all__ = [
    "fetch_worlds",
    "fetch_worlds_tibiadata",
    "fetch_character_snapshot",
    "fetch_character_tibiadata",
]
