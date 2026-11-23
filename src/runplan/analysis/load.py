"""Training load: Banister TRIMP, weekly volume, acute:chronic workload ratio.

    HRr   = (HR_avg - HR_rest) / (HR_max - HR_rest)
    TRIMP = T * HRr * a * e^(b * HRr)        a, b = 0.64, 1.92 (male) or 0.86, 1.67 (female)
    ACWR  = load(last 7 d) / (load(last 28 d) / 4)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from runplan.models import Activity, DailyWellness

TRIMP_COEFFS = {"male": (0.64, 1.92), "female": (0.86, 1.67)}


def trimp(duration_min: float, avg_hr: float, hr_rest: float, hr_max: float, sex: str = "male"):
    if hr_max <= hr_rest:
        raise ValueError("hr_max must exceed hr_rest")
    hrr = max(0.0, min(1.0, (avg_hr - hr_rest) / (hr_max - hr_rest)))
    a, b = TRIMP_COEFFS[sex]
    return duration_min * hrr * a * math.exp(b * hrr)


def activity_load(a: Activity, hr_rest: float, hr_max: float, sex: str) -> float:
    """TRIMP when HR exists; otherwise a pace-free fallback of ~1 TRIMP-ish per easy minute."""
    if a.avg_hr:
        return trimp(a.duration_min, a.avg_hr, hr_rest, hr_max, sex)
    return a.duration_min * 1.0


def estimate_hr_bounds(
    activities: list[Activity], wellness: list[DailyWellness]
) -> tuple[float, float]:
    """(hr_rest, hr_max) estimated from data, with safe defaults."""
    rests = [w.resting_hr for w in wellness if w.resting_hr]
    hr_rest = statistics.median(rests) if rests else 55.0
    maxes = [a.max_hr for a in activities if a.max_hr]
    hr_max = max(maxes) if maxes else 190.0
    hr_max = max(hr_max, hr_rest + 60)
    return float(hr_rest), float(hr_max)


def hr_zones(hr_rest: float, hr_max: float) -> dict[int, tuple[int, int]]:
    """Karvonen zones on heart-rate reserve: Z1 50-60%, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 90-100%."""
    bounds = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    r = hr_max - hr_rest
    return {
        z + 1: (round(hr_rest + bounds[z] * r), round(hr_rest + bounds[z + 1] * r))
        for z in range(5)
    }


@dataclass
class LoadSummary:
    as_of: date
    last7_km: float
    last28_km: float
    chronic_weekly_km: float  # last28 / 4
    acute_load: float
    chronic_load: float
    acwr: float | None
    monotony: float | None
    longest_run_km_28d: float
    runs_last7: int


def summarise_load(
    activities: list[Activity],
    as_of: date,
    hr_rest: float,
    hr_max: float,
    sex: str = "male",
) -> LoadSummary:
    """Summarise the 7 and 28 days ending the day BEFORE `as_of`."""
    start7 = as_of - timedelta(days=7)
    start28 = as_of - timedelta(days=28)
    in7 = [a for a in activities if start7 <= a.day < as_of]
    in28 = [a for a in activities if start28 <= a.day < as_of]

    acute = sum(activity_load(a, hr_rest, hr_max, sex) for a in in7)
    chronic_total = sum(activity_load(a, hr_rest, hr_max, sex) for a in in28)
    chronic = chronic_total / 4
    acwr = acute / chronic if chronic > 0 else None

    daily = [0.0] * 7
    for a in in7:
        daily[(a.day - start7).days] += activity_load(a, hr_rest, hr_max, sex)
    sd = statistics.pstdev(daily)
    monotony = statistics.mean(daily) / sd if sd > 0 else None

    km28 = sum(a.distance_km for a in in28)
    return LoadSummary(
        as_of=as_of,
        last7_km=round(sum(a.distance_km for a in in7), 2),
        last28_km=round(km28, 2),
        chronic_weekly_km=round(km28 / 4, 2),
        acute_load=round(acute, 1),
        chronic_load=round(chronic, 1),
        acwr=round(acwr, 2) if acwr is not None else None,
        monotony=round(monotony, 2) if monotony is not None else None,
        longest_run_km_28d=max((a.distance_km for a in in28), default=0.0),
        runs_last7=len(in7),
    )
