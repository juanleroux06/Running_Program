"""Daniels/Gilbert VDOT model.

    VO2(v)       = -4.60 + 0.182258 v + 0.000104 v^2          (v in m/min)
    %VO2max(t)   = 0.8 + 0.1894393 e^(-0.012778 t) + 0.2989558 e^(-0.1932605 t)   (t in min)
    VDOT         = VO2(v) / %VO2max(t)

Training paces solve VO2(v) = f * VDOT for v, at the fractions f in PACE_FRACTIONS.
"""

from __future__ import annotations

import math

from runplan.models import Activity, DailyWellness

# Fraction of VDOT for each training intensity: (slow end, fast end).
PACE_FRACTIONS: dict[str, tuple[float, float]] = {
    "E": (0.64, 0.72),
    "M": (0.79, 0.83),
    "T": (0.86, 0.89),
    "I": (0.975, 1.00),
    "R": (1.04, 1.08),
}

MIN_VDOT, MAX_VDOT = 20.0, 85.0


def vo2_at_velocity(v_m_per_min: float) -> float:
    return -4.60 + 0.182258 * v_m_per_min + 0.000104 * v_m_per_min**2


def fraction_sustainable(t_min: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot_from_performance(distance_km: float, time_min: float) -> float:
    if distance_km <= 0 or time_min <= 0:
        raise ValueError("distance and time must be positive")
    v = distance_km * 1000 / time_min
    return vo2_at_velocity(v) / fraction_sustainable(time_min)


def velocity_for_vo2(vo2: float) -> float:
    """Inverse of vo2_at_velocity: solve 0.000104 v^2 + 0.182258 v - (4.60 + vo2) = 0."""
    a, b, c = 0.000104, 0.182258, -(4.60 + vo2)
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def pace_s_per_km(vdot: float, fraction: float) -> float:
    v = velocity_for_vo2(vdot * fraction)  # m/min
    return 60_000 / v


def training_paces(vdot: float) -> dict[str, tuple[float, float]]:
    """Return {intensity: (fast_s_per_km, slow_s_per_km)}."""
    out = {}
    for key, (slow_f, fast_f) in PACE_FRACTIONS.items():
        out[key] = (pace_s_per_km(vdot, fast_f), pace_s_per_km(vdot, slow_f))
    return out


def race_time_min(vdot: float, distance_km: float) -> float:
    """Predict race time for a VDOT by bisection on time."""
    lo, hi = 1.0, 600.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot_from_performance(distance_km, mid) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def estimate_vdot_from_activities(activities: list[Activity]) -> float | None:
    """Best VDOT from continuous efforts of 12-90 minutes.

    Training runs are rarely all-out, so this underestimates fitness, which is the safe side.
    """
    best = None
    for a in activities:
        if 12 <= a.duration_min <= 90 and a.distance_km >= 2:
            v = vdot_from_performance(a.distance_km, a.duration_min)
            if MIN_VDOT <= v <= MAX_VDOT and (best is None or v > best):
                best = v
    return best


def choose_vdot(
    recent_result: tuple[float, float] | None,
    activities: list[Activity],
    wellness: list[DailyWellness],
) -> tuple[float, str]:
    """Pick the VDOT to train from, and say where it came from.

    Priority: configured race result > best recent effort > Garmin VO2max > conservative default.
    The value is rounded DOWN to 0.5 so paces err on the easy side.
    """
    if recent_result:
        v, src = vdot_from_performance(*recent_result), "recent race result in config"
    elif (est := estimate_vdot_from_activities(activities)) is not None:
        v, src = est, "best recent effort in Garmin data"
    elif vo2 := [w.vo2max for w in wellness if w.vo2max]:
        v, src = vo2[-1] * 0.95, "Garmin VO2max estimate (x0.95)"
    else:
        v, src = 35.0, "default (no race result or usable data)"
    v = max(MIN_VDOT, min(MAX_VDOT, v))
    return math.floor(v * 2) / 2, src


def fmt_pace(s_per_km: float, units: str = "km") -> str:
    if units == "mi":
        s_per_km *= 1.609344
    m, s = divmod(round(s_per_km), 60)
    return f"{m}:{s:02d}/{units}"
