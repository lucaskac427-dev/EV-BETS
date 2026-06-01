"""Single-tick orchestrator.

Calls all providers in parallel, devigs each sharp book's two-sided market,
computes Brier-weighted consensus, blends with projection (None in Plan 1),
computes Kalshi EV after fees, sizes Kelly stake, writes opportunity.
"""

import asyncio
import time
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from src.config import settings
from src.kalshi.adapter import KalshiAdapter
from src.logger import log
from src.math.blend import blended_fair_prob
from src.math.consensus import COLD_START_WEIGHTS, brier_weighted_consensus
from src.math.devig import devig
from src.math.ev import kalshi_ev
from src.math.kelly import kelly_stake_cents
from src.math.projection_weight import current_projection_weight
from src.providers.base import OddsProvider, OddsQuote
from src.repositories.bankroll import current_bankroll_cents
from src.repositories.markets import fetch_active_markets
from src.repositories.opportunities import insert_opportunity
from src.repositories.projections import latest_projection_prob
from src.repositories.snapshots import OddsSnapshot, bulk_insert_snapshots
from src.repositories.telemetry import record_event


async def run_scan_tick(
    *,
    pool,
    sharp_providers: list[OddsProvider],
    kalshi: KalshiAdapter,
    days_since_launch: int = 0,
    consensus_weights: dict[str, float] | None = None,
) -> int:
    """Execute one full scan tick. Returns number of opportunities written."""
    tick_id = uuid.uuid4().hex
    tick_start = time.monotonic()
    weights = consensus_weights or COLD_START_WEIGHTS
    log.info("tick_start", tick_id=tick_id)

    markets = await fetch_active_markets(pool)
    if not markets:
        log.info("tick_no_markets", tick_id=tick_id)
        await record_event(pool, tick_id=tick_id, source="pipeline", event_type="tick_complete")
        return 0

    kalshi_tickers = [m.kalshi_ticker for m in markets]

    # Fan out all providers + Kalshi in parallel. Sharp providers take a list
    # of tickers (ignored — they scrape everything); Kalshi takes the full
    # Market objects so it can synthesize canonical tickers.
    tasks = [
        _provider_call(pool, tick_id, p, kalshi_tickers) for p in sharp_providers
    ] + [_provider_call(pool, tick_id, kalshi, markets)]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    all_quotes: list[OddsQuote] = [q for sub in results for q in sub]

    # Index by the canonical synth ticker so sharp-book quotes (already on the
    # synth namespace) join Kalshi quotes (which the adapter also maps onto it).
    market_by_ticker = {kalshi.synth_ticker_for(m): m for m in markets}
    snapshots: list[OddsSnapshot] = []
    for q in all_quotes:
        m = market_by_ticker.get(q.market_kalshi_ticker)
        if m is None:
            continue
        snapshots.append(
            OddsSnapshot(
                market_id=m.id,
                book=q.book,
                side=q.side,
                decimal_odds=q.decimal_odds,
                implied_prob=q.implied_prob,
            )
        )
    if snapshots:
        await bulk_insert_snapshots(pool, snapshots)

    quotes_by_market: dict[str, list[OddsQuote]] = defaultdict(list)
    for q in all_quotes:
        quotes_by_market[q.market_kalshi_ticker].append(q)

    bankroll = await current_bankroll_cents(pool)
    proj_weight = current_projection_weight(days_since_launch)

    opps_written = 0
    for ticker, quotes in quotes_by_market.items():
        market = market_by_ticker.get(ticker)
        if market is None:
            continue

        projection_prob = await latest_projection_prob(pool, market.id)
        ev_result = _compute_market_ev(quotes, proj_weight, projection_prob, weights)
        if ev_result is None:
            continue

        (ev_pct, side, kalshi_decimal_odds, consensus_prob,
         blended_prob, projection_for_side, num_books) = ev_result
        if ev_pct < settings.min_ev_threshold:
            continue

        suspicious = ev_pct > settings.suspicious_ev_threshold
        stake = kelly_stake_cents(
            fair_prob=blended_prob,
            decimal_odds=float(kalshi_decimal_odds),
            bankroll_cents=bankroll,
            fraction=settings.kelly_fraction,
            cap_pct=settings.kelly_cap_pct,
        )
        kelly_fraction = Decimal(stake) / Decimal(bankroll) if bankroll > 0 else None

        await insert_opportunity(
            pool,
            market_id=market.id,
            kalshi_side=side,
            kalshi_decimal_odds=kalshi_decimal_odds,
            consensus_fair_prob=Decimal(str(round(consensus_prob, 6))),
            projection_fair_prob=(
                Decimal(str(round(projection_for_side, 6)))
                if projection_for_side is not None else None
            ),
            blended_fair_prob=Decimal(str(round(blended_prob, 6))),
            ev_pct=Decimal(str(round(ev_pct, 4))),
            kelly_fraction=kelly_fraction,
            num_sharp_books=num_books,
            suspicious=suspicious,
        )
        opps_written += 1

    latency_ms = int((time.monotonic() - tick_start) * 1000)
    await record_event(
        pool, tick_id=tick_id, source="pipeline",
        event_type="tick_complete", latency_ms=latency_ms,
        status_detail=f"opps={opps_written}",
    )
    log.info("tick_complete", tick_id=tick_id, opps_written=opps_written, latency_ms=latency_ms)
    return opps_written


