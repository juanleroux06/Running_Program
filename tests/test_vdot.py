import math

import pytest

from runplan.analysis.vdot import (
    choose_vdot,
    fraction_sustainable,
    race_time_min,
    training_paces,
    vdot_from_performance,
    velocity_for_vo2,
    vo2_at_velocity,
)


def test_5k_in_20_minutes_hand_calculated():
    # v = 5000 / 20 = 250 m/min
    # VO2 = -4.60 + 0.182258*250 + 0.000104*250^2 = 47.4645
    # %max = 0.8 + 0.1894393 e^(-0.25556) + 0.2989558 e^(-3.86521) = 0.95298
    assert vo2_at_velocity(250) == pytest.approx(47.4645, abs=1e-4)
    assert fraction_sustainable(20) == pytest.approx(0.95298, abs=1e-4)
    assert vdot_from_performance(5, 20) == pytest.approx(49.81, abs=0.01)


def test_velocity_inverse_roundtrip():
    for v in (150, 200, 250, 320):
        assert velocity_for_vo2(vo2_at_velocity(v)) == pytest.approx(v, rel=1e-9)


def test_race_time_inverse():
    assert race_time_min(vdot_from_performance(10, 45), 10) == pytest.approx(45, abs=0.01)


def test_paces_ordered_fast_to_slow():
    p = training_paces(50)
    order = ["R", "I", "T", "M", "E"]
    for faster, slower in zip(order, order[1:], strict=False):
        assert p[faster][0] < p[slower][0]
    for fast, slow in p.values():
        assert fast < slow
    # VDOT 50 threshold pace is about 4:15/km
    assert 245 <= p["T"][0] <= 260


def test_choose_vdot_rounds_down_and_prefers_config():
    v, src = choose_vdot((5, 20), [], [])
    assert v == 49.5 and "config" in src
    v, src = choose_vdot(None, [], [])
    assert v == 35.0 and "default" in src
    assert math.isfinite(v)
