"""Tests for linear projection weight ramp 0.20 → 0.40 over 90 days."""

import math

from src.math.projection_weight import current_projection_weight


def test_day_zero_is_start():
    assert math.isclose(current_projection_weight(0), 0.20, abs_tol=1e-9)


def test_day_ninety_is_end():
    assert math.isclose(current_projection_weight(90), 0.40, abs_tol=1e-9)


def test_day_forty_five_is_midpoint():
    assert math.isclose(current_projection_weight(45), 0.30, abs_tol=1e-9)


def test_after_ninety_stays_end():
    assert math.isclose(current_projection_weight(120), 0.40, abs_tol=1e-9)


def test_negative_days_clamps_to_start():
    assert math.isclose(current_projection_weight(-5), 0.20, abs_tol=1e-9)
