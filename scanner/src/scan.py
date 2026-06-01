"""On-demand scan — run ONE scan when you're ready to bet, then exit.

This is the token-saver: instead of the 30s scheduler burning Odds API
credits 24/7, you run this only when you're about to bet a game. One pass:
sync the DFS platform lines, pull sharp consensus once, compute edges, print
the +EV bets, exit.

Usage:
    python -m src.scan --sport nba
    python -m src.scan --sport soccer
    python -m src.scan --sport nba --min-edge 0.03   # only show >=3% edges
"""

import argparse
import asyncio

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.prizepicks.pipeline import SPORT_PIPELINE_PRESETS, run_prizepicks_tick


async def main(sport: str, min_edge: float) -> None:
    configure_logging(level="WARNING")
    league_config, odds_configs = SPORT_PIPELINE_PRESETS[sport]
    pool = await get_pool()
    try:
        # Clear this sport's prior edges so the scan reflects right now
        await pool.execute(
            """DELETE FROM dfs_opportunities WHERE dfs_line_id IN
               (SELECT id FROM dfs_lines WHERE sport = $1)""",
            league_config.sport_tag.lower(),
        )
        n = await run_prizepicks_tick(
            pool, league_config=league_config, odds_configs=odds_configs
        )

        # Refresh live book odds (incl. Bovada) into live_book_odds so the Bovada
        # edge page runs on THIS scan's prices, not stale stored snapshots. Same
        # pool, best-effort: a live-odds failure must never break the DFS scan.
        live_quotes = 0
        try:
            from src.dfs.live_odds import refresh as refresh_live_odds

            live_quotes = await refresh_live_odds(sport, pool=pool)
        except Exception as e:  # noqa: BLE001 — never break the scan on live odds
            log.warning("live_odds_refresh_failed", sport=sport, error=str(e)[:120])

        # Auto-bank every edge this scan surfaced into the track record, so
        # "any bet that runs through the software" is graded later vs reality.
        from src.tracking.recorder import record_dfs_edges

        banked = await record_dfs_edges(pool, min_edge=0.0)

        rows = await pool.fetch(
            """SELECT l.source, l.player_name, l.stat_type, l.line, l.odds_type,
                      o.pick_side, o.consensus_fair_prob, o.breakeven_per_leg,
                      o.edge_pct, o.num_sharp_books
               FROM dfs_opportunities o JOIN dfs_lines l ON l.id = o.dfs_line_id
               WHERE l.sport = $1 AND o.edge_pct >= $2
               ORDER BY o.edge_pct DESC LIMIT 40""",
            league_config.sport_tag.lower(), min_edge,
        )
        print(f"\n  SCAN · {sport.upper()} · {len(rows)} bets ≥ {min_edge*100:.0f}% edge "
              f"({n} total evaluations) · {banked} new picks tracked · {live_quotes} live quotes")
        print("  " + "─" * 76)
        if not rows:
            print("  No edges clear the bar right now. Try a lower --min-edge or scan closer to tip.")
        for r in rows:
            side = "MORE" if r["pick_side"] == "over" else "LESS"
            tag = f"[{r['odds_type']}]" if r["odds_type"] != "standard" else ""
            print(f"  {r['source']:10s} {r['player_name']:22s} {side} {float(r['line']):5.1f} "
                  f"{r['stat_type']:9s} {tag:8s} | fair {float(r['consensus_fair_prob'])*100:4.1f}% | "
                  f"edge +{float(r['edge_pct'])*100:5.2f}% | {r['num_sharp_books']} books")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sport", default="nba", choices=sorted(SPORT_PIPELINE_PRESETS.keys()))
    p.add_argument("--min-edge", type=float, default=0.0)
    a = p.parse_args()
    asyncio.run(main(a.sport, a.min_edge))
