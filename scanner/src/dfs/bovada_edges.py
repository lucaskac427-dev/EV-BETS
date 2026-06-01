"""Bovada prop edge finder — props where Bovada's price is off the sharp consensus.

Bovada has a one-click round-robin, so these are the legs to drop straight into it
(one submission = all combos lock at once, no line-movement risk while you place).

Edge = consensus_fair_prob × Bovada_decimal_odds − 1  (EV at Bovada's posted price).
Consensus = the de-vigged average P(over) of the OTHER books. Props only — sportsbook
game lines are efficient. Per-book ROI proves Bovada props run ~+10% on flagged spots.

FRESHNESS: reads our stored sportsbook odds. For the tightest PRE-game edges the live
scan should pull Bovada in the betting window; closing snapshots are sharper (less edge).

    python -m src.dfs.bovada_edges --min-ev 3      # readable
    python -m src.dfs.bovada_edges --json --min-ev 3
"""

import argparse
import asyncio
import json
from collections import defaultdict
from statistics import mean

from src.db import close_pool, get_pool
from src.logger import configure_logging


async def compute(min_ev: float, days: int, sport: str = "basketball_nba") -> tuple[str, list[dict]]:
    pool = await get_pool()
    try:
        # Prefer LIVE odds (refreshed on scan). Fall back to stored snapshots.
        source = "live"
        try:
            rows = await pool.fetch(
                """SELECT event_start, market_key, player_name, line, book, side, decimal_odds
                   FROM live_book_odds
                   WHERE line IS NOT NULL AND side IN ('over','under') AND decimal_odds > 1""")
        except Exception:
            rows = []
        if not rows:
            source = "stored"
            rows = await pool.fetch(
                """WITH mx AS (SELECT max(event_start) m FROM historical_odds_snapshots WHERE sport_key=$1)
                   SELECT event_start, market_key, player_name, line, book, side, decimal_odds
                   FROM historical_odds_snapshots, mx
                   WHERE sport_key=$1 AND market_key LIKE 'player_%'
                     AND event_start >= mx.m - make_interval(days => $2) AND decimal_odds > 1
                     AND line IS NOT NULL AND side IN ('over','under')""",
                sport, days, timeout=180)
        props: dict = defaultdict(lambda: defaultdict(dict))
        for r in rows:
            key = (r["event_start"], r["market_key"], r["player_name"], float(r["line"]))
            props[key][r["book"]][r["side"]] = float(r["decimal_odds"])

        out = []
        for (ev_start, market, player, line), books in props.items():
            fairs = []
            for b, ss in books.items():
                if b == "bovada" or "over" not in ss or "under" not in ss:
                    continue
                io, iu = 1 / ss["over"], 1 / ss["under"]
                if io + iu > 0:
                    fairs.append(io / (io + iu))
            bov = books.get("bovada")
            if len(fairs) < 2 or not bov:
                continue
            cons_over = mean(fairs)
            for side, p in (("over", cons_over), ("under", 1 - cons_over)):
                if side in bov:
                    ev = p * bov[side] - 1
                    if ev >= min_ev / 100.0:
                        backers = [
                            {"book": b, "over": round(ss["over"], 2), "under": round(ss["under"], 2)}
                            for b, ss in sorted(books.items())
                            if b != "bovada" and "over" in ss and "under" in ss
                        ]
                        out.append({
                            "player": player, "market": market.replace("player_", ""),
                            "side": side, "line": line, "bovada_odds": round(bov[side], 2),
                            "fair_pct": round(p * 100, 1), "ev_pct": round(ev * 100, 1),
                            "event": str(ev_start.date()), "books": len(fairs), "backers": backers,
                        })
        out.sort(key=lambda x: -x["ev_pct"])
        return source, out
    finally:
        await close_pool()


async def _main(min_ev: float, days: int, as_json: bool) -> None:
    configure_logging(level="CRITICAL")
    source, edges = await compute(min_ev, days)
    if as_json:
        print(json.dumps({"min_ev": min_ev, "count": len(edges), "source": source, "edges": edges}))
        return
    print(f"\n  BOVADA EDGES ({source} odds) · props where Bovada is off the consensus · EV ≥ {min_ev}%")
    print(f"  (drop these into Bovada's one-click round-robin)")
    print("  " + "─" * 70)
    print(f"  {'player':22s} {'pick':22s} {'odds':>6s} {'fair':>6s} {'EV':>6s} {'books':>5s}")
    for e in edges[:40]:
        pick = f"{e['side']} {e['line']:g} {e['market']}"
        print(f"  {e['player'][:22]:22s} {pick[:22]:22s} {e['bovada_odds']:>6.2f} "
              f"{e['fair_pct']:>5.0f}% {e['ev_pct']:>+5.1f}% {e['books']:>5d}")
    print(f"\n  {len(edges)} edges found.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--min-ev", type=float, default=3.0)
    p.add_argument("--days", type=int, default=2)
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="return every consensus-matched line (no EV filter)")
    a = p.parse_args()
    asyncio.run(_main(-1e9 if a.all else a.min_ev, a.days, a.json))
