from dataclasses import dataclass
import math

WEAPONS = {
    "Standard (500)": {"charges": 500, "price_gp": 347222},
    "Enhanced (1800)": {"charges": 1800, "price_gp": 1250000},
    "Lasting (14400)": {"charges": 14400, "price_gp": 10000000},
}

@dataclass
class TrainingInput:
    skill: str
    vocation: str
    from_level: int
    to_level: int
    weapon_kind: str
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

def compute_training_plan(inp: TrainingInput) -> TrainingPlan:
    if inp.to_level <= inp.from_level:
        return TrainingPlan(False, "O nível final deve ser maior que o inicial.")

    weapon = WEAPONS.get(inp.weapon_kind, WEAPONS["Standard (500)"])
    charges_per_weapon = weapon["charges"]
    price = weapon["price_gp"]

    # multiplicadores
    mult = 1.0
    mult *= (1.0 + inp.loyalty_percent / 100.0)
    if inp.private_dummy:
        mult *= 1.10
    if inp.double_event:
        mult *= 2.0

    # cálculo simples (base): tries por level
    total_tries = 0
    for s in range(inp.from_level, inp.to_level):
        total_tries += 50 * (1.1 ** (s - 10))

    tries_per_charge = 8.0  # padrão aproximado
    charges_needed = math.ceil(total_tries / (tries_per_charge * mult))

    weapons_needed = math.ceil(charges_needed / charges_per_weapon)
    hours = (charges_needed * 2) / 3600.0  # 2s por charge
    total_cost = weapons_needed * price

    return TrainingPlan(True, total_charges=charges_needed, weapons=weapons_needed, hours=hours, total_cost_gp=total_cost)
  
