import random

import pytest
from pydantic import ValidationError

from feedhub import generator
from feedhub.models import NormalizedOffer

VALID = {
    "ean": "2000000000015",
    "brand": "Kestra",
    "model": "Aero 3",
    "width": 205,
    "aspect_ratio": 55,
    "rim_diameter": 16,
    "load_index": 91,
    "speed_index": "V",
    "season": "summer",
    "vehicle_type": "car",
    "noise_db": 70,
    "fuel_class": "C",
    "wet_grip_class": "B",
    "price_eur": 59.9,
    "stock": 12,
    "delivery_days": 2,
}


def invalid_fields(**changes):
    with pytest.raises(ValidationError) as error:
        NormalizedOffer(**{**VALID, **changes})
    return {item["loc"][0] for item in error.value.errors() if item["loc"]}


def test_valid_offer():
    offer = NormalizedOffer(**VALID)
    assert offer.ean == "2000000000015"
    assert offer.price_eur == 59.9


def test_optional_fields_can_be_missing():
    required = ["ean", "brand", "width", "aspect_ratio", "rim_diameter", "price_eur", "stock"]
    offer = NormalizedOffer(**{key: VALID[key] for key in required})
    assert offer.season is None


def test_text_values_are_converted_and_stripped():
    offer = NormalizedOffer(**{**VALID, "ean": " 2000000000015 ", "width": "205", "price_eur": "59.90"})
    assert offer.ean == "2000000000015"
    assert offer.width == 205
    assert offer.price_eur == 59.9


def test_price_is_rounded_to_cents():
    assert NormalizedOffer(**{**VALID, "price_eur": 59.904}).price_eur == 59.9


def test_invalid_ean():
    assert invalid_fields(ean="2000000000016") == {"ean"}


@pytest.mark.parametrize("brand", ["", "   "])
def test_missing_brand(brand):
    assert invalid_fields(brand=brand) == {"brand"}


def test_missing_required_field():
    data = dict(VALID)
    del data["stock"]
    with pytest.raises(ValidationError):
        NormalizedOffer(**data)


@pytest.mark.parametrize("price", [0, -5, "abc", "59,90", "inf", 0.004])
def test_invalid_price(price):
    assert invalid_fields(price_eur=price) == {"price_eur"}


def test_negative_stock():
    assert invalid_fields(stock=-1) == {"stock"}


def test_width_with_letter():
    assert invalid_fields(width="20O") == {"width"}


def test_implausible_size():
    with pytest.raises(ValidationError, match="implausible tyre size"):
        NormalizedOffer(**{**VALID, "width": 200})


@pytest.mark.parametrize("field, value", [
    ("season", "Été"),
    ("speed_index", "O"),
    ("fuel_class", "G"),
    ("vehicle_type", "truck"),
])
def test_unknown_values(field, value):
    assert invalid_fields(**{field: value}) == {field}


def test_unknown_field_is_refused():
    assert invalid_fields(colour="black") == {"colour"}


def test_every_generated_offer_is_valid():
    rng, products, offers, listed = generator.initial_state(seed=1)
    for code in generator.SUPPLIERS:
        for row in generator.build_rows(products, offers[code], listed[code]):
            data = {key: value for key, value in row.items() if key in NormalizedOffer.model_fields}
            NormalizedOffer(**data, price_eur=row["price"])
