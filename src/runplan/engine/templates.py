"""Program templates (src/runplan/programs/*.yaml)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

PROGRAMS_DIR = Path(__file__).resolve().parent.parent / "programs"


class PhaseSpec(BaseModel):
    name: str
    share: float = Field(gt=0, le=1)
    quality: list[str]
    long: str = "long"


class ProgramTemplate(BaseModel):
    name: str
    description: str = ""
    long_run_share: float = Field(0.30, gt=0.1, le=0.35)
    long_run_cap_km: float = Field(32, gt=5)
    taper_weeks: int = Field(2, ge=1, le=3)
    maintenance_phase: str
    phases: list[PhaseSpec]

    @model_validator(mode="after")
    def _check(self) -> ProgramTemplate:
        total = sum(p.share for p in self.phases)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"{self.name}: phase shares must sum to 1 (got {total})")
        if self.maintenance_phase not in {p.name for p in self.phases}:
            raise ValueError(f"{self.name}: maintenance_phase not among phases")
        return self

    def phase(self, name: str) -> PhaseSpec:
        return next(p for p in self.phases if p.name == name)

    def phase_for(self, build_week: int, build_weeks: int) -> PhaseSpec:
        """Which phase a (0-based) build week falls in, splitting build_weeks by share."""
        if build_weeks <= 0:
            return self.phases[-1]
        pos = (build_week + 0.5) / build_weeks
        acc = 0.0
        for p in self.phases:
            acc += p.share
            if pos <= acc + 1e-9:
                return p
        return self.phases[-1]


@cache
def load_template(name: str) -> ProgramTemplate:
    path = PROGRAMS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No program template named {name!r} in {PROGRAMS_DIR}")
    return ProgramTemplate.model_validate(yaml.safe_load(path.read_text()))


def available_templates() -> list[str]:
    return sorted(p.stem for p in PROGRAMS_DIR.glob("*.yaml"))
