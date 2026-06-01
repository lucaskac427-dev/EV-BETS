"""Tests for blending consensus probability with projection probability."""

import math

import pytest

from src.math.blend import blended_fair_prob


def test_no_projection_returns_consensus():
    result = blended_fair_prob(
        consensus_prob=0.55, projection_prob=None, projection_weight=0.4
    )
    assert math.isclose(result, 0.55, abs_tol=1e-9)


def test_full_blend_at_weight_zero_returns_consensus():
    result = blended_fair_prob(
        consensus_prob=0.55, projection_prob=0.65, projection_weight=0.0
    )
    assert math.isclose(result, 0.55, abs_tol=1e-9)


def test_full_blend_at_weight_one_returns_projection():
    result = blended_fair_prob(
        consensus_prob=0.55, projection_prob=0.65, projection_weight=1.0
    )
    assert math.isclose(result, 0.65, abs_tol=1e-9)


def test_blend_at_weight_point_four():
    # 0.6 * 0.55 + 0.4 * 0.65 = 0.33 + 0.26 = 0.59
    result = blended_fair_prob(
        consensus_prob=0.55, projection_prob=0.65, projection_weight=0.4
    )
    assert math.isclose(result, 0.59, abs_tol=1e-9)


def test_invalid_weight_raises():
    with pytest.raises(ValueError):
        blended_fair_prob(consensus_prob=0.5, projection_prob=0.6, projection_weight=-0.1)
    with pytest.raises(ValueError):
        blended_fair_prob(consensus_prob=0.5, projection_prob=0.6, projection_weight=1.1)
