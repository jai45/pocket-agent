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
