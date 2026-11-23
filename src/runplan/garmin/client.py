"""The only interface the rest of the code uses to talk to Garmin."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from runplan.models import Activity, DailyWellness


class GarminClient(ABC):
    @abstractmethod
    def get_activities(self, start: date, end: date) -> list[Activity]:
        """Completed runs between start and end (inclusive)."""

    @abstractmethod
    def get_wellness(self, start: date, end: date) -> list[DailyWellness]:
        """Daily resting HR / HRV / sleep / VO2max between start and end (inclusive)."""

    @abstractmethod
    def list_workouts(self) -> list[dict[str, Any]]:
        """Workouts in the library: each dict has at least workoutId and workoutName."""

    @abstractmethod
    def create_workout(self, payload: dict[str, Any]) -> str:
        """Upload a workout, return its id."""

    @abstractmethod
    def schedule_workout(self, workout_id: str, day: date) -> None:
        """Put a workout on the calendar on `day`."""

    @abstractmethod
    def delete_workout(self, workout_id: str) -> None:
        """Delete a workout (and its calendar entries)."""
