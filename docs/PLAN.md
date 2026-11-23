# Weekly Garmin Running Program Generator — Build Plan

Status: **Phases 1, 3, 4, 5, 6 and 7 built** (see README). The live Garmin connection still needs the one-off login (Phase 2 hands-on step), and the schedule (Phase 8) is not set up.
Owner: juan le roux · Time zone: Africa/Johannesburg (SAST, UTC+2) · Repo: `juanleroux06/Running_Program`

---

## 1. What we are building

A small Python service that, once a week:

1. **Pulls** recent training data from Garmin Connect (runs, heart rate, HRV/sleep/readiness where available).
2. **Analyses** it: current fitness (VDOT), training load (acute vs chronic), compliance with last week's plan.
3. **Applies a rules engine** modelled on established programs (Daniels, Pfitzinger, Hansons, 80/20) to decide next week's volume, intensity mix and key sessions.
4. **Generates 7 days of structured workouts** (warm-up / intervals / recovery / cool-down with pace or HR targets).
5. **Pushes** them to Garmin Connect and **schedules** them on the calendar so they sync to the watch.
6. **Runs automatically** every Sunday night at midnight SAST (set up last, only after you approve).

```
           ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 Garmin ──▶│ 1. fetch     │──▶│ 2. analyse   │──▶│ 3. rules     │
 Connect   │  activities, │   │  VDOT, load, │   │  program     │
           │  HR, HRV     │   │  ACWR, plan  │   │  phase, week │
           └──────────────┘   │  compliance  │   │  targets     │
                              └──────────────┘   └──────┬───────┘
                                                        ▼
           ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 Watch  ◀──│ 6. schedule  │◀──│ 5. push to   │◀──│ 4. generate  │
           │  (Sun 00:00) │   │  Garmin cal. │   │  7 workouts  │
           └──────────────┘   └──────────────┘   └──────────────┘
                     state/plan_state.json  (phase, week no., history)
```

---

## 2. Garmin access: the big decision

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Unofficial: `garminconnect` (python-garminconnect)** (0.3.x, own login; earlier versions used `garth`) | Logs in as you via Garmin's SSO and calls the same endpoints the Connect app uses. Supports reading activities/HR/HRV/sleep and creating + scheduling workouts. | Works today for a personal account. Free. Reads and writes everything we need. Tokens last months, so the password is only used once. | Not supported by Garmin; can break when Garmin changes login (it has before). Grey area of Garmin's ToS. MFA needs a one-off manual step. |
| **B. Official Garmin Connect Developer Program** (Health API + Activity API + **Training API** for pushing workouts) | Proper OAuth app approved by Garmin. | Stable, supported, ToS-clean. | Built for businesses: you must apply and be approved, which can take weeks and may be refused for a one-person hobby project. Webhook/push-based, so needs a public HTTPS endpoint. |
| **C. Fallback: generate `.FIT` workout files** | Write workout files and copy them to the watch (USB / Garmin Express). | No API at all, can't break. | Manual every week; defeats the automation. |

**Recommendation:** build on **A** behind a thin interface (`GarminClient`) so we can swap to **B** later without touching the rest. Keep **C** as an emergency export (`runplan export-fit`).

> **Checked 2026-11-23:** `garminconnect` 0.3.20 no longer uses `garth`; it has its own login and token store, and old garth-format tokens are rejected. It supports `upload_workout`, `schedule_workout`, `delete_workout` and `get_workouts`, which is everything the push step needs. The project pins 0.3.20.

### Where credentials live

- Your Garmin email/password are used **once**, by you, via `runplan garmin-login`, to create a token bundle (saved to `~/.garminconnect`; the password is never stored).
- The token JSON it prints is stored as **one secret**, `GARMIN_TOKENS`:
  - as a **GitHub Actions secret** if the job runs on GitHub Actions, and/or
  - as a **Claude cloud environment secret** if the job runs as a Claude scheduled task.
- Never committed to the repo. `.gitignore` covers `.garminconnect/`, `.garth/`, `*.token`, `.env`.
- If tokens expire, the job fails loudly with "re-authenticate" and you rerun the one-off login script.

