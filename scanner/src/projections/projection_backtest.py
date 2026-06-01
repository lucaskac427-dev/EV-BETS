"""HONEST backtest of the NBA game-line projection model (System 2).

For every historical game where we have BOTH a closing line (consensus across
books in historical_odds_snapshots) AND the model's point-in-time projection
(from team_features), we ask: when the model disagrees with the market by more
than a threshold, and we bet that disagreement at the market price, do we make
money?

  TOTALS  — consensus closing total = median of books' `over` lines.
            Bet OVER  if projected_total >= closing + threshold_pts.
            Bet UNDER if projected_total <= closing - threshold_pts.
            Grade vs actual final total (sum of both teams' points).

  SPREADS — consensus home spread = median of books' home-side lines.
            Model's home spread = -(projected_margin).
            Bet HOME if model spread is `threshold_pts` more favorable to home
            than the market (model thinks home is more underrated), else AWAY.
            Grade vs the actual home margin against the market spread.

Prices: -110 both sides is the norm; we bet at the *consensus* American odds for
the chosen side (median across books) so the ROI reflects a realistic, not
cherry-picked, price. A flat 1 unit per bet.

GROUND TRUTH comes from team_features.pts_scored / pts_allowed (which were
summed from player_game_logs). Odds events are matched to games by ET date +
home/away abbreviations — there is no shared game_id between the two feeds.

This is an efficient market. The honest, expected result is roughly
break-even-to-negative after the vig. The output reports the true number and a
calibration table (projected edge vs realized cover rate); nothing is massaged.

Run:
    python -m src.projections.projection_backtest --market totals --threshold 3
    python -m src.projections.projection_backtest --market spreads --threshold 2
    python -m src.projections.projection_backtest --market both
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.nba_game_model import (
    _season_start_for,
    estimate_constants,
    project_game,
)
from src.projections.teams import abbr_from_full_name, canonical_abbr

# historical_odds_snapshots is 23M+ rows with no index on event_start; the
# yearly-chunked grouped reads below need this partial index to stay under the
# pool's 10s command timeout. Idempotent (matches the module-owns-its-DDL
# convention in src/historical/book_roi.py). NBA game-lines only — never touches
# the DFS prop rows.
_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_hist_odds_nba_gamelines
ON historical_odds_snapshots (sport_key, market_key, event_start)
WHERE sport_key = 'basketball_nba'
  AND market_key IN ('totals', 'spreads', 'h2h');
"""


def _decimal_from_american(american: int) -> float:
    if american > 0:
        return american / 100.0 + 1.0
    return 100.0 / abs(american) + 1.0


@dataclass(slots=True)
class GameBet:
    game_date: date
    home_abbr: str
    away_abbr: str
    market: str  # 'totals' | 'spreads'
    side: str  # 'over'/'under' or 'home'/'away'
    market_line: float  # consensus closing line
    model_line: float  # model's projected total or home-spread
    edge_pts: float  # |model - market| in points (the disagreement)
    decimal_odds: float
    won: bool
    pushed: bool
    ret: float  # +(dec-1) win, -1 loss, 0 push


# ---- ground truth: actual finals, keyed by (date, home_abbr, away_abbr) ----


async def _load_finals(pool) -> dict[tuple[date, str, str], tuple[int, int]]:
    """{(game_date, home_abbr, away_abbr): (home_pts, away_pts)} from the HOME
    rows of team_features (pts_scored = home, pts_allowed = away)."""
    rows = await pool.fetch(
        """
        SELECT game_date, team_abbr AS home, opponent_abbr AS away,
               pts_scored AS home_pts, pts_allowed AS away_pts
        FROM team_features
        WHERE is_home = TRUE AND pts_scored IS NOT NULL
        """
    )
    out: dict[tuple[date, str, str], tuple[int, int]] = {}
    for r in rows:
        out[(r["game_date"], r["home"], r["away"])] = (
            int(r["home_pts"]),
            int(r["away_pts"]),
        )
    return out


# ---- point-in-time team-form lookup, keyed by (date, abbr) ----


async def _load_team_form(pool) -> dict[tuple[date, str], dict]:
    rows = await pool.fetch(
        """
        SELECT game_date, team_abbr, games_played,
               pts_for_l10, pts_against_l10, pts_for_season, pts_against_season
        FROM team_features
        """
    )
    return {(r["game_date"], r["team_abbr"]): dict(r) for r in rows}


# ---- closing-line consensus per event ----


