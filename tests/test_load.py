import math
from datetime import date

import pytest

from runplan.analysis.load import hr_zones, summarise_load, trimp
from runplan.analysis.readiness import assess_readiness

from .conftest import make_runs, make_wellness


def test_trimp_hand_calculated():
    # HRr = (150-50)/(190-50) = 0.714286 ; TRIMP = 60 * 0.714286 * 0.64 * e^(1.92*0.714286)
    expected = 60 * (100 / 140) * 0.64 * math.exp(1.92 * 100 / 140)
    assert trimp(60, 150, 50, 190) == pytest.approx(expected)
    assert trimp(60, 150, 50, 190, "female") < trimp(60, 150, 50, 190, "male") * 1.5


def test_acwr_steady_is_one():
    start = date(2026, 9, 7)  # Monday
    runs = make_runs(start, 8, 40)
    s = summarise_load(runs, date(2026, 11, 2), 50, 190)
    assert s.acwr == pytest.approx(1.0, abs=0.01)
    assert s.chronic_weekly_km == pytest.approx(40, abs=0.1)
    assert s.last7_km == pytest.approx(40, abs=0.1)


def test_acwr_spike():
    start = date(2026, 9, 7)
    runs = make_runs(start, 7, 20) + make_runs(date(2026, 10, 26), 1, 60)
    s = summarise_load(runs, date(2026, 11, 2), 50, 190)
    assert s.acwr > 1.5


def test_zones_monotonic():
    z = hr_zones(50, 190)
    assert z[1][0] == 120 and z[5][1] == 190
    assert all(z[i][1] == z[i + 1][0] for i in range(1, 5))


def test_readiness_flags_low_hrv():
    w = make_wellness(date(2026, 10, 1), 30) + make_wellness(date(2026, 10, 31), 5, hrv="LOW")
    r = assess_readiness(w, date(2026, 11, 5))
    assert r.compromised and "HRV" in r.reasons[0]
    assert not assess_readiness(make_wellness(date(2026, 10, 1), 35), date(2026, 11, 5)).compromised