### Network note

The cloud container's network allowlist must permit `connect.garmin.com`, `sso.garmin.com` and `connectapi.garmin.com` (plus `garmin.com` subdomains). GitHub Actions runners have open internet, so no change is needed there.

---

## 3. Training science the engine will use

We encode the **principles** of each program as rules and formulas. We do not copy published tables or book text verbatim.

### 3.1 Fitness: Daniels VDOT (from a recent race or hard effort)

For a performance of distance $d$ (metres) in time $t$ (minutes), velocity $v = d / t$ (m/min):

$$
\text{VO}_2(v) = -4.60 + 0.182258\,v + 0.000104\,v^{2}
$$

$$
\%\text{VO}_{2\max}(t) = 0.8 + 0.1894393\,e^{-0.012778\,t} + 0.2989558\,e^{-0.1932605\,t}
$$

$$
\text{VDOT} = \frac{\text{VO}_2(v)}{\%\text{VO}_{2\max}(t)}
$$

Training paces come from solving $\text{VO}_2(v) = f \cdot \text{VDOT}$ for $v$ at these fractions $f$:

| Pace | Fraction of VDOT $f$ |
|---|---|
| Easy (E) | 0.59 – 0.74 |
| Marathon (M) | 0.75 – 0.84 |
| Threshold (T) | 0.83 – 0.88 |
| Interval (I) | 0.95 – 1.00 |
| Repetition (R) | ~1.05 – 1.10 |

With no recent race, estimate VDOT from the best 20–60 min continuous hard effort in the last 8 weeks, or fall back to Garmin's own VO₂max estimate.

### 3.2 Training load

Per-run load, using Banister TRIMP with heart-rate reserve
$\text{HR}_r = \dfrac{\text{HR}_{avg} - \text{HR}_{rest}}{\text{HR}_{max} - \text{HR}_{rest}}$ and duration $T$ in minutes:

$$
\text{TRIMP} = T \cdot \text{HR}_r \cdot 0.64\,e^{1.92\,\text{HR}_r} \quad (\text{male coefficients; female: } 0.86\,e^{1.67\,\text{HR}_r})
$$

Acute:chronic workload ratio:

$$
\text{ACWR} = \frac{\text{load over last 7 days}}{\tfrac{1}{4}\,\text{load over last 28 days}}
$$

| ACWR | Engine response |
|---|---|
| < 0.8 | Under-training: allow a normal build (up to +10%). |
| 0.8 – 1.3 | Sweet spot: follow the plan. |
| 1.3 – 1.5 | Caution: hold volume flat, drop one quality session. |
| > 1.5 | Danger: force a down week (−25%). |

### 3.3 Week-to-week guardrails (all programs)

- Weekly volume increase capped at 10%: $V_{w+1} \le 1.10 \cdot V_w$
- Down week every 3rd or 4th week: $V_{down} \approx 0.70 \text{ to } 0.80 \cdot V_{peak}$
- Long run share: $\text{long run} \le 30\%$ of weekly volume (≤ 35% for low-mileage runners), capped at ~2.5–3 h.
- Intensity split (80/20 style): $\ge 80\%$ of weekly time at easy intensity (below aerobic threshold / zone 1–2).
- Never two hard days in a row; at least one rest or very easy day.
- Missed > 50% of last week's planned volume ⇒ repeat that week instead of progressing.
- Readiness override: if HRV status is "low"/"unbalanced" or sleep score is poor several days running, convert the next quality session to easy.

### 3.4 Program templates (as rule sets, `programs/*.yaml`)

| Template | Character | Key sessions |
|---|---|---|
| `daniels` | Four phases (base, early quality, transition quality, final quality), VDOT paces | T runs, I reps, R reps, M runs |
| `pfitzinger` | High aerobic volume, lactate-threshold focus | LT tempo, medium-long run, general aerobic, marathon-pace long runs |
| `hansons` | Cumulative fatigue, long run capped ~16 mi / 26 km | Speed → strength intervals, marathon-pace tempo |
| `eighty_twenty` | Polarised by HR/pace zones | Foundation, fast finish, cruise intervals, long runs mostly Z1–Z2 |

