"""XP Loss (estimativa) – igual GuildStats (promoted + 7 blessings).

Este cálculo é usado no app Android para exibir "xp perdida" nas mortes sem
depender de scraping do GuildStats (que pode falhar/bloquear no Android).

Fonte: fórmula conhecida de Tibia para XP total por level + MeL (Maximum
Experience Loss) com reduções por promoção e blessings.
"""

from __future__ import annotations


def tibia_total_experience_for_level(level: int) -> int:
    """Total de experiência para atingir `level` (xp mínimo no level, 0% próximo)."""
    try:
        lvl = int(level)
    except Exception:
        return 0

    if lvl <= 1:
        return 0

    # Fórmula conhecida do Tibia para XP total por level:
    # exp = (50/3) * (lvl^3 - 6*lvl^2 + 17*lvl - 12)
    return int((50 * (lvl**3 - 6 * lvl**2 + 17 * lvl - 12)) / 3)


def estimate_death_exp_lost(
    level: int,
    *,
    blessings: int = 7,
    promoted: bool = True,
    retro_hardcore: bool = False,
) -> int:
    """Estimativa de XP perdida ao morrer (promoted + 7 blessings por padrão).

    Observação: é uma estimativa (a perda real pode ser menor por unfair fight,
    twist of fate, etc.).
    """

    try:
        x = int(level)
    except Exception:
        return 0

    if x <= 0:
        return 0

    # Base (máxima) de perda
    if x <= 23:
        base = 0.10 * tibia_total_experience_for_level(x)
    else:
        base = ((x + 50) / 100.0) * 50.0 * (x * x - 5 * x + 8)

    if retro_hardcore:
        base *= 1.16
        per_bless = 0.064
    else:
        per_bless = 0.08

    b = max(0, min(int(blessings), 7))
    reduction = b * per_bless + (0.30 if promoted else 0.0)
    reduction = max(0.0, min(reduction, 0.95))

    lost = base * (1.0 - reduction)
    if lost < 0:
        lost = 0

    return int(round(lost))
