"""Rolling per-book Brier weights.

Brier score for a book = mean over settled over/under markets of
(book_fair_prob_over - actual)^2, where actual = 1.0 if the market went over
else 0.0. Lower Brier = better calibrated. Weight = 1 / brier.

Returns {} when no book has >= MIN_SETTLED settled markets — the pipeline then
falls back to COLD_START_WEIGHTS.
"""

import asyncpg

from src.logger import log
from src.repositories.outcomes import book_fair_prob_over, settled_over_under_since

SHARP_BOOKS = ["pinnacle", "novig", "betonline", "draftkings"]
MIN_SETTLED = 100
LOOKBACK_DAYS = 60


async def compute_brier_weights(
    pool: asyncpg.Pool, *, lookback_days: int = LOOKBACK_DAYS, min_settled: int = MIN_SETTLED
) -> dict[str, float]:
    settled = await settled_over_under_since(pool, days=lookback_days)
    if not settled:
        return {}

    sum_sq: dict[str, float] = {b: 0.0 for b in SHARP_BOOKS}
    counts: dict[str, int] = {b: 0 for b in SHARP_BOOKS}

    for market in settled:
        actual = 1.0 if market.outcome == "over" else 0.0
        for book in SHARP_BOOKS:
            prob = await book_fair_prob_over(pool, market.market_id, book)
            if prob is None:
                continue
            sum_sq[book] += (prob - actual) ** 2
            counts[book] += 1

    weights: dict[str, float] = {}
    for book in SHARP_BOOKS:
        if counts[book] < min_settled:
            continue
        brier = sum_sq[book] / counts[book]
        if brier <= 0:
            brier = 1e-6
        weights[book] = 1.0 / brier

    log.info("brier_weights_computed", weights=weights, counts=counts)
    return weights
