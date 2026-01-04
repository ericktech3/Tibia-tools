"""
core.api (compat)

Algumas versões antigas importavam `core.api`. A versão Android atual usa `core.tibia`
e `core.utilities`, mas mantemos este arquivo como *ponte* para evitar crashes.
"""
from __future__ import annotations

from .tibia import fetch_character_snapshot
from .utilities import calc_blessings, blessings_cost, calc_blessings as blessings_breakdown

__all__ = [
    "fetch_character_snapshot",
    "calc_blessings",
    "blessings_cost",
    "blessings_breakdown",
]
