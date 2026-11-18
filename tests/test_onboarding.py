import json
import tomllib
from datetime import date

import pytest

from feedhub import generator, onboarding
from feedhub.db import PROJECT_ROOT, connect, init_db
from feedhub.mapping import load_mapping
from feedhub.pipeline import import_supplier

SAMPLES = PROJECT_ROOT / "data" / "samples"


def sample(code):
    [path] = (SAMPLES / code.lower()).iterdir()
    return path.read_bytes(), path.name


@pytest.mark.parametrize("code", ["NORD", "EURO", "REIF"])
def test_proposal_finds_the_hand_written_mapping(code):
    content, name = sample(code)
    analysis = onboarding.analyze(content, name)
    mapping = onboarding.build_mapping(analysis, code, "x", analysis["proposal"])
    expected = load_mapping(code)

    assert mapping["format"] == expected["format"]
    assert mapping["columns"] == expected["columns"]
    assert mapping.get("transforms") == expected.get("transforms")
    for table in ("season_map", "vehicle_map"):
        # The sample has 10 rows: it may not contain every season.
        assert mapping[table].items() <= expected[table].items()
    for key in ("delimiter", "records"):
        assert mapping["file"].get(key) == expected["file"].get(key)


def test_sud_file():
    content, name = sample("SUD")
    analysis = onboarding.analyze(content, name)

    assert analysis["format"] == "csv"
    assert analysis["file"] == {"encoding": "cp1252", "delimiter": ","}
    assert analysis["proposal"] == {
        "ean": "CodeBarre", "brand": "Fabricant", "size": "Désignation", "price_eur": "PU_HT", "stock": "Qté",
    }
    mapping = onboarding.build_mapping(analysis, "SUD", "Pneus Sud Import", analysis["proposal"])
    assert mapping["transforms"] == {"size": "extract_size_from_text"}
    assert mapping["source"]["file_pattern"] == "export_*.csv"
    assert onboarding.dry_run(content, mapping)["rejected"] == 0


def test_values_are_enough_without_known_column_names():
    content, name = sample("SUD")
    text = content.decode("cp1252").replace("CodeBarre,Fabricant,Désignation,PU_HT,Qté", "c1,c2,c3,c4,c5", 1)

    analysis = onboarding.analyze(text.encode("cp1252"), name)

    assert analysis["proposal"] == {"ean": "c1", "brand": "c2", "size": "c3", "price_eur": "c4", "stock": "c5"}
    assert analysis["scores"]["c1"]["ean"] == 0.8


def test_sud_is_imported_without_code(tmp_path, monkeypatch):
    # The whole path: sample file -> proposed mapping -> files written -> real import.
    content, name = sample("SUD")
    analysis = onboarding.analyze(content, name)
    mapping = onboarding.build_mapping(analysis, "SUD", "Pneus Sud Import", analysis["proposal"])
    (tmp_path / "config").mkdir()
    config_path, doc_path = onboarding.save_supplier_files(mapping, tmp_path / "config", tmp_path / "docs")

    saved = load_mapping("SUD", tmp_path / "config")
    generator.generate(tmp_path / "feeds", days=2, end_date=date(2026, 1, 20), inject_errors=True)
    saved["source"]["local_dir"] = str(tmp_path / "feeds" / "sud")
    init_db(tmp_path / "test.db")
    connection = connect(tmp_path / "test.db")
    results = import_supplier(connection, saved)
    connection.close()

    assert [run["source_name"] for run in results] == ["export_20260119.csv", "export_20260120.csv"]
    assert all(run["status"] in ("success", "partial") for run in results)
    assert all(run["rows_loaded"] > 100 for run in results)
    assert "# Pneus Sud Import (SUD)" in doc_path.read_text(encoding="utf-8")


def test_files_are_never_overwritten(tmp_path):
    mapping = {"code": "SUD", "name": "x", "protocol": "file", "format": "csv", "columns": {}}
    onboarding.save_supplier_files(mapping, tmp_path, tmp_path)
    with pytest.raises(FileExistsError):
        onboarding.save_supplier_files(mapping, tmp_path, tmp_path)


def test_toml_round_trip():
    mapping = {
        "code": "SUD",
        "format": "csv",
        "source": {"file_pattern": "export_*.csv"},
        "file": {"encoding": "cp1252", "delimiter": ";"},
        "columns": {"noise_db": "Bruit (dB)", "brand": 'Marque "fab"'},
        "season_map": {"Été": "summer", "4 saisons": "all_season"},
    }
    assert tomllib.loads(onboarding.mapping_to_toml(mapping)) == mapping


@pytest.mark.parametrize("content, file_name, expected", [
    (b"EAN;Prix\n1;2\n", "a.csv", "csv"),
    (b"<a><b><c>1</c></b></a>", "a.txt", "xml"),
    (b'  [{"a": 1}]', "a.csv", "json"),
])
def test_format_comes_from_the_content(content, file_name, expected):
    assert onboarding.detect_format(content.decode(), file_name) == expected


def test_encodings():
    assert onboarding.detect_encoding("Été".encode("utf-8")) == "utf-8"
    assert onboarding.detect_encoding("Été".encode("cp1252")) == "cp1252"
    assert onboarding.detect_encoding(b"\x81") == "latin-1"
    assert onboarding.detect_encoding(b"\xef\xbb\xbfEAN") == "utf-8-sig"


def test_nested_records():
    xml = b"<export><info><n>1</n></info><items>" + b"<item><ean>1</ean></item>" * 3 + b"</items></export>"
    assert onboarding.detect_xml_records(xml) == "items/item"
    data = {"meta": {"page": 1}, "data": {"offers": [{"ean": "1"}, {"ean": "2"}]}}
    assert onboarding.detect_json_records(json.dumps(data)) == "data.offers"


def test_file_pattern():
    assert onboarding.file_pattern("stock_20260115.csv") == "stock_*.csv"
    assert onboarding.file_pattern("export-2026-01-15.json") == "export-*.json"
    assert onboarding.file_pattern("catalogue.xml") == "catalogue*.xml"


def test_normalize_and_synonyms():
    assert onboarding.normalize("Délai (jours)") == "delaijours"
    assert onboarding.name_matches("Qté", "stock")
    assert onboarding.name_matches("Lieferzeit_Tage", "delivery_days")
    assert not onboarding.name_matches("Silo", "speed_index")


def test_unknown_season_is_reported():
    content = "EAN;Saison\n2000000000015;Été\n2000000000022;Printemps\n".encode("utf-8")
    analysis = onboarding.analyze(content, "a.csv")
    maps, unknown = onboarding.value_maps(analysis, {"season": "Saison"})
    assert maps == {"season_map": {"Été": "summer"}}
    assert unknown == [("season", "Printemps")]


def test_missing_fields():
    assert onboarding.missing_fields({"ean": "a", "brand": "b", "price_eur": "c", "stock": "d"}) == ["size"]
    columns = {"ean": "a", "brand": "b", "price_eur": "c", "stock": "d",
               "width": "w", "aspect_ratio": "s", "rim_diameter": "r"}
    assert onboarding.missing_fields(columns) == []
