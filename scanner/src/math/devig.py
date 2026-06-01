"""Multiplicative devig — strip the vig from a two-sided implied probability pair."""


def devig(implied_over: float, implied_under: float) -> tuple[float, float]:
    """Return (fair_over, fair_under) probabilities that sum to 1.0.

    Standard multiplicative method. Equivalent to:
        fair_over = implied_over / (implied_over + implied_under)

    Raises:
        ValueError: If both inputs are zero (no market).
    """
    total = implied_over + implied_under
    if total <= 0:
        raise ValueError("at least one implied probability must be > 0")
    return implied_over / total, implied_under / total