Each YAML defines phases, phase lengths relative to race date, the weekly session "slots", the volume curve and the per-session templates. The engine picks a template, works out **which week of which phase** we're in, then fills slots using your fitness and the guardrails.

---

## 4. Proposed repo layout

```
Running_Program/
├── pyproject.toml            # Python 3.11+, deps: garminconnect, pydantic, pyyaml, typer, pytest
├── config/athlete.yaml       # your goal race, days available, HR max/rest, units, template choice
├── src/runplan/programs/     # daniels.yaml, pfitzinger.yaml, hansons.yaml, eighty_twenty.yaml
├── state/plan_state.json     # current phase/week + history of generated weeks (committed by the job)
├── src/runplan/
│   ├── garmin/   client.py (interface), live_client.py (incl. login), fake_client.py
│   ├── analysis/ vdot.py, load.py, compliance.py, readiness.py
│   ├── engine/   models.py, rules.py, templates.py, week_planner.py
│   ├── workouts/ library.py, garmin_json.py
│   └── cli.py    # runplan fetch | analyse | plan | push | run-weekly [--dry-run]
├── tests/        fixtures/ (anonymised Garmin JSON), unit + golden tests
└── .github/workflows/  ci.yml, weekly.yml (added in Phase 8 only)
```

---

## 5. Phased build plan

Each phase is one sub-thread (or subagent) and one PR. Phases 2, 3 and 4 can run in parallel once Phase 1 is merged.

| # | Phase | Depends on | Your hands needed? |
|---|---|---|---|
| 0 | Your inputs & decisions | – | **Yes** (questionnaire below) |
| 1 | Scaffold, config schema, CI | 0 | Merge PR |
| 2 | Garmin auth + data pull | 1 | **Yes**: run login once, add secret, allow network |
| 3 | Training-load & fitness analysis | 1 | No |
| 4 | Program rules engine + templates | 1 | Review templates |
| 5 | Weekly workout generator | 3, 4 | Review a sample week |
| 6 | Push & schedule on Garmin Connect | 2, 5 | **Yes**: approve first live push, check watch |
| 7 | End-to-end CLI, state, idempotency, tests | 6 | Merge PR |
| 8 | Weekly schedule (Sun 00:00 SAST) | 7 | **Yes**: approve turning it on |
| 9 | Notifications & monitoring (optional) | 8 | Choose channel |

### Phase 0 — What I need from you

1. **Goal race** (distance, date) or "general fitness / base building".
2. **Recent race result or time-trial** (distance + time) to set VDOT.
3. **Current typical weekly distance** and longest recent run.
4. **Days you can run** each week, and your preferred long-run day.
5. **Max and resting heart rate** (or let us estimate from data).
6. **Preferred program style**: Daniels, Pfitzinger, Hansons, 80/20, or "pick for me".
7. **Units** (km or miles) and **targets** (pace, HR, or both).
8. **Watch model** (to confirm workout step support).
9. **Injuries or constraints** (e.g. no track, treadmill only on Wednesdays).
10. **Garmin account has MFA on?** (affects first login).
11. **Where should the weekly job run**: GitHub Actions (recommended) or a Claude scheduled task.

### Phase 1 — Scaffold

Python package, `pyproject.toml`, `config/athlete.yaml` with a pydantic schema, `.gitignore` for secrets, `pytest` + `ruff` CI on GitHub Actions, README. Includes a `FakeGarminClient` that serves JSON fixtures, so every later phase can be built and tested without live Garmin access.

### Phase 2 — Garmin auth + data pull

