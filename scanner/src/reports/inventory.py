"""Generate the living inventory sheets — backtests, event data, odds data.

Writes CSVs (open in Excel / Google Sheets) describing everything the platform
holds and every backtest we've run. Re-run anytime; numbers refresh from the DB.

    python -m src.reports.inventory      # -> kalshi-ev-scanner/reports/*.csv
"""

import asyncio
import csv
from pathlib import Path

from src.db import close_pool, get_pool
from src.logger import configure_logging

OUT = Path(__file__).resolve().parents[3] / "reports"

# Tables that hold EVENT / stats data (what happened on the field/court).
EVENT_TABLES = [
    ("player_game_logs", "NBA box scores — per player, per game (pts/reb/ast/3pm/blk/stl/min)", "nba_api"),
    ("pbp_events", "NBA play-by-play — every event with shot coordinates", "nba_api playbyplayv3"),
    ("soccer_player_match_stats", "Soccer player per-match stats (shots, assists…) — the prop-projection base", "FBref/Understat (soccerdata)"),
    ("soccer_match_odds", "Soccer match RESULTS (full-time goals) — 300K matches, 1993→now", "football-data.co.uk"),
    ("injuries", "Injury history — soccer (Transfermarkt, deep) + NBA (prosportstransactions)", "Transfermarkt / prosportstransactions"),
    ("sofascore_events", "SofaScore multi-sport schedule + final scores (all sports)", "SofaScore API"),
    ("sofascore_event_details", "SofaScore per-event play-by-play + statistics + lineups + momentum", "SofaScore API"),
    ("team_features", "NBA team feature store (rolling form, pace, defense) — projection inputs", "derived"),
    ("player_features", "NBA player feature store (rolling avgs, rest, usage) — projection inputs", "derived"),
    ("team_defense_ratings", "NBA team defensive ratings by stat", "derived"),
    ("league_averages", "NBA league scoring baselines by season", "derived"),
    ("live_game_state", "Live capture: NBA in-game state time-series (fills during a live game)", "nba_api live"),
    ("live_player_state", "Live capture: NBA in-game player stats time-series", "nba_api live"),
    ("live_pbp_events", "Live capture: NBA live play-by-play stream", "nba_api live"),
]

# Tables that hold ODDS / betting-market data (prices, lines, edges).
ODDS_TABLES = [
    ("historical_odds_snapshots", "Sportsbook odds history — NBA (30 markets) + EPL (7); the devig source for the consensus edge", "The Odds API"),
    ("soccer_match_odds", "Soccer 1X2 + O/U 2.5 + Asian-handicap closing odds (consensus + Pinnacle)", "football-data.co.uk"),
    ("dfs_lines", "Live DFS lines — PrizePicks / Underdog / Sleeper / DK Pick6 / Hard Rock", "DFS platform APIs"),
    ("dfs_opportunities", "Latest scan output — DFS edges (soft line vs sharp consensus)", "derived (scan)"),
    ("tracked_picks", "Forward tracker — every edge the software surfaces, graded vs reality", "derived (recorder)"),
    ("book_roi", "Per-book ROI — which books are soft (beatable) vs sharp", "derived (backtest)"),
    ("markets", "Kalshi markets synced", "Kalshi API"),
]

# Backtests we've run. Numbers from the committed modules (the `module` column is
# the receipt — re-run it to reproduce). book_roi rows are appended live from DB.
BACKTESTS = [
    ["NBA player props — DFS consensus EDGE", "NBA", "6 core prop markets", "4822 backtested", "47.6% (plus-money dogs)", "+6.9% (CI +3.8/+10.2)", "BACKTESTED — real, 4/4 seasons +", "historical/backtest.py"],
    ["NBA game lines — projection", "NBA", "h2h / totals / spreads", "large", "—", "-5%", "efficient market — do NOT bet", "projections/projection_backtest.py"],
    ["Soccer 1X2 — edge test", "Soccer big-5", "moneyline", "16219", "26% (longshot-heavy)", "-6.66%", "efficient — ROI worsens as 'edge' grows", "projections/soccer_gameline_backtest.py"],
    ["Soccer projection — ACCURACY", "Soccer big-5", "full bet menu (DC/TT/AH/totals)", "14175 picks", "83.9% (model said 85.9%)", "n/a — calibration", "ACCURATE predictor (Brier 0.199)", "projections/soccer_projection_accuracy.py"],
    ["Soccer model — ROI at real prices", "Soccer big-5", "ML / O-U 2.5 / Asian handicap", "11601", "56.6%", "-4.01%", "accurate, but vig > edge", "projections/soccer_model_roi.py"],
    ["Forward tracker — LIVE (Game 7 SAS@OKC)", "NBA", "player props", "103", "58.3%", "tracked only (no bet)", "real-world result, 2026-05-30", "tracking/recorder.py"],
]


