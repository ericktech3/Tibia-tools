from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

# Tentamos EN e PT para o mesmo world (o conteúdo pode variar por idioma / cache).
EXEVOPAN_URLS = [
    "https://www.exevopan.com/bosses/{world}",
    "https://www.exevopan.com/pt/bosses/{world}",
]


# ---------------------------------------------------------------------------
# Utilidades: achar lista de bosses no __NEXT_DATA__ (Next.js) (best-effort)
# ---------------------------------------------------------------------------
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
        "expected",
        "eta",
        "expectedIn",
        "expected_in",
    }
    return bool(keys.intersection(boss_keys)) and bool(keys.intersection(chance_keys))


def _score_list(lst: List[Any]) -> int:
    if not lst or not all(isinstance(it, dict) for it in lst):
        return 0
    return sum(1 for it in lst[:100] if isinstance(it, dict) and _is_boss_item(it))  # type: ignore[arg-type]


def _find_best_boss_list(data: Any) -> Optional[List[Dict[str, Any]]]:
    best: Optional[List[Dict[str, Any]]] = None
    best_score = 0

    def walk(x: Any) -> None:
        nonlocal best, best_score
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            sc = _score_list(x)
            if sc > best_score and x and all(isinstance(it, dict) for it in x):
                best_score = sc
                best = x  # type: ignore[assignment]
            for it in x:
                walk(it)

    walk(data)
    return best


# ---------------------------------------------------------------------------
# Parser robusto por HTML -> texto (prioridade)
# ---------------------------------------------------------------------------
_PERCENT_RE = re.compile(r"^\d{1,3}(?:[.,]\d{1,2})?%$")


def _html_to_text_keep_lines(html: str) -> str:
    """Converte HTML em texto preservando quebras de linha úteis."""
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", "", cleaned, flags=re.I | re.S)

    # marca headings como "#### " para facilitar parse
    cleaned = re.sub(r"<h[1-6]\b[^>]*>", "\n#### ", cleaned, flags=re.I)
    cleaned = re.sub(r"</h[1-6]>", "\n", cleaned, flags=re.I)

    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"</(p|div|li|tr|td|th|section|article|ul|ol)>", "\n", cleaned, flags=re.I)

    text = re.sub(r"<[^>]+>", " ", cleaned)

    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_expected(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)

    # PT -> EN
    s = s.replace("Aparecerá em:", "Expected in:")
    s = s.replace("Aparecera em:", "Expected in:")

    # unidades PT
    s = s.replace(" dias", " days").replace(" dia", " day")
    s = s.replace(" horas", " hours").replace(" hora", " hour")
    s = s.replace(" minutos", " minutes").replace(" minuto", " minute")
    return s


def _parse_value_line(value_line: str) -> Tuple[str, str]:
    raw = (value_line or "").strip()
    if not raw:
        return "", ""

    if raw.lower() in {"unknown", "desconhecido"}:
        return "Unknown", ""

    if raw.lower().startswith("sem chance") or raw.lower().startswith("no chance"):
        chance = "No chance"
        expected = ""

        m = re.search(
            r"(Expected in:\s*\d+\s*(?:day|days|hour|hours|minute|minutes))",
            raw,
            flags=re.I,
        )
        if m:
            expected = m.group(1)
        else:
            m = re.search(
                r"(Aparecerá em:\s*\d+\s*(?:dia|dias|hora|horas|minuto|minutos))",
                raw,
                flags=re.I,
            )
            if m:
                expected = m.group(1)

        expected = _normalize_expected(expected)
        return chance, expected

    if _PERCENT_RE.match(raw.replace(",", ".")):
        return raw.replace(",", "."), ""

    m = re.search(r"(\d{1,3}(?:[.,]\d{1,2})?%)", raw)
    if m:
        return m.group(1).replace(",", "."), ""

    return raw, ""


def _parse_bosses_from_rendered_text(html: str) -> List[Dict[str, str]]:
    txt = _html_to_text_keep_lines(html)
    lines = [ln.strip() for ln in txt.split("\n")]
    lines = [ln for ln in lines if ln and ln.lower() not in {"chance", "última vez visto", "last seen"}]

    out: List[Dict[str, str]] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#### "):
            boss = ln.replace("#### ", "", 1).strip()
            j = i + 1
            while j < len(lines) and not lines[j]:
                j += 1
            if j < len(lines):
                chance, status = _parse_value_line(lines[j])
                if boss and 3 <= len(boss) <= 80:
                    out.append({"boss": boss, "chance": chance, "status": status})
                    i = j + 1
                    continue
        i += 1

    seen = set()
    uniq: List[Dict[str, str]] = []
    for b in out:
        key = (b.get("boss", "").lower(), b.get("chance", ""), b.get("status", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return uniq


# ---------------------------------------------------------------------------
# Normalização para __NEXT_DATA__ (fallback)
# ---------------------------------------------------------------------------
def _normalize_chance_from_json(it: Dict[str, Any]) -> str:
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
    )

    if isinstance(val, dict):
        for k in ("text", "label", "value", "percent", "percentage"):
            if k in val and val[k] is not None:
                val = val[k]
                break

    if isinstance(val, (int, float)):
        n = float(val)
        if 0 <= n <= 1:
            n *= 100.0
        if abs(n - round(n)) < 1e-9:
            return f"{int(round(n))}%"
        return f"{n:.2f}%"

    s = str(val or "").strip()
    if not s:
        return ""
    s = s.replace(",", ".")
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,2})?%?", s):
        return s if s.endswith("%") else f"{s}%"

    if s.lower() == "sem chance":
        return "No chance"
    if s.lower() == "desconhecido":
        return "Unknown"
    return s


def _normalize_expected_from_json(it: Dict[str, Any]) -> str:
    val = it.get("expected") or it.get("eta") or it.get("expectedIn") or it.get("expected_in")
    if isinstance(val, (int, float)):
        d = int(round(float(val)))
        return f"Expected in: {d} day" + ("" if d == 1 else "s")
    s = str(val or "").strip()
    return _normalize_expected(s)


def fetch_exevopan_bosses(world: str, timeout: int = 20) -> List[Dict[str, str]]:
    world = (world or "").strip()
    if not world:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    html = ""
    for tpl in EXEVOPAN_URLS:
        url = tpl.format(world=requests.utils.quote(world))
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

    out = _parse_bosses_from_rendered_text(html)
    if out:
        return out

    try:
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return []

        data = json.loads(m.group(1))
        lst = _find_best_boss_list(data)
        if not lst:
            return []

        out2: List[Dict[str, str]] = []
        for it in lst:
            if not isinstance(it, dict):
                continue
            name = it.get("boss") or it.get("bossName") or it.get("boss_name") or it.get("title") or it.get("name")
            if isinstance(name, dict):
                name = name.get("name") or name.get("title")
            if not name:
                continue

            chance = _normalize_chance_from_json(it)
            status = _normalize_expected_from_json(it)
            out2.append({"boss": str(name), "chance": str(chance), "status": str(status)})

        seen = set()
        uniq: List[Dict[str, str]] = []
        for b in out2:
            key = (b.get("boss", "").lower(), b.get("chance", ""), b.get("status", ""))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(b)
        return uniq
    except Exception:
        return []
