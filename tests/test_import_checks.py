from collections import Counter
from datetime import date, datetime, timezone

import pytest

from feedhub import checks, generator
from feedhub.db import connect, init_db
from feedhub.mapping import load_mapping
from feedhub.pipeline import feed_date, import_suppliers, save_anomalies, save_supplier, start_run

END_DATE = date(2026, 1, 20)
THRESHOLDS = checks.load_thresholds()
CODES = ["EURO", "NORD", "REIF"]


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.delenv("NORD_SFTP_HOST", raising=False)
    monkeypatch.delenv("REIF_API_URL", raising=False)


@pytest.fixture
def connection(tmp_path):
    init_db(tmp_path / "test.db")
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def import_all(connection, tmp_path, **options):
    generator.generate(tmp_path / "feeds", days=4, end_date=END_DATE, **options)
    mappings = []
    for code in CODES:
        mapping = load_mapping(code)
        mapping["source"]["local_dir"] = str(tmp_path / "feeds" / code.lower())
        mappings.append(mapping)
    return import_suppliers(connection, mappings, THRESHOLDS)


def rules_by_supplier(connection, severity=None):
    rows = connection.execute(
        """
        SELECT s.code, a.rule_code FROM anomalies AS a JOIN suppliers AS s ON s.id = a.supplier_id
        WHERE ? IS NULL OR a.severity = ?
        """,
        (severity, severity),
    )
    return Counter((row[0], row[1]) for row in rows)


def test_clean_feeds_give_no_anomaly(connection, tmp_path):
    import_all(connection, tmp_path)
    checks.check_stale_feeds(connection, THRESHOLDS, datetime(2026, 1, 20, 18, tzinfo=timezone.utc))
    assert rules_by_supplier(connection) == Counter()


def test_each_scenario_gives_its_rules(connection, tmp_path):
    import_all(connection, tmp_path, scenarios=["truncated-file", "price-crash", "dirty-file", "api-down"])
    checks.check_stale_feeds(connection, THRESHOLDS, datetime(2026, 1, 20, 18, tzinfo=timezone.utc))

    found = rules_by_supplier(connection)
    assert found[("NORD", "ROW_COUNT_DROP")] == 1
    assert found[("NORD", "STOCK_DROP")] == 1
    assert found[("EURO", "PRICE_JUMP")] > 10
    assert found[("EURO", "PRICE_OUTLIER")] > 10
    assert found[("EURO", "REJECT_RATE_HIGH")] == 1
    assert found[("REIF", "FEED_STALE")] == 1
    # Only the supplier with the scenario is reported.
    assert {code for code, rule in found if rule == "PRICE_JUMP"} == {"EURO"}
    assert {code for code, rule in found if rule == "PRICE_OUTLIER"} == {"EURO"}


def test_price_outlier_compares_with_suppliers_imported_later(connection, tmp_path):
    # EURO is imported first; without the check at the end it would have nothing to compare with.
    results = import_all(connection, tmp_path, scenarios=["price-crash"])
    last_euro_run = results["EURO"][-1]["id"]
    outliers = connection.execute(
        "SELECT COUNT(*) FROM anomalies WHERE rule_code = 'PRICE_OUTLIER' AND run_id = ?", (last_euro_run,)
    ).fetchone()[0]
    assert outliers > 0


def test_feed_stale_is_reported_once(connection, tmp_path):
    import_all(connection, tmp_path)
    three_days_later = datetime(2026, 1, 23, 9, tzinfo=timezone.utc)

    first = checks.check_stale_feeds(connection, THRESHOLDS, three_days_later)
    second = checks.check_stale_feeds(connection, THRESHOLDS, three_days_later)

    assert [code for code, details in first] == CODES
    assert first[0][1] == "newest data: 2026-01-20"
    assert second == []


def test_yesterday_file_is_not_stale(connection, tmp_path):
    import_all(connection, tmp_path)
    next_morning = datetime(2026, 1, 21, 8, tzinfo=timezone.utc)
    assert checks.check_stale_feeds(connection, THRESHOLDS, next_morning) == []


def test_supplier_never_imported_is_stale(connection):
    save_supplier(connection, {"code": "NEW", "name": "New", "protocol": "file", "format": "csv"})
    found = checks.check_stale_feeds(connection, THRESHOLDS, datetime(2026, 1, 20, tzinfo=timezone.utc))
    assert found == [("NEW", "newest data: never")]


def test_reject_rate():
    assert checks.check_reject_rate(100, 5, THRESHOLDS) == []
    [(ean, rule, severity, details)] = checks.check_reject_rate(100, 6, THRESHOLDS)
    assert (rule, severity) == ("REJECT_RATE_HIGH", "critical")
    assert details == "6 rejected rows out of 100 (6.0 %)"


def test_row_count():
    previous = {"id": 1, "rows_read": 100}
    assert checks.check_row_count(70, previous, THRESHOLDS) == []
    assert checks.check_row_count(69, previous, THRESHOLDS)[0][1] == "ROW_COUNT_DROP"
    assert checks.check_row_count(10, None, THRESHOLDS) == []


def test_feed_date_from_name():
    assert feed_date("stock_20260120.csv") == "2026-01-20"
    assert feed_date("export-2026-01-20.json") == "2026-01-20"
    assert feed_date("stock_20261399.csv") is None
    assert feed_date(None) is None


def test_readable_text():
    assert checks.readable_text("Ã\x89tÃ©") == "Ã�tÃ©"
    assert checks.readable_text(b"\xff\xfeabc") == "��abc"
    assert checks.readable_text("line\nnext\x00") == "line�next�"
    assert checks.readable_text("Été 205/55 R16") == "Été 205/55 R16"


def test_anomaly_details_are_always_text(connection):
    supplier_id = save_supplier(connection, {"code": "T", "name": "T", "protocol": "file", "format": "csv"})
    run_id = start_run(connection, supplier_id, "a.csv", "2026-01-20 08:00:00")
    anomalies = [
        (None, "VALUE_INVALID", "warning", b"season: \xc3\x89t\xe9"),
        (None, "VALUE_INVALID", "warning", "season: Ã\x89tÃ©"),
    ]
    with connection:
        save_anomalies(connection, run_id, supplier_id, anomalies)

    rows = connection.execute("SELECT typeof(details), details FROM anomalies ORDER BY id").fetchall()
    assert [row[0] for row in rows] == ["text", "text"]
    assert all(text.isprintable() for text in (row[1].replace("�", "") for row in rows))


def test_schema_refuses_blob_details(connection):
    supplier_id = save_supplier(connection, {"code": "T", "name": "T", "protocol": "file", "format": "csv"})
    with pytest.raises(Exception, match="CHECK constraint failed"):
        connection.execute(
            "INSERT INTO anomalies (supplier_id, rule_code, severity, details) VALUES (?, 'X', 'info', ?)",
            (supplier_id, b"\x00\x01"),
        )


def test_broken_encoding_anomaly_is_readable(connection, tmp_path):
    import_all(connection, tmp_path, inject_errors=True, error_rate=0.05)
    rows = connection.execute("SELECT details FROM anomalies WHERE rule_code = 'VALUE_INVALID'").fetchall()
    assert rows
    for row in rows:
        assert row[0].replace("�", "").isprintable()
