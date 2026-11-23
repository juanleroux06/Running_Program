"""Recovery flags from HRV, sleep and resting HR."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from runplan.models import DailyWellness

LOW_HRV = {"LOW", "POOR", "UNBALANCED"}


@dataclass
class Readiness:
    compromised: bool
    reasons: list[str] = field(default_factory=list)


def assess_readiness(wellness: list[DailyWellness], as_of: date, days: int = 5) -> Readiness:
    """Flag when at least 3 of the last `days` days show strain."""
    recent = [w for w in wellness if as_of - timedelta(days=days) <= w.day < as_of]
    reasons = []

    low_hrv = sum(1 for w in recent if (w.hrv_status or "").upper() in LOW_HRV)
    if low_hrv >= 3:
        reasons.append(f"HRV low/unbalanced on {low_hrv} of the last {days} days")

    poor_sleep = sum(1 for w in recent if w.sleep_score is not None and w.sleep_score < 60)
    if poor_sleep >= 3:
        reasons.append(f"sleep score under 60 on {poor_sleep} of the last {days} days")

    baseline = [
        w.resting_hr
        for w in wellness
        if w.resting_hr and as_of - timedelta(days=35) <= w.day < as_of - timedelta(days=days)
    ]
    if len(baseline) >= 10:
        base = statistics.median(baseline)
        elevated = sum(1 for w in recent if w.resting_hr and w.resting_hr >= base + 5)
        if elevated >= 3:
            reasons.append(f"resting HR 5+ bpm above baseline on {elevated} days")

    return Readiness(compromised=bool(reasons), reasons=reasons)
