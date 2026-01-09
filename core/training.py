from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Tuple


# ---------------------------------------------------------------------------
# Exercise weapons (NPC prices in gp)
# ---------------------------------------------------------------------------
WEAPONS = {
    "Standard (500)": {"charges": 500, "price_gp": 347_222},
    "Enhanced (1800)": {"charges": 1_800, "price_gp": 1_250_000},
    "Lasting (14400)": {"charges": 14_400, "price_gp": 10_000_000},
}

# ---------------------------------------------------------------------------
# Skill formulas (based on Tibia skill points / mana spent formulas)
# - Each skill level requires:
#     points_to_advance(level) = skill_constant * vocation_constant ** (level - offset)
# - Offset is 10 for most combat skills and 0 for magic level.
# - "points" means:
#     melee/fist/distance/shielding: hits/blocks "skill tries"
#     magic level: mana spent (burned mana)
# ---------------------------------------------------------------------------

# skill type -> (skill_constant, offset)
SKILL_CONSTANTS: Dict[str, Tuple[float, int]] = {
    "magic": (1600.0, 0),
    "melee": (50.0, 10),       # sword/axe/club and also fist (same base constant/offset)
    "distance": (25.0, 10),
    "shielding": (100.0, 10),
    "fishing": (20.0, 10),
}

# vocation -> constants used in formula, per category
VOCATION_CONSTANTS: Dict[str, Dict[str, float]] = {
    "none":      {"magic": 4.0,  "melee": 2.0, "fist": 1.5, "distance": 2.0, "shielding": 1.5},
    "knight":    {"magic": 3.0,  "melee": 1.1, "fist": 1.1, "distance": 1.4, "shielding": 1.1},
    "paladin":   {"magic": 1.4,  "melee": 1.2, "fist": 1.2, "distance": 1.1, "shielding": 1.1},
    "sorcerer":  {"magic": 1.1,  "melee": 2.0, "fist": 1.5, "distance": 2.0, "shielding": 1.5},
    "druid":     {"magic": 1.1,  "melee": 1.8, "fist": 1.5, "distance": 1.8, "shielding": 1.5},
    "monk":      {"magic": 1.25, "melee": 1.4, "fist": 1.1, "distance": 1.5, "shielding": 1.15},
}

# Points gained per exercise weapon charge (approx. / standard reference)
# Sources commonly used by calculators:
# - Melee/Fist: 7.2 hits per charge
# - Distance: 4.32 "miss hits" per charge (dummy has no blood)
# - Shielding: 14.4 blocks per charge
# - Magic: 600 burned mana per charge
POINTS_PER_CHARGE: Dict[str, float] = {
    "melee": 7.2,
    "fist": 7.2,
    "distance": 4.32,
    "shielding": 14.4,
    "magic": 600.0,
}

# UI skill -> (skill_constant_type, vocation_attr_type)
SKILL_MAP: Dict[str, Tuple[str, str]] = {
    "Sword": ("melee", "melee"),
    "Axe": ("melee", "melee"),
    "Club": ("melee", "melee"),
    "Fist Fighting": ("melee", "fist"),
    "Distance": ("distance", "distance"),
    "Shielding": ("shielding", "shielding"),
    "Magic Level": ("magic", "magic"),
}

# UI vocation -> internal key
VOCATION_UI_MAP: Dict[str, str] = {
    "None": "none",
    "Knight": "knight",
    "Paladin": "paladin",
    "Sorcerer": "sorcerer",
    "Druid": "druid",
    "Monk": "monk",
}


@dataclass
class TrainingInput:
    skill: str
    vocation: str
    from_level: int
    to_level: int
    weapon_kind: str
    percent_left: float = 100.0  # % restante para subir 1 nível (1-100 no Tibia)
    loyalty_percent: float = 0.0
    private_dummy: bool = False
    double_event: bool = False


@dataclass
class TrainingPlan:
    ok: bool
    error: str = ""
    total_charges: int = 0
    weapons: int = 0
    hours: float = 0.0
    total_cost_gp: int = 0


def _norm_skill(skill: str) -> str:
    s = (skill or "").strip()
    return s if s in SKILL_MAP else "Sword"


def _norm_vocation(vocation: str) -> str:
    v = (vocation or "").strip()
    if v in VOCATION_UI_MAP:
        return VOCATION_UI_MAP[v]
    # fallback: allow lowercase keys
    vlow = v.lower()
    if vlow in VOCATION_CONSTANTS:
        return vlow
    return "knight"


def _points_to_advance(skill_const_type: str, voc_attr: str, voc_key: str, level: int) -> float:
    const, offset = SKILL_CONSTANTS[skill_const_type]
    vconst = VOCATION_CONSTANTS[voc_key][voc_attr]
    return const * (vconst ** (level - offset))


def _total_points_needed(skill_const_type: str, voc_attr: str, voc_key: str, from_level: int, to_level: int, percent_left: float) -> float:
    # percent_left: 0..100 (Tibia usually shows 1..100)
    pct = max(0.0, min(100.0, float(percent_left)))
    total = (pct / 100.0) * _points_to_advance(skill_const_type, voc_attr, voc_key, from_level)
    for lvl in range(from_level + 1, to_level):
        total += _points_to_advance(skill_const_type, voc_attr, voc_key, lvl)
    return total


def compute_training_plan(inp: TrainingInput) -> TrainingPlan:
    skill_ui = _norm_skill(inp.skill)
    skill_const_type, voc_attr = SKILL_MAP[skill_ui]
    voc_key = _norm_vocation(inp.vocation)

    if inp.to_level <= inp.from_level:
        return TrainingPlan(False, "O nível final deve ser maior que o inicial.")

    # validações por tipo (evita valores estranhos abaixo do mínimo do jogo)
    min_level = 0 if skill_const_type == "magic" else 10
    if inp.from_level < min_level or inp.to_level < min_level:
        return TrainingPlan(False, f"Para {skill_ui}, use valores >= {min_level}.")

    if inp.percent_left <= 0 or inp.percent_left > 100:
        return TrainingPlan(False, "O % restante deve estar entre 1 e 100.")

    weapon = WEAPONS.get(inp.weapon_kind, WEAPONS["Standard (500)"])
    charges_per_weapon = int(weapon["charges"])
    price = int(weapon["price_gp"])

    # multiplicadores (loyalty + dummy + double event)
    mult = 1.0
    mult *= (1.0 + max(0.0, inp.loyalty_percent) / 100.0)
    if inp.private_dummy:
        mult *= 1.10
    if inp.double_event:
        mult *= 2.0

    points_per_charge = POINTS_PER_CHARGE.get(voc_attr, POINTS_PER_CHARGE.get(skill_const_type, 7.2))

    total_points = _total_points_needed(
        skill_const_type=skill_const_type,
        voc_attr=voc_attr,
        voc_key=voc_key,
        from_level=inp.from_level,
        to_level=inp.to_level,
        percent_left=inp.percent_left,
    )

    if total_points <= 0:
        return TrainingPlan(False, "Nada para calcular.")

    charges_needed = int(math.ceil(total_points / (points_per_charge * mult)))
    weapons_needed = int(math.ceil(charges_needed / charges_per_weapon))

    # Consome 1 charge a cada 2 segundos
    hours = (charges_needed * 2) / 3600.0
    total_cost = weapons_needed * price

    return TrainingPlan(True, total_charges=charges_needed, weapons=weapons_needed, hours=hours, total_cost_gp=total_cost)
