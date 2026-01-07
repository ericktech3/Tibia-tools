# core/bosses.py
# Exevo Pan bosses list (Boss Tracker)

from __future__ import annotations

import json
import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

UA = "TibiaTools/1.0 (+https://github.com/ericktech3/Tibia-tools)"
TIMEOUT = 20

_PERCENT_RE = re.compile(r"^\d+(?:[\.,]\d+)?%$")

def _normalize_line(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s

def fetch_exevopan_bosses(world: str) -> list[dict]:
    """Fetch bosses from Exevo Pan Boss Tracker.

    Returns a list of dicts:
      {'boss': <name>, 'chance': <percent|Unknown|No chance>, 'status': <optional>}
    """
    world = (world or "").strip()
    if not world:
        return []

    # Exevo Pan accepts world in path as-is; URL-encode to be safe.
    w = quote(world, safe="")
    url = f"https://www.exevopan.com/bosses/{w}"

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    try:
        html = requests.get(url, headers=headers, timeout=TIMEOUT).text
    except Exception:
        return []

    # 1) Preferred: parse __NEXT_DATA__ if present (more structured)
    try:
        m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            data = json.loads(m.group(1))
            # Heuristic walk: choose the best list of dicts with boss-ish entries
            candidates = []

            def walk(obj):
                if isinstance(obj, dict):
                    for v in obj.values():
                        walk(v)
                elif isinstance(obj, list):
                    if obj and all(isinstance(x, dict) for x in obj):
                        candidates.append(obj)
                    for v in obj:
                        walk(v)

            walk(data)

            def score(lst):
                # Score lists that look like boss entries
                s = 0
                n = len(lst)
                if n >= 20:
                    s += 2
                keys = set()
                for it in lst[:50]:
                    keys |= set(it.keys())
                # Typical keys we might see
                for k in ("name", "boss", "chance", "probability", "lastSeen", "last_seen", "expected", "next", "spawn"):
                    if k in keys:
                        s += 2 if k in ("chance", "probability") else 1
                # Penalize lists that are clearly not bosses (e.g. navigation)
                if "href" in keys or "url" in keys and "name" not in keys:
                    s -= 2
                return s

            best = max(candidates, key=score, default=None)
            out = []
            if best:
                for it in best:
                    name = it.get("boss") or it.get("name") or it.get("title")
                    if not name:
                        continue
                    chance = it.get("chance") or it.get("probability") or it.get("spawnChance") or it.get("spawn_chance")
                    status = it.get("status") or it.get("expected") or it.get("next") or it.get("next_spawn") or ""
                    # Normalize numbers
                    if isinstance(chance, (int, float)):
                        chance = f"{chance:.2f}%"
                    if chance is None:
                        chance = "Unknown"
                    out.append({"boss": str(name), "chance": str(chance), "status": str(status) if status else ""})
                # If the parsed list is meaningful, return it.
                if len(out) >= 10:
                    return out
    except Exception:
        pass

    # 2) Fallback: text parsing (works even if __NEXT_DATA__ changes)
    try:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n")
        # Clean lines
        raw_lines = [ _normalize_line(x) for x in text.splitlines() ]
        lines = [x for x in raw_lines if x]

        out = []
        i = 0
        while i < len(lines) - 1:
            name = lines[i]
            nxt = lines[i + 1]

            # Candidate if next line looks like a chance/status line
            if nxt == "Unknown" or _PERCENT_RE.match(nxt):
                out.append({"boss": name, "chance": nxt, "status": ""})
                i += 2
                continue

            if nxt.startswith("No chance") or nxt.startswith("Expected in") or "Expected in" in nxt:
                # Sometimes "No chance" and "Expected in" are split across 2-3 lines.
                status_parts = [nxt]
                j = i + 2
                while j < len(lines) and len(status_parts) < 3:
                    if _PERCENT_RE.match(lines[j]) or lines[j] == "Unknown":
                        break
                    # stop if next line is clearly a new section/boss (heuristic: capitalized and short)
                    status_parts.append(lines[j])
                    if "Expected in" in lines[j]:
                        break
                    j += 1
                status = " ".join(status_parts)
                out.append({"boss": name, "chance": "No chance" if status.startswith("No chance") else "Unknown", "status": status})
                i = j
                continue

            i += 1

        # Basic de-dup + sanity filter: keep entries that have either % or Unknown/No chance
        seen = set()
        cleaned = []
        for it in out:
            boss = it["boss"]
            if boss in seen:
                continue
            seen.add(boss)
            cleaned.append(it)

        return cleaned
    except Exception:
        return []
