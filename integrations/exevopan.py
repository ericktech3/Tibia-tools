from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import requests
from urllib.parse import quote

# ExevoPan (Next.js) – algumas rotas variam por idioma.
EXEVOPAN_URLS = [
    "https://www.exevopan.com/bosses/{world}",
    "https://www.exevopan.com/pt/bosses/{world}",
]

# Chance pode vir como % (com decimal) ou como categorias.
_CHANCE_RE = (
    r"\d{1,3}(?:[.,]\d{1,2})?%|"
    r"No chance|Unknown|Low chance|Medium chance|High chance|"
    r"Sem chance|Desconhecido"
)

# "Expected in" (EN) ou "Aparecerá em" (PT). Às vezes vem grudado.
_EXPECTED_RE = re.compile(
    r"(?:Expected in:|Aparecerá em:|Aparecera em:)\s*"
    r"\d+\s*(?:day|days|dia|dias|hour|hours|hora|horas|minute|minutes|minuto|minutos)",
    re.I,
)

# Padrão principal: BOSS seguido (bem perto) de CHANCE.
# No ExevoPan PT, muitas vezes aparece como:
#   <nome do boss> 66.42%
# ou
#   <nome do boss> Sem chance Aparecerá em: 1 dia
_BOSS_NEAR_CHANCE_RE = re.compile(
    rf"(?P<boss>[A-Z][A-Za-z0-9'’\-\.\(\) ]{{2,80}}?)\s+"
    rf"(?P<chance>{_CHANCE_RE})",
    re.I,
)

# Itens do menu/headers que às vezes entram no HTML (não são bosses).
_FORBIDDEN_BOSS_PREFIX = {
    "char bazaar",
    "calculators",
    "advertise",
    "boss tracker",
    "recently appeared",
    "updated",
    "bosses",
    "statistics",
    "blog",
    "hunting groups",
    "hunting group",
    "listar bosses por",
    "servidor selecionado",
}

# Alguns textos de "Expected in: X day(s)" podem vazar para o parser (ex.: "day Dharalion").
# Este helper remove prefixos de tempo indevidos antes do nome real do boss.
_TIME_PREFIX_RE = re.compile(
    r"^(?:\d+\s*)?(?:day|days|dia|dias|hour|hours|hora|horas|minute|minutes|minuto|minutos)\s+",
    re.I,
)

def _clean_boss_name(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "")).strip()
    name = _TIME_PREFIX_RE.sub("", name).strip()
    return name



