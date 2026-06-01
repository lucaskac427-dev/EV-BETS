"""Per-book ROI — which sportsbooks are SOFT (beatable) vs SHARP (trustworthy).

For every historical prop where our consensus flagged an edge, we record the
result of betting that edge AT each book that offered the price. Rolled up:

  - High ROI  -> the book is SOFT (its prices are often wrong in your favor).
                 Great to bet against; a NOISIER vote in the consensus.
  - ~0 / neg  -> the book is SHARP (you can't beat it). A BETTER vote for the
                 fair number — an edge that survives a sharp book is the real deal.

One pass over all opportunities + in-memory outcomes (reuses the backtest's
loaders). Writes book_roi so the dashboard can show the ranking.

Run: python -m src.historical.book_roi
"""

import argparse
import asyncio
from collections import defaultdict

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.historical.backtest import (
    NBA_MARKET_TO_COLUMN,
    _decimal_from_american,
    _load_outcomes,
    _lookup_actual,
)

_CREATE = """
CREATE TABLE IF NOT EXISTS book_roi (
    book          TEXT NOT NULL,
    sport         TEXT NOT NULL,
    threshold     NUMERIC NOT NULL,
    n_bets        INT NOT NULL,
    wins          INT NOT NULL,
    losses        INT NOT NULL,
    pushes        INT NOT NULL,
    win_rate      NUMERIC,
    roi_pct       NUMERIC,
    avg_edge_pct  NUMERIC,
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (book, sport, threshold)
);
"""


async def compute_book_roi(
    sport: str = "basketball_nba", *, threshold: float = 0.03, min_books: int = 2
) -> dict[str, dict]:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        await pool.execute(_CREATE)
        rows = await pool.fetch(
            """
            SELECT event_id, event_start, market_key, player_name, line,
                   array_agg(book ORDER BY book)          AS books,
                   array_agg(side ORDER BY book)          AS sides,
                   array_agg(american_odds ORDER BY book) AS odds
            FROM historical_odds_snapshots
            WHERE sport_key = $1 AND market_key = ANY($2::text[])
              AND player_name IS NOT NULL AND line IS NOT NULL
            GROUP BY event_id, event_start, market_key, player_name, line
            """,
            sport, list(NBA_MARKET_TO_COLUMN.keys()),
            timeout=300,  # heavy aggregation over a 30M-row table — override the 10s pool default
        )
        outcomes = await _load_outcomes(pool)
        log.info("book_roi_loaded", opportunities=len(rows), outcomes=len(outcomes))

        agg: dict[str, dict] = defaultdict(
            lambda: {"n": 0, "wins": 0, "losses": 0, "pushes": 0, "ret": 0.0, "edge": 0.0}
        )

        for r in rows:
            line = float(r["line"])
            per_book: dict[str, dict[str, int]] = defaultdict(dict)
            for b, s, o in zip(r["books"], r["sides"], r["odds"]):
                per_book[b][s] = o

            fair_overs: dict[str, float] = {}
            for b, ss in per_book.items():
                if "over" in ss and "under" in ss:
                    oi = 1.0 / _decimal_from_american(ss["over"])
                    ui = 1.0 / _decimal_from_american(ss["under"])
                    if oi + ui > 0:
                        fair_overs[b] = oi / (oi + ui)
            if len(fair_overs) < min_books:
                continue
            consensus_over = sum(fair_overs.values()) / len(fair_overs)

            actual = _lookup_actual(
                outcomes, player=r["player_name"], market=r["market_key"],
                game_date=r["event_start"].date(),
            )
            if actual is None:
                continue

            for side, consensus_side in (
                ("over", consensus_over), ("under", 1.0 - consensus_over)
            ):
                won_side = actual > line if side == "over" else actual < line
                pushed = actual == line
                for b, ss in per_book.items():
                    if side not in ss:
                        continue
                    dec = _decimal_from_american(ss[side])
                    edge = consensus_side - 1.0 / dec
                    if edge < threshold:
                        continue
                    a = agg[b]
                    a["n"] += 1
                    a["edge"] += edge
                    if pushed:
                        a["pushes"] += 1
                    elif won_side:
                        a["wins"] += 1
                        a["ret"] += dec - 1.0
                    else:
                        a["losses"] += 1
                        a["ret"] -= 1.0

        results: dict[str, dict] = {}
        for book, a in agg.items():
            decided = a["wins"] + a["losses"]
            roi = 100.0 * a["ret"] / a["n"] if a["n"] else 0.0
            wr = a["wins"] / decided if decided else 0.0
            avg_edge = 100.0 * a["edge"] / a["n"] if a["n"] else 0.0
            results[book] = {
                "n": a["n"], "wins": a["wins"], "losses": a["losses"],
                "pushes": a["pushes"], "win_rate": wr, "roi_pct": roi,
                "avg_edge_pct": avg_edge,
            }
            await pool.execute(
                """
                INSERT INTO book_roi (book, sport, threshold, n_bets, wins, losses,
                                      pushes, win_rate, roi_pct, avg_edge_pct, computed_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, NOW())
                ON CONFLICT (book, sport, threshold) DO UPDATE SET
                    n_bets=EXCLUDED.n_bets, wins=EXCLUDED.wins, losses=EXCLUDED.losses,
                    pushes=EXCLUDED.pushes, win_rate=EXCLUDED.win_rate,
                    roi_pct=EXCLUDED.roi_pct, avg_edge_pct=EXCLUDED.avg_edge_pct,
                    computed_at=NOW()
                """,
                book, sport, round(threshold, 4), a["n"], a["wins"], a["losses"],
                a["pushes"], round(wr, 4), round(roi, 2), round(avg_edge, 2),
            )
        log.info("book_roi_done", books=len(results))
        return results
    finally:
        await close_pool()


def _main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", default="basketball_nba")
    p.add_argument("--threshold", type=float, default=0.03)
    p.add_argument("--min-books", type=int, default=2)
    a = p.parse_args()
    res = asyncio.run(compute_book_roi(a.sport, threshold=a.threshold, min_books=a.min_books))
    print(f"\n  PER-BOOK ROI · {a.sport} · edge >= {a.threshold*100:.0f}%")
    print("  " + "-" * 58)
    print(f"  {'book':18s} {'bets':>5s} {'win%':>6s} {'ROI':>8s}  verdict")
    for book, s in sorted(res.items(), key=lambda kv: -kv[1]["roi_pct"]):
        verdict = "SOFT (bet it)" if s["roi_pct"] > 3 else "SHARP (trust it)" if s["roi_pct"] < 0 else "neutral"
        print(f"  {book:18s} {s['n']:5d} {s['win_rate']*100:5.1f}% {s['roi_pct']:+7.1f}%  {verdict}")


if __name__ == "__main__":
    _main()
