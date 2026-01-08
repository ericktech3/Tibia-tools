import requests

def fetch_boosted():
    """Retorna boosted creature e boosted boss usando TibiaData v4."""
    try:
        c = requests.get("https://api.tibiadata.com/v4/creatures", timeout=10).json()
        b = requests.get("https://api.tibiadata.com/v4/boostablebosses", timeout=10).json()

        creature = ((c.get("creatures") or {}).get("boosted") or {}).get("name", "N/A")
        boss = ((b.get("boostable_bosses") or {}).get("boosted") or {}).get("name", "N/A")

        return {"creature": creature, "boss": boss}
    except Exception:
        return None