async def _date_col(pool, table: str) -> str | None:
    rows = await pool.fetch(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_name=$1 AND data_type IN
             ('date','timestamp with time zone','timestamp without time zone')
           ORDER BY ordinal_position""", table)
    if not rows:
        return None
    pref = ("game_date", "match_date", "event_start", "start_time", "from_date", "game_day", "recorded_at")
    names = [r["column_name"] for r in rows]
    for p in pref:
        if p in names:
            return p
    return names[0]


async def _table_row(pool, table: str, desc: str, src: str) -> list:
    try:
        n = await pool.fetchval(f"SELECT count(*) FROM {table}", timeout=300)
        col = await _date_col(pool, table)
        lo = hi = ""
        if col and n:
            r = await pool.fetchrow(f"SELECT min({col})::date lo, max({col})::date hi FROM {table}", timeout=300)
            lo, hi = str(r["lo"] or ""), str(r["hi"] or "")
        return [table, n, lo, hi, desc, src]
    except Exception as e:
        return [table, "ERR", "", "", f"{desc} (query failed: {str(e)[:40]})", src]


def _write(name: str, header: list, rows: list) -> Path:
    OUT.mkdir(exist_ok=True)
    p = OUT / name
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


async def run() -> None:
    configure_logging(level="WARNING")
    pool = await get_pool()
    try:
        # 1) EVENTS sheet
        ev = [await _table_row(pool, t, d, s) for t, d, s in EVENT_TABLES]
        p1 = _write("data_events.csv", ["table", "rows", "first", "last", "what_it_is", "source"], ev)

        # 2) ODDS sheet (table-level)
        od = [await _table_row(pool, t, d, s) for t, d, s in ODDS_TABLES]
        p2 = _write("data_odds.csv", ["table", "rows", "first", "last", "what_it_is", "source"], od)

        # 3) ODDS markets detail — every sport×market we hold prices for
        mk = await pool.fetch(
            """SELECT sport_key, market_key, count(*) rows,
                      min(event_start)::date lo, max(event_start)::date hi
               FROM historical_odds_snapshots GROUP BY 1,2 ORDER BY 1, rows DESC""", timeout=300)
        mrows = [[r["sport_key"], r["market_key"], r["rows"], str(r["lo"]), str(r["hi"])] for r in mk]
        # DFS line coverage by platform
        dfs = await pool.fetch("SELECT source, count(*) n FROM dfs_lines GROUP BY 1 ORDER BY n DESC")
        for r in dfs:
            mrows.append(["dfs:" + r["source"], "player props", r["n"], "live", "live"])
        p3 = _write("data_odds_markets.csv", ["sport_or_platform", "market", "rows", "first", "last"], mrows)

        # 4) BACKTESTS sheet (+ live per-book ROI)
        bt = [list(r) for r in BACKTESTS]
        try:
            br = await pool.fetch("SELECT book, n_bets, win_rate, roi_pct FROM book_roi ORDER BY roi_pct DESC")
            for r in br:
                verdict = "SOFT — beatable" if (r["roi_pct"] or 0) > 3 else "SHARP — trust it" if (r["roi_pct"] or 0) < 0 else "neutral"
                bt.append([f"Per-book ROI — {r['book']}", "NBA", "props (consensus edge)", str(r["n_bets"]),
                           f"{float(r['win_rate'] or 0)*100:.1f}%", f"{float(r['roi_pct'] or 0):+.1f}%", verdict, "historical/book_roi.py"])
        except Exception:
            pass
        p4 = _write("backtests.csv", ["backtest", "sport", "market(s)", "sample", "win_rate", "ROI", "verdict", "module"], bt)

        for p in (p4, p1, p2, p3):
            print(f"  wrote {p}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(run())
