"""Blend market consensus probability with projection probability."""


def blended_fair_prob(
    *,
    consensus_prob: float,
    projection_prob: float | None,
    projection_weight: float,
) -> float:
    """Return the blended fair probability for the YES/over side.

    Formula:  (1 - w) * consensus + w * projection
    If projection_prob is None, returns consensus_prob unchanged.

    Raises:
        ValueError: If projection_weight is outside [0, 1].
    """
    if not 0.0 <= projection_weight <= 1.0:
        raise ValueError(f"projection_weight out of range: {projection_weight}")

    if projection_prob is None:
        return consensus_prob

    return (1.0 - projection_weight) * consensus_prob + projection_weight * projection_prob
