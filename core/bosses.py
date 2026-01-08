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



def _looks_like_world_list(items: List[Dict[str, str]]) -> bool:
    """Heurística: se quase tudo é 1 palavra e a lista é muito grande,
    provavelmente estamos pegando a lista de worlds (página errada) e não bosses.
    """
    names = [str(it.get("boss", "")).strip() for it in items if isinstance(it, dict)]
    names = [n for n in names if n]
    if not names:
        return False
    single = sum(1 for n in names if len(n.split()) == 1)
    return len(names) >= 40 and (single / max(1, len(names))) > 0.9


def _parse_bosses_from_text(html: str) -> List[Dict[str, str]]:
    """Fallback: extrai bosses pelo texto visível (sem depender do __NEXT_DATA__)."""
    # remove scripts/styles para reduzir ruído
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned, flags=re.I | re.S)
    # remove tags
    text = re.sub(r"<[^>]+>", " ", cleaned)
    text = re.sub(r"\s+", " ", text).strip()

    # padrões comuns no ExevoPan
    chance_re = r"(\d{1,3}%|No chance|Unknown|Low chance|Medium chance|High chance)"
    pat = re.compile(rf"([A-Z][A-Za-z'’\- ]{{2,60}}?)\s+{chance_re}\b", re.U)

    out: List[Dict[str, str]] = []
    for name, chance in pat.findall(text):
        boss = name.strip(" -")
        # filtros básicos
        if len(boss) < 3:
            continue
        if boss.lower() in {"bosses", "worlds", "buscar", "buscar bosses"}:
            continue
        out.append({"boss": boss, "chance": chance, "status": ""})

    # dedupe mantendo ordem
    seen = set()
    uniq: List[Dict[str, str]] = []
    for b in out:
        key = (b.get("boss", "").lower(), b.get("chance", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return uniq


def _normalize_chance(it: Dict[str, Any]) -> str:
    """Normaliza o campo de chance.
    - Se vier número: converte para % (0-1 -> 0-100%).
    - Se vier dict: tenta extrair 'text'/'label'/'percent'/'value'.
    - Se vier string com '%': mantém.
    """
    val = (
        it.get("spawnChance")
        or it.get("spawn_chance")
        or it.get("chancePercent")
        or it.get("chance_percent")
        or it.get("percentage")
        or it.get("percent")
        or it.get("probability")
        or it.get("chanceText")
        or it.get("chance_text")
        or it.get("chance")
        or ""
    )
    # dict
    if isinstance(val, dict):
        for k in ("text", "label", "name", "value", "percent", "percentage"):
            if k in val and val[k] not in (None, ""):
                val = val[k]
                break
    # number
    if isinstance(val, (int, float)):
        n = float(val)
        if 0 <= n <= 1:
            return f"{int(round(n * 100))}%"
        if 0 < n <= 100:
            return f"{int(round(n))}%"
        return str(val)
    # string
    s = str(val).strip()
    if not s:
        return ""
    # if looks like 0.23
    m = re.fullmatch(r"\d+(?:\.\d+)?", s)
    if m:
        try:
            n = float(s)
            if 0 <= n <= 1:
                return f"{int(round(n * 100))}%"
            if 0 < n <= 100:
                return f"{int(round(n))}%"
        except Exception:
            pass
    # keep percentage
    if "%" in s:
        return s
    # unify common strings
    s2 = s.replace("Chance", "chance").strip()
    return s2

def fetch_exevopan_bosses(world: str, timeout: int = 20) -> List[Dict[str, str]]:
    """Busca bosses do ExevoPan para um world.

    Retorna lista de dicts:
      {"boss": "...", "chance": "...", "status": "..."}
    """
    world = (world or "").strip()
    if not world:
        return []

    # ExevoPan usa path; encode para não quebrar worlds com espaço
    url = EXEVOPAN_URL.format(world=requests.utils.quote(world))
    headers = {"User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0"}

    html = requests.get(url, headers=headers, timeout=timeout).text

    # 1) Tenta via __NEXT_DATA__ (mais estruturado)
    out: List[Dict[str, str]] = []
    try:
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            data = json.loads(m.group(1))
            lst = _find_best_boss_list(data)
            if lst:
                for it in lst:
                    if not isinstance(it, dict):
                        continue
                    name = it.get("boss") or it.get("bossName") or it.get("boss_name") or it.get("title") or it.get("name")
                    if isinstance(name, dict):
                        name = name.get("name") or name.get("title")
                    if not name:
                        continue
                    chance = _normalize_chance(it)
                    status = it.get('status') or it.get('state') or it.get('time') or it.get('expected') or it.get('eta') or it.get('nextSpawn') or ''
                    out.append({"boss": str(name), "chance": str(chance), "status": str(status)})
    except Exception:
        out = []

    # Se parece lista de worlds (bug comum), faz fallback
    if not out or _looks_like_world_list(out):
        out = _parse_bosses_from_text(html)

    # remove duplicados mantendo ordem
    seen = set()
    uniq: List[Dict[str, str]] = []
    for b in out:
        key = (b.get("boss", "").lower(), b.get("chance", ""), b.get("status", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return uniq