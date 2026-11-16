import os
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

import typer

from feedhub import checks, db, generator, mapping, pipeline

app = typer.Typer(no_args_is_help=True)
ENV_FILE = db.PROJECT_ROOT / ".env"


def load_env_file(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # A variable already set in the environment wins over the .env file.
        os.environ.setdefault(key.strip(), value.strip())


def open_database(db_path):
    try:
        return db.open_db(db_path)
    except db.DatabaseNotReady as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1)


def print_run(run):
    typer.echo(
        f"  {run['source_name'] or '-':<24} {run['status']:<8}"
        f" read {run['rows_read']:>4}  loaded {run['rows_loaded']:>4}"
        f"  rejected {run['rows_rejected']:>4}"
    )
    if run["error_message"]:
        typer.echo(f"    {run['error_message']}")


# Without a callback, Typer turns a single command into the root command
# and "feedhub init-db" stops working.
@app.callback()
def main():
    """Tyre supplier feeds: import and monitoring."""
    load_env_file(ENV_FILE)


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


@app.command("import")
def import_feeds(
    supplier: list[str] = typer.Option(None, help="Supplier code. Can be repeated."),
    all_suppliers: bool = typer.Option(False, "--all", help="Import every configured supplier."),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Database file."),
):
    """Import the new files of the suppliers."""
    known = mapping.supplier_codes()
    codes = known if all_suppliers else [code.upper() for code in supplier or []]
    if not codes:
        raise typer.BadParameter("give --supplier CODE or --all", param_hint="--supplier")
    for code in codes:
        if code not in known:
            raise typer.BadParameter(f"no config/suppliers/{code.lower()}.toml", param_hint="--supplier")

    mappings = [mapping.load_mapping(code) for code in codes]
    thresholds = checks.load_thresholds()
    with closing(open_database(db_path)) as connection:
        results = pipeline.import_suppliers(connection, mappings, thresholds)
        for supplier_mapping in mappings:
            runs = results[supplier_mapping["code"]]
            typer.echo(f"{supplier_mapping['code']}: {pipeline.describe_source(supplier_mapping)}")
            if not runs:
                typer.echo("  no new file")
            for run in runs:
                print_run(run)
        stale = checks.check_stale_feeds(connection, thresholds, datetime.now(timezone.utc))
        for code, details in stale:
            typer.echo(f"FEED_STALE {code}: {details}")
        anomalies = connection.execute(
            "SELECT severity, COUNT(*) FROM anomalies GROUP BY severity ORDER BY severity"
        ).fetchall()
        typer.echo("Anomalies in the database: " + ", ".join(f"{n} {sev}" for sev, n in anomalies))

    failed = any(run["status"] == "failed" for runs in results.values() for run in runs)
    # A non-zero exit code lets a scheduler or a monitoring tool see the failure.
    if failed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
