import re
import tomllib
from datetime import date, datetime, timedelta, timezone
from html import unescape

import pytest
import requests

from feedhub import checks, generator
from feedhub.db import PROJECT_ROOT, connect, init_db
from feedhub.mapping import load_mapping
from feedhub.pipeline import import_suppliers, save_supplier
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


SUD_SAMPLE = next((PROJECT_ROOT / "data" / "samples" / "sud").iterdir())


def upload_sud(url, **fields):
    data = {"code": "SUD", "name": "Pneus Sud Import", **fields}
    files = {"file": (SUD_SAMPLE.name, SUD_SAMPLE.read_bytes(), "text/csv")}
    return requests.post(url + "/nouveau-fournisseur", data=data, files=files, timeout=10)


def hidden(html, name):
    return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)


@pytest.fixture
def supplier_app(db_path, tmp_path, start_server):
    def start(demo):
        app = create_app(db_path, demo=demo, config_dir=tmp_path / "config", docs_dir=tmp_path / "docs")
        return start_server(app)

    (tmp_path / "config").mkdir()
    return start


def test_new_supplier_form(url):
    status, html = get(url, "/nouveau-fournisseur")
    assert status == 200
    assert 'type="file"' in html


def test_new_supplier_proposal(supplier_app):
    response = upload_sud(supplier_app(demo=False))
    html = response.text
    assert response.status_code == 200
    assert '<option value="Désignation" selected>' in html
    assert 'size = "extract_size_from_text"' in unescape(html)
    assert "Taux de rejet</span><span class=\"value\">0.0 %" in html
    assert "SELECT DISTINCT brand" in html


def test_new_supplier_correction_and_save(supplier_app, tmp_path):
    url = supplier_app(demo=False)
    first = upload_sud(url).text
    form = {
        "content": hidden(first, "content"), "file_name": SUD_SAMPLE.name,
        "code": "SUD", "name": "Pneus Sud Import",
        "column_ean": "CodeBarre", "column_brand": "Fabricant", "column_size": "Désignation",
        "column_price_eur": "PU_HT", "column_stock": "",
        "transform_size": "extract_size_from_text", "transform_price_eur": "",
    }

    without_stock = requests.post(url + "/nouveau-fournisseur", data=form, timeout=10).text
    assert "Champs obligatoires sans colonne : Stock." in without_stock
    assert not (tmp_path / "config" / "sud.toml").exists()

    form.update(column_stock="Qté", action="save")
    saved = requests.post(url + "/nouveau-fournisseur", data=form, timeout=10).text
    assert "Fournisseur enregistré" in saved
    assert tomllib.loads((tmp_path / "config" / "sud.toml").read_text(encoding="utf-8"))["columns"]["stock"] == "Qté"
    assert (tmp_path / "docs" / "sud.md").exists()

    again = requests.post(url + "/nouveau-fournisseur", data=form, timeout=10).text
    assert "Le code SUD est déjà utilisé." in again


def test_demo_mode_writes_nothing(supplier_app, tmp_path):
    response = upload_sud(supplier_app(demo=True), action="save")
    assert "Mode démonstration" in response.text
    assert "voici le fichier qui aurait été enregistré" in response.text
    assert list((tmp_path / "config").iterdir()) == []


def test_new_supplier_bad_input(supplier_app):
    url = supplier_app(demo=False)
    files = {"file": ("bad.xml", b"<a><b>", "text/xml")}
    html = requests.post(url + "/nouveau-fournisseur", data={"code": "x"}, files=files, timeout=10).text
    assert "Fichier illisible" in html

    html = requests.post(url + "/nouveau-fournisseur", data={"code": "SUD"}, timeout=10).text
    assert "Choisissez un fichier" in html

    html = upload_sud(url, code="1SUD").text
    assert "Le code doit faire 2 à 10 caractères" in html


def critical_link(code, count):
    return f'href="/anomalies?supplier={code}&amp;severity=critical">{count}</a>'


def test_dashboard_counts_feed_stale(url):
    status, html = get(url, "/")
    # REIF: no critical anomaly on its last import, but its data is late (FEED_STALE).
    assert critical_link("REIF", 1) in html
    # NORD: ROW_COUNT_DROP and STOCK_DROP on the cut file.
    assert critical_link("NORD", 2) in html


def test_feed_stale_is_no_longer_counted_once_data_is_fresh(tmp_path, start_server):
    generator.generate(tmp_path / "feeds", days=2, end_date=date.today())
    init_db(tmp_path / "fresh.db")
    connection = connect(tmp_path / "fresh.db")
    mapping = load_mapping("EURO")
    mapping["source"]["local_dir"] = str(tmp_path / "feeds" / "euro")
    supplier_id = save_supplier(connection, mapping)
    # An old FEED_STALE, before the supplier sent fresh data.
    connection.execute(
        "INSERT INTO anomalies (supplier_id, rule_code, severity, details, created_at)"
        " VALUES (?, 'FEED_STALE', 'critical', 'newest data: never', '2026-01-01 00:00:00')",
        (supplier_id,),
    )
    connection.commit()
    import_suppliers(connection, [mapping])
    connection.close()

    status, html = get(start_server(create_app(tmp_path / "fresh.db")), "/")

    assert lights(html) == {"EURO": "green"}
    assert "critical-count" not in html


def test_search_flags_offers_of_late_suppliers(url):
    status, html = get(url, "/search", size="205/55 R16")
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    reif_rows = [row for row in rows if "<td>REIF</td>" in row]
    other_rows = [row for row in rows if "<td>NORD</td>" in row or "<td>EURO</td>" in row]
    late_day = (date.today() - timedelta(days=2)).strftime("%d/%m")

    assert reif_rows and other_rows
    assert all(f"données du {late_day}" in row for row in reif_rows)
    assert not any('class="stale"' in row for row in other_rows)
