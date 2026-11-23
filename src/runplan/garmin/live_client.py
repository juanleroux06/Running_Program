"""Garmin Connect client built on the unofficial `garminconnect` library (pinned in pyproject).

Authentication uses saved tokens only. Create them once with `runplan garmin-login`,
then provide them through the GARMIN_TOKENS environment variable (the token JSON itself,
or a path to the token folder). This module never sees your password.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any

from runplan.garmin.client import GarminClient
from runplan.models import Activity, DailyWellness

log = logging.getLogger(__name__)

TOKEN_ENV = "GARMIN_TOKENS"
RUN_TYPES = ("running", "treadmill_running", "trail_running", "track_running", "street_running")


class GarminAuthError(RuntimeError):
    pass


def _dig(d: Any, *path: Any) -> Any:
    for p in path:
        if d is None:
            return None
        try:
            d = d[p]
        except (KeyError, IndexError, TypeError):
            return None
    return d


class LiveGarminClient(GarminClient):
    def __init__(self, tokens: str | None = None, delay_s: float = 0.4) -> None:
        from garminconnect import Garmin  # imported lazily so tests never need network libs

        tokens = tokens or os.getenv(TOKEN_ENV)
        if not tokens:
            raise GarminAuthError(
                f"No Garmin tokens. Run `runplan garmin-login` once and set {TOKEN_ENV}."
            )
        self.api = Garmin()
        try:
            self.api.login(tokenstore=tokens)
        except Exception as e:  # library raises several auth error types
            raise GarminAuthError(
                f"Garmin login with saved tokens failed ({type(e).__name__}). "
                "Tokens may have expired: run `runplan garmin-login` again and update the secret."
            ) from e
        self.delay_s = delay_s

    def _pause(self) -> None:
        time.sleep(self.delay_s)

    # ------------------------------------------------------------------ reads

    def get_activities(self, start: date, end: date) -> list[Activity]:
        raw = self.api.get_activities_by_date(start.isoformat(), end.isoformat())
        out = []
        for a in raw or []:
            type_key = _dig(a, "activityType", "typeKey") or ""
            if type_key not in RUN_TYPES:
                continue
            try:
                out.append(Activity(
                    activity_id=str(a["activityId"]),
                    start=datetime.fromisoformat(a["startTimeLocal"].replace(" ", "T")),
                    distance_km=(a.get("distance") or 0) / 1000,
                    duration_min=(a.get("duration") or 0) / 60,
                    avg_hr=a.get("averageHR"),
                    max_hr=a.get("maxHR"),
                    name=a.get("activityName") or "",
                ))
            except (KeyError, ValueError) as e:
                log.warning("Skipping activity with unexpected shape: %s", e)
        return out

    def get_wellness(self, start: date, end: date) -> list[DailyWellness]:
        """Resting HR for every day; HRV and sleep for the last 7 days; VO2max once."""
        out = []
        day = start
        detail_from = end - timedelta(days=7)
        while day <= end:
            ds = day.isoformat()
            w = DailyWellness(day=day)
            try:
                rhr = self.api.get_rhr_day(ds)
                w.resting_hr = _dig(rhr, "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", 0, "value")
                self._pause()
                if day >= detail_from:
                    hrv = self.api.get_hrv_data(ds)
                    w.hrv_status = _dig(hrv, "hrvSummary", "status")
                    self._pause()
                    sleep = self.api.get_sleep_data(ds)
                    w.sleep_score = _dig(sleep, "dailySleepDTO", "sleepScores", "overall", "value")
                    self._pause()
                if day == end:
                    mm = self.api.get_max_metrics(ds)
                    w.vo2max = _dig(mm, 0, "generic", "vo2MaxPreciseValue") or _dig(mm, 0, "generic", "vo2MaxValue")
            except Exception as e:  # missing days are normal; keep going
                log.info("Wellness for %s incomplete: %s", ds, type(e).__name__)
            out.append(w)
            day += timedelta(days=1)
        return out

    # ------------------------------------------------------------------ writes

    def list_workouts(self) -> list[dict[str, Any]]:
        return self.api.get_workouts(0, 500) or []

    def create_workout(self, payload: dict[str, Any]) -> str:
        res = self.api.upload_workout(payload)
        self._pause()
        return str(res["workoutId"])

    def schedule_workout(self, workout_id: str, day: date) -> None:
        self.api.schedule_workout(workout_id, day.isoformat())
        self._pause()

    def delete_workout(self, workout_id: str) -> None:
        self.api.delete_workout(workout_id)
        self._pause()


def interactive_login(token_dir: str = "~/.garminconnect") -> str:
    """One-off login with email/password (+ MFA). Saves tokens and returns the token JSON."""
    import getpass

    from garminconnect import Garmin

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password (not stored): ")
    api = Garmin(email=email, password=password, prompt_mfa=lambda: input("MFA code: ").strip())
    api.login()
    path = os.path.expanduser(token_dir)
    api.client.dump(path)
    return api.client.dumps()
