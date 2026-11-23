from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from runplan.analysis.load import hr_zones
from runplan.analysis.vdot import training_paces
from runplan.config import WEEKDAYS, AthleteConfig
from runplan.engine.templates import load_template
from runplan.engine.week_planner import build_week, choose_quality_days
from runplan.models import WeekTargets
from runplan.workouts.library import ALL_SESSIONS, Ctx, measure

MON = date(2026, 11, 30)


def ctx(volume, target_type="pace", vdot=45):
    return Ctx(paces=training_paces(vdot), zones=hr_zones(50, 190), target_type=target_type, weekly_km=volume)


def targets(volume, quality, long_km=None, long_session="long", override=False):
    return WeekTargets(week_start=MON, week_index=2, phase="x", week_type="build", volume_km=volume,
                       long_run_km=long_km or round(volume * 0.3, 1), quality_sessions=quality,
                       long_run_session=long_session, readiness_override=override)


def hard_days(week):
    return [w.day.weekday() for w in week.workouts if w.hard]


def assert_no_back_to_back_hard(week):
    days = sorted(hard_days(week))
    for a, b in zip(days, days[1:], strict=False):
        assert b - a > 1, f"hard days {days}"


@pytest.mark.parametrize("name", ["daniels", "pfitzinger", "hansons", "eighty_twenty"])
@pytest.mark.parametrize("volume", [25, 50, 90])
def test_every_template_phase_builds_a_sane_week(cfg, name, volume):
    tpl = load_template(name)
    for phase in tpl.phases:
        t = targets(volume, phase.quality[:2], long_session=phase.long)
        week = build_week(cfg, t, ctx(volume))
        assert len(week.workouts) == 7
        assert_no_back_to_back_hard(week)
        assert week.planned_km == pytest.approx(volume, rel=0.15)
        assert week.hard_share <= 0.25


def test_quality_days_not_adjacent():
    days = choose_quality_days([1, 2, 3, 5, 6], [6], 2)
    assert len(days) == 2
    for d in days:
        assert all(min(abs(d - h) % 7, 7 - abs(d - h) % 7) > 1 for h in [6, *[x for x in days if x != d]])


def test_readiness_override_makes_first_quality_easy(cfg):
    week = build_week(cfg, targets(50, ["threshold", "vo2_intervals"], override=True), ctx(50))
    keys = [w.session for w in week.workouts]
    assert "threshold" not in keys and "vo2_intervals" in keys


def test_three_day_runner_gets_rest_days():
    c = AthleteConfig(run_days=["tue", "thu", "sun"], long_run_day="sun")
    week = build_week(c, targets(20, ["fartlek"]), ctx(20))
    assert sum(w.is_rest for w in week.workouts) == 4


def test_hr_targets(cfg):
    week = build_week(cfg, targets(40, ["threshold"]), ctx(40, "hr"))
    t = next(w for w in week.workouts if w.session == "threshold")
    interval = t.steps[1]
    assert interval.target.hr_low and interval.target.pace_fast_s_per_km is None


def test_all_sessions_build():
    c = ctx(50)
    for key, fn in ALL_SESSIONS.items():
        s = fn(c, 10.0)
        km, secs, hard = measure(s.steps, c)
        assert km > 0 and secs > 0 and hard <= secs, key


@settings(max_examples=60, deadline=None)
@given(
    volume=st.floats(15, 120),
    days=st.sets(st.sampled_from(range(7)), min_size=3, max_size=7),
    vdot=st.floats(30, 70),
)
def test_property_guardrails_hold(volume, days, vdot):
    run_days = [WEEKDAYS[d] for d in sorted(days)]
    c = AthleteConfig(run_days=run_days, long_run_day=run_days[-1])
    quality = ["threshold", "vo2_intervals"] if len(days) > 3 else ["cruise_intervals"]
    week = build_week(c, targets(round(volume, 1), quality), ctx(volume, vdot=vdot))
    assert_no_back_to_back_hard(week)
    for w in week.workouts:
        if not w.is_rest:
            assert w.day.weekday() in days