def _consensus_total(
    per_book: dict[str, dict[str, tuple[float, int]]],
) -> tuple[float, int] | None:
    """Median over-line + median over-odds across books that quote totals."""
    lines: list[float] = []
    over_odds: list[int] = []
    for ss in per_book.values():
        if "over" in ss:
            ln, od = ss["over"]
            lines.append(ln)
            over_odds.append(od)
    if len(lines) < 2:
        return None
    return statistics.median(lines), int(statistics.median(over_odds))


def _consensus_home_spread(
    per_book: dict[str, dict[str, tuple[float, int]]],
    home_abbr: str,
) -> tuple[float, int] | None:
    """Median home-side spread + median home-side odds across books."""
    lines: list[float] = []
    odds: list[int] = []
    for ss in per_book.values():
        if home_abbr in ss:
            ln, od = ss[home_abbr]
            lines.append(ln)
            odds.append(od)
    if len(lines) < 2:
        return None
    return statistics.median(lines), int(statistics.median(odds))


async def run_backtest(
    *,
    market: str = "totals",
    threshold_pts: float = 3.0,
    min_books: int = 2,
) -> dict:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        await pool.execute(_CREATE_INDEX)
        finals = await _load_finals(pool)
        team_form = await _load_team_form(pool)
        log.info("proj_backtest_loaded", finals=len(finals), team_rows=len(team_form))

        # Pull odds grouped per event for the requested market. The full
        # grouped array_agg over 220K+ rows blows the 10s pool timeout, so we
        # page it one season-year at a time and concatenate.
        market_keys = ["totals", "spreads"] if market == "both" else [market]
        yr_row = await pool.fetchrow(
            """
            SELECT EXTRACT(YEAR FROM MIN(event_start))::int AS lo,
                   EXTRACT(YEAR FROM MAX(event_start))::int AS hi
            FROM historical_odds_snapshots
            WHERE sport_key = 'basketball_nba' AND market_key = ANY($1::text[])
            """,
            market_keys,
        )
        rows: list = []
        for yr in range(int(yr_row["lo"]), int(yr_row["hi"]) + 1):
            chunk = await pool.fetch(
                """
                SELECT event_id,
                       (event_start AT TIME ZONE 'America/New_York')::date AS game_date,
                       market_key, home_team, away_team,
                       array_agg(book)          AS books,
                       array_agg(side)          AS sides,
                       array_agg(line)          AS lines,
                       array_agg(american_odds) AS odds
                FROM historical_odds_snapshots
                WHERE sport_key = 'basketball_nba'
                  AND market_key = ANY($1::text[])
                  AND line IS NOT NULL
                  AND event_start >= make_timestamptz($2, 1, 1, 0, 0, 0)
                  AND event_start <  make_timestamptz($2 + 1, 1, 1, 0, 0, 0)
                GROUP BY event_id, game_date, market_key, home_team, away_team
                """,
                market_keys,
                yr,
            )
            rows.extend(chunk)
        log.info("proj_backtest_events", count=len(rows))

        bets: list[GameBet] = []
        skipped: dict[str, int] = defaultdict(int)
        # Cache point-in-time constants per (season_start, game_date).
        const_cache: dict[tuple[date, date], tuple[float, float]] = {}

        for r in rows:
            game_date: date = r["game_date"]
            home_abbr = abbr_from_full_name(r["home_team"])
            away_abbr = abbr_from_full_name(r["away_team"])
            if home_abbr is None or away_abbr is None:
                skipped["unmapped_team"] += 1
                continue

            actual = finals.get((game_date, home_abbr, away_abbr))
            if actual is None:
                skipped["no_final"] += 1
                continue
            home_pts, away_pts = actual

            home_form = team_form.get((game_date, home_abbr))
            away_form = team_form.get((game_date, away_abbr))
            if home_form is None or away_form is None:
                skipped["no_form"] += 1
                continue

            ck = (_season_start_for(game_date), game_date)
            if ck not in const_cache:
                const_cache[ck] = await estimate_constants(pool, game_date, ck[0])
            league_avg, home_edge = const_cache[ck]

            proj = project_game(
                home=home_form,
                away=away_form,
                league_avg=league_avg,
                home_edge=home_edge,
                game_date=game_date,
            )
            if proj is None:
                skipped["no_projection"] += 1
                continue

            # Group book quotes for this event.
            per_book: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
            for b, s, ln, od in zip(r["books"], r["sides"], r["lines"], r["odds"], strict=True):
                if ln is None or od is None:
                    continue
                per_book[b][s] = (float(ln), int(od))

            mk = r["market_key"]
            if mk == "totals":
                bet = _grade_total(
                    per_book,
                    proj,
                    home_pts,
                    away_pts,
                    threshold_pts,
                    min_books,
                    game_date,
                )
            else:
                bet = _grade_spread(
                    per_book,
                    proj,
                    home_abbr,
                    away_abbr,
                    home_pts,
                    away_pts,
                    threshold_pts,
                    min_books,
                    game_date,
                )
            if bet is None:
                skipped["no_bet_or_consensus"] += 1
                continue
            bets.append(bet)

        summary = _summarize(bets)
        by_market = defaultdict(list)
        for b in bets:
            by_market[b.market].append(b)
        per_market = {m: _summarize(v) for m, v in by_market.items()}
        calib = _calibration(bets)
        log.info(
            "proj_backtest_complete",
            events=len(rows),
            bets=len(bets),
            skipped=dict(skipped),
            **summary,
        )
        return {
            "summary": summary,
            "per_market": per_market,
            "calibration": calib,
            "skipped": dict(skipped),
            "bets": bets,
        }
    finally:
        await close_pool()


