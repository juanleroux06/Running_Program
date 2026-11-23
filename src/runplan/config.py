"""Athlete configuration (config/athlete.yaml)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: list[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TemplateName = Literal["daniels", "pfitzinger", "hansons", "eighty_twenty"]


def parse_duration(text: str) -> float:
    """Parse 'mm:ss' or 'h:mm:ss' into minutes."""
    parts = [float(p) for p in str(text).strip().split(":")]
    if len(parts) == 2:
        m, s = parts
        return m + s / 60
    if len(parts) == 3:
        h, m, s = parts
        return h * 60 + m + s / 60
    raise ValueError(f"Cannot parse duration {text!r}; use mm:ss or h:mm:ss")


class Goal(BaseModel):
    race_distance_km: float = Field(21.0975, gt=0)
    race_date: dt.date | None = None
    plan_start: dt.date | None = None


class RecentResult(BaseModel):
    distance_km: float = Field(gt=0)
    time: str
    date: dt.date | None = None

    @property
    def minutes(self) -> float:
        return parse_duration(self.time)

    @field_validator("time")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        parse_duration(v)
        return v


class AthleteConfig(BaseModel):
    name: str = "Runner"
    goal: Goal = Goal()
    recent_result: RecentResult | None = None
    current_weekly_km: float = Field(30.0, ge=0)
    longest_recent_run_km: float = Field(12.0, ge=0)
    peak_weekly_km: float = Field(60.0, gt=0)
    run_days: list[Weekday] = ["tue", "thu", "sat", "sun"]
    long_run_day: Weekday = "sun"
    hr_max: int | None = Field(None, gt=100, lt=230)
    hr_rest: int | None = Field(None, gt=25, lt=100)
    sex: Literal["male", "female"] = "male"
    template: TemplateName = "eighty_twenty"
    units: Literal["km", "mi"] = "km"
    target_type: Literal["pace", "hr", "none"] = "pace"
    watch: str | None = None
    notes: str = ""
    max_weekly_increase: float = Field(0.10, ge=0, le=0.10)
    down_week_every: int = Field(4, ge=3, le=5)
    down_week_factor: float = Field(0.75, ge=0.6, le=0.9)

    @model_validator(mode="after")
    def _check(self) -> AthleteConfig:
        if len(set(self.run_days)) < 3:
            raise ValueError("run_days needs at least 3 distinct days")
        if self.long_run_day not in self.run_days:
            raise ValueError("long_run_day must be one of run_days")
        self.run_days = sorted(set(self.run_days), key=WEEKDAYS.index)
        return self


def load_config(path: str | Path = "config/athlete.yaml") -> AthleteConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return AthleteConfig.model_validate(data)