- Confirm current library status; pin versions.
- `auth_login.py`: one-off interactive script that you run locally or in a cloud session. It handles MFA, saves the token folder and prints a base64 blob for the `GARMIN_TOKENS` secret.
- `garth_client.py`: loads tokens from env, refreshes them, fetches the last 8–12 weeks of activities (with laps/splits), daily resting HR, HRV status, sleep score, Garmin VO₂max and training status.
- Normalises everything into our own models (`Activity`, `DailyWellness`).
- Rate-limit friendly (small delays, retries with backoff), caches raw JSON to `cache/` (gitignored).

### Phase 3 — Analysis

`vdot.py` (formulas in §3.1 + pace tables), `load.py` (TRIMP, weekly volume, ACWR, monotony), `compliance.py` (planned vs actual for last week, matched by date and workout name), `readiness.py` (HRV/sleep flags). Pure functions, fully unit-tested with hand-checked numbers.

### Phase 4 — Rules engine

Pydantic models for `ProgramTemplate`, `Phase`, `SessionSlot`, `SessionTemplate`. Four YAML templates. `rules.py` applies the guardrails in §3.3. Input: athlete config + analysis + state. Output: a `WeekTargets` object (total volume, long-run length, which quality sessions, intensity split).

### Phase 5 — Weekly generator

Turns `WeekTargets` into seven dated `PlannedWorkout`s with steps (warm-up, repeats, recovery, cool-down), each with a pace or HR target from VDOT/zones. Places sessions on your available days, hard/easy alternation, long run on your chosen day. Writes `out/week-YYYY-MM-DD.json` and a readable Markdown summary.

### Phase 6 — Push to Garmin

- `garmin_json.py`: converts `PlannedWorkout` to Garmin's workout JSON (sport type running, step types, end conditions by time/distance/lap button, target types pace/HR zone).
- Push: create workout → schedule it on its date.
- Idempotency: every generated workout is named `RP | <date> · <type>`; before pushing a week, delete any existing `RP ·` workouts for that week, so a re-run never duplicates.
- `--dry-run` prints payloads without sending. The first live push is done with you watching.
- `fit_export.py`: fallback FIT export (option C).

### Phase 7 — End-to-end

`runplan run-weekly` = fetch → analyse → plan → generate → push → save state. Retries, clear exit codes, a log summary. Golden tests: fixture data in, expected week out. Property tests: the guardrails in §3.3 always hold.

### Phase 8 — Schedule (only after your go-ahead)

"Sunday night at midnight" is read as **00:00 SAST at the start of Monday**, generating Monday–Sunday. SAST = UTC+2, so in UTC that is **Sunday 22:00**:

$$
\text{Mon } 00{:}00\ \text{SAST} \;-\; 2\,\text{h} \;=\; \text{Sun } 22{:}00\ \text{UTC} \;\;\Rightarrow\;\; \texttt{cron: "0 22 * * 0"}
$$

(If you meant the start of Sunday instead, it becomes `0 22 * * 6`.)

- **GitHub Actions** (recommended): `.github/workflows/weekly.yml` with that cron plus a manual "Run workflow" button; commits `state/plan_state.json` back to the repo. Note that GitHub can start scheduled jobs a few minutes late.
- **Claude scheduled task** (alternative): a weekly trigger that runs `runplan run-weekly` in a cloud session; useful if you want Claude to also write you a short coaching note each week.

### Phase 9 — Notifications (optional)

After each run: a short email or message with the week's plan, last week's compliance, ACWR, and any warnings (tokens expiring, readiness override applied).

---

## 6. Prompts for each sub-thread / subagent

Every prompt below starts with this shared block:

> **Shared rules.** Repo `juanleroux06/Running_Program`. Work only in the cloud repo, on your own branch, and open a PR. Do **not** touch the user's local device or any other project on it. Read `docs/PLAN.md` first and follow its layout and formulas. Python 3.11+, type hints, pydantic models, pytest. Never commit credentials, tokens or raw personal data; test fixtures must be anonymised. Keep the `GarminClient` interface as the only place that talks to Garmin. Address the user as "/..\ gotliep /..\" and format any maths neatly.

### Prompt 1 — Scaffold