def _grade_total(
    per_book, proj, home_pts, away_pts, threshold_pts, min_books, game_date
) -> GameBet | None:
    if sum(1 for ss in per_book.values() if "over" in ss) < min_books:
        return None
    cons = _consensus_total(per_book)
    if cons is None:
        return None
    market_line, over_odds = cons
    actual_total = home_pts + away_pts
    edge = proj.projected_total - market_line
    if abs(edge) < threshold_pts:
        return None

    if edge > 0:  # model says OVER
        side, line_odds = "over", over_odds
        won = actual_total > market_line
    else:  # model says UNDER — price the under at the median under odds
        side = "under"
        unders = [ss["under"][1] for ss in per_book.values() if "under" in ss]
        line_odds = int(statistics.median(unders)) if unders else over_odds
        won = actual_total < market_line
    pushed = actual_total == market_line
    dec = _decimal_from_american(line_odds)
    ret = 0.0 if pushed else (dec - 1.0 if won else -1.0)
    return GameBet(
        game_date=game_date,
        home_abbr=proj.home_abbr,
        away_abbr=proj.away_abbr,
        market="totals",
        side=side,
        market_line=market_line,
        model_line=proj.projected_total,
        edge_pts=abs(edge),
        decimal_odds=dec,
        won=won,
        pushed=pushed,
        ret=ret,
    )


def _grade_spread(
    per_book,
    proj,
    home_abbr,
    away_abbr,
    home_pts,
    away_pts,
    threshold_pts,
    min_books,
    game_date,
) -> GameBet | None:
    # Spread side labels are full team names; remap to abbreviations.
    remapped: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
    for book, ss in per_book.items():
        for side_name, val in ss.items():
            ab = abbr_from_full_name(side_name) or canonical_abbr(side_name)
            if ab in (home_abbr, away_abbr):
                remapped[book][ab] = val
    if sum(1 for ss in remapped.values() if home_abbr in ss) < min_books:
        return None
    cons = _consensus_home_spread(remapped, home_abbr)
    if cons is None:
        return None
    market_home_spread, home_odds = cons  # e.g. -3.5 (home favored by 3.5)
    model_home_spread = proj.fair_home_spread
    # edge < 0 => model gives home a more favorable (more negative) number than
    # the market => model likes HOME. edge > 0 => model likes AWAY.
    edge = model_home_spread - market_home_spread
    if abs(edge) < threshold_pts:
        return None

    actual_home_margin = home_pts - away_pts
    # Home covers when actual margin beats the spread it's giving:
    #   actual_home_margin + market_home_spread > 0
    home_cover_value = actual_home_margin + market_home_spread
    if edge < 0:  # bet HOME
        side, line_odds = "home", home_odds
        won = home_cover_value > 0
    else:  # bet AWAY
        side = "away"
        aways = [ss[away_abbr][1] for ss in remapped.values() if away_abbr in ss]
        line_odds = int(statistics.median(aways)) if aways else home_odds
        won = home_cover_value < 0
    pushed = home_cover_value == 0
    dec = _decimal_from_american(line_odds)
    ret = 0.0 if pushed else (dec - 1.0 if won else -1.0)
    return GameBet(
        game_date=game_date,
        home_abbr=home_abbr,
        away_abbr=away_abbr,
        market="spreads",
        side=side,
        market_line=market_home_spread,
        model_line=model_home_spread,
        edge_pts=abs(edge),
        decimal_odds=dec,
        won=won,
        pushed=pushed,
        ret=ret,
    )


