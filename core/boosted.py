import requests

def fetch_boosted():
    """Retorna boosted creature e boosted boss usando TibiaData v4.

    Além dos nomes, tenta retornar também os sprites (image_url) quando disponíveis.
    """
    try:
        c = requests.get("https://api.tibiadata.com/v4/creatures", timeout=10).json()
        b = requests.get("https://api.tibiadata.com/v4/boostablebosses", timeout=10).json()

        c_boosted = ((c.get("creatures") or {}).get("boosted") or {})
        b_boosted = ((b.get("boostable_bosses") or {}).get("boosted") or {})

        creature = c_boosted.get("name", "N/A")
        boss = b_boosted.get("name", "N/A")

        creature_image = c_boosted.get("image_url") or ""
        boss_image = b_boosted.get("image_url") or ""

        return {
            "creature": creature,
            "boss": boss,
            "creature_image": creature_image,
            "boss_image": boss_image,
        }
    except Exception:
        return None
