"""Tests for fractional Kelly stake sizing with cap."""

import math

import pytest

from src.math.kelly import kelly_stake_cents


def test_no_edge_zero_stake():
    stake = kelly_stake_cents(
        fair_prob=0.5, decimal_odds=2.0, bankroll_cents=100_000
    )
    assert stake == 0


def test_negative_edge_zero_stake():
    stake = kelly_stake_cents(
        fair_prob=0.4, decimal_odds=2.0, bankroll_cents=100_000
    )
    assert stake == 0


def test_positive_edge_quarter_kelly_default():
    # Full Kelly: (b*p - q) / b
    # b = decimal_odds - 1 = 1.0
    # p = 0.55, q = 0.45
    # kelly = (1.0 * 0.55 - 0.45) / 1.0 = 0.10
    # quarter = 0.025 → 2.5% of $1000 = $25 = 2500c
    stake = kelly_stake_cents(
        fair_prob=0.55, decimal_odds=2.0, bankroll_cents=100_000, fraction=0.25
    )
    assert stake == 2500


def test_cap_enforces_max():
    # Huge edge — full Kelly would say bet more than cap
    # cap = 5% of 100k cents = 5000c
    stake = kelly_stake_cents(
        fair_prob=0.95, decimal_odds=2.0, bankroll_cents=100_000,
        fraction=0.25, cap_pct=0.05,
    )
    assert stake == 5000


def test_zero_bankroll_zero_stake():
    stake = kelly_stake_cents(
        fair_prob=0.9, decimal_odds=2.0, bankroll_cents=0
    )
    assert stake == 0


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        kelly_stake_cents(fair_prob=1.5, decimal_odds=2.0, bankroll_cents=100_000)
    with pytest.raises(ValueError):
        kelly_stake_cents(fair_prob=0.5, decimal_odds=0.5, bankroll_cents=100_000)
