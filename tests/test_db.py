import sqlite3

import pytest

from feedhub.db import connect, init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def connection(db_path):
    conn = connect(db_path)
    yield conn
    conn.close()


def add_supplier(conn, code="NORD"):
    conn.execute(
        "INSERT INTO suppliers (code, name, protocol, format) VALUES (?, ?, ?, ?)",
        (code, "Pneus Nord Distribution", "sftp", "csv"),
    )


def test_all_tables_exist(connection):
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    assert {row["name"] for row in rows} == {
        "suppliers",
        "products",
        "offers",
        "import_runs",
        "offer_snapshots",
        "anomalies",
    }


def test_size_search_index_exists(connection):
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    assert "idx_products_size" in {row["name"] for row in rows}


def test_second_init_keeps_existing_data(db_path, connection):
    add_supplier(connection)
    connection.commit()

    init_db(db_path)

    count = connection.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
    assert count == 1


def test_supplier_code_is_unique(connection):
    add_supplier(connection)
    with pytest.raises(sqlite3.IntegrityError):
        add_supplier(connection)


def test_offer_with_unknown_references_is_refused(connection):
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO offers (supplier_id, ean, price_eur, stock, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (999, "0000000000000", 59.90, 4, "2026-01-15 08:00:00"),
        )


def test_import_status_is_restricted(connection):
    add_supplier(connection)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO import_runs (supplier_id, started_at, status) VALUES (?, ?, ?)",
            (1, "2026-01-15 08:00:00", "unknown"),
        )


def test_anomaly_accepts_ean_missing_from_products(connection):
    add_supplier(connection)
    connection.execute(
        "INSERT INTO anomalies (supplier_id, ean, rule_code, severity) VALUES (?, ?, ?, ?)",
        (1, "123", "EAN_INVALID", "warning"),
    )
    count = connection.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0]
    assert count == 1
