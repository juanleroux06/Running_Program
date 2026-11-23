"""Command line: `runplan --help`."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from runplan.config import load_config

app = typer.Typer(add_completion=False, help="Weekly running program generator for Garmin.")


def _client(offline: bool, fixture: Path | None):
    from runplan.garmin.fake_client import FakeGarminClient

    if fixture:
        return FakeGarminClient.from_fixture(fixture)
    if offline:
        return FakeGarminClient()
    from runplan.garmin.live_client import LiveGarminClient

    return LiveGarminClient()


@app.command("run-weekly")
def run_weekly(
    week: str = typer.Option(None, help="Monday to plan (YYYY-MM-DD). Default: today if Monday, else next Monday."),
    config: Path = typer.Option(Path("config/athlete.yaml")),
    state: Path = typer.Option(Path("state/plan_state.json")),
    out: Path = typer.Option(Path("out")),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan and write files, but do not push or save state."),
    offline: bool = typer.Option(False, "--offline", help="Do not contact Garmin; plan from config only."),
    fixture: Path = typer.Option(None, help="Read Garmin data from a JSON fixture instead of the live account."),
) -> None:
    """Fetch data, plan next week, push it to Garmin Connect and save state."""
    from runplan.garmin.live_client import GarminAuthError
    from runplan.pipeline import run_week, target_week

    cfg = load_config(config)
    ws = date.fromisoformat(week) if week else target_week()
    try:
        client = _client(offline, fixture)
    except GarminAuthError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(2) from e

    live = not (offline or fixture)
    res = run_week(cfg, client, ws, state_path=state, out_dir=out,
                   push=live and not dry_run, save=not dry_run)
    typer.echo(res.md_path.read_text())
    typer.echo(f"Wrote {res.json_path} and {res.md_path}")
    if dry_run:
        typer.echo("Dry run: nothing pushed, state not saved.")


@app.command()
def paces(config: Path = typer.Option(Path("config/athlete.yaml"))) -> None:
    """Show VDOT and training paces from the race result in config."""
    from runplan.analysis.vdot import fmt_pace, training_paces, vdot_from_performance

    cfg = load_config(config)
    if not cfg.recent_result:
        typer.echo("No recent_result in config.")
        raise typer.Exit(1)
    v = vdot_from_performance(cfg.recent_result.distance_km, cfg.recent_result.minutes)
    typer.echo(f"VDOT {v:.1f}")
    for k, (f, s) in training_paces(v).items():
        typer.echo(f"  {k}: {fmt_pace(f, cfg.units)} - {fmt_pace(s, cfg.units)}")


@app.command("garmin-login")
def garmin_login(token_dir: str = typer.Option("~/.garminconnect")) -> None:
    """One-off interactive Garmin login. Prints the token JSON to store as the GARMIN_TOKENS secret."""
    from runplan.garmin.live_client import interactive_login

    tokens = interactive_login(token_dir)
    typer.echo(f"\nTokens saved to {token_dir}.")
    typer.echo("Store the line below as the GARMIN_TOKENS secret. Treat it like a password:\n")
    typer.echo(tokens)


if __name__ == "__main__":
    app()
