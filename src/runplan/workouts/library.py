"""Session library: turns a session key into structured workout steps.

Work volume per session follows Daniels-style limits on share of weekly volume V:
threshold work <= 10% of V, interval work <= 8% of V (max 10 km), repetition work <= 5% of V (max 8 km).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from runplan.models import Intensity, Repeat, Step, Target

ZONE_FOR = {"E": 2, "M": 3, "T": 4, "I": 5, "R": 5}
HARD_INTENSITIES = {"M", "T", "I", "R"}


@dataclass
class Ctx:
    """Everything a session builder needs."""

    paces: dict[str, tuple[float, float]]  # intensity -> (fast, slow) sec/km
    zones: dict[int, tuple[int, int]]
    target_type: str  # pace | hr | none
    weekly_km: float
    scale: float = 1.0  # < 1 shrinks the hard work (used to respect 80/20)
    race_pace_s_per_km: float | None = None

    def target(self, intensity: Intensity) -> Target | None:
        if self.target_type == "none":
            return None
        fast, slow = self.paces[intensity]
        lo, hi = self.zones[ZONE_FOR[intensity]]
        t = Target(intensity=intensity, hr_zone=ZONE_FOR[intensity])
        if self.target_type == "pace":
            t.pace_fast_s_per_km, t.pace_slow_s_per_km = round(fast), round(slow)
        else:
            t.hr_low, t.hr_high = lo, hi
        return t

    def mid_pace(self, intensity: str) -> float:
        fast, slow = self.paces[intensity]
        return (fast + slow) / 2

    def wu_km(self) -> float:
        return 1.5 if self.weekly_km < 25 else 2.0


@dataclass
class Session:
    key: str
    title: str
    hard: bool
    steps: list[Step | Repeat]
    description: str = ""


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _n(x: float, lo: int, hi: int) -> int:
    return int(_clamp(round(x), lo, hi))


def _run(kind: str, km: float, ctx: Ctx, intensity: Intensity = "E", note: str = "") -> Step:
    return Step(kind=kind, distance_m=round(km * 1000), target=ctx.target(intensity), note=note)


def _jog(seconds: float) -> Step:
    return Step(kind="recovery", time_s=seconds, note="easy jog")


def _wu_cd(ctx: Ctx, main: list[Step | Repeat]) -> list[Step | Repeat]:
    w = ctx.wu_km()
    return [_run("warmup", w, ctx), *main, _run("cooldown", w, ctx)]


# ------------------------------------------------------------------ easy-type sessions


def easy(ctx: Ctx, km: float) -> Session:
    return Session("easy", f"Easy {km:.0f} km", False, [_run("run", km, ctx)], "Conversational effort.")


def strides(ctx: Ctx, km: float) -> Session:
    reps = Repeat(count=6, steps=[
        Step(kind="interval", time_s=20, target=ctx.target("R"), note="stride: fast, relaxed"),
        _jog(60),
    ])
    base = max(1.0, km - 0.8)
    return Session(
        "strides", f"Easy {km:.0f} km + strides", False,
        [_run("run", base, ctx), reps],
        "Easy run finishing with 6 relaxed 20-second strides.",
    )


def long(ctx: Ctx, km: float) -> Session:
    return Session("long", f"Long run {km:.0f} km", True, [_run("run", km, ctx)], "Steady and easy.")


def long_fast_finish(ctx: Ctx, km: float) -> Session:
    ff = round(min(0.2 * km, 5.0) * ctx.scale, 1)
    if ff < 1:
        return long(ctx, km)
    return Session(
        "long_fast_finish", f"Long run {km:.0f} km, fast finish", True,
        [_run("run", km - ff, ctx), _run("interval", ff, ctx, "M", "finish at marathon effort")],
        f"Easy, then the last {ff:g} km at marathon effort.",
    )


def long_mp(ctx: Ctx, km: float) -> Session:
    mp = round(min(0.35 * km, 16.0) * ctx.scale, 1)
    if mp < 2 or km < 10:
        return long(ctx, km)
    wu = 3.0
    rest = max(1.0, km - wu - mp)
    return Session(
        "long_mp", f"Long run {km:.0f} km with {mp:g} km at MP", True,
        [_run("warmup", wu, ctx), _run("interval", mp, ctx, "M"), _run("cooldown", rest, ctx)],
        "Long run with a marathon-pace block in the middle.",
    )


def medium_long(ctx: Ctx, km: float | None = None) -> Session:
    km = _clamp(0.18 * ctx.weekly_km, 8, 24)
    return Session("medium_long", f"Medium-long {km:.0f} km", True, [_run("run", km, ctx)],
                   "Aerobic endurance at easy-to-steady effort.")


def race(ctx: Ctx, km: float) -> Session:
    step = Step(kind="run", distance_m=round(km * 1000), note="race")
    if ctx.race_pace_s_per_km and ctx.target_type == "pace":
        p = ctx.race_pace_s_per_km
        step.target = Target(intensity="M", pace_fast_s_per_km=round(p - 5), pace_slow_s_per_km=round(p + 5))
    return Session("race", f"RACE {km:g} km", True, [step], "Race day. Good luck!")


# ------------------------------------------------------------------ quality sessions


def threshold(ctx: Ctx, _km: float | None = None) -> Session:
    t = round(_clamp(0.10 * ctx.weekly_km * ctx.scale, 2, 10), 1)
    return Session("threshold", f"Threshold {t:g} km", True,
                   _wu_cd(ctx, [_run("interval", t, ctx, "T", "comfortably hard")]),
                   "Continuous tempo at threshold pace.")


def _reps_session(key, title, ctx, n, rep_km, intensity, rec_s, note, desc) -> Session:
    main = Repeat(count=n, steps=[_run("interval", rep_km, ctx, intensity, note), _jog(rec_s)])
    return Session(key, title.format(n=n, d=_fmt_d(rep_km)), True, _wu_cd(ctx, [main]), desc)


def _fmt_d(km: float) -> str:
    return f"{km * 1000:.0f} m" if km < 1 else f"{km:g} km"


def cruise_intervals(ctx: Ctx, _km=None) -> Session:
    n = _n(0.10 * ctx.weekly_km * ctx.scale / 1.6, 2, 6)
    return _reps_session("cruise_intervals", "Cruise intervals {n} x {d}", ctx, n, 1.6, "T", 60,
                         "threshold", "Threshold repeats with short jog recoveries.")


def lt_intervals(ctx: Ctx, _km=None) -> Session:
    n = _n(0.10 * ctx.weekly_km * ctx.scale / 2.0, 2, 5)
    return _reps_session("lt_intervals", "LT intervals {n} x {d}", ctx, n, 2.0, "T", 120,
                         "threshold", "Lactate-threshold repeats.")


def vo2_intervals(ctx: Ctx, _km=None) -> Session:
    n = _n(min(0.08 * ctx.weekly_km, 10) * ctx.scale / 1.0, 3, 8)
    return _reps_session("vo2_intervals", "Intervals {n} x {d}", ctx, n, 1.0, "I", 180,
                         "hard, controlled", "VO2max intervals at I pace.")


def reps(ctx: Ctx, _km=None) -> Session:
    n = _n(min(0.05 * ctx.weekly_km, 8) * ctx.scale / 0.4, 4, 12)
    return _reps_session("reps", "Repetitions {n} x {d}", ctx, n, 0.4, "R", 150,
                         "fast and relaxed", "Short fast repetitions for speed and economy.")


def hansons_speed(ctx: Ctx, _km=None) -> Session:
    n = _n(0.06 * ctx.weekly_km * ctx.scale / 0.8, 4, 12)
    return _reps_session("hansons_speed", "Speed {n} x {d}", ctx, n, 0.8, "I", 120,
                         "5K-10K effort", "Speed block repeats at 5K-10K effort.")


def hansons_strength(ctx: Ctx, _km=None) -> Session:
    n = _n(0.12 * ctx.weekly_km * ctx.scale / 1.6, 3, 6)
    return _reps_session("hansons_strength", "Strength {n} x {d}", ctx, n, 1.6, "T", 120,
                         "just faster than marathon pace", "Longer repeats a bit quicker than MP.")


def hills(ctx: Ctx, _km=None) -> Session:
    n = _n(8 * ctx.scale, 5, 10)
    main = Repeat(count=n, steps=[
        Step(kind="interval", time_s=60, target=ctx.target("I"), note="uphill, strong effort"),
        Step(kind="recovery", time_s=90, note="jog back down"),
    ])
    return Session("hills", f"Hill repeats {n} x 60 s", True, _wu_cd(ctx, [main]),
                   "Find a moderate hill. Hard up, easy jog down.")


def fartlek(ctx: Ctx, _km=None) -> Session:
    n = _n(8 * ctx.scale, 4, 10)
    main = Repeat(count=n, steps=[
        Step(kind="interval", time_s=60, target=ctx.target("T"), note="pick it up"),
        Step(kind="recovery", time_s=120, target=ctx.target("E"), note="easy"),
    ])
    return Session("fartlek", f"Fartlek {n} x 1 min", True, _wu_cd(ctx, [main]),
                   "Play with pace: 1 minute brisk, 2 minutes easy.")


def mp_run(ctx: Ctx, _km=None) -> Session:
    m = round(_clamp(0.15 * ctx.weekly_km * ctx.scale, 4, 16), 1)
    return Session("mp_run", f"Marathon-pace run {m:g} km", True,
                   _wu_cd(ctx, [_run("interval", m, ctx, "M")]), "Steady at marathon pace.")


def race_tune(ctx: Ctx, _km=None) -> Session:
    main = Repeat(count=3, steps=[_run("interval", 1.0, ctx, "T"), _jog(90)])
    return Session("race_tune", "Race tune-up 3 x 1 km", True, _wu_cd(ctx, [main]),
                   "Short and sharp to stay fresh for race day.")


# Sessions whose length is set by the planner (km argument) vs. by weekly volume.
DISTANCE_SESSIONS: dict[str, Callable[[Ctx, float], Session]] = {
    "easy": easy, "strides": strides, "long": long, "long_fast_finish": long_fast_finish,
    "long_mp": long_mp, "race": race,
}
QUALITY_SESSIONS: dict[str, Callable[..., Session]] = {
    "threshold": threshold, "cruise_intervals": cruise_intervals, "lt_intervals": lt_intervals,
    "vo2_intervals": vo2_intervals, "reps": reps, "hansons_speed": hansons_speed,
    "hansons_strength": hansons_strength, "hills": hills, "fartlek": fartlek, "mp_run": mp_run,
    "race_tune": race_tune, "medium_long": medium_long,
}
ALL_SESSIONS = {**DISTANCE_SESSIONS, **QUALITY_SESSIONS}


# ------------------------------------------------------------------ measuring


def _step_km_time(step: Step, ctx: Ctx) -> tuple[float, float, bool]:
    """(km, seconds, is_hard) for one step."""
    intensity = step.target.intensity if step.target else "E"
    pace = ctx.mid_pace(intensity) if intensity in ctx.paces else ctx.mid_pace("E")
    if step.kind == "recovery":
        pace = ctx.paces["E"][1] + 30  # jog slower than easy
    if step.distance_m is not None:
        km = step.distance_m / 1000
        return km, km * pace, intensity in HARD_INTENSITIES
    secs = step.time_s or 0
    return secs / pace, secs, intensity in HARD_INTENSITIES and step.kind == "interval"


def measure(steps: list[Step | Repeat], ctx: Ctx) -> tuple[float, float, float]:
    """Return (km, total seconds, hard seconds)."""
    km = total = hard = 0.0
    for s in steps:
        if isinstance(s, Repeat):
            k, t, h = measure(s.steps, ctx)
            km, total, hard = km + k * s.count, total + t * s.count, hard + h * s.count
        else:
            k, t, is_hard = _step_km_time(s, ctx)
            km, total = km + k, total + t
            hard += t if is_hard else 0
    return km, total, hard
