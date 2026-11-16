import re
from datetime import date, datetime, timezone

import pytest
import requests

from feedhub import checks, generator
from feedhub.db import connect, init_db
from feedhub.mapping import load_mapping
from feedhub.pipeline import import_suppliers
from feedhub.web.app import create_app

SCENARIOS = ["truncated-file", "price-crash", "dirty-file", "api-down"]


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    folder = tmp_path_factory.mktemp("web")
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
    checks.check_stale_feeds(connection, checks.load_thresholds(), datetime.now(timezone.utc))
    connection.close()
    return folder / "test.db"


@pytest.fixture
def url(db_path, start_server):
    return start_server(create_app(db_path))


def get(url, path, **params):
    response = requests.get(url + path, params=params, timeout=10)
    return response.status_code, response.text


def lights(html):
    """Colour of the status light of each supplier row, by supplier code."""
    rows = re.findall(r'class="light (\w+)".*?<strong>(\w+)</strong>', html, re.DOTALL)
    return {code: colour for colour, code in rows}


def test_dashboard(url):
    status, html = get(url, "/")
    assert status == 200
    # EURO: dirty file, NORD: cut file, REIF: no data for two days. All three are red.
    assert lights(html) == {"EURO": "red", "NORD": "red", "REIF": "red"}
    assert "en retard" in html
    assert "Historique des imports" in html
    assert "<summary>Requête SQL utilisée</summary>" in html
    assert "WITH last_run AS" in html


def test_dashboard_is_green_on_clean_feeds(tmp_path, start_server):
    generator.generate(tmp_path / "feeds", days=2, end_date=date.today())
    init_db(tmp_path / "clean.db")
    connection = connect(tmp_path / "clean.db")
    mapping = load_mapping("EURO")
    mapping["source"]["local_dir"] = str(tmp_path / "feeds" / "euro")
    import_suppliers(connection, [mapping])
    connection.close()

    status, html = get(start_server(create_app(tmp_path / "clean.db")), "/")

    assert lights(html) == {"EURO": "green"}


def test_anomalies_filters(url):
    status, html = get(url, "/anomalies", supplier="NORD", severity="critical")
    assert status == 200
    assert "ROW_COUNT_DROP" in html
    assert "STOCK_DROP" in html
    assert "PRICE_JUMP</code>" not in html
    assert ":supplier = NORD" in html


def test_anomalies_without_filter(url):
    status, html = get(url, "/anomalies", supplier="", rule_code="", severity="", data_date="")
    assert status == 200
    for rule in ["FEED_STALE", "REJECT_RATE_HIGH", "PRICE_OUTLIER", "EAN_INVALID"]:
        assert f"<code>{rule}</code>" in html


def test_supplier_data_is_escaped(url):
    # A rejected row shows the raw supplier data: it must never be read as HTML.
    status, html = get(url, "/anomalies", rule_code="EAN_INVALID")
    assert "&#34;" in html or "&quot;" in html
    assert "<script" not in html


def test_import_detail(url, db_path):
    connection = connect(db_path)
    run_id = connection.execute("""
        SELECT r.id FROM import_runs AS r JOIN suppliers AS s ON s.id = r.supplier_id
        WHERE s.code = 'NORD' ORDER BY r.id DESC LIMIT 1
    """).fetchone()[0]
    connection.close()

    status, html = get(url, f"/imports/{run_id}")

    assert status == 200
    assert "ROW_COUNT_DROP" in html
    assert "Lignes lues" in html
    assert "Ligne reçue" in html


def test_unknown_import_is_404(url):
    status, html = get(url, "/imports/99999")
    assert status == 404
    assert "Page introuvable" in html


def test_search(url):
    status, html = get(url, "/search", size="205/55r16")
    assert status == 200
    assert "205/55 R16 :" in html
    prices = [float(p) for p in re.findall(r'<td class="number">([\d.]+) €</td>', html)]
    assert prices
    assert prices == sorted(prices)
    assert "Dimensions les plus disponibles" in html


def test_search_unreadable_size(url):
    status, html = get(url, "/search", size="205-55")
    assert status == 200
    assert "Dimension illisible" in html


def test_static_css(url):
    response = requests.get(url + "/static/style.css", timeout=10)
    assert response.status_code == 200
    assert "--accent" in response.text


def test_page_without_database(tmp_path, start_server):
    status, html = get(start_server(create_app(tmp_path / "none.db")), "/")
    assert status == 503
    assert "feedhub init-db" in html
