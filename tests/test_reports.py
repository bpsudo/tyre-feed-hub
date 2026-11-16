from datetime import date

import pytest
from typer.testing import CliRunner

from feedhub import generator, reports
from feedhub.cli import app
from feedhub.db import connect, init_db
from feedhub.mapping import load_mapping
from feedhub.pipeline import import_suppliers

runner = CliRunner()
SCENARIOS = ["truncated-file", "price-crash", "dirty-file", "api-down"]


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    folder = tmp_path_factory.mktemp("reports")
    # Ends today, so that the queries using 'now' see recent data.
    generator.generate(folder / "feeds", days=4, end_date=date.today(), inject_errors=True, scenarios=SCENARIOS)
    mappings = []
    for code in ["EURO", "NORD", "REIF"]:
        mapping = load_mapping(code)
        mapping["source"]["local_dir"] = str(folder / "feeds" / code.lower())
        mappings.append(mapping)
    init_db(folder / "test.db")
    connection = connect(folder / "test.db")
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("NORD_SFTP_HOST", raising=False)
        patch.delenv("REIF_API_URL", raising=False)
        import_suppliers(connection, mappings)
    connection.close()
    return folder / "test.db"


@pytest.fixture
def connection(db_path):
    conn = connect(db_path)
    yield conn
    conn.close()


def run(connection, number, **values):
    return reports.find_query(number).run(connection, values)


def test_there_are_ten_queries_with_a_question():
    queries = reports.all_queries()
    assert [query.number for query in queries] == list(range(1, 11))
    assert all(query.question.endswith("?") for query in queries)


def test_parameters_are_found():
    assert reports.find_query(6).parameters == ["width", "aspect_ratio", "rim_diameter"]
    assert reports.find_query(5).optional_parameters == {"supplier"}
    assert reports.find_query(1).parameters == []


@pytest.mark.parametrize("number", range(1, 11))
def test_every_query_runs(connection, number):
    values = {"supplier": "NORD", "width": 205, "aspect_ratio": 55, "rim_diameter": 16}
    columns, rows = run(connection, number, **values)
    assert columns


def test_best_price_is_the_minimum(connection):
    columns, rows = run(connection, 1)
    best = {row[0]: row[4] for row in rows}
    minimum = dict(connection.execute("SELECT ean, MIN(price_eur) FROM offers GROUP BY ean").fetchall())
    assert best == minimum


def test_coverage_adds_up(connection):
    columns, rows = run(connection, 2)
    assert sum(row[1] for row in rows) == connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    exclusive = connection.execute(
        "SELECT COUNT(*) FROM (SELECT ean FROM offers GROUP BY ean HAVING COUNT(*) = 1)"
    ).fetchone()[0]
    assert sum(row[2] for row in rows) == exclusive


def test_reject_rate_filter(connection):
    columns, all_rows = run(connection, 5)
    columns, euro_rows = run(connection, 5, supplier="EURO")
    assert {row[1] for row in all_rows} == {"EURO", "NORD", "REIF"}
    assert {row[1] for row in euro_rows} == {"EURO"}
    # dirty-file: the last EURO file has more than 5 % of rejected rows.
    assert euro_rows[0][6] > 5


def test_offers_for_size_are_sorted_and_in_stock(connection):
    columns, rows = run(connection, 6, width=205, aspect_ratio=55, rim_diameter=16)
    prices = [row[columns.index("price_eur")] for row in rows]
    assert rows
    assert prices == sorted(prices)
    assert all(row[columns.index("stock")] > 0 for row in rows)


def test_stock_change_shows_the_cut_file(connection):
    columns, rows = run(connection, 7, supplier="NORD")
    assert rows[0][columns.index("stock_change")] is None
    assert rows[-1][columns.index("change_pct")] < -50


def test_eans_gone_after_the_cut_file(connection):
    columns, rows = run(connection, 8, supplier="NORD")
    assert len(rows) > 100


def test_supplier_without_recent_data(connection):
    columns, rows = run(connection, 9)
    assert [row[0] for row in rows] == ["REIF"]


def test_top_sizes(connection):
    columns, rows = run(connection, 10)
    stocks = [row[3] for row in rows]
    assert len(rows) == 10
    assert stocks == sorted(stocks, reverse=True)


def test_report_command(db_path):
    result = runner.invoke(app, ["report", "6", "--size", "205/55 R16", "--sql", "--db", str(db_path)])
    assert result.exit_code == 0
    assert "WHERE p.width = :width" in result.output
    assert "price_eur" in result.output


def test_report_list():
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0
    assert "[supplier]" in result.output


def test_report_needs_its_parameter(db_path):
    result = runner.invoke(app, ["report", "7", "--db", str(db_path)])
    assert result.exit_code == 2
    assert "needs --supplier" in result.output


def test_report_unknown_number():
    assert runner.invoke(app, ["report", "42"]).exit_code == 2


def test_report_without_database(tmp_path):
    result = runner.invoke(app, ["report", "1", "--db", str(tmp_path / "none.db")])
    assert result.exit_code == 1
    assert "feedhub init-db" in result.output


def test_format_table():
    text = reports.format_table(["a", "price"], [(1, 59.9), (None, 100.0)])
    assert text.splitlines() == ["a  price", "-  -----", "1  59.9", "   100"]
