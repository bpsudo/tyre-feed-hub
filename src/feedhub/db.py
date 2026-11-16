import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "feedhub.db"


def now():
    # Same format and time zone (UTC) as CURRENT_TIMESTAMP in SQLite.
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect(db_path=DEFAULT_DB_PATH):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    # SQLite ignores foreign keys unless they are enabled on each connection.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path=DEFAULT_DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with closing(connect(db_path)) as connection:
        connection.executescript(schema)


TABLES = {"suppliers", "products", "offers", "import_runs", "offer_snapshots", "anomalies"}


class DatabaseNotReady(Exception):
    pass


def open_db(db_path=DEFAULT_DB_PATH):
    """Connect to a database already made by init-db, or raise DatabaseNotReady."""
    message = f"database not initialized: {db_path}. Run 'feedhub init-db' first."
    # sqlite3.connect would create an empty file without any table.
    if not Path(db_path).exists():
        raise DatabaseNotReady(message)
    connection = connect(db_path)
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    if not TABLES <= {row["name"] for row in rows}:
        connection.close()
        raise DatabaseNotReady(message)
    return connection
