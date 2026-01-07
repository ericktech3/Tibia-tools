import json
import re
from typing import Any, Dict, List, Optional

import requests


def _walk_collect_boss_lists(obj: Any, found: List[List[Dict[str, Any]]]) -> None:
    """Recursively collect lists that look like boss entries."""
    if isinstance(obj, dict):
        # If dict contains an obvious bosses list key, grab it.
        for k, v in obj.items():
            if isinstance(v, list) and any(isinstance(it, dict) for it in v):
                lk = str(k).lower()
                if "boss" in lk or "tracker" in lk:
                    # heuristic: boss entries contain a boss name + chance/status
                    sample = [it for it in v if isinstance(it, dict)]
                    if any(("boss" in it or "bossName" in it or "name" in it) for it in sample):
                        found.append(sample)
            _walk_collect_boss_lists(v, found)
    elif isinstance(obj, list):
        for it in obj:
            _walk_collect_boss_lists(it, found)


def _normalize_boss_entry(it: Dict[str, Any]) -> Optional[Dict[str, str]]:
    name = it.get("boss") or it.get("bossName") or it.get("name") or it.get("title")
    if not name:
        return None
    chance = it.get("chance") or it.get("chanceText") or it.get("spawnChance") or it.get("probability")
    status = it.get("status") or it.get("state") or it.get("lastSeen") or it.get("last_seen") or it.get("expectedIn") or it.get("expected_in")
    return {
        "boss": str(name).strip(),
        "chance": (str(chance).strip() if chance is not None else "Unknown"),
        "status": (str(status).strip() if status is not None else ""),
    }


def _parse_bosses_from_html_ssr(html: str) -> List[Dict[str, str]]:
    """Fallback parser for the server-rendered HTML (works even without __NEXT_DATA__)."""
    out: List[Dict[str, str]] = []
    # Pattern: '#### Boss Name' then next non-empty line is chance/status text.
    pattern = re.compile(r"####\s+([^\n]+)\s*\n\s*\n\s*([^\n]+)", re.M)
    for boss, meta in pattern.findall(html):
        boss = boss.strip()
        meta = meta.strip()
        if not boss:
            continue
        # meta examples: '63.55%' / 'Unknown' / 'No chance Expected in: 1 day'
        chance = meta
        status = ""
        if meta.lower().startswith("no chance"):
            chance = "No chance"
            status = meta
        out.append({"boss": boss, "chance": chance, "status": status})
    return out


def fetch_exevopan_bosses(world: str) -> List[Dict[str, str]]:
    """Fetch ExevoPan boss tracker list for a world.

    Returns list of dicts: {boss, chance, status}.
    """
    world = (world or "").strip()
    if not world:
        return []

    url = f"https://www.exevopan.com/bosses/{world}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text

        # 1) Try __NEXT_DATA__ (Next.js)
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                found: List[List[Dict[str, Any]]] = []
                _walk_collect_boss_lists(data, found)
                # pick the biggest list found
                best = max(found, key=len) if found else []
                out = []
                for it in best:
                    if isinstance(it, dict):
                        norm = _normalize_boss_entry(it)
                        if norm:
                            out.append(norm)
                if out:
                    return out
            except Exception:
                # fall back to SSR parsing below
                pass

        # 2) Fallback: parse SSR HTML text (still works even if scripts are blocked/changed)
        out = _parse_bosses_from_html_ssr(html)
        return out

    except Exception:
        return []