def _summarize(bets: list[GameBet]) -> dict:
    if not bets:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "win_rate": 0.0,
            "roi_pct": 0.0,
            "avg_edge_pts": 0.0,
        }
    wins = sum(1 for b in bets if b.won and not b.pushed)
    losses = sum(1 for b in bets if not b.won and not b.pushed)
    pushes = sum(1 for b in bets if b.pushed)
    ret = sum(b.ret for b in bets)
    decided = wins + losses
    return {
        "n": len(bets),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round(wins / decided, 4) if decided else 0.0,
        "roi_pct": round(100.0 * ret / len(bets), 2),
        "avg_edge_pts": round(sum(b.edge_pts for b in bets) / len(bets), 2),
    }


def _calibration(bets: list[GameBet]) -> list[dict]:
    """Bucket by the size of the model's disagreement and report realized win
    rate. If the model has real signal, bigger disagreements should win more;
    on an efficient market they won't (the honest tell)."""
    buckets = [(0, 3), (3, 5), (5, 8), (8, 12), (12, 100)]
    out: list[dict] = []
    for lo, hi in buckets:
        b = [x for x in bets if lo <= x.edge_pts < hi and not x.pushed]
        if not b:
            out.append({"bucket": f"{lo}-{hi}", "n": 0, "win_rate": 0.0, "roi_pct": 0.0})
            continue
        wins = sum(1 for x in b if x.won)
        ret = sum(x.ret for x in b)
        out.append(
            {
                "bucket": f"{lo}-{hi}",
                "n": len(b),
                "win_rate": round(wins / len(b), 4),
                "roi_pct": round(100.0 * ret / len(b), 2),
            }
        )
    return out


def _fmt_pct(v: float) -> str:
    return f"{v:+6.2f}%"


def _main() -> None:
    p = argparse.ArgumentParser(description="Backtest the NBA game-line model.")
    p.add_argument("--market", choices=["totals", "spreads", "both"], default="totals")
    p.add_argument(
        "--threshold",
        type=float,
        default=3.0,
        help="Min model-vs-market disagreement in points to bet.",
    )
    p.add_argument("--min-books", type=int, default=2)
    a = p.parse_args()
    res = asyncio.run(
        run_backtest(market=a.market, threshold_pts=a.threshold, min_books=a.min_books)
    )
    s = res["summary"]
    print(f"\nNBA GAME-LINE BACKTEST · market={a.market} · disagree>= {a.threshold} pts")
    print("  " + "=" * 60)
    print(f"  bets:      {s['n']}  ({s['wins']}W-{s['losses']}L-{s['pushes']}P)")
    print(f"  win rate:  {s['win_rate'] * 100:5.2f}%   (break-even at -110 = 52.38%)")
    print(f"  ROI:       {_fmt_pct(s['roi_pct'])}")
    print(f"  avg edge:  {s['avg_edge_pts']:.2f} pts")
    print(f"  skipped:   {res['skipped']}")
    if a.market == "both":
        print("\n  Per market:")
        for m, sm in sorted(res["per_market"].items()):
            print(
                f"    {m:8s} n={sm['n']:5d}  wr={sm['win_rate'] * 100:5.2f}%  "
                f"ROI={_fmt_pct(sm['roi_pct'])}"
            )
    print("\n  Calibration (disagreement bucket -> realized win rate):")
    print(f"    {'edge_pts':10s} {'n':>6s} {'win%':>7s} {'ROI':>8s}")
    for c in res["calibration"]:
        print(
            f"    {c['bucket']:10s} {c['n']:6d} {c['win_rate'] * 100:6.2f}% "
            f"{_fmt_pct(c['roi_pct'])}"
        )
    # Honest verdict.
    roi = s["roi_pct"]
    verdict = (
        "EDGE (survives the vig)"
        if roi > 1.5
        else "BREAK-EVEN / no real edge"
        if roi > -3
        else "LOSING — market beats the model"
    )
    print(f"\n  VERDICT: {verdict}")
    print(
        "  (Game lines are an efficient market; ~break-even-to-negative is the honest expectation.)"
    )


if __name__ == "__main__":
    _main()
