import csv
import json
import random
import re
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from feedhub import generator
from feedhub.ean import is_valid_ean

END_DATE = date(2026, 1, 20)


def read_nord(path):
    with open(path, encoding="latin-1", newline="") as file:
        return list(csv.DictReader(file, delimiter=";"))


def read_injections(output_dir):
    with open(output_dir / "injections.csv", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def euro_prices(path):
    root = ET.parse(path).getroot()
    return {product.findtext("ean"): int(product.findtext("priceCents")) for product in root}


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    output_dir = tmp_path_factory.mktemp("clean")
    generator.generate(output_dir, days=3, end_date=END_DATE)
    return output_dir


@pytest.fixture(scope="module")
def error_run(tmp_path_factory):
    output_dir = tmp_path_factory.mktemp("errors")
    generator.generate(
        output_dir,
        days=3,
        end_date=END_DATE,
        inject_errors=True,
        error_rate=0.05,
        scenarios=generator.SCENARIOS,
    )
    return output_dir


def test_catalogue_has_500_unique_valid_eans():
    catalogue = generator.build_catalogue(random.Random(1))
    eans = [product["ean"] for product in catalogue]
    assert len(set(eans)) == 500
    assert all(is_valid_ean(ean) for ean in eans)


def test_suppliers_share_eans():
    rng = random.Random(1)
    assortments = generator.assign_assortments(rng, generator.build_catalogue(rng))
    common = set(assortments["NORD"]) & set(assortments["EURO"]) & set(assortments["REIF"])
    assert len(common) > 50


def test_one_file_per_supplier_and_day(clean_run):
    for folder, pattern in [
        ("nord", "stock_*.csv"),
        ("euro", "catalogue_*.xml"),
        ("reif", "offers_*.json"),
        ("sud", "export_*.csv"),
    ]:
        assert len(list((clean_run / folder).glob(pattern))) == 3
    assert (clean_run / "nord" / "stock_20260120.csv").exists()


def test_same_seed_gives_same_files(clean_run, tmp_path):
    generator.generate(tmp_path, days=3, end_date=END_DATE)
    for path in clean_run.rglob("*"):
        if path.is_file():
            assert (tmp_path / path.relative_to(clean_run)).read_bytes() == path.read_bytes()


def test_nord_format(clean_run):
    first = read_nord(clean_run / "nord" / "stock_20260120.csv")[0]
    assert "Modèle" in first
    assert re.fullmatch(r"\d+,\d{2}", first["Prix HT"])
    assert re.fullmatch(r"\d{3}/\d{2}R\d{2} \d{2,3}[A-Z]", first["Dimension"])


def test_euro_format(clean_run):
    products = ET.parse(clean_run / "euro" / "catalogue_20260120.xml").getroot().findall("product")
    assert all(product.findtext("priceCents").isdigit() for product in products)
    assert {product.findtext("season") for product in products} <= {"S", "W", "A"}


def test_reif_format(clean_run):
    content = (clean_run / "reif" / "offers_20260120.json").read_text(encoding="utf-8")
    first = json.loads(content)["artikel"][0]
    assert {"Breite", "Querschnitt", "Felge", "Preis", "Bestand"} <= first.keys()


def test_sud_is_cp1252_not_utf8(clean_run):
    content = (clean_run / "sud" / "export_20260120.csv").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        content.decode("utf-8")
    assert content.decode("cp1252").startswith("CodeBarre,Fabricant,Désignation")


def test_no_injection_without_option(clean_run):
    assert read_injections(clean_run) == []


def test_every_error_and_scenario_is_injected(error_run):
    injected = {entry["error"] for entry in read_injections(error_run)}
    assert injected == set(generator.COMMON_ERRORS) | {"broken_encoding"} | set(generator.SCENARIOS)


def test_invalid_eans_are_in_the_file(error_run):
    expected = [
        entry for entry in read_injections(error_run)
        if entry["supplier"] == "NORD" and entry["date"] == "2026-01-18" and entry["error"] == "ean_invalid"
    ]
    rows = read_nord(error_run / "nord" / "stock_20260118.csv")
    invalid = [row for row in rows if not is_valid_ean(row["EAN"])]
    assert len(invalid) == len(expected) > 0


def test_truncated_file_loses_most_rows(error_run):
    before = read_nord(error_run / "nord" / "stock_20260119.csv")
    after = read_nord(error_run / "nord" / "stock_20260120.csv")
    assert len(after) < len(before) * 0.7


def test_api_down_leaves_two_days_without_file(error_run):
    names = [path.name for path in (error_run / "reif").iterdir()]
    assert names == ["offers_20260118.json"]


def test_price_crash_lowers_euro_prices(error_run):
    before = euro_prices(error_run / "euro" / "catalogue_20260119.xml")
    after = euro_prices(error_run / "euro" / "catalogue_20260120.xml")
    common = before.keys() & after.keys()
    crashed = [ean for ean in common if after[ean] < before[ean] * 0.6]
    assert len(crashed) > len(common) * 0.2


def test_broken_encoding_puts_utf8_bytes_in_latin1_file():
    product = generator.make_product(random.Random(1), "2000000000015")
    row = {**product, "season": "summer", "price": 50.0, "stock": 3, "delivery_days": 1,
           "broken_encoding": True}
    content = generator.nord_text([row]).encode("latin-1")
    assert "Été".encode("utf-8") in content
    assert "Été".encode("latin-1") not in content


def test_samples_are_small(tmp_path):
    paths = generator.write_samples(tmp_path)
    assert len(paths) == 4
    assert len(read_nord(tmp_path / "nord" / "stock_20260115.csv")) == 10