> Create the package skeleton from PLAN.md §4: `pyproject.toml` (deps: garminconnect, garth, pydantic>=2, pyyaml, typer, pytest, ruff), `src/runplan/` with empty modules, `config/athlete.example.yaml` plus a pydantic `AthleteConfig` that validates it (goal race, race date, recent result, weekly volume, available days, long-run day, HR max/rest, units, target type, template name). Add `GarminClient` as an abstract interface (`get_activities(start, end)`, `get_wellness(start, end)`, `list_workouts()`, `create_workout(payload)`, `schedule_workout(id, date)`, `delete_workout(id)`) and a `FakeGarminClient` backed by JSON files in `tests/fixtures/`. Add `.gitignore` (`.garth/`, `.env`, `cache/`, `out/`), a GitHub Actions CI workflow running ruff + pytest on push/PR, and a README with setup steps. Tests: config validation and the fake client.

### Prompt 2 — Garmin auth + data pull

> First, check the current state of `python-garminconnect` and `garth` (latest release, open issues about login/auth). Report findings in the PR description and pin versions that work. Implement `garmin/auth_login.py`: an interactive one-off script that logs in with email/password (prompting for MFA if needed), saves tokens, and prints a base64 blob to store as the `GARMIN_TOKENS` secret. Implement `GarthGarminClient` that loads tokens from `GARMIN_TOKENS` (or a local token dir), and fetches the last N weeks of running activities (with splits/laps, avg/max HR, distance, duration, pace), daily resting HR, HRV status, sleep score, Garmin VO₂max and training status. Map to our own `Activity` and `DailyWellness` models. Add retry with backoff and polite delays. Do not run against the live account; build and test with recorded/anonymised fixtures and `FakeGarminClient`. Document exactly what the user must do by hand (run login once, add the secret, network allowlist for Garmin hosts).

### Prompt 3 — Analysis

> Implement `analysis/` per PLAN.md §3.1–3.2: `vdot.py` (VO₂(v), %VO₂max(t), VDOT, and inverse to get E/M/T/I/R paces; also estimate VDOT from best recent continuous effort, falling back to Garmin VO₂max), `load.py` (Banister TRIMP with HR reserve, weekly volume and time-in-zone, ACWR over 7/28 days, monotony), `compliance.py` (planned vs actual by date, % of volume and key sessions completed), `readiness.py` (flag low HRV/sleep streaks). Pure functions only. Unit tests must check known values (e.g. a 5 km in 20:00 gives VDOT ≈ 49.8; verify against the formula, not a copied table).

### Prompt 4 — Rules engine and templates

> Implement `engine/models.py` (ProgramTemplate, Phase, SessionSlot, SessionTemplate, WeekTargets) and four YAML templates in `programs/` (daniels, pfitzinger, hansons, eighty_twenty) that encode each method's structure and principles in our own words — do not copy book tables or text. Implement `engine/rules.py`: given AthleteConfig + analysis results + plan state, decide the phase and week number, target weekly volume, long-run length, which quality sessions, and intensity split, applying every guardrail in PLAN.md §3.3 (10% cap, down weeks, long-run share, 80/20 split, no back-to-back hard days, repeat week on low compliance, ACWR table, readiness override). Also support "no race date" mode (rolling base/maintenance). Tests: one per guardrail, plus property tests (hypothesis) that guardrails always hold.

### Prompt 5 — Weekly generator

> Implement `engine/week_planner.py` and `workouts/builder.py`: turn WeekTargets into seven dated PlannedWorkout objects (Monday–Sunday in Africa/Johannesburg) with structured steps (warm-up, intervals/repeats, recovery, cool-down, easy run, rest) and targets as pace ranges (from VDOT) and/or HR zones depending on config. Respect available days and long-run day; alternate hard/easy. Output `out/week-<monday>.json` and a human-readable `out/week-<monday>.md`. Golden tests: three athlete fixtures (beginner 25 km/wk, intermediate 50 km/wk, advanced 90 km/wk) each produce a stable, reviewed week.

### Prompt 6 — Push to Garmin Connect

