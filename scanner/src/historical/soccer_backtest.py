"""Soccer player-prop backtest — EPL (the one league with both prop odds and
overlapping outcomes).

Mirrors the NBA backtest: for every historical (event, market, player, line)
with >=2 books quoting both sides, devig per book -> consensus, then look up
the player's actual stat in soccer_player_match_stats and score the bet.

Market -> stat column:
  player_shots            -> shots
  player_shots_on_target  -> shots_on_target
  player_assists          -> assists

Run: python -m src.historical.soccer_backtest --threshold 0.02
"""

import argparse
import asyncio
import re
import unicodedata
from collections import defaultdict

from src.config import settings
from src.db import close_pool, get_pool
from src.historical.backtest import BetResult, _summarize
from src.logger import configure_logging, log

MARKET_TO_COLUMN = {
    "player_shots": "shots",
    "player_shots_on_target": "shots_on_target",
    "player_assists": "assists",
}


def _slug(name: str) -> str:
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z]+", "", ascii_only).upper()


def _dec(american: int) -> float:
    return american / 100.0 + 1.0 if american > 0 else 100.0 / abs(american) + 1.0


async def _lookup_actual(pool, *, slug: str, column: str, match_date) -> int | None:
    row = await pool.fetchrow(
        f"""
        SELECT {column} AS v FROM soccer_player_match_stats
        WHERE player_name_slug = $1
          AND match_date BETWEEN $2::date - 1 AND $2::date + 1
        ORDER BY (source='fbref') DESC, abs(match_date - $2::date)
        LIMIT 1
        """,
        slug, match_date,
    )
    return int(row["v"]) if row and row["v"] is not None else None


async def run(threshold: float = 0.02, min_books: int = 2) -> dict:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT event_id, event_start, market_key, player_name, line,
                   array_agg(book ORDER BY book) AS books,
                   array_agg(side ORDER BY book) AS sides,
                   array_agg(american_odds ORDER BY book) AS odds
            FROM historical_odds_snapshots
            WHERE sport_key = 'soccer_epl' AND market_key = ANY($1::text[])
              AND player_name IS NOT NULL AND line IS NOT NULL
            GROUP BY event_id, event_start, market_key, player_name, line
            """,
            list(MARKET_TO_COLUMN.keys()),
        )
        log.info("soccer_backtest_opportunities", count=len(rows))

        bets: list[BetResult] = []
        skipped = defaultdict(int)
        for r in rows:
            per_book: dict[str, dict[str, int]] = defaultdict(dict)
            for b, s, o in zip(r["books"], r["sides"], r["odds"]):
                per_book[b][s] = o
            fair_overs = {}
            for b, ss in per_book.items():
                if "over" in ss and "under" in ss:
                    oi, ui = 1.0 / _dec(ss["over"]), 1.0 / _dec(ss["under"])
                    if oi + ui > 0:
                        fair_overs[b] = oi / (oi + ui)
            if len(fair_overs) < min_books:
                skipped["min_books"] += 1
                continue
            consensus_over = sum(fair_overs.values()) / len(fair_overs)

            col = MARKET_TO_COLUMN[r["market_key"]]
            actual = await _lookup_actual(
                pool, slug=_slug(r["player_name"]), column=col,
                match_date=r["event_start"].date(),
            )
            if actual is None:
                skipped["no_outcome"] += 1
                continue
            line = float(r["line"])
            for side, fair in (("over", consensus_over), ("under", 1 - consensus_over)):
                quotes = [(b, _dec(per_book[b][side])) for b in per_book if side in per_book[b]]
                if not quotes:
                    continue
                book_used, best = max(quotes, key=lambda t: t[1])
                edge = fair - 1.0 / best
                if edge < threshold:
                    continue
                won = actual > line if side == "over" else actual < line
                pushed = actual == line
                ret = 0.0 if pushed else (best - 1.0 if won else -1.0)
                bets.append(BetResult(
                    market=r["market_key"], player=r["player_name"], line=line,
                    side=side, decimal_odds=best, fair_prob=fair, consensus_prob=fair,
                    projection_prob=None, edge=edge, actual_stat=actual, won=won,
                    pushed=pushed, return_per_unit=ret, book=book_used,
                    event_date=r["event_start"].date(),
                ))

        summary = _summarize(bets)
        by_market = defaultdict(list)
        for b in bets:
            by_market[b.market].append(b)
        log.info("soccer_backtest_complete", bets=len(bets), skipped=dict(skipped), **summary)
        return {"summary": summary, "per_market": {m: _summarize(bs) for m, bs in by_market.items()},
                "skipped": dict(skipped), "bets": bets}
    finally:
        await close_pool()


def _fmt(s, label):
    if s["n"] == 0:
        return f"  {label:24s} n=   0"
    flag = "🟢" if s["roi_pct"] > 0 else "🔴"
    return f"  {label:24s} n={s['n']:4d}  wr={s['win_rate']*100:5.1f}%  ROI={s['roi_pct']:+6.2f}%  edge={s['avg_edge_pct']:+5.2f}%  {flag}"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=float, default=0.02)
    p.add_argument("--min-books", type=int, default=2)
    a = p.parse_args()
    res = asyncio.run(run(a.threshold, a.min_books))
    print(f"\nEPL SOCCER PROP BACKTEST · threshold {a.threshold*100:.0f}%")
    print(_fmt(res["summary"], "ALL"))
    for m, s in sorted(res["per_market"].items()):
        print(_fmt(s, m.replace("player_", "")))
    print(f"  skipped: {res['skipped']}")