async def _provider_call(
    pool, tick_id: str, provider, kalshi_tickers: list[str]
) -> list[OddsQuote]:
    start = time.monotonic()
    try:
        quotes = await provider.fetch_odds(kalshi_tickers)
        latency_ms = int((time.monotonic() - start) * 1000)
        await record_event(
            pool, tick_id=tick_id, source=provider.name,
            event_type="fetch_success", latency_ms=latency_ms,
        )
        return quotes
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        await record_event(
            pool, tick_id=tick_id, source=provider.name,
            event_type="fetch_failure", latency_ms=latency_ms,
            status_detail=str(e)[:500],
        )
        log.warning("provider_fetch_failed", source=provider.name, error=str(e))
        return []


def _compute_market_ev(
    quotes: list[OddsQuote],
    projection_weight: float,
    projection_prob_over: float | None,
    weights: dict[str, float],
) -> tuple[float, str, Decimal, float, float, float | None, int] | None:
    """For one market's quotes, return (ev_pct, kalshi_side, kalshi_decimal_odds,
    consensus_prob, blended_prob, projection_prob_for_side, num_sharp_books) for
    the side with positive edge, or None if no edge / not enough data.
    """
    sharp_quotes: dict[str, dict[str, OddsQuote]] = defaultdict(dict)
    kalshi_yes: OddsQuote | None = None
    kalshi_no: OddsQuote | None = None

    for q in quotes:
        if q.book == "kalshi":
            if q.side == "yes":
                kalshi_yes = q
            elif q.side == "no":
                kalshi_no = q
        else:
            sharp_quotes[q.book][q.side] = q

    if kalshi_yes is None or kalshi_no is None:
        return None

    fair_over_per_book: dict[str, float] = {}
    for book, sides in sharp_quotes.items():
        if "over" not in sides or "under" not in sides:
            continue
        try:
            fair_over, _ = devig(
                float(sides["over"].implied_prob),
                float(sides["under"].implied_prob),
            )
            fair_over_per_book[book] = fair_over
        except ValueError:
            continue

    num_books = len(fair_over_per_book)
    if num_books < settings.min_sharp_books:
        return None

    safe_weights = dict(weights)
    for book in fair_over_per_book:
        if book not in safe_weights:
            safe_weights[book] = COLD_START_WEIGHTS.get(book, 0.5)
    consensus_over = brier_weighted_consensus(
        fair_probs=fair_over_per_book,
        weights=safe_weights,
    )
    consensus_under = 1.0 - consensus_over

    blended_over = blended_fair_prob(
        consensus_prob=consensus_over,
        projection_prob=projection_prob_over,
        projection_weight=projection_weight,
    )
    blended_under = 1.0 - blended_over
    projection_under = (1.0 - projection_prob_over) if projection_prob_over is not None else None

    yes_ev = kalshi_ev(
        fair_prob_yes=blended_over,
        yes_price_cents=int(round(float(kalshi_yes.implied_prob) * 100)),
    )
    no_ev = kalshi_ev(
        fair_prob_yes=blended_under,
        yes_price_cents=int(round(float(kalshi_no.implied_prob) * 100)),
    )

    if yes_ev >= no_ev:
        return (yes_ev, "yes", kalshi_yes.decimal_odds, consensus_over,
                blended_over, projection_prob_over, num_books)
    return (no_ev, "no", kalshi_no.decimal_odds, consensus_under,
            blended_under, projection_under, num_books)
