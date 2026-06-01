"""Expected-value calculation for Kalshi contracts.

Kalshi YES contract: pay `yes_price` cents, win $1 if YES, $0 if NO.
Kalshi fee (per winning contract): 0.07 * yes_price_dollars * (1 - yes_price_dollars).
"""

KALSHI_FEE_COEFFICIENT = 0.07


def kalshi_ev(*, fair_prob_yes: float, yes_price_cents: int) -> float:
    """Return expected value as a fraction of stake, after Kalshi fees.

    EV > 0 means positive expected value (we'd profit on average).
    EV is expressed as a fraction of stake — e.g. 0.063 == +6.3%.

    Args:
        fair_prob_yes: our blended fair probability for YES outcome, in [0, 1]
        yes_price_cents: Kalshi YES contract price in cents, exclusive (0, 100)

    Raises:
        ValueError: If inputs are out of range.
    """
    if not 0.0 <= fair_prob_yes <= 1.0:
        raise ValueError(f"fair_prob_yes out of range: {fair_prob_yes}")
    if not 0 < yes_price_cents < 100:
        raise ValueError(f"yes_price_cents must be in (0, 100): {yes_price_cents}")

    yes_price = yes_price_cents / 100.0
    fee_per_winning_contract = KALSHI_FEE_COEFFICIENT * yes_price * (1.0 - yes_price)
    payout_if_win = 1.0 - fee_per_winning_contract
    expected_profit_per_contract = fair_prob_yes * payout_if_win - yes_price
    return expected_profit_per_contract / yes_price
