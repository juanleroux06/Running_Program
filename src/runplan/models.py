"""Core data models shared by every part of the generator."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- Garmin data


class Activity(BaseModel):
    """One completed run, normalised from Garmin."""

    activity_id: str
    start: datetime
    distance_km: float = Field(ge=0)
    duration_min: float = Field(ge=0)
    avg_hr: float | None = None
    max_hr: float | None = None
    name: str = ""

    @property
    def day(self) -> date:
        return self.start.date()

    @property
    def pace_min_per_km(self) -> float | None:
        if self.distance_km <= 0:
            return None
        return self.duration_min / self.distance_km


class DailyWellness(BaseModel):
    """One day of recovery signals from Garmin (any field may be missing)."""

    day: date
    resting_hr: float | None = None
    hrv_status: str | None = None  # e.g. BALANCED, UNBALANCED, LOW, POOR
    sleep_score: float | None = None
    vo2max: float | None = None


# ---------------------------------------------------------------- Workouts

StepKind = Literal["warmup", "interval", "recovery", "cooldown", "run", "rest"]
Intensity = Literal["E", "M", "T", "I", "R"]


class Target(BaseModel):
    """A pace range (sec/km, fast..slow) and/or an HR range (bpm, low..high)."""

    intensity: Intensity
    pace_fast_s_per_km: float | None = None
    pace_slow_s_per_km: float | None = None
    hr_low: int | None = None
    hr_high: int | None = None
    hr_zone: int | None = None


class Step(BaseModel):
    kind: StepKind
    distance_m: float | None = None
    time_s: float | None = None
    lap_button: bool = False
    target: Target | None = None
    note: str = ""


class Repeat(BaseModel):
    count: int = Field(ge=1)
    steps: list[Step]


class PlannedWorkout(BaseModel):
    day: date
    session: str  # session key, e.g. "easy", "threshold", "long"
    title: str
    description: str = ""
    hard: bool = False
    steps: list[Step | Repeat] = []

    @property
    def is_rest(self) -> bool:
        return self.session == "rest"


# ---------------------------------------------------------------- Planning


class WeekTargets(BaseModel):
    """What the rules engine decided for the coming week."""

    week_start: date
    week_index: int  # 1-based week number since plan start
    phase: str
    week_type: Literal["build", "down", "repeat", "taper", "race", "hold"]
    volume_km: float
    long_run_km: float
    quality_sessions: list[str]
    long_run_session: str = "long"
    readiness_override: bool = False
    reasons: list[str] = []


class WeekRecord(BaseModel):
    week_start: date
    targets: WeekTargets
    planned_km: float
    actual_km: float | None = None
    pushed: bool = False
    garmin_workout_ids: list[str] = []


class PlanState(BaseModel):
    template: str | None = None
    plan_start: date | None = None
    history: list[WeekRecord] = []

    def last(self) -> WeekRecord | None:
        return self.history[-1] if self.history else None

    def upsert(self, record: WeekRecord) -> None:
        self.history = [r for r in self.history if r.week_start != record.week_start]
        self.history.append(record)
        self.history.sort(key=lambda r: r.week_start)
