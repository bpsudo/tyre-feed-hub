from datetime import date, datetime
from pathlib import Path

import typer

from feedhub import db, generator

app = typer.Typer(no_args_is_help=True)


# Without a callback, Typer turns a single command into the root command
# and "feedhub init-db" stops working.
@app.callback()
def main():
    """Tyre supplier feeds: import and monitoring."""


@app.command()
def init_db(db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Database file.")):
    """Create the database tables if they do not exist."""
    db.init_db(db_path)
    typer.echo(f"Database ready: {db_path}")


@app.command()
def generate(
    days: int = typer.Option(1, min=1, help="Number of successive days."),
    inject_errors: bool = typer.Option(False, "--inject-errors", help="Add errors to some rows."),
    error_rate: float = typer.Option(0.02, min=0.0, max=1.0, help="Share of rows with an error."),
    scenario: list[str] = typer.Option(
        None, help="One of: " + ", ".join(generator.SCENARIOS) + ". Can be repeated."
    ),
    end_date: datetime = typer.Option(None, formats=["%Y-%m-%d"], help="Last day. Default: today."),
    seed: int = typer.Option(42, help="Same seed, same files."),
    output: Path = typer.Option(generator.DEFAULT_OUTPUT_DIR, help="Output folder."),
    samples: bool = typer.Option(False, "--samples", help="Write the example files of data/samples instead."),
):
    """Write supplier files with fake tyre data."""
    if samples:
        for path in generator.write_samples(seed=seed):
            typer.echo(f"Written: {path}")
        return

    scenarios = scenario or []
    for name in scenarios:
        if name not in generator.SCENARIOS:
            raise typer.BadParameter(f"unknown scenario: {name}", param_hint="--scenario")
    # Scenarios compare the last day with the previous ones.
    if scenarios and days < 3:
        raise typer.BadParameter("scenarios need at least 3 days", param_hint="--days")

    last_day = end_date.date() if end_date else date.today()
    summary, injections = generator.generate(
        output, days, last_day, inject_errors, error_rate, scenarios, seed
    )
    for item in summary:
        name = item["file"].name if item["file"] else "no file"
        note = f"  ({item['note']})" if item["note"] else ""
        typer.echo(f"{item['supplier']:<5} {item['day']}  {name:<24} {item['rows']:>4} rows{note}")
    typer.echo(f"{len(injections)} injected errors and scenarios, see {output / 'injections.csv'}")


if __name__ == "__main__":
    app()