> Implement `workouts/garmin_json.py`: convert PlannedWorkout to Garmin Connect workout JSON (running sport type; warmup/interval/recovery/cooldown/rest/repeat steps; duration by time, distance or lap button; pace or HR-zone targets). Check the payload format against the pinned `garminconnect` version's workout-upload and scheduling calls. Implement push: for the target week, list existing workouts named with the `RP | ` prefix in that date range and delete them, then create and schedule each new workout on its date. Add `--dry-run` that prints payloads only. Implement `fit_export.py` as an offline fallback. Tests use FakeGarminClient and snapshot the JSON. Do NOT push to the live account; leave a clear checklist for the first live push, which the user will approve and watch.

### Prompt 7 — End-to-end CLI and state

> Implement `cli.py` with Typer: `fetch`, `analyse`, `plan`, `push`, `export-fit`, and `run-weekly [--dry-run] [--week YYYY-MM-DD]`. `run-weekly` does fetch → analyse → plan → generate → push → write `state/plan_state.json` (template, phase, week number, history of generated weeks with targets and actuals). Make it idempotent (re-running for the same week replaces, never duplicates). Clear exit codes and a one-screen summary. Add an end-to-end test using FakeGarminClient for 12 simulated weeks, checking progression, down weeks and guardrails. Update README with the weekly run instructions.

### Prompt 8 — Schedule (only after the user approves)

> Add `.github/workflows/weekly.yml`: `schedule: cron "0 22 * * 0"` (= Monday 00:00 SAST) plus `workflow_dispatch`. Steps: checkout, set up Python, install, run `runplan run-weekly` with `GARMIN_TOKENS` from secrets, then commit `state/plan_state.json` and `out/` summary back to the branch. On failure, the run must fail visibly. Do not enable it until the user confirms the first manual run worked. Alternatively, if the user chose a Claude scheduled task, create one weekly trigger with the same schedule that runs the same command.

### Prompt 9 — Notifications (optional)

> After `run-weekly`, send a short summary (next week's sessions, last week's compliance %, ACWR, warnings) via the channel the user chose. Make it optional via config.

### Review subagent prompt (use on every PR)

> Review this PR against `docs/PLAN.md`. Check: no secrets or personal data committed; GarminClient is the only Garmin touch-point; guardrails in §3.3 are enforced and tested; formulas match §3.1–3.2; tests pass and cover edge cases (no recent race, missing HR, zero runs last week, race week, post-race recovery). Report findings ranked by severity.

---

## 7. Testing strategy

- **Unit:** every formula with hand-calculated values; every guardrail.
- **Property-based (hypothesis):** random histories never break the 10% cap, the 80/20 split or the hard/easy rule.
- **Golden:** fixed athlete fixtures produce reviewed, stable weeks (snapshot files).
- **Contract:** Garmin workout JSON snapshots; a manual "live smoke test" checklist run with you once.
- **Simulation:** 12–16 week simulated block to eyeball the volume curve and down weeks.
- **Dry runs:** the scheduled job runs in `--dry-run` for the first week before going live.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Garmin changes login, unofficial library breaks | `GarminClient` interface, pinned versions, FIT fallback, clear failure message; apply for official API later if needed. |
| Tokens expire | Job fails with a "re-run login" message; notification in Phase 9. |
| Bad data (GPS glitches, missing HR) | Outlier filters, fall back to pace-based load when HR missing. |
| Over-training from a wrong VDOT | Conservative VDOT rounding down, guardrails, readiness override. |
| Duplicate workouts on re-run | `RP | ` naming + delete-then-create per week. |
| Scheduled job starts late / disabled | Manual "Run workflow" button; GitHub disables schedules on repos idle for 60 days — the weekly state commit keeps it active. |

## 9. What happens next

1. You answer the Phase 0 questions.
2. Phase 1 scaffold PR.
3. Phases 2, 3, 4 in parallel threads.
4. Phases 5 → 6 → 7.
5. You do the one-off Garmin login and approve the first live push.
6. You approve the schedule; Phase 8 turns it on.
