"""Tests for Kalshi EV calculation with fee adjustment.

Kalshi fee = 0.07 * yes_price * (1 - yes_price) per winning contract.
"""

import math

import pytest

from src.math.ev import kalshi_ev


def test_zero_edge_returns_zero():
    # Fair = 0.50, YES = 50¢ → no edge
    ev = kalshi_ev(fair_prob_yes=0.50, yes_price_cents=50)
    assert ev < 0  # slightly negative due to fee
    assert ev > -0.05


def test_positive_edge():
    # Fair = 0.60, YES = 50¢ → strong +EV
    ev = kalshi_ev(fair_prob_yes=0.60, yes_price_cents=50)
    assert ev > 0.15


def test_negative_edge():
    ev = kalshi_ev(fair_prob_yes=0.40, yes_price_cents=50)
    assert ev < -0.15


def test_fee_eats_some_edge():
    ev_with_fee = kalshi_ev(fair_prob_yes=0.55, yes_price_cents=50)
    # Without fee, EV would be (0.55 * 1.0) / 0.50 - 1 = +10.0%
    # With 0.07 * 0.5 * 0.5 = 0.0175 fee per win, payout = 0.9825
    # EV = 0.55 * 0.9825 / 0.50 - 1 = +8.08%
    assert math.isclose(ev_with_fee, 0.55 * 0.9825 / 0.50 - 1, abs_tol=1e-6)


def test_invalid_yes_price_raises():
    with pytest.raises(ValueError):
        kalshi_ev(fair_prob_yes=0.5, yes_price_cents=0)
    with pytest.raises(ValueError):
        kalshi_ev(fair_prob_yes=0.5, yes_price_cents=100)


def test_invalid_prob_raises():
    with pytest.raises(ValueError):
        kalshi_ev(fair_prob_yes=-0.1, yes_price_cents=50)
    with pytest.raises(ValueError):
        kalshi_ev(fair_prob_yes=1.1, yes_price_cents=50)
