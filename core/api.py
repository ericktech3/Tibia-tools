# core/api.py
"""
Compat layer.

Algumas versões do app importam:
    from core import api

No Android (e no buildozer), se esse módulo não existir, o app fecha/tela preta.
Este arquivo reexporta funções úteis do projeto para manter compatibilidade.
"""

from .tibia import fetch_character_snapshot
from .utilities import (
    blessings_cost,
    rashid_location,
    server_save_countdown_seconds,
    stamina_offline_needed,
)
from .state import (
    load_state,
    save_state,
    add_favorite,
    remove_favorite,
    state_path,
)

__all__ = [
    "fetch_character_snapshot",
    "blessings_cost",
    "rashid_location",
    "server_save_countdown_seconds",
    "stamina_offline_needed",
    "load_state",
    "save_state",
    "add_favorite",
    "state_path",
]
