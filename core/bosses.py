from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import requests

EXEVOPAN_URL = "https://www.exevopan.com/bosses/{world}"


def _is_boss_item(d: Dict[str, Any]) -> bool:
    keys = set(d.keys())
    # chaves típicas que aparecem em listas de bosses no ExevoPan
    boss_keys = {"boss", "bossName", "boss_name", "bossId", "boss_id", "title"}
    if keys.intersection(boss_keys):
        return True
    # alguns payloads usam "name" mas também trazem chance/state
    if "name" in keys and (("chance" in keys) or ("chanceText" in keys) or ("spawnChance" in keys) or ("status" in keys) or ("state" in keys)):
        return True
    return False


def _score_list(lst: List[Any]) -> int:
    if not lst or not all(isinstance(it, dict) for it in lst):
        return -10

    dicts: List[Dict[str, Any]] = [it for it in lst if isinstance(it, dict)]  # type: ignore[list-item]
    if not dicts:
        return -10

    # proporção de itens que parecem bosses
    boss_like = sum(1 for d in dicts[:80] if _is_boss_item(d))
    frac = boss_like / max(1, min(len(dicts), 80))

    # penaliza listas que parecem de mundos/servidores
    worldish_keys = {"world", "pvpType", "battleye", "location", "transfer_type", "online", "players_online"}
    worldish = 0
    for d in dicts[:20]:
        keys = set(d.keys())
        if keys.intersection(worldish_keys):
            worldish += 1

    score = int(frac * 100)
    score -= worldish * 10

    # bônus por chaves bem características
    for d in dicts[:20]:
        keys = set(d.keys())
        if "bossName" in keys or "boss" in keys:
            score += 5
        if "chanceText" in keys or "spawnChance" in keys or "chance" in keys:
            score += 3
        if "state" in keys or "status" in keys:
            score += 1

    return score


def _find_best_boss_list(obj: Any) -> Optional[List[Dict[str, Any]]]:
    best: Optional[List[Dict[str, Any]]] = None
    best_score = -10

    def walk(x: Any):
        nonlocal best, best_score
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            sc = _score_list(x)
            if sc > best_score:
                # type ignore because we know it's list[dict] when sc valid
                if x and all(isinstance(it, dict) for it in x):
                    best = x  # type: ignore[assignment]
                    best_score = sc
            for it in x:
                walk(it)

    walk(obj)
    return best


def fetch_exevopan_bosses(world: str, timeout: int = 20) -> List[Dict[str, str]]:
    """Busca bosses do ExevoPan para um world.

    Retorna lista de dicts:
      {"boss": "...", "chance": "...", "status": "..."}
    """
    url = EXEVOPAN_URL.format(world=world)
    headers = {"User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0"}
    html = requests.get(url, headers=headers, timeout=timeout).text

    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []

    data = json.loads(m.group(1))
    lst = _find_best_boss_list(data)
    if not lst:
        return []

    out: List[Dict[str, str]] = []
    for it in lst:
        if not isinstance(it, dict):
            continue

        # nome do boss
        name = it.get("boss") or it.get("bossName") or it.get("boss_name") or it.get("title") or it.get("name")
        if isinstance(name, dict):
            # às vezes vem como {"name": "..."}
            name = name.get("name") or name.get("title")
        if not name:
            continue

        chance = it.get("chanceText") or it.get("chance") or it.get("spawnChance") or it.get("spawn_chance") or ""
        if isinstance(chance, dict):
            chance = chance.get("text") or chance.get("name") or ""
        if isinstance(chance, (int, float)):
            chance = str(chance)

        status = it.get("status") or it.get("state") or it.get("spawnState") or it.get("spawn_state") or ""
        if isinstance(status, dict):
            status = status.get("text") or status.get("name") or ""
        if isinstance(status, (int, float)):
            status = str(status)

        out.append({"boss": str(name), "chance": str(chance), "status": str(status)})

    # remove duplicados mantendo ordem
    seen = set()
    uniq = []
    for b in out:
        key = (b.get("boss", "").lower(), b.get("chance", ""), b.get("status", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return uniq
