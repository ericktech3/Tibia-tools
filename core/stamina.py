# -*- coding: utf-8 -*-
"""Stamina calculator helpers.

Implements Tibia stamina regeneration rules (offline):
- Stamina starts regenerating after 10 minutes logged off.
- Up to 39:00 stamina: +1 min stamina for each 3 min offline.
- From 39:00 to 42:00 (bonus/green): +1 min stamina for each 6 min offline.

References:
- TibiaWiki (pt-BR): https://www.tibiawiki.com.br/wiki/Stamina
- Tibia.com News Archive (green regen 6:1): https://www.tibia.com/news/?id=5465&subtopic=newsarchive
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

MAX_STAMINA_MIN = 42 * 60
BONUS_START_MIN = 39 * 60
OFFLINE_DELAY_MIN = 10

NORMAL_OFFLINE_PER_STAMINA_MIN = 3
BONUS_OFFLINE_PER_STAMINA_MIN = 6


@dataclass(frozen=True)
class StaminaCalcResult:
    current_min: int
    target_min: int
    offline_needed_min: int  # includes the initial OFFLINE_DELAY_MIN when target>current
    regen_offline_only_min: int  # without the initial delay


def clamp_int(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def hm_to_minutes(hours: int, minutes: int) -> int:
    hours = clamp_int(hours, 0, 9999)
    minutes = clamp_int(minutes, 0, 59)
    return hours * 60 + minutes


def minutes_to_hm(total_minutes: int) -> Tuple[int, int]:
    total_minutes = clamp_int(total_minutes, 0, 999999)
    return total_minutes // 60, total_minutes % 60


def format_hm(total_minutes: int) -> str:
    h, m = minutes_to_hm(total_minutes)
    return f"{h:02d}:{m:02d}"


def clamp_stamina_minutes(total_minutes: int) -> int:
    return clamp_int(total_minutes, 0, MAX_STAMINA_MIN)


def parse_hm_text(hours_text: str, minutes_text: str) -> int:
    """Parse hours/minutes text fields into stamina minutes (clamped)."""
    ht = (hours_text or "").strip()
    mt = (minutes_text or "").strip()

    hours = int(ht) if ht else 0
    minutes = int(mt) if mt else 0

    if minutes < 0 or minutes > 59:
        raise ValueError("Minutos devem estar entre 0 e 59.")

    total = hm_to_minutes(hours, minutes)
    return clamp_stamina_minutes(total)


def compute_offline_regen(current_min: int, target_min: int) -> StaminaCalcResult:
    """Compute offline time required to reach target stamina.

    Returns offline minutes required (including the initial 10-minute delay, when applicable).
    """
    cur = clamp_stamina_minutes(int(current_min))
    tgt = clamp_stamina_minutes(int(target_min))

    if tgt <= cur:
        return StaminaCalcResult(cur, tgt, 0, 0)

    regen_offline = 0
    temp = cur

    # Normal range: up to 39:00
    if temp < BONUS_START_MIN:
        up_to = min(tgt, BONUS_START_MIN)
        d = up_to - temp
        if d > 0:
            regen_offline += d * NORMAL_OFFLINE_PER_STAMINA_MIN
            temp += d

    # Bonus/green range: 39:00 to 42:00
    if tgt > temp:
        d = tgt - temp
        regen_offline += d * BONUS_OFFLINE_PER_STAMINA_MIN
        temp += d

    offline_needed = regen_offline + OFFLINE_DELAY_MIN
    return StaminaCalcResult(cur, tgt, offline_needed, regen_offline)
