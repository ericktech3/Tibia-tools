# core/boosted.py
# Boosted creature + boosted boss (TibiaData v4)

from __future__ import annotations

from .api import fetch_json

def fetch_boosted() -> dict:
    """Return {'creature': <name>, 'boss': <name>} or {} on error."""
    try:
        # Boosted creature comes from /v4/creatures (key: creatures.boosted)
        creatures = fetch_json("https://api.tibiadata.com/v4/creatures")
        boosted_creature = (
            creatures.get("creatures", {}).get("boosted", {}) or {}
        )
        creature_name = boosted_creature.get("name")

        # Boosted boss comes from /v4/boostablebosses (key: boostable_bosses.boosted)
        bosses = fetch_json("https://api.tibiadata.com/v4/boostablebosses")
        boosted_boss = (
            bosses.get("boostable_bosses", {}).get("boosted", {}) or {}
        )
        boss_name = boosted_boss.get("name")

        out = {"creature": creature_name or "N/A", "boss": boss_name or "N/A"}
        return out
    except Exception:
        return {}
