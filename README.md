# Running_Program

Generates a running program **one week at a time** from your recent Garmin data, using rules modelled on
established methods (Daniels, Pfitzinger, Hansons, 80/20), and pushes the week's structured workouts to
Garmin Connect so they sync to your watch.

See [`docs/PLAN.md`](docs/PLAN.md) for the design, the training maths, and the phased build plan.

## Status

| Piece | State |
|---|---|
| Athlete config (`config/athlete.yaml`) | Done, **placeholder values: edit them** |
| Analysis: VDOT paces, TRIMP load, ACWR, compliance, readiness | Done, tested |
| Rules engine + 4 program templates | Done, tested |
| Weekly workout generator | Done, tested |
| Garmin workout JSON + idempotent push | Done, tested against a fake Garmin |
| Live Garmin connection | Code done, **not yet run against a real account** (needs your one-off login) |
| Weekly schedule (Monday 00:00 SAST) | **Not set up yet** (waiting for your go-ahead) |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # 56 tests

# Plan a week without touching Garmin, using synthetic sample data:
runplan run-weekly --fixture tests/fixtures/sample_garmin.json --dry-run

# Or with no data at all (config only):
runplan run-weekly --offline --dry-run

# Paces from the race result in your config:
runplan paces
```

Each run writes `out/week-<monday>.md` (readable plan) and `out/week-<monday>.json` (workouts plus the exact
Garmin payloads).

## Fill in your details

Edit `config/athlete.yaml`: goal race and date (or `null` for rolling base training), a recent race time,
weekly distance, run days, long-run day, heart rate, program style (`daniels`, `pfitzinger`, `hansons`,
`eighty_twenty`), units and target type (pace or HR).

## Connecting Garmin (needs you, once)

This uses the unofficial [`garminconnect`](https://pypi.org/project/garminconnect/) library (pinned to 0.3.20),
which logs in like the Garmin Connect app. Garmin does not support it officially, and a Garmin change can
break it. All Garmin calls go through `GarminClient`, so an official API client can replace it later.

1. On a computer you trust, run `runplan garmin-login`. It asks for your email, password and (if enabled) MFA
   code. **The password is not stored.** It saves tokens to `~/.garminconnect` and prints the token JSON.
2. Store that JSON as a secret named `GARMIN_TOKENS` (GitHub: *Settings → Secrets and variables → Actions*).
   Never commit it.
3. First live run, watched: `GARMIN_TOKENS='<json>' runplan run-weekly --dry-run` (reads only), then
   `runplan run-weekly` to push. Check the calendar in Garmin Connect and on your watch.

If tokens expire, the run stops with "run `runplan garmin-login` again". Re-run step 1 and update the secret.

## How a weekly run works

```
fetch 12 weeks of runs + 5 weeks of wellness
  → VDOT and paces, TRIMP load, ACWR, last week's compliance, HRV/sleep readiness
  → rules engine: phase, week type (build / hold / repeat / down / taper / race), volume, long run, sessions
  → week planner: 7 dated workouts, no back-to-back hard days, ≥ 80% of time easy
  → delete this week's old "RP | " workouts on Garmin, upload and schedule the new ones
  → save state/plan_state.json
```

Workouts are named `RP | YYYY-MM-DD | <title>`. Only workouts with that prefix are ever deleted, so your own
workouts are never touched. Re-running the same week replaces its workouts instead of duplicating them.
