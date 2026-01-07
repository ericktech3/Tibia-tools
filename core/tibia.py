from typing import Dict, Any
import requests

TIBIADATA_CHAR = "https://api.tibiadata.com/v4/character/{name}"

def fetch_character_snapshot(name: str, timeout: int = 12) -> Dict[str, Any]:
    '''
    Snapshot mínimo para monitor:
    - level
    - online (quando disponível)
    - deaths (lista de datas/killers)
    '''
    url = TIBIADATA_CHAR.format(name=requests.utils.quote(name))
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "TibiaToolsAndroid/0.2"})
    r.raise_for_status()
    data = r.json()
    ch = (data.get("character") or {}).get("character") or {}
    deaths = (data.get("character") or {}).get("deaths") or ch.get("deaths") or []
    level = ch.get("level")
    online = ch.get("online")
    status = ch.get("status")
    if online is None and isinstance(status, str):
        online = (status.lower() == "online")
    return {"name": name, "level": level, "online": online, "deaths": deaths}
