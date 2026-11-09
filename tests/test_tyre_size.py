import random

import pytest

from feedhub import generator
from feedhub.tyre_size import TyreSize, find_size, format_size, parse_size


@pytest.mark.parametrize("text", [
    "205/55 R16 91V",
    "205/55R16 91V",
    "205 / 55 R 16 91V",
    "205/55 ZR16 91V",
    "205/55r16 91v",
    "  205/55R16 91V  ",
])
def test_parse_full_size(text):
    assert parse_size(text) == TyreSize(205, 55, 16, 91, "V")


def test_parse_size_without_load_and_speed():
    assert parse_size("205/55 R16") == TyreSize(205, 55, 16)


def test_parse_three_digit_load_index():
    assert parse_size("235/65R16 115R") == TyreSize(235, 65, 16, 115, "R")


@pytest.mark.parametrize("text", [
    "20O/55R16 91V",
    "20555R16 91V",
    "205/55R16 91O",
    "205/55R16 91V extra",
    "",
])
def test_unreadable_size(text):
    assert parse_size(text) is None


@pytest.mark.parametrize("text", ["200/55R16", "205/57R16", "205/55R30", "105/55R16"])
def test_implausible_size(text):
    assert parse_size(text) is None


def test_find_size_in_description():
    text = "PNEU KESTRA AERO 3 205/55R16 91V"
    assert find_size(text) == TyreSize(205, 55, 16, 91, "V")


def test_find_size_ignores_longer_numbers():
    assert find_size("REF 1205/55R16") is None


def test_find_size_without_size():
    assert find_size("PNEU KESTRA AERO 3") is None


def test_format_size():
    assert format_size(205, 55, 16) == "205/55 R16"


def test_every_generated_size_can_be_read_back():
    for product in generator.build_catalogue(random.Random(1)):
        expected = TyreSize(
            product["width"],
            product["aspect_ratio"],
            product["rim_diameter"],
            product["load_index"],
            product["speed_index"],
        )
        assert parse_size(generator.size_text(product)) == expected
