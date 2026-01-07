import requests
from urllib.parse import quote


API_BASE = "https://api.tibiadata.com/v4"


def fetch_character_full(name: str, timeout: int = 20) -> dict:
    """Fetch full character payload from TibiaData v4."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Nome do personagem vazio.")
    url = f"{API_BASE}/character/{quote(name)}"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_character_snapshot(name: str, timeout: int = 20) -> dict:
    """Small, robust snapshot extracted from the full payload."""
    data = fetch_character_full(name, timeout=timeout)

    # TibiaData v4 usually nests as: {"character": {"character": {...}, "deaths": [...], ...}}
    c = {}
    try:
        c = data.get("character", {})
        if isinstance(c, dict) and "character" in c and isinstance(c.get("character"), dict):
            c = c["character"]
    except Exception:
        c = {}

    out = {
        "name": c.get("name", name),
        "level": c.get("level"),
        "vocation": c.get("vocation"),
        "world": c.get("world"),
        "status": c.get("status"),
    }
    return out
