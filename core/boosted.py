import requests


def _deep_get(data, path):
    cur = data
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def fetch_boosted(timeout: int = 10):
    """Busca boosted creature e boosted boss no TibiaData (v4).

    Retorna dict: {"creature": str, "boss": str}
    """
    url_c = "https://api.tibiadata.com/v4/boostedcreature"
    url_b = "https://api.tibiadata.com/v4/boostedboss"
    headers = {"User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0"}

    def pick_name(payload, candidates):
        for path in candidates:
            val = _deep_get(payload, path)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return "N/A"

    try:
        dc = requests.get(url_c, headers=headers, timeout=timeout).json()
    except Exception:
        dc = {}

    try:
        db = requests.get(url_b, headers=headers, timeout=timeout).json()
    except Exception:
        db = {}

    creature = pick_name(dc, [
        ("boosted", "creature", "name"),
        ("boosted", "boosted_creature", "name"),
        ("boosted_creature", "name"),
        ("boostedcreature", "name"),
        ("creature", "name"),
    ])

    boss = pick_name(db, [
        ("boosted", "boss", "name"),
        ("boosted", "boosted_boss", "name"),
        ("boosted_boss", "name"),
        ("boostedboss", "name"),
        ("boss", "name"),
    ])

    return {"creature": creature, "boss": boss}
