from pathlib import Path

import pytest
from pydantic import ValidationError

from runplan.config import AthleteConfig, load_config, parse_duration

ROOT = Path(__file__).resolve().parent.parent


def test_placeholder_config_loads():
    cfg = load_config(ROOT / "config" / "athlete.yaml")
    assert cfg.template in {"daniels", "pfitzinger", "hansons", "eighty_twenty"}
    assert cfg.long_run_day in cfg.run_days


def test_parse_duration():
    assert parse_duration("25:00") == 25
    assert parse_duration("1:30:00") == 90


def test_long_run_day_must_be_a_run_day():
    with pytest.raises(ValidationError):
        AthleteConfig(run_days=["mon", "wed", "fri"], long_run_day="sun")


def test_weekly_increase_capped_at_ten_percent():
    with pytest.raises(ValidationError):
        AthleteConfig(max_weekly_increase=0.2)
