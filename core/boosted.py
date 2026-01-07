from typing import Any, Optional

import requests


API_BASE = "https://api.tibiadata.com/v4"


def _dig_first_string(obj: Any, keys: list[str]) -> Optional[str]:
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # search nested
        for v in obj.values():
            got = _dig_first_string(v, keys)
            if got:
                return got
    elif isinstance(obj, list):
        for it in obj:
            got = _dig_first_string(it, keys)
            if got:
                return got
    return None


def fetch_boosted(timeout: int = 20) -> dict:
    """Fetch boosted creature + boss from TibiaData v4.

    Returns: {"creature": "...", "boss": "..."} (values may be 'N/A' if API changed).
    """
    headers = {"User-Agent": "Mozilla/5.0"}

    creature_name = "N/A"
    boss_name = "N/A"

    try:
        r = requests.get(f"{API_BASE}/boostedcreature", headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        creature_name = _dig_first_string(data, ["name", "creature", "boosted_creature"]) or creature_name
    except Exception:
        pass

    try:
        r = requests.get(f"{API_BASE}/boostedboss", headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        boss_name = _dig_first_string(data, ["name", "boss", "boosted_boss"]) or boss_name
    except Exception:
        pass

    return {"creature": creature_name, "boss": boss_name}
