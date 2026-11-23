from datetime import date

import pytest

from runplan.analysis.load import hr_zones
from runplan.analysis.vdot import training_paces
from runplan.models import PlannedWorkout
from runplan.workouts.garmin_json import PREFIX, to_garmin, workout_name
from runplan.workouts.library import Ctx, cruise_intervals, easy


def c(tt="pace"):
    return Ctx(paces=training_paces(45), zones=hr_zones(50, 190), target_type=tt, weekly_km=50)


def pw(session):
    return PlannedWorkout(day=date(2026, 12, 1), session=session.key, title=session.title,
                          description=session.description, hard=session.hard, steps=session.steps)


def test_name_prefix_and_date():
    w = pw(easy(c(), 8))
    assert workout_name(w).startswith(PREFIX + "2026-12-01")


def test_interval_payload_structure():
    p = to_garmin(pw(cruise_intervals(c())), 3600)
    assert p["sportType"]["sportTypeKey"] == "running"
    steps = p["workoutSegments"][0]["workoutSteps"]
    assert [s["stepType"]["stepTypeKey"] for s in steps] == ["warmup", "repeat", "cooldown"]
    rep = steps[1]
    assert rep["numberOfIterations"] == rep["endConditionValue"]
    work = rep["workoutSteps"][0]
    assert work["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert work["targetValueOne"] < work["targetValueTwo"]  # slow speed first
    orders = [steps[0]["stepOrder"], rep["stepOrder"], *[s["stepOrder"] for s in rep["workoutSteps"]],
              steps[2]["stepOrder"]]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)


def test_hr_payload():
    p = to_garmin(pw(easy(c("hr"), 8)))
    step = p["workoutSegments"][0]["workoutSteps"][0]
    assert step["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert step["targetValueOne"] < step["targetValueTwo"]


def test_rest_not_uploaded():
    with pytest.raises(ValueError):
        to_garmin(PlannedWorkout(day=date(2026, 12, 1), session="rest", title="Rest"))


def test_payload_validates_against_garminconnect_models():
    workout = pytest.importorskip("garminconnect.workout")
    p = to_garmin(pw(cruise_intervals(c())), 3600)
    workout.RunningWorkout.model_validate(p)
