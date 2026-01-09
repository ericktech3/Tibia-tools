from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import requests

# ExevoPan possui rotas em EN e PT. Tentamos as duas para aumentar a compatibilidade.
EXEVOPAN_URLS = [
    "https://www.exevopan.com/bosses/{world}",
    "https://www.exevopan.com/pt/bosses/{world}",
]


# -----------------------------
# Helpers para achar a lista no __NEXT_DATA__ (Next.js)
# -----------------------------
def _is_boss_item(d: Dict[str, Any]) -> bool:
    keys = set(d.keys())
    boss_keys = {"boss", "bossName", "boss_name", "bossId", "boss_id", "title", "name"}
    chance_keys = {
        "spawnChance",
        "spawn_chance",
        "chancePercent",
        "chance_percent",
        "percentage",
        "percent",
        "probability",
        "chance",
        "chanceText",
        "chance_text",
    }
    return bool(keys.intersection(boss_keys)) and (
        bool(keys.intersection(chance_keys)) or "status" in keys or "expected" in keys or "eta" in keys
    )


def _score_list(lst: List[Any]) -> int:
    if not lst:
        return 0
    if not all(isinstance(it, dict) for it in lst):
        return 0
    return sum(1 for it in lst if _is_boss_item(it))  # type: ignore[arg-type]


def _find_best_boss_list(data: Any) -> Optional[List[Dict[str, Any]]]:
    """Percorre o JSON e devolve a lista mais provável de bosses."""
    best: Optional[List[Dict[str, Any]]] = None
    best_score = 0

    def walk(x: Any):
        nonlocal best, best_score
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            sc = _score_list(x)
            if sc > best_score:
                if x and all(isinstance(it, dict) for it in x):
                    best = x  # type: ignore[assignment]
                    best_score = sc
            for it in x:
                walk(it)

    walk(data)
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


# -----------------------------
# Parsing por texto (fallback)
# -----------------------------
def _parse_bosses_from_text(html: str) -> List[Dict[str, str]]:
    """Fallback: extrai bosses pelo texto visível (sem depender do __NEXT_DATA__).

    Corrige 2 problemas comuns:
    - ExevoPan usa % com casas decimais (ex.: 73.99%).
    - Alguns bosses têm previsão (Expected in / Aparecerá em).
    """
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", cleaned)
    text = re.sub(r"\s+", " ", text).strip()

    percent = r"\d{1,3}(?:[\,\.]\d{1,2})?%"
    chance_words = r"No chance|Unknown|Low chance|Medium chance|High chance|Sem chance|Desconhecido"
    chance_re = rf"(?:{percent}|{chance_words})"

    expected_re = (
        r"(?:Expected in:|Aparecerá em:)\s*"
        r"\d+\s*(?:day|days|dia|dias|hour|hours|hora|horas|minute|minutes|minuto|minutos)"
    )

    pat = re.compile(
        rf"(?P<boss>[A-Z][A-Za-z0-9'’\-\.() ]{{2,80}}?)\s+"
        rf"(?P<chance>{chance_re})\b"
        rf"(?:\s+(?P<expected>{expected_re}))?",
        re.U,
    )

    out: List[Dict[str, str]] = []
    for m in pat.finditer(text):
        boss = m.group("boss").strip(" -")
        chance = (m.group("chance") or "").strip().replace(",", ".")
        expected = (m.group("expected") or "").strip()

        # normaliza PT -> EN (o app exibe EN nessa aba hoje)
        if chance.lower() == "sem chance":
            chance = "No chance"
        elif chance.lower() == "desconhecido":
            chance = "Unknown"

        if boss.lower() in {"bosses", "worlds", "buscar", "buscar bosses", "boss tracker"}:
            continue

        out.append({"boss": boss, "chance": chance, "status": expected})

    # dedupe mantendo ordem
    seen = set()
    uniq: List[Dict[str, str]] = []
    for b in out:
        key = (b.get("boss", "").lower(), b.get("chance", ""), b.get("status", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return uniq


# -----------------------------
# Normalizações (JSON)
# -----------------------------
def _normalize_chance(it: Dict[str, Any]) -> str:
    """Normaliza chance preservando casas decimais (2) quando existir."""
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
        or it.get("spawn")
    )

    def fmt_percent(p: float) -> str:
        if abs(p - round(p)) < 1e-9:
            return f"{int(round(p))}%"
        return f"{p:.2f}%"

    if isinstance(val, dict):
        for k in ("text", "label", "value", "percent", "percentage"):
            if k in val and val[k] is not None:
                val = val[k]
                break

    if isinstance(val, (int, float)):
        n = float(val)
        if 0 <= n <= 1:
            return fmt_percent(n * 100.0)
        if 0 <= n <= 100:
            return fmt_percent(n)
        return str(val)

    s = str(val or "").strip()
    if not s:
        return ""

    s = s.replace(",", ".")
    # número sem %, adiciona
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,2})?", s):
        try:
            return fmt_percent(float(s))
        except Exception:
            return s

    if "%" in s:
        return s

    s2 = s.replace("Chance", "chance").strip()
    if s2.lower() == "sem chance":
        return "No chance"
    if s2.lower() == "desconhecido":
        return "Unknown"
    return s2


