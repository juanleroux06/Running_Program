"""fetch -> analyse -> plan -> generate -> (push) -> save state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from runplan.analysis.compliance import week_compliance
from runplan.analysis.load import estimate_hr_bounds, hr_zones, summarise_load
from runplan.analysis.readiness import assess_readiness
from runplan.analysis.vdot import choose_vdot, fmt_pace, race_time_min, training_paces
from runplan.config import AthleteConfig
from runplan.engine.rules import EngineInputs, monday_of, plan_week
from runplan.engine.templates import load_template
from runplan.engine.week_planner import PlannedWeek, build_week
from runplan.garmin.client import GarminClient
from runplan.models import PlanState, WeekRecord
from runplan.workouts.garmin_json import PREFIX, to_garmin
from runplan.workouts.library import Ctx, measure

TZ = ZoneInfo("Africa/Johannesburg")
HISTORY_DAYS = 84
WELLNESS_DAYS = 35


def target_week(today: date | None = None) -> date:
    """The Monday to plan: today if it is Monday (the scheduled run), else next Monday."""
    today = today or datetime.now(TZ).date()
    return today if today.weekday() == 0 else monday_of(today) + timedelta(days=7)


# ------------------------------------------------------------------ state


def load_state(path: Path) -> PlanState:
    if path.exists():
        return PlanState.model_validate_json(path.read_text())
    return PlanState()


def save_state(state: PlanState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2) + "\n")


# ------------------------------------------------------------------ push


def push_week(client: GarminClient, week: PlannedWeek, ctx: Ctx) -> list[str]:
    """Replace this week's generated workouts on Garmin Connect. Safe to re-run."""
    dates = {(week.targets.week_start + timedelta(days=i)).isoformat() for i in range(7)}
    for w in client.list_workouts():
        name = str(w.get("workoutName", ""))
        if name.startswith(PREFIX) and name[len(PREFIX):len(PREFIX) + 10] in dates:
            client.delete_workout(str(w["workoutId"]))
    ids = []
    for w in week.workouts:
        if w.is_rest:
            continue
        _, secs, _ = measure(w.steps, ctx)
        wid = client.create_workout(to_garmin(w, secs))
        client.schedule_workout(wid, w.day)
        ids.append(wid)
    return ids


# ------------------------------------------------------------------ main pipeline


@dataclass
class RunResult:
    week: PlannedWeek
    vdot: float
    vdot_source: str
    paces: dict[str, tuple[float, float]]
    json_path: Path
    md_path: Path
    pushed_ids: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


