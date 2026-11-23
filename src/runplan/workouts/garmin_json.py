"""Convert PlannedWorkout into Garmin Connect workout JSON.

Shape matches what garminconnect's own workout models produce:
  * step types: warmup 1, cooldown 2, interval 3, recovery 4, rest 5, repeat 6
  * end conditions: lap.button 1, time 2 (s), distance 3 (m), iterations 7
  * targets: no.target 1, heart.rate.zone 4 (bpm low/high), pace.zone 6 (m/s, slow first)
"""

from __future__ import annotations

from typing import Any

from runplan.models import PlannedWorkout, Repeat, Step

PREFIX = "RP | "
RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

STEP_TYPES = {
    "warmup": (1, "warmup"),
    "cooldown": (2, "cooldown"),
    "interval": (3, "interval"),
    "run": (3, "interval"),
    "recovery": (4, "recovery"),
    "rest": (5, "rest"),
}
COND = {
    "lap": {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True},
    "time": {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
    "distance": {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True},
    "iterations": {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False},
}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
HR_TARGET = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
PACE_TARGET = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}


def workout_name(w: PlannedWorkout) -> str:
    return f"{PREFIX}{w.day.isoformat()} | {w.title}"[:80]


def _mps(s_per_km: float) -> float:
    return round(1000 / s_per_km, 4)


def _step(step: Step, order: int) -> dict[str, Any]:
    type_id, type_key = STEP_TYPES[step.kind]
    d: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key, "displayOrder": type_id},
        "targetType": NO_TARGET,
    }
    if step.distance_m is not None:
        d["endCondition"], d["endConditionValue"] = COND["distance"], float(step.distance_m)
    elif step.time_s is not None:
        d["endCondition"], d["endConditionValue"] = COND["time"], float(step.time_s)
    else:
        d["endCondition"] = COND["lap"]
    t = step.target
    if t and t.pace_fast_s_per_km and t.pace_slow_s_per_km:
        d["targetType"] = PACE_TARGET
        d["targetValueOne"] = _mps(t.pace_slow_s_per_km)  # lower speed
        d["targetValueTwo"] = _mps(t.pace_fast_s_per_km)  # higher speed
    elif t and t.hr_low and t.hr_high:
        d["targetType"] = HR_TARGET
        d["targetValueOne"], d["targetValueTwo"] = float(t.hr_low), float(t.hr_high)
    if step.note:
        d["description"] = step.note
    return d


def _steps(items: list[Step | Repeat], counter: list[int]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        counter[0] += 1
        order = counter[0]
        if isinstance(item, Repeat):
            out.append({
                "type": "RepeatGroupDTO",
                "stepOrder": order,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                "numberOfIterations": item.count,
                "endCondition": COND["iterations"],
                "endConditionValue": float(item.count),
                "smartRepeat": False,
                "workoutSteps": _steps(item.steps, counter),
            })
        else:
            out.append(_step(item, order))
    return out


def to_garmin(w: PlannedWorkout, estimated_seconds: float | None = None) -> dict[str, Any]:
    if w.is_rest:
        raise ValueError("rest days are not uploaded")
    payload: dict[str, Any] = {
        "workoutName": workout_name(w),
        "description": w.description[:500],
        "sportType": RUNNING,
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": RUNNING,
            "workoutSteps": _steps(w.steps, [0]),
        }],
    }
    if estimated_seconds:
        payload["estimatedDurationInSecs"] = int(estimated_seconds)
    return payload
