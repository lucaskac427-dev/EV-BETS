"""Tests for Brier-weighted consensus across multiple books."""

import math

import pytest

from src.math.consensus import COLD_START_WEIGHTS, brier_weighted_consensus


def test_single_book_returns_its_probability():
    result = brier_weighted_consensus(
        fair_probs={"pinnacle": 0.55},
        weights={"pinnacle": 1.0},
    )
    assert math.isclose(result, 0.55, abs_tol=1e-9)


def test_equal_weights_returns_arithmetic_mean():
    result = brier_weighted_consensus(
        fair_probs={"pinnacle": 0.6, "novig": 0.5},
        weights={"pinnacle": 1.0, "novig": 1.0},
    )
    assert math.isclose(result, 0.55, abs_tol=1e-9)


def test_higher_weight_pulls_result():
    # Pinnacle weight 10x → result much closer to 0.6 than 0.5
    result = brier_weighted_consensus(
        fair_probs={"pinnacle": 0.6, "draftkings": 0.5},
        weights={"pinnacle": 1.0, "draftkings": 0.1},
    )
    assert result > 0.58


def test_unknown_book_in_probs_raises():
    with pytest.raises(ValueError, match="weight missing"):
        brier_weighted_consensus(
            fair_probs={"pinnacle": 0.55, "betonline": 0.56},
            weights={"pinnacle": 1.0},
        )


def test_empty_input_raises():
    with pytest.raises(ValueError, match="no books"):
        brier_weighted_consensus(fair_probs={}, weights={})


def test_cold_start_weights_pinnacle_highest():
    assert COLD_START_WEIGHTS["pinnacle"] >= COLD_START_WEIGHTS["novig"]
    assert COLD_START_WEIGHTS["novig"] >= COLD_START_WEIGHTS["betonline"]
    assert COLD_START_WEIGHTS["betonline"] >= COLD_START_WEIGHTS["draftkings"]
