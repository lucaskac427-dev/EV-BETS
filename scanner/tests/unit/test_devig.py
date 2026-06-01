"""Tests for multiplicative devig — removing the vig from a two-sided market."""

import math

import pytest

from src.math.devig import devig


def test_devig_balanced_minus_110():
    # -110 / -110 → implied 0.524 / 0.524 → fair 0.5 / 0.5
    fair_over, fair_under = devig(0.524, 0.524)
    assert math.isclose(fair_over, 0.5, abs_tol=1e-9)
    assert math.isclose(fair_under, 0.5, abs_tol=1e-9)


def test_devig_skewed_favorite():
    # -150 / +130 → 0.6 / 0.435 (raw) → fair ~0.580 / ~0.420
    fair_over, fair_under = devig(0.6, 0.435)
    assert math.isclose(fair_over + fair_under, 1.0, abs_tol=1e-9)
    assert fair_over > fair_under


def test_devig_sums_to_one():
    fair_over, fair_under = devig(0.55, 0.5)
    assert math.isclose(fair_over + fair_under, 1.0, abs_tol=1e-9)


def test_devig_zero_inputs_raises():
    with pytest.raises(ValueError):
        devig(0.0, 0.0)
