"""Tests for distribution → P(actual > line) conversion."""

import math

import pytest

from src.math.distributions import STAT_DISTRIBUTIONS, fair_prob_over


def test_normal_at_mean_is_half():
    # If line == mean (with continuity correction at line+0.5),
    # P(over) should be slightly below 0.5.
    p = fair_prob_over(mean=25.0, std=5.0, line=25.0, distribution="normal")
    assert 0.4 < p < 0.5


def test_normal_far_below_line_is_low():
    p = fair_prob_over(mean=10.0, std=2.0, line=25.0, distribution="normal")
    assert p < 0.01


def test_normal_far_above_line_is_high():
    p = fair_prob_over(mean=40.0, std=2.0, line=25.0, distribution="normal")
    assert p > 0.99


def test_negbin_at_low_line_high_prob():
    # μ=8 rebounds, line 3.5 → very likely over
    p = fair_prob_over(mean=8.0, std=3.0, line=3.5, distribution="negative_binomial")
    assert p > 0.85


def test_negbin_at_high_line_low_prob():
    p = fair_prob_over(mean=8.0, std=3.0, line=15.5, distribution="negative_binomial")
    assert p < 0.05


def test_unknown_distribution_raises():
    with pytest.raises(ValueError, match="unsupported distribution"):
        fair_prob_over(mean=10.0, std=2.0, line=5.0, distribution="cauchy")


def test_stat_distributions_mapping():
    assert STAT_DISTRIBUTIONS["points"] == "normal"
    assert STAT_DISTRIBUTIONS["pra"] == "normal"
    assert STAT_DISTRIBUTIONS["rebounds"] == "negative_binomial"
    assert STAT_DISTRIBUTIONS["assists"] == "negative_binomial"
    assert STAT_DISTRIBUTIONS["threes"] == "negative_binomial"
