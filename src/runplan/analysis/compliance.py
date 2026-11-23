"""How much of last week's plan was actually run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from runplan.models import Activity, WeekRecord


@dataclass
class Compliance:
    week_start: date
    planned_km: float
    actual_km: float
    ratio: float  # actual / planned


def week_compliance(record: WeekRecord, activities: list[Activity]) -> Compliance:
    end = record.week_start + timedelta(days=7)
    actual = sum(a.distance_km for a in activities if record.week_start <= a.day < end)
    ratio = actual / record.planned_km if record.planned_km > 0 else 1.0
    return Compliance(record.week_start, record.planned_km, round(actual, 2), round(ratio, 2))
