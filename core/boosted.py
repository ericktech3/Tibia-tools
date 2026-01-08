import requests

def fetch_boosted():
    try:
        c = requests.get("https://api.tibiadata.com/v4/boostedcreature", timeout=10).json()
        b = requests.get("https://api.tibiadata.com/v4/boostedboss", timeout=10).json()
        return {
            "creature": c.get("boosted", {}).get("creature", {}).get("name", "N/A"),
            "boss": b.get("boosted", {}).get("boss", {}).get("name", "N/A"),
        }
    except Exception:
        return None
