from datetime import date, timedelta

import pytest

from runplan.analysis.compliance import Compliance
from runplan.analysis.load import LoadSummary
from runplan.analysis.readiness import Readiness
from runplan.engine.rules import EngineInputs, plan_week
from runplan.engine.templates import available_templates, load_template
from runplan.models import PlanState, WeekRecord, WeekTargets

MON = date(2026, 11, 30)


def record(ws, volume, week_type="build", long_km=12.0):
    t = WeekTargets(week_start=ws, week_index=1, phase="x", week_type=week_type, volume_km=volume,
                    long_run_km=long_km, quality_sessions=[])
    return WeekRecord(week_start=ws, targets=t, planned_km=volume)


def load(acwr=1.0, km=40.0):
    return LoadSummary(MON, km, km * 4, km, 100, 100, acwr, None, 14, 4)


def inputs(cfg, state=None, **kw):
    return EngineInputs(config=cfg, template=load_template(cfg.template), state=state or PlanState(),
                        week_start=kw.pop("week_start", MON), **kw)


def state_with(*records, start=None):
    return PlanState(plan_start=start or records[0].week_start, history=list(records))


def test_all_templates_valid():
    assert set(available_templates()) == {"daniels", "pfitzinger", "hansons", "eighty_twenty"}


def test_first_week_holds(cfg):
    t = plan_week(inputs(cfg))
    assert t.week_type == "hold" and t.volume_km == 40


def test_build_capped_at_ten_percent(cfg):
    st = state_with(record(MON - timedelta(days=7), 40))
    t = plan_week(inputs(cfg, st, load=load(), last_compliance=Compliance(MON, 40, 40, 1.0)))
    assert t.week_type == "build"
    assert t.volume_km <= 40 * 1.10 + 1e-9


def test_peak_cap(cfg):
    st = state_with(record(MON - timedelta(days=7), 69))
    t = plan_week(inputs(cfg, st, last_compliance=Compliance(MON, 69, 69, 1.0)))
    assert t.volume_km <= cfg.peak_weekly_km


def test_down_week_every_fourth(cfg):
    start = MON - timedelta(days=21)
    st = state_with(*[record(start + timedelta(days=7 * i), 40 + i) for i in range(3)], start=start)
    t = plan_week(inputs(cfg, st, last_compliance=Compliance(MON, 42, 42, 1.0)))
    assert t.week_index == 4 and t.week_type == "down"
    assert t.volume_km == pytest.approx(42 * cfg.down_week_factor, abs=0.1)


def test_after_down_week_builds_from_pre_down_volume(cfg):
    start = MON - timedelta(days=28)
    recs = [record(start + timedelta(days=7 * i), v) for i, v in enumerate([40, 42, 44])]
    recs.append(record(start + timedelta(days=21), 33, "down"))
    t = plan_week(inputs(cfg, state_with(*recs, start=start), last_compliance=Compliance(MON, 33, 33, 1)))
    assert t.week_type == "build" and t.volume_km == pytest.approx(44 * 1.1, abs=0.1)


def test_low_compliance_repeats(cfg):
    st = state_with(record(MON - timedelta(days=7), 40))
    t = plan_week(inputs(cfg, st, last_compliance=Compliance(MON, 40, 15, 0.375)))
    assert t.week_type == "repeat" and t.volume_km == 40


def test_partial_compliance_holds(cfg):
    st = state_with(record(MON - timedelta(days=7), 40))
    t = plan_week(inputs(cfg, st, last_compliance=Compliance(MON, 40, 28, 0.7)))
    assert t.week_type == "hold" and t.volume_km == 40


def test_acwr_danger_forces_down(cfg):
    st = state_with(record(MON - timedelta(days=7), 40))
    t = plan_week(inputs(cfg, st, load=load(acwr=1.6), last_compliance=Compliance(MON, 40, 40, 1)))
    assert t.week_type == "down"


def test_acwr_caution_holds_and_drops_quality(cfg):
    st = state_with(record(MON - timedelta(days=7), 40))
    normal = plan_week(inputs(cfg, st, load=load(), last_compliance=Compliance(MON, 40, 40, 1)))
    t = plan_week(inputs(cfg, st, load=load(acwr=1.4), last_compliance=Compliance(MON, 40, 40, 1)))
    assert t.volume_km == 40
    assert len(t.quality_sessions) == len(normal.quality_sessions) - 1


def test_long_run_share_and_growth(cfg):
    st = state_with(record(MON - timedelta(days=7), 60, long_km=12))
    t = plan_week(inputs(cfg, st, last_compliance=Compliance(MON, 60, 60, 1)))
    assert t.long_run_km <= 0.30 * t.volume_km + 1e-9
    assert t.long_run_km <= 12 + 2.0


def test_hansons_long_run_cap(cfg):
    cfg.template = "hansons"
    cfg.peak_weekly_km = 150
    st = state_with(record(MON - timedelta(days=7), 120, long_km=30))
    t = plan_week(inputs(cfg, st, last_compliance=Compliance(MON, 120, 120, 1)))
    assert t.long_run_km <= 26


def test_readiness_flag_passed_through(cfg):
    t = plan_week(inputs(cfg, readiness=Readiness(True, ["HRV low"])))
    assert t.readiness_override


def test_race_mode_phases_taper_and_race(cfg):
    race = MON + timedelta(days=7 * 12 + 6)  # Sunday of week 13
    cfg.goal.race_date = race
    st = PlanState(plan_start=MON)
    phases = []
    for i in range(13):
        ws = MON + timedelta(days=7 * i)
        t = plan_week(inputs(cfg, st, week_start=ws))
        phases.append((t.phase, t.week_type))
        st.upsert(record(ws, t.volume_km, t.week_type, t.long_run_km))
        st.history[-1].targets = t
    assert phases[0][0] == "foundation"
    assert phases[-1] == ("race", "race")
    assert phases[-2][1] == "taper" and phases[-3][1] == "taper"
    final = plan_week(inputs(cfg, st, week_start=MON + timedelta(days=7 * 12)))
    assert final.long_run_session == "race" and final.long_run_km == pytest.approx(cfg.goal.race_distance_km, abs=0.1)
