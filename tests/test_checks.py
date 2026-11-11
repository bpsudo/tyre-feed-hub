import pytest
from pydantic import ValidationError

from feedhub.checks import row_rejection
from feedhub.mapping import MappingError
from feedhub.models import NormalizedOffer

VALID = {
    "ean": "2000000000015",
    "brand": "Kestra",
    "width": 205,
    "aspect_ratio": 55,
    "rim_diameter": 16,
    "price_eur": 59.9,
    "stock": 12,
}


def rule_for(**changes):
    data = {**VALID, **changes}
    data = {key: value for key, value in data.items() if value is not None}
    with pytest.raises(ValidationError) as error:
        NormalizedOffer(**data)
    return row_rejection(error.value)[0]


@pytest.mark.parametrize("changes, rule", [
    ({"ean": "2000000000016"}, "EAN_INVALID"),
    ({"brand": None}, "MISSING_FIELD"),
    ({"stock": None}, "MISSING_FIELD"),
    ({"width": "20O"}, "SIZE_UNPARSABLE"),
    ({"width": 200}, "SIZE_UNPARSABLE"),
    ({"price_eur": 0}, "PRICE_INVALID"),
    ({"price_eur": "abc"}, "PRICE_INVALID"),
    ({"stock": -2}, "STOCK_NEGATIVE"),
    ({"stock": "abc"}, "VALUE_INVALID"),
    ({"fuel_class": "G"}, "VALUE_INVALID"),
])
def test_rule_codes(changes, rule):
    assert rule_for(**changes) == rule


def test_mapping_errors():
    assert row_rejection(MappingError("size", "unreadable size"))[0] == "SIZE_UNPARSABLE"
    assert row_rejection(MappingError("season", "unknown value"))[0] == "VALUE_INVALID"
    assert row_rejection(MappingError("price_eur", "not cents"))[0] == "PRICE_INVALID"


def test_message_names_the_field():
    with pytest.raises(ValidationError) as error:
        NormalizedOffer(**{**VALID, "stock": -2})
    assert row_rejection(error.value)[1].startswith("stock: ")
