"""Turn WeekTargets into seven dated workouts (Monday-Sunday).

Placement rules:
  * long run on the configured long-run day (race on race day in race week)
  * quality sessions on run days that are not next to another hard day (week treated as circular)
  * remaining run days are easy; leftover volume is split evenly across them
  * at least 80% of running time is easy; if not, hard work is scaled down
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from itertools import combinations

from runplan.config import WEEKDAYS, AthleteConfig
from runplan.models import PlannedWorkout, WeekTargets
from runplan.workouts.library import (
    ALL_SESSIONS,
    DISTANCE_SESSIONS,
    Ctx,
    Session,
    easy,
    measure,
    strides,
)

MIN_EASY_KM = 3.0
MAX_HARD_SHARE = 0.20


@dataclass
class PlannedWeek:
    targets: WeekTargets
    workouts: list[PlannedWorkout]
    planned_km: float
    hard_share: float
    notes: list[str] = field(default_factory=list)


def _circ_dist(a: int, b: int) -> int:
    d = abs(a - b) % 7
    return min(d, 7 - d)


def choose_quality_days(run_days: list[int], hard_days: list[int], n: int) -> list[int]:
    """Pick up to n days so no two hard days are adjacent (week treated as circular).

    Tries every combination (at most 7 days) and keeps the one with the most sessions,
    then the widest minimum gap between hard days.
    """
    free = [d for d in run_days if d not in hard_days]
    for k in range(min(n, len(free)), 0, -1):
        best: tuple[int, list[int]] | None = None
        for combo in combinations(free, k):
            all_hard = [*hard_days, *combo]
            gaps = [_circ_dist(a, b) for a, b in combinations(all_hard, 2)]
            if gaps and min(gaps) <= 1:
                continue
            score = min(gaps, default=7)
            if best is None or score > best[0]:
                best = (score, sorted(combo))
        if best:
            return best[1]
    return []


def _build(cfg: AthleteConfig, targets: WeekTargets, ctx: Ctx) -> PlannedWeek:
    notes: list[str] = []
    ws = targets.week_start
    run_days = [WEEKDAYS.index(d) for d in cfg.run_days]

    long_day = WEEKDAYS.index(cfg.long_run_day)
    if targets.long_run_session == "race" and cfg.goal.race_date:
        long_day = (cfg.goal.race_date - ws).days
        if long_day not in run_days:
            run_days = sorted({*run_days, long_day})

    sessions: dict[int, Session] = {}
    sessions[long_day] = DISTANCE_SESSIONS[targets.long_run_session](ctx, targets.long_run_km)

    quality_keys = list(targets.quality_sessions)
    hard_quality = [k for k in quality_keys if k != "strides"]
    soft_quality = [k for k in quality_keys if k == "strides"]

    q_days = choose_quality_days(run_days, [long_day], len(hard_quality))
    if len(q_days) < len(hard_quality):
        dropped = hard_quality[len(q_days):]
        notes.append(f"not enough non-adjacent days; dropped {', '.join(dropped)}")
        hard_quality = hard_quality[: len(q_days)]

    for i, (day, key) in enumerate(zip(q_days, hard_quality, strict=True)):
        if targets.readiness_override and i == 0:
            notes.append(f"readiness override: {key} replaced by an easy run")
            sessions[day] = None  # becomes easy below
        else:
            sessions[day] = ALL_SESSIONS[key](ctx, None)

    easy_days = [d for d in run_days if d not in sessions or sessions[d] is None]
    fixed_km = sum(measure(s.steps, ctx)[0] for s in sessions.values() if s is not None)
    remaining = targets.volume_km - fixed_km

    # Drop easy days until each one is a meaningful run.
    while easy_days and remaining / len(easy_days) < MIN_EASY_KM:
        d = easy_days.pop(0)
        sessions.pop(d, None)
        notes.append(f"{WEEKDAYS[d]} made a rest day (not enough volume for an easy run)")

    per_easy = remaining / len(easy_days) if easy_days else 0
    strides_left = len(soft_quality)
    for d in easy_days:
        if strides_left and _circ_dist(d, long_day) > 1:
            sessions[d] = strides(ctx, per_easy)
            strides_left -= 1
        else:
            sessions[d] = easy(ctx, per_easy)
    if strides_left:
        for d in easy_days:
            if strides_left and sessions[d].key == "easy":
                sessions[d] = strides(ctx, per_easy)
                strides_left -= 1

    workouts: list[PlannedWorkout] = []
    total_km = total_s = hard_s = 0.0
    for d in range(7):
        day = ws + timedelta(days=d)
        s = sessions.get(d)
        if s is None:
            workouts.append(PlannedWorkout(day=day, session="rest", title="Rest", description="Rest or cross-train."))
            continue
        km, t, h = measure(s.steps, ctx)
        total_km, total_s, hard_s = total_km + km, total_s + t, hard_s + h
        workouts.append(PlannedWorkout(
            day=day, session=s.key, title=s.title, description=s.description, hard=s.hard, steps=s.steps,
        ))
    share = hard_s / total_s if total_s else 0.0
    return PlannedWeek(targets, workouts, round(total_km, 1), round(share, 3), notes)


def build_week(cfg: AthleteConfig, targets: WeekTargets, ctx: Ctx) -> PlannedWeek:
    """Build the week, shrinking hard work until at most 20% of running time is hard.

    First scales hard work down (to 40% at most); if that is not enough (very low volume),
    drops quality sessions from the end of the list.
    """
    if targets.week_type == "race":
        return _build(cfg, targets, ctx)
    notes: list[str] = []
    while True:
        for step in range(7):  # scale 1.0, 0.9, ... 0.4
            ctx.scale = round(1.0 - 0.1 * step, 1)
            week = _build(cfg, targets, ctx)
            if week.hard_share <= MAX_HARD_SHARE:
                break
        hard_q = [q for q in targets.quality_sessions if q != "strides"]
        if week.hard_share <= MAX_HARD_SHARE or len(hard_q) <= 1:
            break
        dropped = hard_q[-1]
        targets = targets.model_copy(update={
            "quality_sessions": [q for q in targets.quality_sessions if q != dropped]
        })
        notes.append(f"dropped {dropped}: volume too low for two quality sessions at 80/20")
    if ctx.scale < 1.0:
        notes.append(f"hard work scaled to {ctx.scale:.0%} to keep at least 80% of time easy")
    week.notes.extend(notes)
    return week
