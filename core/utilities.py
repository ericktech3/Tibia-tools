from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime, timezone
from typing import Dict, Any, Tuple, Optional

# ---------------------------
# Blessings (custos editáveis)
# ---------------------------

@dataclass
class BlessConfig:
    threshold_level: int = 120
    regular_base: int = 20000
    regular_step: int = 75
    enhanced_base: int = 26000
    enhanced_step: int = 100
    twist_cost: int = 20000
    inq_discount_pct: int = 10

def _cost_piecewise(level: int, base: int, step: int, threshold: int) -> int:
    if level <= threshold:
        return int(base)
    return int(base + step * (level - threshold))

def calc_blessings(level: int,
                   regular_count: int,
                   enhanced_count: int,
                   include_twist: bool,
                   inq_discount: bool,
                   cfg: BlessConfig) -> Dict[str, Any]:
    level = max(1, int(level or 1))
    regular_count = max(0, min(5, int(regular_count)))
    enhanced_count = max(0, min(2, int(enhanced_count)))

    reg_each = _cost_piecewise(level, cfg.regular_base, cfg.regular_step, cfg.threshold_level)
    enh_each = _cost_piecewise(level, cfg.enhanced_base, cfg.enhanced_step, cfg.threshold_level)

    reg_total = reg_each * regular_count
    enh_total = enh_each * enhanced_count
    twist_total = int(cfg.twist_cost) if include_twist else 0

    discount_amt = 0
    if inq_discount and regular_count == 5 and cfg.inq_discount_pct:
        discount_amt = int(round(reg_total * (cfg.inq_discount_pct / 100.0)))
        reg_total -= discount_amt

    total = reg_total + enh_total + twist_total
    return {
        "level": level,
        "regular_each": reg_each,
        "enhanced_each": enh_each,
        "regular_count": regular_count,
        "enhanced_count": enhanced_count,
        "include_twist": include_twist,
        "inq_discount": inq_discount,
        "discount_amt": discount_amt,
        "total": total,
        "breakdown": {
            "regular": reg_total,
            "enhanced": enh_total,
            "twist": twist_total
        }
    }

# ---------------------------
# Rashid + Server Save (CET/CEST)
# ---------------------------

RASHID_SCHEDULE = {
    0: ("Svargrond", "Taverna (Barbarian Camp)"),
    1: ("Liberty Bay", "Em frente ao depot"),
    2: ("Port Hope", "No mercado"),
    3: ("Ankrahmun", "Base do mercado"),
    4: ("Darashia", "Centro (mercado)"),
    5: ("Edron", "Em frente ao depot"),
    6: ("Carlin", "Em frente ao depot"),
}

def _last_sunday(year: int, month: int) -> datetime:
    # último dia do mês -> volta até domingo
    if month == 12:
        d = datetime(year, 12, 31)
    else:
        d = datetime(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != 6:  # Sunday=6
        d -= timedelta(days=1)
    return d

def eu_is_dst(utc_dt: datetime) -> bool:
    # Regra UE: DST começa último domingo de março, 01:00 UTC; termina último domingo de outubro, 01:00 UTC
    y = utc_dt.year
    start = _last_sunday(y, 3).replace(hour=1, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    end = _last_sunday(y, 10).replace(hour=1, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    return start <= utc_dt < end

def cet_offset_hours(utc_dt: datetime) -> int:
    return 2 if eu_is_dst(utc_dt) else 1

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def to_cet(utc_dt: datetime) -> datetime:
    return utc_dt + timedelta(hours=cet_offset_hours(utc_dt))

def next_server_save_utc(utc_dt: Optional[datetime] = None) -> datetime:
    utc_dt = utc_dt or now_utc()
    cet_dt = to_cet(utc_dt)
    target_date = cet_dt.date()
    target_time = dtime(10, 0)

    if cet_dt.time() >= target_time:
        target_date = target_date + timedelta(days=1)

    # primeiro chute: assume offset atual
    candidate_cet = datetime.combine(target_date, target_time)
    # converter para UTC precisa saber se nesse momento é DST
    # Faz um chute convertendo como se fosse UTC, testa DST, ajusta
    # 1) suponha offset=1
    cand_utc = candidate_cet.replace(tzinfo=timezone.utc) - timedelta(hours=1)
    off = cet_offset_hours(cand_utc)
    cand_utc = candidate_cet.replace(tzinfo=timezone.utc) - timedelta(hours=off)
    return cand_utc

def rashid_today(utc_dt: Optional[datetime] = None) -> Dict[str, str]:
    utc_dt = utc_dt or now_utc()
    cet_dt = to_cet(utc_dt)
    wd = cet_dt.weekday()  # Monday=0
    city, where = RASHID_SCHEDULE.get(wd, ("?", "?"))
    return {"city": city, "where": where, "weekday": wd}

# ---------------------------
# Stamina (offline)
# ---------------------------

def parse_stamina(s: str) -> int:
    # retorna minutos (0..2520)
    s = (s or "").strip()
    if ":" not in s:
        raise ValueError("Use formato HH:MM")
    hh, mm = s.split(":", 1)
    h = int(hh)
    m = int(mm)
    if m < 0 or m >= 60:
        raise ValueError("Minutos inválidos")
    total = h * 60 + m
    if total < 0 or total > 42 * 60:
        raise ValueError("Stamina deve estar entre 00:00 e 42:00")
    return total

def fmt_minutes(mins: int) -> str:
    mins = max(0, int(mins))
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

def offline_needed_minutes(current_min: int, target_min: int) -> int:
    if current_min >= target_min:
        return 0
    cur = current_min
    tgt = target_min
    # até 39:00 (2340): 1 min stamina / 3 min offline
    # 39->42: 1 min stamina / 10 min offline
    off = 0
    if cur < 39*60:
        up_to = min(tgt, 39*60)
        gain = up_to - cur
        off += gain * 3
        cur = up_to
    if cur < tgt:
        gain = tgt - cur
        off += gain * 10
    return off

def calc_stamina_offline(current_str: str, target_str: str = "42:00", add_delay_10min: bool = True) -> Dict[str, str]:
    cur = parse_stamina(current_str)
    tgt = parse_stamina(target_str)
    to39 = offline_needed_minutes(cur, 39*60)
    to42 = offline_needed_minutes(cur, 42*60)
    toT = offline_needed_minutes(cur, tgt)

    delay = 10 if add_delay_10min and toT > 0 else 0
    return {
        "current": fmt_minutes(cur),
        "target": fmt_minutes(tgt),
        "offline_to_39": fmt_minutes(to39 + (10 if add_delay_10min and to39 > 0 else 0)),
        "offline_to_42": fmt_minutes(to42 + (10 if add_delay_10min and to42 > 0 else 0)),
        "offline_to_target": fmt_minutes(toT + delay),
        "note": "Inclui +10 min de delay inicial" if add_delay_10min else "Sem delay inicial"
    }

# ---------------------------------------------------------------------------
# Compat: versões antigas chamavam isso de `blessings_cost`.
# Retorna o mesmo dicionário do `calc_blessings` (total + breakdown).
# ---------------------------------------------------------------------------

def blessings_cost(
    level: int,
    regular_count: int = 5,
    enhanced_count: int = 2,
    include_twist: bool = False,
    inquisition_discount: bool = False,
    config: dict | None = None,
) -> dict:
    return calc_blessings(
        level=level,
        regular_count=regular_count,
        enhanced_count=enhanced_count,
        include_twist=include_twist,
        inquisition_discount=inquisition_discount,
        config=config,
    )
