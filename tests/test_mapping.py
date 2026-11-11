import pytest

from feedhub.db import PROJECT_ROOT
from feedhub.mapping import MappingError, load_mapping, map_row, supplier_codes
from feedhub.models import NormalizedOffer
from feedhub.readers import read_file

MAPPING = {
    "columns": {"ean": "Code", "price_eur": "Prix", "size": "Taille", "season": "Saison"},
    "transforms": {"price_eur": "decimal_comma", "size": "size_combined"},
    "season_map": {"Été": "summer", "Hiver": "winter"},
}


def test_columns_and_transforms():
    raw = {"Code": " 2000000000015 ", "Prix": "59,90", "Taille": "205/55R16 91V", "Saison": "Été"}
    assert map_row(raw, MAPPING) == {
        "ean": "2000000000015",
        "price_eur": "59.90",
        "width": 205,
        "aspect_ratio": 55,
        "rim_diameter": 16,
        "load_index": 91,
        "speed_index": "V",
        "season": "summer",
    }


def test_empty_and_missing_cells_are_left_out():
    row = map_row({"Code": "", "Prix": None}, MAPPING)
    assert "ean" not in row
    assert "price_eur" not in row


def test_size_without_load_index():
    row = map_row({"Taille": "205/55 R16"}, MAPPING)
    assert "load_index" not in row
    assert row["width"] == 205


def test_unreadable_size():
    with pytest.raises(MappingError) as error:
        map_row({"Taille": "20O/55R16 91V"}, MAPPING)
    assert error.value.field == "size"


def test_unknown_season():
    with pytest.raises(MappingError) as error:
        map_row({"Saison": "Ã\x89tÃ©"}, MAPPING)
    assert error.value.field == "season"


def test_cents_to_eur():
    mapping = {"columns": {"price_eur": "price"}, "transforms": {"price_eur": "cents_to_eur"}}
    assert map_row({"price": "5990"}, mapping) == {"price_eur": 59.9}
    with pytest.raises(MappingError):
        map_row({"price": "-5"}, mapping)


def test_extract_size_from_text():
    mapping = {"columns": {"size": "label"}, "transforms": {"size": "extract_size_from_text"}}
    row = map_row({"label": "PNEU KESTRA AERO 3 205/55R16 91V"}, mapping)
    assert (row["width"], row["aspect_ratio"], row["rim_diameter"]) == (205, 55, 16)


def test_unknown_transform_is_a_config_error():
    mapping = {"columns": {"price_eur": "price"}, "transforms": {"price_eur": "comma"}}
    with pytest.raises(ValueError, match="unknown transform"):
        map_row({"price": "5"}, mapping)


def test_configs_are_found():
    assert supplier_codes() == ["EURO", "NORD", "REIF"]
    assert load_mapping("EURO")["format"] == "xml"


@pytest.mark.parametrize("code", ["NORD", "EURO", "REIF"])
def test_sample_is_fully_valid(code):
    mapping = load_mapping(code)
    [path] = (PROJECT_ROOT / "data" / "samples" / code.lower()).glob(mapping["source"]["file_pattern"])
    rows = read_file(path.read_bytes(), mapping)
    offers = [NormalizedOffer(**map_row(raw, mapping)) for raw in rows]
    assert len(offers) == 10
    assert all(offer.season and offer.vehicle_type and offer.load_index for offer in offers)


def test_same_product_reads_the_same_in_every_format():
    # 2002255794152 is in the three samples, with a different price and stock each time.
    products = {}
    for code in ["NORD", "EURO", "REIF"]:
        mapping = load_mapping(code)
        [path] = (PROJECT_ROOT / "data" / "samples" / code.lower()).glob(mapping["source"]["file_pattern"])
        for raw in read_file(path.read_bytes(), mapping):
            offer = NormalizedOffer(**map_row(raw, mapping))
            if offer.ean == "2002255794152":
                products[code] = offer.model_dump(exclude={"price_eur", "stock", "delivery_days"})
    assert products["NORD"] == products["EURO"] == products["REIF"]
