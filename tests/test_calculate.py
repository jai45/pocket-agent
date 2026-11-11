"""Tests for the safe calculator."""

import pytest

from bot.tools.calculate import calculate


@pytest.mark.parametrize("expr,expected", [
    ("2 + 3 * 4", 14),
    ("(2 + 3) * 4", 20),
    ("2 ** 10", 1024),
    ("17 % 5", 2),
    ("-3 + 1", -2),
    ("10 / 4", 2.5),
    ("round(84.5 * 1.18 / 3, 2)", 33.24),
    ("round(2.567)", 3),
])
def test_valid_expressions(expr, expected):
    assert calculate(expr)["result"] == expected


def test_division_by_zero():
    assert calculate("1 / 0") == {"error": "division by zero"}


@pytest.mark.parametrize("expr", [
    "__import__('os').system('ls')",
    "abs(-1)",
    "x + 1",
    "'a' * 3",
    "[1, 2]",
    "2 +",
])
def test_rejects_anything_but_arithmetic(expr):
    assert "error" in calculate(expr)


def test_huge_exponent_is_refused():
    assert "error" in calculate("9 ** 9 ** 9")


def test_big_number_plus_fraction_keeps_precision():
    # The case that broke with floats: ~1e17 + a fraction lost every decimal.
    result = calculate("838283883 * 838383838 + 83838383 / 737373")["result"]
    assert isinstance(result, str)
    assert result.startswith("702803659163083067.6987426987")
    assert len(result.replace(".", "")) > 40  # ~50 digits, not Python's default 28


def test_classic_float_error_is_gone():
    assert calculate("0.1 + 0.2")["result"] == 0.3


def test_repeating_decimal_returns_digits_as_text():
    assert calculate("1 / 3")["result"].startswith("0.33333333333333333333")


def test_modulo_follows_python_sign_rules():
    assert calculate("-7 % 3")["result"] == 2


def test_fractional_power_falls_back_to_float():
    assert calculate("2 ** 0.5")["result"] == pytest.approx(1.41421356)


def test_fractional_power_of_negative_is_an_error():
    assert "error" in calculate("(-8) ** 0.5")


def test_zero_divided_by_zero():
    assert "error" in calculate("0 / 0")
