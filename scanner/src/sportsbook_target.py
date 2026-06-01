"""Sportsbook-target scanner — find +EV bets AT a soft book vs sharp consensus.

DFS pick'em (PrizePicks/Underdog/Sleeper) use a fixed-multiplier breakeven.
A real sportsbook like Hard Rock posts its own two-sided odds, so the model
is different: compute consensus from every OTHER book, then bet at the target
book wherever its price beats that consensus.

  edge(side) = consensus_fair(side) − target_implied(side)
  you bet the target's actual posted odds, so EV = fair × target_decimal − 1.

Hard Rock Bet (hardrockbet_fl) is Florida's only legal mobile sportsbook, so
it's the natural target. Generalizes to any book key.

Run: python -m src.sportsbook_target --target hardrockbet_fl --min-edge 0.02
"""

import argparse
import asyncio
from collections import defaultdict

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging
from src.providers.sport_config import NBA_ODDS
from src.providers.the_odds_api import OddsAPIProvider


def _implied(decimal: float) -> float:
    return 1.0 / decimal if decimal > 0 else 0.0


async def scan(target: str, min_edge: float, min_ref_books: int = 3) -> list[dict]:
    odds = OddsAPIProvider(config=NBA_ODDS)
    try:
        quotes = await odds.fetch_odds([])
    finally:
        await odds.aclose()

    # ticker -> book -> side -> quote
    by_ticker: dict[str, dict[str, dict[str, object]]] = defaultdict(lambda: defaultdict(dict))
    for q in quotes:
        by_ticker[q.market_kalshi_ticker][q.book][q.side] = q

    bets: list[dict] = []
    for ticker, per_book in by_ticker.items():
        if target not in per_book:
            continue  # target doesn't offer this market
        # Sharp reference consensus from every OTHER book with both sides
        fair_overs = []
        for book, sides in per_book.items():
            if book == target:
                continue
            over, under = sides.get("over"), sides.get("under")
            if not over or not under:
                continue
            oi, ui = float(over.implied_prob), float(under.implied_prob)
            if oi + ui > 0:
                fair_overs.append(oi / (oi + ui))
        if len(fair_overs) < min_ref_books:
            continue
        consensus_over = sum(fair_overs) / len(fair_overs)

        tsides = per_book[target]
        for side, fair in (("over", consensus_over), ("under", 1 - consensus_over)):
            tq = tsides.get(side)
            if not tq:
                continue
            target_dec = float(tq.decimal_odds)
            edge = fair * target_dec - 1.0  # true EV at the target's own price
            if edge < min_edge:
                continue
            bets.append({
                "ticker": ticker, "side": side, "fair": fair,
                "target_decimal": target_dec, "edge": edge,
                "ref_books": len(fair_overs),
            })
    bets.sort(key=lambda b: -b["edge"])
    return bets


async def main(target: str, min_edge: float) -> None:
    configure_logging(level="WARNING")
    pool = await get_pool()
    try:
        bets = await scan(target, min_edge)
        print(f"\n  {target.upper()} TARGET SCAN · {len(bets)} bets ≥ {min_edge*100:.0f}% EV")
        print("  " + "─" * 74)
        if not bets:
            print("  No +EV bets at this book right now.")
        for b in bets[:40]:
            # ticker = SYN-NBA-PLAYERSLUG-STAT-LINE
            parts = b["ticker"].split("-")
            player = parts[2] if len(parts) > 2 else "?"
            stat = parts[3].lower() if len(parts) > 3 else "?"
            line = parts[4] if len(parts) > 4 else "?"
            am = (f"+{int(round((b['target_decimal']-1)*100))}" if b['target_decimal'] >= 2
                  else f"-{int(round(100/(b['target_decimal']-1)))}")
            print(f"  {player:22s} {b['side'].upper():5s} {line:5s} {stat:9s} | "
                  f"{am:5s} | fair {b['fair']*100:4.1f}% | EV +{b['edge']*100:5.2f}% | "
                  f"{b['ref_books']} ref books")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="hardrockbet_fl")
    p.add_argument("--min-edge", type=float, default=0.02)
    a = p.parse_args()
    asyncio.run(main(a.target, a.min_edge))
