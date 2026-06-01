"""Property-based tests for math module invariants."""

import math

from hypothesis import given, strategies as st

from src.math.blend import blended_fair_prob
from src.math.consensus import COLD_START_WEIGHTS, brier_weighted_consensus
from src.math.devig import devig
from src.math.kelly import kelly_stake_cents


@given(
    over=st.floats(min_value=0.01, max_value=0.99),
    under=st.floats(min_value=0.01, max_value=0.99),
)
def test_devig_outputs_sum_to_one(over, under):
    fair_over, fair_under = devig(over, under)
    assert math.isclose(fair_over + fair_under, 1.0, abs_tol=1e-9)


@given(
    over=st.floats(min_value=0.01, max_value=0.99),
    under=st.floats(min_value=0.01, max_value=0.99),
)
def test_devig_outputs_in_unit_interval(over, under):
    fair_over, fair_under = devig(over, under)
    assert 0.0 <= fair_over <= 1.0
    assert 0.0 <= fair_under <= 1.0


@given(
    pinnacle=st.floats(min_value=0.01, max_value=0.99),
    novig=st.floats(min_value=0.01, max_value=0.99),
)
def test_consensus_in_unit_interval(pinnacle, novig):
    result = brier_weighted_consensus(
        fair_probs={"pinnacle": pinnacle, "novig": novig},
        weights=COLD_START_WEIGHTS,
    )
    assert 0.0 <= result <= 1.0


@given(
    consensus=st.floats(min_value=0.01, max_value=0.99),
    projection=st.floats(min_value=0.01, max_value=0.99),
    weight=st.floats(min_value=0.0, max_value=1.0),
)
def test_blend_in_unit_interval(consensus, projection, weight):
    result = blended_fair_prob(
        consensus_prob=consensus,
        projection_prob=projection,
        projection_weight=weight,
    )
    assert 0.0 <= result <= 1.0


@given(
    fair_prob=st.floats(min_value=0.0, max_value=1.0),
    decimal_odds=st.floats(min_value=1.01, max_value=20.0),
    bankroll=st.integers(min_value=0, max_value=10_000_000),
)
def test_kelly_stake_never_exceeds_cap(fair_prob, decimal_odds, bankroll):
    cap_pct = 0.05
    stake = kelly_stake_cents(
        fair_prob=fair_prob,
        decimal_odds=decimal_odds,
        bankroll_cents=bankroll,
        cap_pct=cap_pct,
    )
    assert stake <= int(bankroll * cap_pct) + 1  # +1 for int rounding