def _normalize_expected(it: Dict[str, Any]) -> str:
    """Normaliza o campo de previsão (Expected in / Aparecerá em)."""
    val = (
        it.get("expected")
        or it.get("eta")
        or it.get("nextSpawn")
        or it.get("next_spawn")
        or it.get("expectedIn")
        or it.get("expected_in")
        or it.get("expectedTime")
        or it.get("expected_time")
    )

    days = (
        it.get("expectedDays")
        or it.get("expected_days")
        or it.get("daysUntil")
        or it.get("days_until")
        or it.get("expectedInDays")
        or it.get("expected_in_days")
    )

    if isinstance(val, dict):
        for k in ("text", "label", "value", "expected"):
            if k in val and val[k]:
                val = val[k]
                break
        if days is None and "days" in val and isinstance(val["days"], (int, float)):
            days = val["days"]

    if isinstance(days, (int, float)):
        d = int(round(float(days)))
        return f"Expected in: {d} day" + ("" if d == 1 else "s")

    if isinstance(val, (int, float)):
        d = int(round(float(val)))
        return f"Expected in: {d} day" + ("" if d == 1 else "s")

    s = str(val or "").strip()
    if not s:
        return ""

    s = s.replace("Aparecerá em:", "Expected in:")
    s = re.sub(r"\s+", " ", s).strip()
    # normaliza unidades PT -> EN
    s = s.replace(" dias", " days").replace(" dia", " day")
    s = s.replace(" horas", " hours").replace(" hora", " hour")
    s = s.replace(" minutos", " minutes").replace(" minuto", " minute")
    return s


# -----------------------------
# API pública usada pelo app
# -----------------------------
def fetch_exevopan_bosses(world: str, timeout: int = 20) -> List[Dict[str, str]]:
    """Busca bosses do ExevoPan para um world.

    Retorna lista de dicts:
      {"boss": "...", "chance": "...", "status": "..."}

    Onde status pode conter a previsão "Expected in: ..." quando disponível.
    """
    world = (world or "").strip()
    if not world:
        return []

    world_q = requests.utils.quote(world)
    headers = {"User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0"}

    html = ""
    for tpl in EXEVOPAN_URLS:
        try:
            url = tpl.format(world=world_q)
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code >= 400:
                continue
            html = resp.text or ""
            if html:
                break
        except Exception:
            continue

    if not html:
        return []

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
                    name = (
                        it.get("boss")
                        or it.get("bossName")
                        or it.get("boss_name")
                        or it.get("title")
                        or it.get("name")
                    )
                    if isinstance(name, dict):
                        name = name.get("name") or name.get("title")
                    if not name:
                        continue

                    chance = _normalize_chance(it)
                    status = it.get("status") or it.get("state") or it.get("availability") or ""
                    expected = _normalize_expected(it)
                    if expected and (expected not in str(status)):
                        status = (str(status).strip() + " " + expected).strip() if status else expected

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
