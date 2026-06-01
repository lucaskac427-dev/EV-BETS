"""Fractional Kelly stake sizing with hard cap."""


def kelly_stake_cents(
    *,
    fair_prob: float,
    decimal_odds: float,
    bankroll_cents: int,
    fraction: float = 0.25,
    cap_pct: float = 0.05,
) -> int:
    """Return the recommended stake in cents.

    Full Kelly = (b*p - q) / b, where b = decimal_odds - 1, q = 1 - p.
    Then we scale by `fraction` (quarter-Kelly default) and clamp at `cap_pct` of bankroll.

    Args:
        fair_prob: our fair probability the bet wins, in [0, 1]
        decimal_odds: > 1.0 (e.g. 2.0 for +100, 1.91 for -110)
        bankroll_cents: integer bankroll in cents
        fraction: fraction of full Kelly to deploy (0.25 default)
        cap_pct: max fraction of bankroll per bet (0.05 default)

    Returns:
        Stake in cents (integer, floor).

    Raises:
        ValueError: If inputs are out of range.
    """
    if not 0.0 <= fair_prob <= 1.0:
        raise ValueError(f"fair_prob out of range: {fair_prob}")
    if decimal_odds <= 1.0:
        raise ValueError(f"decimal_odds must be > 1.0: {decimal_odds}")
    if bankroll_cents < 0:
        raise ValueError(f"bankroll_cents must be >= 0: {bankroll_cents}")

    b = decimal_odds - 1.0
    p = fair_prob
    q = 1.0 - p
    full_kelly_pct = (b * p - q) / b
    if full_kelly_pct <= 0:
        return 0

    sized_pct = min(full_kelly_pct * fraction, cap_pct)
    return int(bankroll_cents * sized_pct)
