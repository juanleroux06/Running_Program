"""Rules engine: decide next week's volume, long run, phase and quality sessions.

Guardrails (docs/PLAN.md section 3.3):
  * weekly volume  V(w+1) <= (1 + max_weekly_increase) * V(w),  max_weekly_increase <= 10%
  * every `down_week_every`-th week is a recovery week at `down_week_factor` of the reference
  * long run <= long_run_share of V (35% for low volume), <= template cap, <= 150 min at easy pace
  * compliance < 50% last week  -> repeat last week
  * ACWR > 1.5 -> forced down week; 1.3-1.5 -> hold volume and drop one quality session
  * readiness compromised -> first quality session becomes easy (applied by the week planner)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from runplan.analysis.compliance import Compliance
from runplan.analysis.load import LoadSummary
from runplan.analysis.readiness import Readiness
from runplan.config import AthleteConfig
from runplan.engine.templates import ProgramTemplate
from runplan.models import PlanState, WeekRecord, WeekTargets

MIN_WEEKLY_KM = 8.0
LONG_RUN_MAX_MIN = 150.0
TAPER_FACTORS = {3: 0.90, 2: 0.80, 1: 0.70}
RACE_WEEK_OTHER_FACTOR = 0.30


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


@dataclass
class EngineInputs:
    config: AthleteConfig
    template: ProgramTemplate
    state: PlanState
    week_start: date
    load: LoadSummary | None = None
    last_compliance: Compliance | None = None
    readiness: Readiness | None = None
    easy_pace_s_per_km: float = 360.0


def _previous(state: PlanState, week_start: date) -> WeekRecord | None:
    prev = [r for r in state.history if r.week_start < week_start]
    if not prev:
        return None
    last = prev[-1]
    # A gap of more than two weeks means we restart from what the data says.
    return last if (week_start - last.week_start).days <= 14 else None


def _reference_volume(inp: EngineInputs, prev: WeekRecord | None) -> tuple[float, str]:
    """The 'normal' volume the coming week is built from."""
    if prev is not None:
        if prev.targets.week_type in ("down", "taper", "race"):
            builds = [
                r.targets.volume_km
                for r in inp.state.history
                if r.week_start < prev.week_start and r.targets.week_type in ("build", "hold", "repeat")
            ]
            if builds:
                return builds[-1], "last normal week before the recovery week"
        return prev.targets.volume_km, "last week's planned volume"
    if inp.load and inp.load.last28_km > 0:
        return max(inp.load.chronic_weekly_km, inp.load.last7_km), "recent Garmin volume"
    return inp.config.current_weekly_km, "current_weekly_km in config"


def _peak_volume(state: PlanState, fallback: float) -> float:
    vols = [r.targets.volume_km for r in state.history if r.targets.week_type in ("build", "hold")]
    return max(vols, default=fallback)


def plan_week(inp: EngineInputs) -> WeekTargets:
    cfg, tpl, state = inp.config, inp.template, inp.state
    ws = monday_of(inp.week_start)
    reasons: list[str] = []

    plan_start = state.plan_start or cfg.goal.plan_start or ws
    plan_start = monday_of(plan_start)
    week_index = max(1, (ws - plan_start).days // 7 + 1)

    prev = _previous(state, ws)
    ref, ref_src = _reference_volume(inp, prev)
    ref = max(MIN_WEEKLY_KM, min(ref, cfg.peak_weekly_km))
    reasons.append(f"reference volume {ref:.1f} km from {ref_src}")
    cap = ref * (1 + cfg.max_weekly_increase)

    n_quality = 1 if len(cfg.run_days) <= 3 else 2

    # ---------------------------------------------------------- phase / week type
    race_date = cfg.goal.race_date
    week_type = "build"
    phase_name: str
    race_mode = False
    if race_date:
        race_ws = monday_of(race_date)
        weeks_to_race = (race_ws - ws).days // 7
        if weeks_to_race >= 0:
            race_mode = True
        elif weeks_to_race >= -1:
            reasons.append("week after the race: recovery")
        else:
            reasons.append("race date has passed: rolling maintenance mode")

    if race_mode:
        if weeks_to_race == 0:
            week_type, phase_name = "race", "race"
        elif weeks_to_race <= tpl.taper_weeks:
            week_type, phase_name = "taper", "taper"
        else:
            build_weeks = max(1, (race_ws - plan_start).days // 7 - tpl.taper_weeks)
            phase_name = tpl.phase_for(week_index - 1, build_weeks).name
    else:
        phase_name = tpl.maintenance_phase
        if race_date and -1 <= (monday_of(race_date) - ws).days // 7 < 0:
            week_type = "down"

    phase = tpl.phase(phase_name) if phase_name not in ("taper", "race") else tpl.phases[-1]

    # ---------------------------------------------------------- volume
    comp = inp.last_compliance
    if week_type == "race":
        peak = _peak_volume(state, ref)
        volume = cfg.goal.race_distance_km + RACE_WEEK_OTHER_FACTOR * peak
        reasons.append("race week: short sharpening run plus the race")
    elif week_type == "taper":
        peak = _peak_volume(state, ref)
        factor = TAPER_FACTORS.get(weeks_to_race, 0.7)
        volume = factor * peak
        reasons.append(f"taper: {factor:.0%} of peak {peak:.1f} km")
    elif week_type == "down":
        volume = ref * 0.6
    elif prev is None:
        week_type, volume = "hold", ref
        reasons.append("first week: hold at current volume")
    elif comp is not None and comp.ratio < 0.5:
        week_type, volume = "repeat", prev.targets.volume_km
        reasons.append(f"only {comp.ratio:.0%} of last week was run: repeating it")
    elif week_index % cfg.down_week_every == 0:
        week_type, volume = "down", ref * cfg.down_week_factor
        reasons.append(f"recovery week (every {cfg.down_week_every} weeks)")
    elif comp is not None and comp.ratio < 0.8:
        week_type, volume = "hold", ref
        reasons.append(f"{comp.ratio:.0%} of last week was run: holding volume")
    else:
        volume = ref * (1 + cfg.max_weekly_increase)

    # ---------------------------------------------------------- ACWR
    drop_quality = 0
    load = inp.load
    if load and load.acwr is not None and load.last28_km > 0 and week_type in ("build", "hold", "repeat"):
        if load.acwr > 1.5:
            week_type, volume = "down", ref * cfg.down_week_factor
            reasons.append(f"ACWR {load.acwr:.2f} > 1.5: forced recovery week")
        elif load.acwr > 1.3:
            if volume > ref:
                week_type, volume = "hold", ref
            drop_quality = 1
            reasons.append(f"ACWR {load.acwr:.2f} in 1.3-1.5: hold volume, one less quality session")

    # ---------------------------------------------------------- hard caps
    if week_type != "race":
        volume = min(volume, cap, cfg.peak_weekly_km)
    volume = round(max(MIN_WEEKLY_KM, volume), 1)

    # ---------------------------------------------------------- quality sessions
    if week_type == "race":
        quality = ["race_tune"]
    else:
        quality = list(phase.quality[:n_quality])
        if week_type in ("down", "taper") and len(quality) > 1:
            quality = quality[:1]
        if drop_quality and len(quality) > 1:
            quality = quality[:-1]
        elif drop_quality:
            quality = ["strides"]

    # ---------------------------------------------------------- long run
    if week_type == "race":
        long_km = cfg.goal.race_distance_km
        long_session = "race"
    else:
        share = tpl.long_run_share if volume >= 40 else min(0.35, tpl.long_run_share + 0.05)
        long_km = share * volume
        time_cap_km = LONG_RUN_MAX_MIN * 60 / inp.easy_pace_s_per_km
        long_km = min(long_km, tpl.long_run_cap_km, time_cap_km)
        prev_long = (
            prev.targets.long_run_km
            if prev and prev.targets.long_run_session != "race"
            else (load.longest_run_km_28d if load and load.longest_run_km_28d else cfg.longest_recent_run_km)
        )
        if prev_long > 0:
            long_km = min(long_km, prev_long + 2.0)
        long_km = max(long_km, min(5.0, 0.4 * volume))
        long_session = phase.long if week_type in ("build", "hold") else "long"

    readiness_override = bool(inp.readiness and inp.readiness.compromised)
    if readiness_override:
        reasons.append("readiness low (" + "; ".join(inp.readiness.reasons) + "): first quality session made easy")

    return WeekTargets(
        week_start=ws,
        week_index=week_index,
        phase=phase_name,
        week_type=week_type,
        volume_km=volume,
        long_run_km=round(long_km, 1),
        quality_sessions=quality,
        long_run_session=long_session,
        readiness_override=readiness_override,
        reasons=reasons,
    )
