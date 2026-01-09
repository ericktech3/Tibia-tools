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
    """Converte HTML em texto preservando quebras de linha úteis.

    A ideia aqui é NÃO depender de estrutura/campos internos do Next.js, e sim
    ler o texto que o site já renderiza (boss name + % / sem chance + previsão).
    """
    # remove scripts/styles pra reduzir ruído
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", "", cleaned, flags=re.I | re.S)

    # marca headings como "#### " para facilitar parse (similar ao que o site gera)
    cleaned = re.sub(r"<h[1-6]\b[^>]*>", "\n#### ", cleaned, flags=re.I)
    cleaned = re.sub(r"</h[1-6]>", "\n", cleaned, flags=re.I)

    # tags que naturalmente quebram linha
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"</(p|div|li|tr|td|th|section|article|ul|ol)>", "\n", cleaned, flags=re.I)

    # remove o resto das tags
    text = re.sub(r"<[^>]+>", " ", cleaned)

    # normaliza espaços, mas mantém \n
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
    """Recebe a linha de valor (chance/status) e devolve (chance, status).

    Regras:
    - Chance válida: percentual (com decimal), "No chance", "Unknown", "Low/Medium/High chance" (EN/PT básico)
    - Expected pode vir junto (mesma linha) ou sozinho em linha separada ("Expected in:" / "Aparecerá em:")
    - Se não reconhecer, retorna ("", "") para evitar capturar itens do menu do site.
    """
    raw = (value_line or "").strip()
    if not raw:
        return "", ""

    # Expected sozinho (linha separada)
    exp_only = re.search(
        r"(?:Expected in:|Aparecerá em:|Aparecera em:)\s*\d+\s*(?:day|days|hour|hours|minute|minutes|dia|dias|hora|horas|minuto|minutos)",
        raw,
        flags=re.I,
    )
    if exp_only and raw.lower().startswith(("expected in:", "aparecerá em:", "aparecera em:")):
        return "", _normalize_expected(raw)

    low = raw.lower()

    # Unknown (EN/PT)
    if low in {"unknown", "desconhecido"}:
        return "Unknown", ""

    # Outros níveis (às vezes o ExevoPan usa texto em vez de %)
    chance_map = {
        "low chance": "Low chance",
        "medium chance": "Medium chance",
        "high chance": "High chance",
        "very high chance": "Very high chance",
        "baixa chance": "Low chance",
        "média chance": "Medium chance",
        "media chance": "Medium chance",
        "alta chance": "High chance",
        "muito alta chance": "Very high chance",
    }
    if low in chance_map:
        return chance_map[low], ""

    # Sem chance / No chance (+ previsão opcional)
    if low.startswith("sem chance") or low.startswith("no chance"):
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

    # Percentual (aceita decimal)
    if _PERCENT_RE.match(raw.replace(",", ".")):
        return raw.replace(",", "."), ""

    # fallback: tenta achar um percentual dentro da linha
    m = re.search(r"(\d{1,3}(?:[.,]\d{1,2})?%)", raw)
    if m:
        return m.group(1).replace(",", "."), ""

    # Não reconhecido -> descarta (evita menu/rodapé)
    return "", ""


def _parse_bosses_from_rendered_text(html: str) -> List[Dict[str, str]]:
    """Extrai bosses do HTML renderizado.

    Estratégia:
    1) Converte HTML -> texto com linhas.
    2) Procura padrões por linha:
       - "Boss Name - 73.99%" ou "Boss Name - No chance"
       - Expected pode vir na mesma linha ou na linha seguinte
    3) Fallback: headings (####) + próxima linha.
    """
    txt = _html_to_text_keep_lines(html)
    lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]

    out: List[Dict[str, str]] = []

    # 1) Padrão direto: "Boss - chance ..."
    percent = r"\d{1,3}(?:[\.,]\d{1,2})?%"
    chance_words = r"No chance|Unknown|Low chance|Medium chance|High chance|Very high chance|Sem chance|Desconhecido"
    expected = (
        r"(?:Expected in:|Aparecerá em:|Aparecera em:)\s*\d+\s*(?:day|days|hour|hours|minute|minutes|dia|dias|hora|horas|minuto|minutos)"
    )
    line_re = re.compile(
        rf"^(?P<boss>[^#\-].{{3,120}}?)\s*-\s*(?P<chance>(?:{percent}|{chance_words}))\b(?:\s+(?P<expected>{expected}))?$",
        flags=re.I,
    )

    for i, ln in enumerate(lines):
        m = line_re.match(ln)
        if not m:
            continue
        boss = m.group("boss").strip(" -")
        chance_raw = (m.group("chance") or "").strip()
        exp_raw = (m.group("expected") or "").strip()
        chance, _ = _parse_value_line(chance_raw)
        status = _normalize_expected(exp_raw)

        # expected pode estar na linha seguinte
        if not status and i + 1 < len(lines):
            ch2, st2 = _parse_value_line(lines[i + 1])
            if ch2 == "" and st2:
                status = st2

        if chance:
            out.append({"boss": boss, "chance": chance, "status": status})

    # 2) Fallback: headings (####) + próxima linha
    if not out:
        i = 0
        while i < len(lines):
            ln = lines[i]
            if ln.startswith("#### "):
                boss = ln.replace("#### ", "", 1).strip()
                # próxima linha não vazia
                j = i + 1
                while j < len(lines) and not lines[j]:
                    j += 1
                if j < len(lines):
                    chance, status = _parse_value_line(lines[j])

                    # expected pode estar na linha seguinte (em coluna separada)
                    if chance and not status and j + 1 < len(lines):
                        ch2, st2 = _parse_value_line(lines[j + 1])
                        if ch2 == "" and st2:
                            status = st2

                    # só aceita se chance reconhecida
                    if chance:
                        out.append({"boss": boss, "chance": chance, "status": status})
                        i = j + 1
                        continue
            i += 1

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


def _normalize_expected_from_json(it: Dict[str, Any]) -> str:
    val = it.get("expected") or it.get("eta") or it.get("expectedIn") or it.get("expected_in")
    if isinstance(val, (int, float)):
        d = int(round(float(val)))
        return f"Expected in: {d} day" + ("" if d == 1 else "s")
    s = str(val or "").strip()
    return _normalize_expected(s)


# ---------------------------------------------------------------------------
# Função pública usada pelo app
# ---------------------------------------------------------------------------
def fetch_exevopan_bosses(world: str, timeout: int = 20) -> List[Dict[str, str]]:
    """Busca bosses do ExevoPan para um world.

    Retorna lista de dicts:
      {"boss": "...", "chance": "...", "status": "..."}
    Onde status pode conter "Expected in: X day(s)" quando aplicável.
    """
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

    # 1) Preferência: parse pelo texto renderizado (pega % decimais e previsão)
    out = _parse_bosses_from_rendered_text(html)
    if out:
        return out

    # 2) Fallback: tenta __NEXT_DATA__ (best-effort)
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

        # dedupe mantendo ordem
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
