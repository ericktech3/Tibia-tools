import json
import os
from typing import Dict, Any, List, Tuple

MAX_FAVORITES = 10

def state_path(user_data_dir: str) -> str:
    return os.path.join(user_data_dir, "favorites.json")

def load_state(user_data_dir: str) -> Dict[str, Any]:
    path = state_path(user_data_dir)
    if not os.path.exists(path):
        return {
            "favorites": [],
            "interval_seconds": 60,
            "monitoring": False,
            "last": {},
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
    try:
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    st.setdefault("favorites", [])
    st.setdefault("interval_seconds", 60)
    st.setdefault("monitoring", False)
    st.setdefault("last", {})
    st.setdefault("bless_cfg", {
        "threshold_level": 120,
        "regular_base": 20000,
        "regular_step": 75,
        "enhanced_base": 26000,
        "enhanced_step": 100,
        "twist_cost": 20000,
        "inq_discount_pct": 10
    })
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
    if name in fav:
        return True, "Já está nos favoritos.", fav
    if len(fav) >= MAX_FAVORITES:
        return False, f"Limite de {MAX_FAVORITES} favoritos atingido.", fav
    fav.append(name)
    st["favorites"] = fav
    save_state(user_data_dir, st)
    return True, "OK", fav

def remove_favorite(user_data_dir: str, name: str) -> Tuple[bool, str, List[str]]:
    st = load_state(user_data_dir)
    fav = st.get("favorites", [])
    if name in fav:
        fav.remove(name)
        st["favorites"] = fav
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
