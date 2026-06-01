"""Tests for odds conversion helpers."""

import math
from decimal import Decimal

from src.providers.base import american_to_decimal, decimal_to_implied


def test_american_plus_100_is_2():
    assert math.isclose(float(american_to_decimal(100)), 2.0)


def test_american_minus_110():
    # -110 → decimal 1.909...
    assert math.isclose(float(american_to_decimal(-110)), 1.9090909, abs_tol=1e-5)


def test_american_minus_200_is_1_5():
    assert math.isclose(float(american_to_decimal(-200)), 1.5)


def test_decimal_to_implied():
    assert math.isclose(float(decimal_to_implied(Decimal("2.0"))), 0.5)
    assert math.isclose(float(decimal_to_implied(Decimal("1.91"))), 0.5235602, abs_tol=1e-5)
