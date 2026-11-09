from pathlib import Path

import typer

from feedhub import db

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


if __name__ == "__main__":
    app()
