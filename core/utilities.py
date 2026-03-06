from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


# ------------------------------------------------------------
# Rashid (NPC)
# ------------------------------------------------------------
# weekday(): Monday=0 ... Sunday=6
RASHID_SCHEDULE: Dict[int, str] = {
    0: "Svargrond",
    1: "Liberty Bay",
    2: "Port Hope",
    3: "Ankrahmun",
    4: "Darashia",
    5: "Edron",
    6: "Carlin",
}


def tibia_utc_now() -> datetime:
    # Mantém simples e compatível no Android
    return datetime.utcnow()


def rashid_today(dt: Optional[datetime] = None) -> str:
    dt = dt or tibia_utc_now()
    return RASHID_SCHEDULE.get(dt.weekday(), "Unknown")


def is_rashid_day(dt: Optional[datetime] = None) -> bool:
    dt = dt or tibia_utc_now()
    return dt.weekday() in RASHID_SCHEDULE


# ------------------------------------------------------------
# Blessings
# ------------------------------------------------------------
@dataclass(frozen=True)
class BlessConfig:
    # Base (custo por nível) e limites
    factor: int = 200                 # base = factor * level
    min_base: int = 2000              # evita base muito baixa em lvl baixo
    regular_cap: int = 20000          # limite por blessing regular
    enhanced_cap: int = 50000         # limite por blessing enhanced
    enhanced_multiplier: float = 1.5  # enhanced = base * multiplier (antes do cap)

    # Twist of Fate
    twist_base: int = 200000
    twist_extra_after_level: int = 150
    twist_extra_per_level: int = 2000

    # Desconto Inquisition (exemplo: 10% off)
    inq_discount_multiplier: float = 0.9


def _to_cfg(cfg: Optional[BlessConfig], config: Optional[dict]) -> BlessConfig:
    if cfg is not None:
        return cfg
    if isinstance(config, dict) and config:
        # aceita override parcial se alguém passar config via dict
        base = BlessConfig()
        data = {**base.__dict__, **config}
        return BlessConfig(**data)
    return BlessConfig()


def calc_blessings(
    level: int,
    regular_count: int = 5,
    enhanced_count: int = 0,
    include_twist: bool = False,
    inq_discount: bool = False,
    cfg: Optional[BlessConfig] = None,
    *,
    # compat: alguns lugares podem chamar com esses nomes
    inquisition_discount: Optional[bool] = None,
    config: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Retorna breakdown e total.
    """
    if inquisition_discount is not None:
        inq_discount = bool(inquisition_discount)

    cfg = _to_cfg(cfg, config)

    # normaliza
    level = max(1, int(level))
    regular_count = max(0, min(5, int(regular_count)))
    enhanced_count = max(0, min(2, int(enhanced_count)))

    base = max(cfg.min_base, cfg.factor * level)

    regular_each = min(cfg.regular_cap, base)
    enhanced_each = min(cfg.enhanced_cap, int(base * cfg.enhanced_multiplier))

    regular_total = regular_each * regular_count
    enhanced_total = enhanced_each * enhanced_count

    twist_cost = 0
    if include_twist:
        twist_cost = cfg.twist_base
        if level > cfg.twist_extra_after_level:
            twist_cost += (level - cfg.twist_extra_after_level) * cfg.twist_extra_per_level

    total_before_discount = regular_total + enhanced_total + twist_cost
    discount_multiplier = cfg.inq_discount_multiplier if inq_discount else 1.0
    total = int(total_before_discount * discount_multiplier)

    return {
        "level": level,
        "regular_count": regular_count,
        "enhanced_count": enhanced_count,
        "include_twist": include_twist,
        "inq_discount": inq_discount,
        "regular_each": regular_each,
        "enhanced_each": enhanced_each,
        "regular_total": regular_total,
        "enhanced_total": enhanced_total,
        "twist_cost": twist_cost,
        "discount_multiplier": discount_multiplier,
        "total": total,
    }


def blessings_cost(
    level: int,
    regular_count: int = 5,
    enhanced_count: int = 0,
    include_twist: bool = False,
    inq_discount: bool = False,
    cfg: Optional[BlessConfig] = None,
    *,
    # compat
    inquisition_discount: Optional[bool] = None,
    config: Optional[dict] = None,
) -> int:
    """
    Wrapper que o core/api.py espera existir.
    Retorna SOMENTE o total (int).
    """
    data = calc_blessings(
        level=level,
        regular_count=regular_count,
        enhanced_count=enhanced_count,
        include_twist=include_twist,
        inq_discount=inq_discount,
        cfg=cfg,
        inquisition_discount=inquisition_discount,
        config=config,
    )
    return int(data["total"])


def calc_blessings_cost(level: int, pvp: bool = True) -> int:
    """Compatibilidade com a UI.

    A UI do Android/Windows antiga chama `calc_blessings_cost(level, pvp=...)`.
    O parâmetro `pvp` é mantido apenas para evitar crash (o custo de compra das
    blessings não depende diretamente do tipo de PvP).

    Retorna o custo total das 5 blessings regulares (sem Inquisition por padrão).
    """

    _ = pvp  # compat: atualmente não altera o cálculo
    return blessings_cost(level=level, regular_count=5, enhanced_count=0, inq_discount=False)


def stamina_to_full(current_stamina: str | float, max_hours: int = 42) -> float:
    """Compatibilidade: calcula quantas horas faltam para chegar ao máximo.

    Observação: o cálculo de regen de stamina no Tibia é mais complexo (e varia
    conforme o intervalo). Como, no Android, essa função é usada apenas para
    exibir uma estimativa básica, aqui retornamos **apenas a diferença** até o
    máximo.

    Args:
        current_stamina: pode ser float (ex.: 37.5) ou string "HH:MM".
        max_hours: limite superior de stamina em horas (padrão 42).

    Returns:
        Horas restantes (float), nunca menor que 0.
    """

    if isinstance(current_stamina, str):
        s = current_stamina.strip()
        if ":" in s:
            hh, mm = s.split(":", 1)
            try:
                current = float(int(hh)) + (float(int(mm)) / 60.0)
            except ValueError:
                # fallback: tenta converter direto
                current = float(s)
        else:
            current = float(s)
    else:
        current = float(current_stamina)

    remaining = float(max_hours) - current
    return remaining if remaining > 0 else 0.0
