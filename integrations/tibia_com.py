from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote, quote_plus

import requests
from bs4 import BeautifulSoup

TIBIADATA_CHAR = "https://api.tibiadata.com/v4/character/{name}"
TIBIADATA_WORLD = "https://api.tibiadata.com/v4/world/{world}"
TIBIA_CHAR_URL = "https://www.tibia.com/community/?subtopic=characters&name={name}"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_character_raw(name: str, timeout: int = 12) -> Dict[str, Any]:
    url = TIBIADATA_CHAR.format(name=quote(str(name)))
    r = requests.get(url, timeout=timeout, headers=_UA)
    r.raise_for_status()
    return r.json() if r.text else {}


def fetch_character_world(name: str, timeout: int = 12) -> Optional[str]:
    try:
        data = fetch_character_raw(name, timeout=timeout)
        ch = (data.get("character") or {}).get("character") or {}
        world = ch.get("world") or ch.get("server")
        if isinstance(world, str) and world.strip():
            return world.strip()
    except Exception:
        return None
    return None


def fetch_world_online_players(world: str, timeout: int = 12) -> Optional[Set[str]]:
    try:
        safe_world = quote(str(world).strip())
        url = TIBIADATA_WORLD.format(world=safe_world)
        r = requests.get(url, timeout=timeout, headers=_UA)
        r.raise_for_status()
        data = r.json() if r.text else {}
        wb = (data or {}).get("world", {}) if isinstance(data, dict) else {}
        players = None
        if isinstance(wb, dict):
            players = wb.get("online_players") or wb.get("players_online") or wb.get("players")
            if isinstance(players, dict):
                players = (
                    players.get("online_players")
                    or players.get("players")
                    or players.get("online")
                    or players.get("data")
                )
        if not isinstance(players, list):
            return set()
        out: Set[str] = set()
        for player in players:
            if isinstance(player, dict):
                name = player.get("name")
            else:
                name = player
            if isinstance(name, str) and name.strip():
                out.add(name.strip().lower())
        return out
    except Exception:
        return None


def _extract_deaths(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    chblk = (data.get("character") or {})
    deaths = chblk.get("deaths")
    if deaths is None:
        ch = chblk.get("character") or {}
        deaths = ch.get("deaths")
    return deaths if isinstance(deaths, list) else []


def fetch_character_snapshot(name: str, timeout: int = 12) -> Dict[str, Any]:
    data = fetch_character_raw(name, timeout=timeout)
    ch = (data.get("character") or {}).get("character") or {}
    deaths = _extract_deaths(data)
    level = ch.get("level")
    world = ch.get("world") or ch.get("server")
    online = ch.get("online")
    status = ch.get("status")
    if online is None and isinstance(status, str):
        online = status.lower() == "online"
    return {"name": name, "level": level, "world": world, "online": online, "deaths": deaths}


def newest_death_time(deaths: List[Dict[str, Any]]) -> Optional[str]:
    if not deaths:
        return None
    d0 = deaths[0]
    if isinstance(d0, dict):
        t = d0.get("time") or d0.get("date")
        if isinstance(t, str) and t.strip():
            return t.strip()
    return None


def death_summary(deaths: List[Dict[str, Any]], max_killers: int = 2) -> str:
    if not deaths:
        return ""
    d0 = deaths[0] if isinstance(deaths[0], dict) else {}
    level = d0.get("level")
    killers = d0.get("killers") or d0.get("involved") or []
    names: List[str] = []
    if isinstance(killers, list):
        for killer in killers[:max_killers]:
            if isinstance(killer, dict):
                name = killer.get("name")
            else:
                name = killer
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    parts = []
    if level:
        parts.append(f"lvl {level}")
    if names:
        parts.append("por " + ", ".join(names))
    return " ".join(parts).strip()


def is_character_online_tibia_com(name: str, world: str, timeout: int = 12, *, light_only: bool = False) -> Optional[bool]:
    _ = world
    try:
        safe_name = quote_plus(str(name))
        url = TIBIA_CHAR_URL.format(name=safe_name)
        r = requests.get(url, timeout=timeout, headers=_UA)
        if r.status_code != 200:
            return None
        html = r.text or ""
        if not html:
            return None
        try:
            match = re.search(r"status:</td>\s*<td[^>]*>\s*(online|offline)\s*<", html, flags=re.I)
            if match:
                return match.group(1).strip().lower() == "online"
        except Exception:
            pass
        if light_only:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            key = (tds[0].get_text(" ", strip=True) or "").strip().rstrip(":").strip().lower()
            if key != "status":
                continue
            value = (tds[1].get_text(" ", strip=True) or "").strip().lower()
            if "online" in value:
                return True
            if "offline" in value:
                return False
            return None
        return None
    except Exception:
        return None


def eu_dst_offset_hours(dt_local: datetime) -> int:
    year = dt_local.year
    mar31 = datetime(year, 3, 31)
    last_sun_march = mar31 - timedelta(days=(mar31.weekday() + 1) % 7)
    oct31 = datetime(year, 10, 31)
    last_sun_oct = oct31 - timedelta(days=(oct31.weekday() + 1) % 7)
    start = datetime(year, 3, last_sun_march.day, 2, 0, 0)
    end = datetime(year, 10, last_sun_oct.day, 3, 0, 0)
    return 2 if start <= dt_local < end else 1


def parse_tibia_datetime(raw: str) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().replace("\u00a0", " ")
    if not s or s.lower() in ("n/a", "none", "null"):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d, %H:%M:%S", "%Y-%m-%d"):
        try:
            dt_local = datetime.strptime(s, fmt)
            return dt_local - timedelta(hours=eu_dst_offset_hours(dt_local))
        except Exception:
            continue
    match = re.match(r"^([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4}),\s*(\d{2}:\d{2}:\d{2})(?:\s+([A-Za-z]{2,5}))?$", s)
    if not match:
        return None
    mon, day, year, hhmmss, tz_name = match.groups()
    try:
        dt_local = datetime.strptime(f"{mon} {day} {year}, {hhmmss}", "%b %d %Y, %H:%M:%S")
    except Exception:
        return None
    tz_u = (tz_name or "").upper().strip()
    if tz_u == "CEST":
        off = 2
    elif tz_u == "CET":
        off = 1
    elif tz_u in ("UTC", "GMT"):
        off = 0
    else:
        off = eu_dst_offset_hours(dt_local)
    return dt_local - timedelta(hours=off)


def fetch_last_login_dt(name: str, timeout: int = 12) -> Optional[datetime]:
    try:
        safe = quote_plus(str(name))
        url = TIBIA_CHAR_URL.format(name=safe)
        r = requests.get(url, timeout=timeout, headers=_UA)
        if r.status_code != 200:
            return None
        html = r.text or ""
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            key = (tds[0].get_text(" ", strip=True) or "").strip().rstrip(":").strip().lower()
            if key not in ("last login", "last login time", "last login:") and not key.startswith("last login"):
                continue
            value = (tds[1].get_text(" ", strip=True) or "").strip()
            return parse_tibia_datetime(value)
    except Exception:
        return None
    return None
