from decimal import Decimal
import pytest
from app.tools.calculate import calculate


@pytest.mark.parametrize("expression,expected", [
    ("599.90 + 349.90", "949.80"),
    ("2 * (599.90 - 50)", "1099.80"),
    ("1000 / 3", "333.33"),
    ("-10 + 25", "15.00"),
    ("0.1 + 0.2", "0.30"),
])
def test_arithmetic(expression, expected):
    assert calculate(expression) == Decimal(expected)


@pytest.mark.parametrize("expression", [
    "__import__('os').system('dir')",
    "open('secret.txt')",
    "x + 1",
    "(1).__class__",
    "[1, 2]",
    "9 ** 9 ** 9",
    "2 // 1",
    "True + 1",
    "'a' * 3",
    "599,90 + 1",
])
def test_rejects_anything_that_is_not_plain_arithmetic(expression):
    with pytest.raises(ValueError):
        calculate(expression)


def test_rejects_long_expressions():
    with pytest.raises(ValueError):
        calculate("1 + " * 100 + "1")


def test_division_by_zero():
    with pytest.raises(ValueError):
        calculate("10 / 0")


def test_invalid_syntax():
    with pytest.raises(ValueError):
        calculate("10 +")