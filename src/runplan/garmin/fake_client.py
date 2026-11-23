"""In-memory Garmin client for tests and dry runs. Never touches the network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from runplan.garmin.client import GarminClient
from runplan.models import Activity, DailyWellness


class FakeGarminClient(GarminClient):
    def __init__(
        self,
        activities: list[Activity] | None = None,
        wellness: list[DailyWellness] | None = None,
    ) -> None:
        self.activities = activities or []
        self.wellness = wellness or []
        self.workouts: dict[str, dict[str, Any]] = {}
        self.schedule: dict[str, date] = {}
        self._next = 1000

    @classmethod
    def from_fixture(cls, path: str | Path) -> FakeGarminClient:
        data = json.loads(Path(path).read_text())
        return cls(
            [Activity.model_validate(a) for a in data.get("activities", [])],
            [DailyWellness.model_validate(w) for w in data.get("wellness", [])],
        )

    def get_activities(self, start: date, end: date) -> list[Activity]:
        return [a for a in self.activities if start <= a.day <= end]

    def get_wellness(self, start: date, end: date) -> list[DailyWellness]:
        return [w for w in self.wellness if start <= w.day <= end]

    def list_workouts(self) -> list[dict[str, Any]]:
        return [{"workoutId": k, "workoutName": v["workoutName"]} for k, v in self.workouts.items()]

    def create_workout(self, payload: dict[str, Any]) -> str:
        self._next += 1
        wid = str(self._next)
        self.workouts[wid] = payload
        return wid

    def schedule_workout(self, workout_id: str, day: date) -> None:
        if workout_id not in self.workouts:
            raise KeyError(workout_id)
        self.schedule[workout_id] = day

    def delete_workout(self, workout_id: str) -> None:
        self.workouts.pop(workout_id, None)
        self.schedule.pop(workout_id, None)
