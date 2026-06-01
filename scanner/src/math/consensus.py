"""Brier-weighted consensus blending across multiple books.

Brier score = mean squared error of (predicted_prob - actual_outcome)
over the rolling 60-day window. Lower = more accurate book.
Weight = 1 / brier; we normalize across input books.

Plan 1 uses the cold-start weights below until Brier scores exist
(Plan 2 implements the rolling recompute).
"""

COLD_START_WEIGHTS: dict[str, float] = {
    "pinnacle": 1.00,
    "novig": 0.90,
    "betonline": 0.70,
    "draftkings": 0.40,
}


def brier_weighted_consensus(
    fair_probs: dict[str, float],
    weights: dict[str, float],
) -> float:
    """Weighted average of fair probabilities across books.

    Args:
        fair_probs: book name -> devigged fair probability for the side we care about
        weights: book name -> weight (typically COLD_START_WEIGHTS or 1/brier)

    Returns:
        Single consensus probability in [0, 1].

    Raises:
        ValueError: If fair_probs is empty or a book has no weight.
    """
    if not fair_probs:
        raise ValueError("no books in fair_probs")
    for book in fair_probs:
        if book not in weights:
            raise ValueError(f"weight missing for book {book!r}")

    total_weight = sum(weights[b] for b in fair_probs)
    if total_weight <= 0:
        raise ValueError("total weight must be > 0")

    return sum(fair_probs[b] * weights[b] for b in fair_probs) / total_weight
