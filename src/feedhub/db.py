import sqlite3
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "feedhub.db"


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