def _html_to_text(html: str) -> str:
    """Remove scripts/styles e converte tags HTML em texto com espaços."""
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = cleaned.replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _normalize_chance(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low == "sem chance":
        return "No chance"
    if low == "desconhecido":
        return "Unknown"
    if "%" in s:
        s = s.replace(",", ".")
    return s


def _normalize_expected(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    s = s.replace("Aparecerá em:", "Expected in:")
    s = s.replace("Aparecera em:", "Expected in:")
    # unidades PT -> EN
    s = s.replace(" dias", " days").replace(" dia", " day")
    s = s.replace(" horas", " hours").replace(" hora", " hour")
    s = s.replace(" minutos", " minutes").replace(" minuto", " minute")
    return s


def _looks_like_nav_item(boss_name: str) -> bool:
    b = (boss_name or "").strip().lower()
    if not b:
        return True
    if "#" in b:
        return True
    for pref in _FORBIDDEN_BOSS_PREFIX:
        if b.startswith(pref):
            return True
    return False


# ---------------------------------------------------------------------------
# __NEXT_DATA__ (fallback)
# ---------------------------------------------------------------------------
def _find_best_list(data: Any) -> Optional[List[Dict[str, Any]]]:
    best: Optional[List[Dict[str, Any]]] = None
    best_score = 0

    def is_boss_dict(d: Dict[str, Any]) -> bool:
        keys = set(d.keys())
        boss_keys = {"boss", "bossName", "boss_name", "title", "name"}
        chance_keys = {"spawnChance", "spawn_chance", "chancePercent", "chance_percent", "percentage", "percent", "chance", "chanceText", "chance_text"}
        return bool(keys & boss_keys) and bool(keys & chance_keys)

    def score_list(lst: List[Any]) -> int:
        if not lst or not all(isinstance(x, dict) for x in lst):
            return 0
        return sum(1 for x in lst[:300] if isinstance(x, dict) and is_boss_dict(x))  # type: ignore[arg-type]

    def walk(x: Any) -> None:
        nonlocal best, best_score
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            sc = score_list(x)
            if sc > best_score and x and all(isinstance(it, dict) for it in x):
                best_score = sc
                best = x  # type: ignore[assignment]
            for it in x:
                walk(it)

    walk(data)
    return best


def _parse_from_next_data(html: str) -> List[Dict[str, str]]:
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, flags=re.S | re.I)
    if not m:
        return []

    try:
        data = json.loads(m.group(1))
    except Exception:
        return []

    lst = _find_best_list(data)
    if not lst:
        return []

    out: List[Dict[str, str]] = []
    for it in lst:
        if not isinstance(it, dict):
            continue
        name = it.get("boss") or it.get("bossName") or it.get("boss_name") or it.get("title") or it.get("name")
        if isinstance(name, dict):
            name = name.get("name") or name.get("title")
        if not name:
            continue
        boss = _clean_boss_name(str(name))
        if _looks_like_nav_item(boss):
            continue

        val = (
            it.get("spawnChance")
            or it.get("spawn_chance")
            or it.get("chancePercent")
            or it.get("chance_percent")
            or it.get("percentage")
            or it.get("percent")
            or it.get("chanceText")
            or it.get("chance_text")
            or it.get("chance")
        )

        chance = ""
        if isinstance(val, (int, float)):
            f = float(val)
            if 0 <= f <= 1:
                f *= 100.0
            num = f"{f:.2f}".rstrip("0").rstrip(".")
            chance = f"{num}%"
        else:
            chance = _normalize_chance(str(val or ""))

        expected = (
            it.get("expected")
            or it.get("eta")
            or it.get("expectedIn")
            or it.get("expected_in")
            or it.get("nextSpawn")
            or it.get("next_spawn")
        )
        status = _normalize_expected(str(expected or ""))

        out.append({"boss": boss, "chance": chance, "status": status})

    return out


# ---------------------------------------------------------------------------
# Parser principal (texto do HTML)
# ---------------------------------------------------------------------------
def _parse_from_text(html: str) -> List[Dict[str, str]]:
    text = _html_to_text(html)

    out: List[Dict[str, str]] = []
    for m in _BOSS_NEAR_CHANCE_RE.finditer(text):
        boss = _clean_boss_name((m.group("boss") or ""))
        if not boss or _looks_like_nav_item(boss):
            continue

        chance = _normalize_chance(m.group("chance") or "")

        # pega "Expected in" logo depois (janela pequena para não misturar bosses)
        tail = text[m.end(): m.end() + 200]
        em = _EXPECTED_RE.search(tail)
        status = _normalize_expected(em.group(0)) if em else ""

        out.append({"boss": boss, "chance": chance, "status": status})

    # dedupe mantendo ordem
    seen = set()
    uniq: List[Dict[str, str]] = []
    for b in out:
        key = (b["boss"].lower(), b.get("chance", ""), b.get("status", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return uniq


def _score(items: List[Dict[str, str]]) -> int:
    score = 0
    for it in items:
        ch = (it.get("chance") or "").strip()
        st = (it.get("status") or "").strip()
        if "%" in ch:
            score += 3
        elif ch:
            score += 1
        if st.lower().startswith("expected in:"):
            score += 1
    return score


def fetch_exevopan_bosses(world: str, timeout: int = 20) -> List[Dict[str, str]]:
    """Busca bosses do ExevoPan (nome, chance e optional Expected)."""
    world = (world or "").strip()
    if not world:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    html = ""
    for tpl in EXEVOPAN_URLS:
        url = tpl.format(world=quote(world))
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code >= 400:
                continue
            html = r.text or ""
            if html:
                break
        except Exception:
            continue

    if not html:
        return []

    text_list = _parse_from_text(html)
    json_list = _parse_from_next_data(html)

    # escolhe o melhor (o que tem mais % / expected)
    return json_list if _score(json_list) > _score(text_list) else text_list