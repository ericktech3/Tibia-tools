from __future__ import annotations

from core import state as fav_state
from core.storage import safe_read_json, safe_write_json


def load_favorites(data_dir: str, fav_path: str) -> list[str]:
    """Carrega favoritos do estado compartilhado; usa formato legado como fallback."""
    try:
        state = fav_state.load_state(data_dir)
    except Exception:
        state = {}

    favorites = state.get('favorites', []) if isinstance(state, dict) else []
    if isinstance(favorites, list):
        return [str(item) for item in favorites]

    data = safe_read_json(fav_path, default=[])
    if isinstance(data, list):
        return [str(item) for item in data]
    return []


def save_favorites(data_dir: str, fav_path: str, favorites: list[str]) -> None:
    """Persiste favoritos no formato compartilhado com o serviço; cai no formato antigo se necessário."""
    normalized = [str(item) for item in (favorites or [])]
    try:
        state = fav_state.load_state(data_dir)
        if not isinstance(state, dict):
            state = {}
        state['favorites'] = normalized
        fav_state.save_state(data_dir, state)
        return
    except Exception:
        safe_write_json(fav_path, normalized)
