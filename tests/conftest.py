from datetime import date, datetime, timedelta

import pytest

from runplan.config import AthleteConfig
from runplan.models import Activity, DailyWellness


@pytest.fixture
def cfg() -> AthleteConfig:
    return AthleteConfig.model_validate({
        "recent_result": {"distance_km": 5, "time": "22:30"},
        "current_weekly_km": 40,
        "longest_recent_run_km": 14,
        "peak_weekly_km": 70,
        "run_days": ["tue", "wed", "thu", "sat", "sun"],
        "long_run_day": "sun",
        "hr_max": 190,
        "hr_rest": 50,
    })


def make_runs(start: date, weeks: int, km_per_week: float, days=(1, 3, 6)) -> list[Activity]:
    """Synthetic easy runs: km split evenly across `days` (0=Mon) each week, 6:00/km, HR 140."""
    out = []
    for w in range(weeks):
        for d in days:
            day = start + timedelta(days=7 * w + d)
            km = km_per_week / len(days)
            out.append(Activity(
                activity_id=f"{day}", start=datetime.combine(day, datetime.min.time()).replace(hour=6),
                distance_km=km, duration_min=km * 6, avg_hr=140, max_hr=170,
            ))
    return out


def make_wellness(start: date, days: int, hrv="BALANCED", sleep=80, rhr=50) -> list[DailyWellness]:
    return [
        DailyWellness(day=start + timedelta(days=i), hrv_status=hrv, sleep_score=sleep, resting_hr=rhr)
        for i in range(days)
    ]
