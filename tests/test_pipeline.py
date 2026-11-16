import csv
from collections import Counter
from datetime import date

import pytest

from feedhub import generator
from feedhub.db import connect, init_db
from feedhub.mapping import load_mapping
from feedhub.models import NormalizedOffer
from feedhub.pipeline import import_supplier, load_offers, save_supplier, start_run

END_DATE = date(2026, 1, 20)
RULE_FOR_ERROR = {
    "ean_invalid": "EAN_INVALID",
    "size_typo": "SIZE_UNPARSABLE",
    "price_zero": "PRICE_INVALID",
    "negative_stock": "STOCK_NEGATIVE",
    "missing_field": "MISSING_FIELD",
    "duplicate": "DUPLICATE_IN_FILE",
    "broken_encoding": "VALUE_INVALID",
}


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.delenv("NORD_SFTP_HOST", raising=False)
    monkeypatch.delenv("REIF_API_URL", raising=False)


@pytest.fixture
def connection(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    yield conn
    conn.close()


def supplier_mapping(tmp_path, code, **options):
    generator.generate(tmp_path / "feeds", days=3, end_date=END_DATE, **options)
    mapping = load_mapping(code)
    mapping["source"]["local_dir"] = str(tmp_path / "feeds" / code.lower())
    return mapping


def nord_mapping(tmp_path, **options):
    return supplier_mapping(tmp_path, "NORD", **options)


def count(connection, sql, *params):
    return connection.execute(sql, params).fetchone()[0]


@pytest.mark.parametrize("code", ["NORD", "EURO", "REIF"])
def test_clean_import(connection, tmp_path, code):
    mapping = supplier_mapping(tmp_path, code)

    results = import_supplier(connection, mapping)

    assert [run["status"] for run in results] == ["success"] * 3
    assert [run["source_name"] for run in results] == [
        generator.FILE_NAMES[code].format(date(2026, 1, day)) for day in (18, 19, 20)
    ]
    last_run = results[-1]
    assert last_run["rows_read"] == last_run["rows_loaded"]
    assert count(connection, "SELECT COUNT(*) FROM offer_snapshots WHERE run_id = ?", last_run["id"]) \
        == last_run["rows_loaded"]
    assert count(connection, "SELECT COUNT(*) FROM anomalies") == 0


def test_offers_match_the_last_file(connection, tmp_path):
    mapping = nord_mapping(tmp_path)
    import_supplier(connection, mapping)

    with open(tmp_path / "feeds" / "nord" / "stock_20260120.csv", encoding="latin-1", newline="") as file:
        eans_in_file = {row["EAN"] for row in csv.DictReader(file, delimiter=";")}
    eans_in_offers = {row[0] for row in connection.execute("SELECT ean FROM offers")}
    assert eans_in_offers == eans_in_file


def test_files_are_imported_once(connection, tmp_path):
    mapping = nord_mapping(tmp_path)
    import_supplier(connection, mapping)

    assert import_supplier(connection, mapping) == []
    assert count(connection, "SELECT COUNT(*) FROM import_runs") == 3


@pytest.mark.parametrize("code", ["NORD", "EURO", "REIF"])
def test_each_injected_error_gives_one_anomaly(connection, tmp_path, code):
    mapping = supplier_mapping(tmp_path, code, inject_errors=True, error_rate=0.05)

    results = import_supplier(connection, mapping)

    with open(tmp_path / "feeds" / "injections.csv", encoding="utf-8", newline="") as file:
        injected = Counter(
            RULE_FOR_ERROR[row["error"]] for row in csv.DictReader(file) if row["supplier"] == code
        )
    rules = connection.execute("SELECT rule_code FROM anomalies")
    found = Counter(row[0] for row in rules if row[0] in RULE_FOR_ERROR.values())
    assert found == injected
    assert all(run["status"] == "partial" for run in results)
    assert sum(run["rows_rejected"] for run in results) == sum(injected.values()) - injected["DUPLICATE_IN_FILE"]


def test_truncated_file(connection, tmp_path):
    mapping = nord_mapping(tmp_path, scenarios=["truncated-file"])

    results = import_supplier(connection, mapping)

    last_run = results[-1]
    assert last_run["rows_loaded"] < results[-2]["rows_loaded"] * 0.5
    # The offers missing from the cut file are kept.
    assert count(connection, "SELECT COUNT(*) FROM offers") >= results[-2]["rows_loaded"]
    assert count(connection, "SELECT COUNT(*) FROM anomalies WHERE rule_code = 'MISSING_FIELD'") == 1
    rules = {row[0] for row in connection.execute(
        "SELECT rule_code FROM anomalies WHERE run_id = ? AND severity = 'critical'", (last_run["id"],)
    )}
    assert rules == {"ROW_COUNT_DROP", "STOCK_DROP"}


def test_cut_xml_file_fails(connection, tmp_path):
    mapping = supplier_mapping(tmp_path, "EURO")
    path = tmp_path / "feeds" / "euro" / "catalogue_20260120.xml"
    path.write_bytes(path.read_bytes()[:5000])

    results = import_supplier(connection, mapping)

    assert [run["status"] for run in results] == ["success", "success", "failed"]
    assert results[-1]["error_message"].startswith("ParseError")


def test_three_suppliers_share_products(connection, tmp_path):
    generator.generate(tmp_path / "feeds", days=1, end_date=END_DATE)
    for code in ["NORD", "EURO", "REIF"]:
        mapping = load_mapping(code)
        mapping["source"]["local_dir"] = str(tmp_path / "feeds" / code.lower())
        import_supplier(connection, mapping)

    shared = count(connection, """
        SELECT COUNT(*) FROM (SELECT ean FROM offers GROUP BY ean HAVING COUNT(*) = 3)
    """)
    assert shared > 0
    assert count(connection, "SELECT COUNT(*) FROM products") \
        == count(connection, "SELECT COUNT(DISTINCT ean) FROM offers")


def test_unreadable_files_fail_and_are_retried(connection, tmp_path):
    mapping = nord_mapping(tmp_path)
    mapping["file"]["encoding"] = "ascii"

    results = import_supplier(connection, mapping)

    assert [run["status"] for run in results] == ["failed"] * 3
    assert results[0]["error_message"].startswith("UnicodeDecodeError")

    mapping["file"]["encoding"] = "latin-1"
    assert [run["status"] for run in import_supplier(connection, mapping)] == ["success"] * 3


def test_missing_folder_is_a_failed_run(connection, tmp_path):
    mapping = load_mapping("NORD")
    mapping["source"]["local_dir"] = str(tmp_path / "nowhere")

    results = import_supplier(connection, mapping)

    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert results[0]["source_name"] is None
    assert "folder not found" in results[0]["error_message"]


def test_file_without_valid_row_keeps_previous_offers(connection, tmp_path):
    folder = tmp_path / "nord"
    folder.mkdir()
    mapping = load_mapping("NORD")
    mapping["source"]["local_dir"] = str(folder)
    generator.write_samples(tmp_path / "samples")
    (folder / "stock_20260115.csv").write_bytes(
        (tmp_path / "samples" / "nord" / "stock_20260115.csv").read_bytes()
    )
    import_supplier(connection, mapping)
    (folder / "stock_20260116.csv").write_bytes("EAN;Marque\r\n123;Kestra\r\n".encode("latin-1"))

    results = import_supplier(connection, mapping)

    assert results[0]["status"] == "failed"
    assert results[0]["error_message"] == "no valid row"
    assert count(connection, "SELECT COUNT(*) FROM offers") == 10


def test_product_keeps_values_another_supplier_gave(connection):
    supplier_id = save_supplier(
        connection, {"code": "TEST", "name": "Test", "protocol": "file", "format": "csv"}
    )
    base = {"ean": "2000000000015", "brand": "Kestra", "width": 205, "aspect_ratio": 55,
            "rim_diameter": 16, "price_eur": 59.9, "stock": 4}
    run_id = start_run(connection, supplier_id, "a.csv", "2026-01-15 08:00:00")
    load_offers(connection, run_id, supplier_id, [NormalizedOffer(**base, season="winter")], "2026-01-15")
    run_id = start_run(connection, supplier_id, "b.csv", "2026-01-16 08:00:00")
    load_offers(connection, run_id, supplier_id, [NormalizedOffer(**base)], "2026-01-16")

    season = connection.execute("SELECT season FROM products").fetchone()[0]
    assert season == "winter"
