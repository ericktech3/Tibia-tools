import json
import os
from typing import Dict, Any, List, Tuple

MAX_FAVORITES = 10

def state_path(user_data_dir: str) -> str:
    # Shared state file between the UI app and the background service
    return os.path.join(user_data_dir, "favorites.json")

def _default_state() -> Dict[str, Any]:
    return {
        "favorites": [],
        # background monitor
        "interval_seconds": 60,
        "monitoring": True,
        "notify_fav_online": True,
        "notify_fav_death": True,
        "notify_fav_level": True,
        # caches / last seen (persist across restarts to avoid spam)
        "worlds": {},  # lower(name) -> world
        "last": {},    # lower(name) -> {"online": bool, "level": int, "death_time": str}
        # existing app config (kept for compatibility)
        "bless_cfg": {
            "threshold_level": 120,
            "regular_base": 20000,
            "regular_step": 75,
            "enhanced_base": 26000,
            "enhanced_step": 100,
            "twist_cost": 20000,
            "inq_discount_pct": 10
        }
    }

def load_state(user_data_dir: str) -> Dict[str, Any]:
    path = state_path(user_data_dir)
    if not os.path.exists(path):
        return _default_state()

    try:
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}

    # Migration: older builds used a plain list in favorites.json
    if isinstance(st, list):
        st = {"favorites": [str(x) for x in st]}

    if not isinstance(st, dict):
        st = {}

    d = _default_state()
    # merge defaults without wiping user choices
    for k, v in d.items():
        if k not in st:
            st[k] = v

    # ensure types
    if not isinstance(st.get("favorites"), list):
        st["favorites"] = []
    st["favorites"] = [str(x) for x in st["favorites"]]

    if not isinstance(st.get("worlds"), dict):
        st["worlds"] = {}
    if not isinstance(st.get("last"), dict):
        st["last"] = {}

    return st

def save_state(user_data_dir: str, state: Dict[str, Any]) -> None:
    os.makedirs(user_data_dir, exist_ok=True)
    path = state_path(user_data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def add_favorite(user_data_dir: str, name: str) -> Tuple[bool, str, List[str]]:
    st = load_state(user_data_dir)
    fav = st.get("favorites", [])
    name = name.strip()
    if not name:
        return False, "Nome inválido.", fav
    if name in fav:
        return True, "Já está nos favoritos.", fav
    if len(fav) >= MAX_FAVORITES:
        return False, f"Limite de {MAX_FAVORITES} favoritos atingido.", fav
    fav.append(name)
    st["favorites"] = fav
    save_state(user_data_dir, st)
    return True, f"Adicionado: {name}", fav

def remove_favorite(user_data_dir: str, name: str) -> Tuple[bool, str, List[str]]:
    st = load_state(user_data_dir)
    fav = st.get("favorites", [])
    if name in fav:
        fav.remove(name)
        st["favorites"] = fav
        # clean cached info for this char
        ln = name.strip().lower()
        try:
            st.get("worlds", {}).pop(ln, None)
            st.get("last", {}).pop(ln, None)
        except Exception:
            pass
        save_state(user_data_dir, st)
        return True, f"Removido: {name}", fav
    return False, "Não estava nos favoritos.", fav

def default_data_dir_android() -> str:
    """Retorna um diretório gravável no Android para o serviço."""
    try:
        from android.storage import app_storage_path  # type: ignore
        p = app_storage_path()
        if p:
            return p
    except Exception:
        pass
    return os.getcwd()
