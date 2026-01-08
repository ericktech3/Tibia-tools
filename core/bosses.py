import json
import re
from typing import Any, Dict, List, Optional

import requests


def _find_best_list(obj: Any) -> Optional[List[Dict]]:
    best: Optional[List[Dict]] = None

    def score(lst: List[Dict]) -> int:
        s = 0
        for it in lst[:50]:
            if not isinstance(it, dict):
                continue
            keys = set(it.keys())
            if ("boss" in keys or "bossName" in keys or "name" in keys):
                s += 2
            if ("chance" in keys or "chanceText" in keys or "spawnChance" in keys):
                s += 2
            if ("status" in keys or "state" in keys or "spawnState" in keys):
                s += 1
        return s

    def walk(x: Any):
        nonlocal best
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            if x and all(isinstance(it, dict) for it in x):
                sc = score(x)  # type: ignore[arg-type]
                if sc > 0 and (best is None or sc > score(best)):  # type: ignore[arg-type]
                    best = x  # type: ignore[assignment]
            for it in x:
                walk(it)

    walk(obj)
    return best


def fetch_exevopan_bosses(world: str):
    url = f"https://www.exevopan.com/bosses/{world}"
    headers = {"User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0"}
    try:
        html = requests.get(url, headers=headers, timeout=15).text
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            return []
        data = json.loads(m.group(1))
        lst = _find_best_list(data)
        if not lst:
            return []

        out = []
        for it in lst:
            if not isinstance(it, dict):
                continue
            name = it.get("boss") or it.get("bossName") or it.get("name") or it.get("title")
            if not name:
                continue
            chance = it.get("chance") or it.get("chanceText") or it.get("spawnChance") or ""
            status = it.get("status") or it.get("state") or it.get("spawnState") or ""
            out.append(
                {
                    "boss": str(name),
                    "chance": str(chance) if chance is not None else "",
                    "status": str(status) if status is not None else "",
                }
            )
        return out
    except Exception:
        return []
