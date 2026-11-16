import json
from datetime import date

import pytest
import requests
from conftest import free_port

from feedhub import generator
from feedhub.connectors import rest_api
from feedhub.db import connect, init_db
from feedhub.mapping import load_mapping
from feedhub.pipeline import import_supplier
from mock_supplier_api.app import create_app

END_DATE = date(2026, 1, 20)


@pytest.fixture
def feeds(tmp_path):
    generator.generate(tmp_path / "feeds", days=3, end_date=END_DATE)
    return tmp_path / "feeds" / "reif"


@pytest.fixture
def start_api(feeds, start_server):
    """Start the fake API and return its app and its URL."""
    def start(**options):
        options = {"api_key": "test-key", "retry_after": 0, **options}
        app = create_app(feeds, **options)
        return app, start_server(app)

    return start


@pytest.fixture
def connection(tmp_path):
    init_db(tmp_path / "test.db")
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def reif_mapping(monkeypatch, url, key="test-key", per_page=50):
    monkeypatch.setenv("REIF_API_URL", url)
    monkeypatch.setenv("REIF_API_KEY", key)
    mapping = load_mapping("REIF")
    mapping["source"]["per_page"] = per_page
    return mapping


def test_api_needs_the_key(start_api):
    app, url = start_api()
    assert requests.get(f"{url}/api/v1/exports").status_code == 401
    response = requests.get(f"{url}/api/v1/exports", headers={"X-API-Key": "test-key"})
    assert response.json() == {"exports": ["2026-01-18", "2026-01-19", "2026-01-20"]}


def test_api_pages(start_api):
    app, url = start_api(rate_limit_every=0)
    page_url = f"{url}/api/v1/exports/2026-01-20/artikel"
    headers = {"X-API-Key": "test-key"}

    first = requests.get(page_url, params={"page": 1, "per_page": 100}, headers=headers).json()
    after_end = requests.get(page_url, params={"page": 99, "per_page": 100}, headers=headers).json()

    assert len(first["artikel"]) == 100
    assert first["total"] > 100
    assert after_end["artikel"] == []
    assert requests.get(f"{url}/api/v1/exports/2025-01-01/artikel", headers=headers).status_code == 404


def test_api_refuses_some_requests(start_api):
    app, url = start_api(rate_limit_every=2, retry_after=3)
    headers = {"X-API-Key": "test-key"}
    first = requests.get(f"{url}/api/v1/exports", headers=headers)
    second = requests.get(f"{url}/api/v1/exports", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "3"


def test_import_from_api(start_api, connection, monkeypatch, feeds):
    app, url = start_api(rate_limit_every=4)
    mapping = reif_mapping(monkeypatch, url)

    results = import_supplier(connection, mapping)

    assert [run["status"] for run in results] == ["success"] * 3
    assert [run["source_name"] for run in results] == [
        "offers_20260118.json", "offers_20260119.json", "offers_20260120.json"
    ]
    last_file = json.loads((feeds / "offers_20260120.json").read_text(encoding="utf-8"))
    assert results[-1]["rows_read"] == len(last_file["artikel"])
    assert app.state.refused > 0


def test_api_import_skips_known_exports(start_api, connection, monkeypatch):
    app, url = start_api(rate_limit_every=0)
    mapping = reif_mapping(monkeypatch, url)
    import_supplier(connection, mapping)
    requests_before = app.state.requests

    assert import_supplier(connection, mapping) == []
    # Only the list of exports is asked again.
    assert app.state.requests == requests_before + 1


def test_wrong_key_is_a_failed_run(start_api, connection, monkeypatch):
    app, url = start_api()
    mapping = reif_mapping(monkeypatch, url, key="wrong")

    [run] = import_supplier(connection, mapping)

    assert run["status"] == "failed"
    assert "401" in run["error_message"]


def test_rate_limit_that_never_ends(start_api, connection, monkeypatch):
    app, url = start_api(rate_limit_every=1)
    mapping = reif_mapping(monkeypatch, url)

    [run] = import_supplier(connection, mapping)

    assert run["status"] == "failed"
    assert run["error_message"].startswith("RateLimitError")
    assert app.state.refused == rest_api.MAX_RETRIES + 1


def test_api_down_is_a_failed_run(connection, monkeypatch):
    mapping = reif_mapping(monkeypatch, f"http://127.0.0.1:{free_port()}")

    [run] = import_supplier(connection, mapping)

    assert run["status"] == "failed"
    assert run["error_message"].startswith("ConnectionError")


def test_without_url_reads_local_folder(monkeypatch, feeds):
    monkeypatch.delenv("REIF_API_URL", raising=False)
    source = {**load_mapping("REIF")["source"], "local_dir": str(feeds)}

    files = rest_api.fetch_files(source)

    assert [name for name, content in files] == [
        "offers_20260118.json", "offers_20260119.json", "offers_20260120.json"
    ]
    assert "REIF_API_URL not set" in rest_api.describe(source)


def test_wait_seconds_has_a_limit():
    class Response:
        def __init__(self, value):
            self.headers = {"Retry-After": value}

    assert rest_api.wait_seconds(Response("2")) == 2
    assert rest_api.wait_seconds(Response("3600")) == rest_api.MAX_WAIT_SECONDS
    assert rest_api.wait_seconds(Response("Wed, 21 Oct 2026 07:28:00 GMT")) == 1
