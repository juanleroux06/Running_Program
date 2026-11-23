from datetime import date, datetime, timedelta

from runplan.config import AthleteConfig
from runplan.garmin.fake_client import FakeGarminClient
from runplan.models import Activity
from runplan.pipeline import load_state, run_week, target_week
from runplan.workouts.garmin_json import PREFIX
from runplan.workouts.library import Ctx, measure

from .conftest import make_runs, make_wellness

MON = date(2026, 11, 30)


def athlete_runs_the_plan(client, result):
    """Simulate the athlete completing every planned workout."""
    c = Ctx(paces=result.paces, zones={i: (0, 0) for i in range(1, 6)}, target_type="none", weekly_km=1)
    for w in result.week.workouts:
        if w.is_rest:
            continue
        km, secs, _ = measure(w.steps, c)
        client.activities.append(Activity(
            activity_id=f"sim-{w.day}", start=datetime.combine(w.day, datetime.min.time()),
            distance_km=km, duration_min=secs / 60, avg_hr=145, max_hr=175,
        ))


def test_target_week():
    assert target_week(date(2026, 11, 30)) == date(2026, 11, 30)  # Monday: this week
    assert target_week(date(2026, 11, 29)) == date(2026, 11, 30)  # Sunday: next Monday


def test_sixteen_week_simulation(tmp_path, cfg):
    client = FakeGarminClient(make_runs(MON - timedelta(days=56), 8, 40), make_wellness(MON - timedelta(days=60), 200))
    state_path = tmp_path / "state.json"
    volumes, types = [], []
    for i in range(16):
        ws = MON + timedelta(days=7 * i)
        res = run_week(cfg, client, ws, state_path=state_path, out_dir=tmp_path / "out", push=True)
        volumes.append(res.week.targets.volume_km)
        types.append(res.week.targets.week_type)
        athlete_runs_the_plan(client, res)
        assert res.md_path.exists() and res.json_path.exists()

    for prev, cur in zip(volumes, volumes[1:], strict=False):
        assert cur <= prev * 1.10 + 0.1 or cur <= max(volumes[: volumes.index(prev) + 1]) * 1.10 + 0.1
    assert types.count("down") >= 3
    assert max(volumes) <= cfg.peak_weekly_km
    assert max(volumes) > volumes[0]

    state = load_state(state_path)
    assert len(state.history) == 16
    assert all(r.actual_km is not None for r in state.history[:-1])


def test_push_is_idempotent(tmp_path, cfg):
    client = FakeGarminClient(make_runs(MON - timedelta(days=56), 8, 40))
    for _ in range(3):
        run_week(cfg, client, MON, state_path=tmp_path / "s.json", out_dir=tmp_path, push=True)
    names = [w["workoutName"] for w in client.list_workouts()]
    assert len(names) == len(set(names))
    assert all(n.startswith(PREFIX) for n in names)
    assert len(client.schedule) == len(names) == 5  # five run days


def test_push_leaves_other_workouts_alone(tmp_path, cfg):
    client = FakeGarminClient()
    mine = client.create_workout({"workoutName": "My own workout"})
    run_week(cfg, client, MON, state_path=tmp_path / "s.json", out_dir=tmp_path, push=True)
    run_week(cfg, client, MON, state_path=tmp_path / "s.json", out_dir=tmp_path, push=True)
    assert mine in client.workouts


def test_dry_run_saves_nothing(tmp_path):
    cfg = AthleteConfig()
    client = FakeGarminClient()
    res = run_week(cfg, client, MON, state_path=tmp_path / "s.json", out_dir=tmp_path, push=False, save=False)
    assert not (tmp_path / "s.json").exists()
    assert client.workouts == {}
    assert res.week.planned_km > 0
