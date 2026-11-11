"""Tests for unit conversion."""

import pytest

from bot.tools.convert_units import convert_units


@pytest.mark.parametrize("value,f,t,expected", [
    (5, "km", "mi", 3.1069),
    (1, "lb", "g", 453.5924),
    (100, "C", "F", 212),
    (32, "fahrenheit", "celsius", 0),
    (0, "C", "K", 273.15),
    (2, "cups", "ml", 473.176),
    (3, "tsp", "tbsp", 1.0),
    (6, "feet", "m", 1.8288),
])
def test_conversions(value, f, t, expected):
    assert convert_units(value, f, t)["value"] == pytest.approx(expected, abs=1e-3)


def test_cups_of_flour_to_grams_uses_density():
    result = convert_units(1, "cup", "g", ingredient="flour")
    assert result["value"] == pytest.approx(125.39, abs=0.01)
    assert "flour" in result["note"]


def test_grams_to_cups_defaults_to_water():
    assert convert_units(236.588, "g", "cup")["value"] == pytest.approx(1.0)


def test_incompatible_units():
    assert "error" in convert_units(1, "km", "kg")


def test_unknown_ingredient():
    assert "error" in convert_units(1, "cup", "g", ingredient="unobtainium")