def run_week(
    cfg: AthleteConfig,
    client: GarminClient,
    week_start: date,
    state_path: Path = Path("state/plan_state.json"),
    out_dir: Path = Path("out"),
    push: bool = False,
    save: bool = True,
) -> RunResult:
    ws = monday_of(week_start)
    info: list[str] = []

    activities = client.get_activities(ws - timedelta(days=HISTORY_DAYS), ws - timedelta(days=1))
    wellness = client.get_wellness(ws - timedelta(days=WELLNESS_DAYS), ws - timedelta(days=1))
    info.append(f"{len(activities)} runs and {len(wellness)} wellness days read from Garmin")

    est_rest, est_max = estimate_hr_bounds(activities, wellness)
    hr_rest = cfg.hr_rest or est_rest
    hr_max = cfg.hr_max or est_max
    load = summarise_load(activities, ws, hr_rest, hr_max, cfg.sex)

    rr = (cfg.recent_result.distance_km, cfg.recent_result.minutes) if cfg.recent_result else None
    vdot, vdot_src = choose_vdot(rr, activities, wellness)
    paces = training_paces(vdot)
    zones = hr_zones(hr_rest, hr_max)

    state = load_state(state_path)
    template = load_template(cfg.template)
    if state.template and state.template != cfg.template:
        info.append(f"template changed {state.template} -> {cfg.template}")
    state.template = cfg.template
    state.plan_start = state.plan_start or cfg.goal.plan_start or ws

    comp = None
    prev = [r for r in state.history if r.week_start < ws]
    if prev and prev[-1].week_start + timedelta(days=7) <= ws:
        comp = week_compliance(prev[-1], activities)
        prev[-1].actual_km = comp.actual_km
        info.append(f"last week: {comp.actual_km:.1f} of {comp.planned_km:.1f} km ({comp.ratio:.0%})")

    readiness = assess_readiness(wellness, ws)
    targets = plan_week(EngineInputs(
        config=cfg, template=template, state=state, week_start=ws, load=load,
        last_compliance=comp, readiness=readiness, easy_pace_s_per_km=paces["E"][1],
    ))

    race_pace = race_time_min(vdot, cfg.goal.race_distance_km) * 60 / cfg.goal.race_distance_km
    ctx = Ctx(paces=paces, zones=zones, target_type=cfg.target_type, weekly_km=targets.volume_km,
              race_pace_s_per_km=race_pace)
    week = build_week(cfg, targets, ctx)

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"week-{ws.isoformat()}.json"
    md_path = out_dir / f"week-{ws.isoformat()}.md"
    json_path.write_text(json.dumps({
        "targets": targets.model_dump(mode="json"),
        "planned_km": week.planned_km,
        "hard_share": week.hard_share,
        "vdot": vdot,
        "load": load.__dict__ | {"as_of": load.as_of.isoformat()},
        "workouts": [w.model_dump(mode="json") for w in week.workouts],
        "garmin_payloads": [to_garmin(w) for w in week.workouts if not w.is_rest],
    }, indent=2))
    md_path.write_text(render_markdown(cfg, week, vdot, vdot_src, paces, load, info))

    ids: list[str] = []
    if push:
        ids = push_week(client, week, ctx)
        info.append(f"pushed {len(ids)} workouts to Garmin Connect")

    if save:
        state.upsert(WeekRecord(
            week_start=ws, targets=targets, planned_km=week.planned_km,
            pushed=push, garmin_workout_ids=ids,
        ))
        save_state(state, state_path)

    return RunResult(week, vdot, vdot_src, paces, json_path, md_path, ids, info)


def render_markdown(cfg, week: PlannedWeek, vdot, vdot_src, paces, load, info) -> str:
    t = week.targets
    u = cfg.units
    lines = [
        f"# Week of {t.week_start:%a %d %b %Y}",
        "",
        f"**Template:** {cfg.template} · **Phase:** {t.phase} · **Week type:** {t.week_type} "
        f"· **Week #{t.week_index}**",
        "",
        f"**Planned volume:** {week.planned_km:.1f} km (target {t.volume_km:.1f} km) · "
        f"**Long run:** {t.long_run_km:.1f} km · **Hard time:** {week.hard_share:.0%}",
        "",
        "| Day | Session | km |",
        "|---|---|---|",
    ]
    from runplan.workouts.library import Ctx as _Ctx  # local to avoid cycle in type hints

    ctx = _Ctx(paces=paces, zones={i: (0, 0) for i in range(1, 6)}, target_type="none", weekly_km=t.volume_km)
    for w in week.workouts:
        km = measure(w.steps, ctx)[0] if not w.is_rest else 0
        lines.append(f"| {w.day:%a %d %b} | {w.title} | {km:.1f} |" if km else f"| {w.day:%a %d %b} | Rest | – |")
    lines += [
        "",
        f"**VDOT {vdot:g}** ({vdot_src}). Paces: "
        + ", ".join(f"{k} {fmt_pace(f, u)}–{fmt_pace(s, u)}" for k, (f, s) in paces.items()),
        "",
        f"**Load:** last 7 d {load.last7_km:.1f} km, 28-d weekly avg {load.chronic_weekly_km:.1f} km, "
        f"ACWR {load.acwr if load.acwr is not None else 'n/a'}",
        "",
        "**Why:**",
        *[f"- {r}" for r in t.reasons + week.notes + info],
        "",
    ]
    return "\n".join(lines)
