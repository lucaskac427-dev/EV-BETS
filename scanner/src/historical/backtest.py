"""Strategy backtest against historical odds + actual outcomes.

For every historical (event, market, player, line) where we have ≥2 books
quoting both over/under, we compute the strategy's "would-have-bet" decision:

  1. Per book, devig over/under → fair_over.
  2. Average fair_over across books → consensus.
  3. For each side, edge = consensus_for_side − implied_for_side_at_best_book.
  4. If edge ≥ threshold, this is a "bet" at the best available price.
  5. Look up the player's actual stat in player_game_logs (game_date matches
     the event commence date). Compute win/loss/push.
  6. Roll up to ROI + win rate per market + overall.

Run:
    python -m src.historical.backtest --sport basketball_nba --threshold 0.02
"""

import argparse
import asyncio
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timezone, timedelta

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.nba import project_over as nba_project_over


# Blend weight on the projection (matches the reference 60/40 split).
PROJECTION_BLEND_WEIGHT = 0.40


# Map Odds API market keys -> the stat column in player_game_logs.
# Odds API market key -> the player_game_logs column(s) to SUM for the outcome.
# Singles + their alt-line ladders + the combo props — all gradeable from the box
# score we already store. (double/triple-double + first-basket need different
# grading and are handled separately, not here.)
NBA_MARKET_TO_COLUMN: dict[str, tuple[str, ...]] = {
    "player_points": ("points",),
    "player_points_alternate": ("points",),
    "player_rebounds": ("rebounds",),
    "player_rebounds_alternate": ("rebounds",),
    "player_assists": ("assists",),
    "player_assists_alternate": ("assists",),
    "player_threes": ("threes",),
    "player_threes_alternate": ("threes",),
    "player_blocks": ("blocks",),
    "player_blocks_alternate": ("blocks",),
    "player_steals": ("steals",),
    "player_steals_alternate": ("steals",),
    "player_points_rebounds_assists": ("points", "rebounds", "assists"),
    "player_points_rebounds_assists_alternate": ("points", "rebounds", "assists"),
    "player_points_rebounds": ("points", "rebounds"),
    "player_points_rebounds_alternate": ("points", "rebounds"),
    "player_points_assists": ("points", "assists"),
    "player_points_assists_alternate": ("points", "assists"),
    "player_rebounds_assists": ("rebounds", "assists"),
    "player_rebounds_assists_alternate": ("rebounds", "assists"),
    "player_blocks_steals": ("blocks", "steals"),
    "player_blocks_steals_alternate": ("blocks", "steals"),
}


# MLB — Odds API market key -> mlb_game_logs column to grade against. Only the
# 6 deep markets we backfill (≥4-book consensus); thin batter props are skipped
# upstream. NOTE the box-score column for RBIs is `rbi` (singular).
MLB_MARKET_TO_COLUMN: dict[str, tuple[str, ...]] = {
    "pitcher_strikeouts": ("pitcher_strikeouts",),
    "pitcher_strikeouts_alternate": ("pitcher_strikeouts",),
    "pitcher_outs": ("pitcher_outs",),
    "pitcher_outs_alternate": ("pitcher_outs",),
    "batter_total_bases": ("total_bases",),
    "batter_total_bases_alternate": ("total_bases",),
    "batter_hits": ("hits",),
    "batter_hits_alternate": ("hits",),
    "batter_home_runs": ("home_runs",),
    "batter_home_runs_alternate": ("home_runs",),
    "batter_rbis": ("rbi",),
    "batter_rbis_alternate": ("rbi",),
}

# WNBA — same basketball markets/columns as the NBA, graded against wnba_game_logs.
# Books offer points/rebounds/assists/threes/PRA (no blocks/steals).
WNBA_MARKET_TO_COLUMN: dict[str, tuple[str, ...]] = {
    "player_points": ("points",),
    "player_points_alternate": ("points",),
    "player_rebounds": ("rebounds",),
    "player_rebounds_alternate": ("rebounds",),
    "player_assists": ("assists",),
    "player_assists_alternate": ("assists",),
    "player_threes": ("threes",),
    "player_threes_alternate": ("threes",),
    "player_points_rebounds_assists": ("points", "rebounds", "assists"),
    "player_points_rebounds_assists_alternate": ("points", "rebounds", "assists"),
}

# Per-sport routing: which market map, which outcomes table, which stat columns.
MARKET_TO_COLUMN_BY_SPORT: dict[str, dict[str, tuple[str, ...]]] = {
    "basketball_nba": NBA_MARKET_TO_COLUMN,
    "baseball_mlb": MLB_MARKET_TO_COLUMN,
    "basketball_wnba": WNBA_MARKET_TO_COLUMN,
}
_STAT_COLUMNS_NBA = ("points", "rebounds", "assists", "threes", "blocks", "steals")
_STAT_COLUMNS_MLB = ("pitcher_strikeouts", "pitcher_outs", "total_bases", "hits", "home_runs", "rbi")
_STAT_COLUMNS_WNBA = ("points", "rebounds", "assists", "threes")
OUTCOME_SOURCE_BY_SPORT: dict[str, tuple[str, tuple[str, ...]]] = {
    "basketball_nba": ("player_game_logs", _STAT_COLUMNS_NBA),
    "baseball_mlb": ("mlb_game_logs", _STAT_COLUMNS_MLB),
    "basketball_wnba": ("wnba_game_logs", _STAT_COLUMNS_WNBA),
}


@dataclass
class BetResult:
    market: str
    player: str
    line: float
    side: str  # 'over' | 'under'
    decimal_odds: float
    fair_prob: float          # blended fair (consensus + projection if avail)
    consensus_prob: float
    projection_prob: float | None
    edge: float
    actual_stat: int
    won: bool
    pushed: bool
    return_per_unit: float  # 1 * (decimal - 1) on win, -1 on loss, 0 on push
    book: str
    event_date: date | None = None

    @property
    def segment(self) -> str:
        """NBA regular season vs playoffs by calendar. May/Jun = playoffs,
        Oct-Mar = regular season, Apr split on the 14th (playoffs start mid-Apr)."""
        if self.event_date is None:
            return "unknown"
        mo, day = self.event_date.month, self.event_date.day
        if mo in (5, 6, 7):
            return "playoffs"
        if mo in (10, 11, 12, 1, 2, 3):
            return "regular"
        if mo == 4:
            return "playoffs" if day >= 14 else "regular"
        return "unknown"


def _decimal_from_american(american: int) -> float:
    if american > 0:
        return american / 100.0 + 1.0
    return 100.0 / abs(american) + 1.0


async def run_backtest(
    sport: str = "basketball_nba",
    *,
    threshold: float = 0.02,
    min_books: int = 2,
    target_book: str | None = None,
    use_projection: bool = True,
    min_fair: float = 0.0,
) -> dict:
    configure_logging(level=settings.log_level)
    m2c = MARKET_TO_COLUMN_BY_SPORT[sport]
    pool = await get_pool()
    try:
        # Pull all (event, market, player, line) opportunities, grouping all
        # the bookmaker prices into per-row arrays.
        rows = await pool.fetch(
            """
            SELECT event_id, event_start,
                   regexp_replace(market_key, '_alternate$', '') AS market_key,
                   player_name, line,
                   array_agg(book ORDER BY book)                     AS books,
                   array_agg(side ORDER BY book)                     AS sides,
                   array_agg(american_odds ORDER BY book)            AS odds
            FROM historical_odds_snapshots
            WHERE sport_key = $1
              AND market_key = ANY($2::text[])
              AND player_name IS NOT NULL AND line IS NOT NULL
            -- de-fragment: main + _alternate of the same stat are ONE ladder, so
            -- books that quoted the same real line group together (no interpolation).
            GROUP BY event_id, event_start, regexp_replace(market_key, '_alternate$', ''), player_name, line
            """,
            sport,
            list(m2c.keys()),
            timeout=600,  # 24M-row aggregation; the 10s pool default is far too short
        )
        log.info("backtest_opportunities_loaded", count=len(rows))

        # Preload ALL game-log outcomes into memory once. The old per-row DB
        # lookup made the backtest unusable (one query × ~1M rows = ~30 min);
        # an in-memory dict turns the whole run into seconds.
        outcomes = await _load_outcomes(pool, sport)
        log.info("backtest_outcomes_loaded", count=len(outcomes))

        bets: list[BetResult] = []
        skipped = defaultdict(int)

        for r in rows:
            event_start = r["event_start"]
            market = r["market_key"]
            player = r["player_name"]
            line = float(r["line"])
            books = r["books"]
            sides = r["sides"]
            odds = r["odds"]

            # Group per book to find books that have BOTH sides quoted.
            per_book: dict[str, dict[str, int]] = defaultdict(dict)
            for b, s, o in zip(books, sides, odds):
                per_book[b][s] = o

            fair_overs: dict[str, float] = {}
            for b, ss in per_book.items():
                if "over" in ss and "under" in ss:
                    o_imp = 1.0 / _decimal_from_american(ss["over"])
                    u_imp = 1.0 / _decimal_from_american(ss["under"])
                    total = o_imp + u_imp
                    if total > 0:
                        fair_overs[b] = o_imp / total

            if len(fair_overs) < min_books:
                skipped["min_books"] += 1
                continue

            consensus_over = sum(fair_overs.values()) / len(fair_overs)
            consensus_under = 1.0 - consensus_over

            actual = _lookup_actual(
                outcomes, player=player, market=market,
                game_date=event_start.date(), m2c=m2c,
            )
            if actual is None:
                skipped["no_outcome"] += 1
                continue

            # Projection model — NBA only for now.
            proj_over: float | None = None
            _cols = m2c[market]
            if use_projection and sport == "basketball_nba" and len(_cols) == 1:
                proj_over = await nba_project_over(
                    pool, player_name=player, stat=_cols[0],
                    line=line,
                )

            def blend(consensus: float, projection_for_side: float | None) -> float:
                if projection_for_side is None:
                    return consensus
                w = PROJECTION_BLEND_WEIGHT
                return (1.0 - w) * consensus + w * projection_for_side

            blended_over = blend(consensus_over, proj_over)
            proj_under = (1.0 - proj_over) if proj_over is not None else None
            blended_under = blend(consensus_under, proj_under)

            # Evaluate each side at the BEST available decimal odds.
            for side, fair, consensus_side, proj_side in (
                ("over", blended_over, consensus_over, proj_over),
                ("under", blended_under, consensus_under, proj_under),
            ):
                # Determine which book(s) to evaluate this side at.
                # If target_book is set: bet only at that book (proper
                # "soft book vs sharp reference" mode). Otherwise: bet at
                # the best available price across all books (cherry-pick).
                side_quotes: list[tuple[str, float]] = []
                if target_book is not None:
                    if target_book in per_book and side in per_book[target_book]:
                        side_quotes.append(
                            (target_book, _decimal_from_american(per_book[target_book][side]))
                        )
                else:
                    side_quotes = [
                        (b, _decimal_from_american(per_book[b][side]))
                        for b in per_book
                        if side in per_book[b]
                    ]
                if not side_quotes:
                    continue
                # Pick best price among allowed quotes.
                book_used, best_decimal = max(side_quotes, key=lambda t: t[1])
                implied = 1.0 / best_decimal
                edge = fair - implied
                # min_fair filters to higher win-probability sides (favor winning
                # more often) while STILL requiring +edge so we never chase -EV chalk.
                if edge < threshold or fair < min_fair:
                    continue
                # Actual outcome
                if side == "over":
                    won = actual > line
                else:
                    won = actual < line
                pushed = actual == line
                if pushed:
                    ret = 0.0
                else:
                    ret = (best_decimal - 1.0) if won else -1.0
                bets.append(
                    BetResult(
                        market=market,
                        player=player,
                        line=line,
                        side=side,
                        decimal_odds=best_decimal,
                        fair_prob=fair,
                        consensus_prob=consensus_side,
                        projection_prob=proj_side,
                        edge=edge,
                        actual_stat=actual,
                        won=won,
                        pushed=pushed,
                        return_per_unit=ret,
                        book=book_used,
                        event_date=event_start.date(),
                    )
                )

        # Summary
        summary = _summarize(bets)
        log.info(
            "backtest_complete",
            opportunities=len(rows),
            bets_made=len(bets),
            skipped=dict(skipped),
            **summary,
        )

        # Per-market breakdown
        by_market: dict[str, list[BetResult]] = defaultdict(list)
        for b in bets:
            by_market[b.market].append(b)
        per_market = {m: _summarize(bs) for m, bs in by_market.items()}

        return {
            "summary": summary,
            "per_market": per_market,
            "bets": bets,
            "skipped": dict(skipped),
        }
    finally:
        await close_pool()


_NAME_SUFFIX = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", re.IGNORECASE)


def _norm_name(s: str) -> str:
    """Canonical player key: strip accents (Jokić→jokic), drop punctuation
    (C.J.→cj, De'Aaron→deaaron, hyphen→space) and the Jr/Sr/II/III suffix, lower.
    Fixes the ~19% of prop names that failed to match a box score."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    s = _NAME_SUFFIX.sub("", s)
    return " ".join(s.split())


def _initial_last(norm: str) -> str | None:
    """First-initial + last name for nickname matches: 'nicolas claxton' and
    'nic claxton' both -> 'n claxton'. Used only when unambiguous on a date."""
    parts = norm.split()
    return f"{parts[0][0]} {parts[-1]}" if len(parts) >= 2 and parts[0] else None


def _strip_suffix(name: str) -> str:
    """Drop common name suffixes so 'Isaiah Stewart II' matches 'Isaiah Stewart'."""
    return _NAME_SUFFIX.sub("", name).strip()


async def _load_outcomes(pool, sport: str) -> dict[tuple[str, date], dict]:
    """Load every game-log row into a dict keyed by (player_name, game_date).
    One bulk query replaces the per-candidate lookups. Sport picks the table
    (player_game_logs for NBA, mlb_game_logs for MLB) and stat columns."""
    table, stat_cols = OUTCOME_SOURCE_BY_SPORT[sport]
    rows = await pool.fetch(
        f"SELECT player_name, game_date, {', '.join(stat_cols)} FROM {table}",
        timeout=600,
    )
    out: dict = {}
    il_names: dict = defaultdict(set)
    il_row: dict = {}
    for r in rows:
        nm = _norm_name(r["player_name"])
        out[("F", nm, r["game_date"])] = r
        il = _initial_last(nm)
        if il:
            il_names[(il, r["game_date"])].add(nm)
            il_row[(il, r["game_date"])] = r
    for (il, gd), names in il_names.items():
        if len(names) == 1:  # unambiguous -> safe nickname fallback, never forced
            out[("I", il, gd)] = il_row[(il, gd)]
    return out


_SUFFIXES = ("", " Jr.", " Jr", " II", " III")


def _lookup_actual(
    outcomes: dict[tuple[str, date], dict], *, player: str, market: str, game_date: date,
    m2c: dict[str, tuple[str, ...]],
) -> int | None:
    cols = m2c.get(market)
    if not cols:
        return None
    # Exact normalized name first, then the unambiguous initial+last nickname
    # fallback × +/-1 day for the UTC↔ET rollover on late games. Combo props sum
    # their columns (PRA = points+rebounds+assists).
    nm = _norm_name(player)
    il = _initial_last(nm)
    for gd in (game_date, game_date - timedelta(days=1), game_date + timedelta(days=1)):
        row = outcomes.get(("F", nm, gd)) or (outcomes.get(("I", il, gd)) if il else None)
        if row is not None:
            vals = [row[c] for c in cols]
            if all(v is not None for v in vals):
                return int(sum(vals))
    return None


def _summarize(bets: list[BetResult]) -> dict:
    if not bets:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "win_rate": 0.0,
            "total_return": 0.0,
            "roi_pct": 0.0,
            "avg_edge_pct": 0.0,
        }
    wins = sum(1 for b in bets if b.won and not b.pushed)
    losses = sum(1 for b in bets if not b.won and not b.pushed)
    pushes = sum(1 for b in bets if b.pushed)
    total_return = sum(b.return_per_unit for b in bets)
    decided = wins + losses
    return {
        "n": len(bets),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": wins / decided if decided else 0.0,
        "total_return": round(total_return, 2),
        "roi_pct": round(100.0 * total_return / len(bets), 2),
        "avg_edge_pct": round(100.0 * sum(b.edge for b in bets) / len(bets), 2),
    }


def _format_pct(v: float) -> str:
    return f"{v:+5.2f}%" if v else " 0.00%"


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="basketball_nba")
    parser.add_argument("--threshold", type=float, default=0.02)
    parser.add_argument("--min-books", type=int, default=2)
    parser.add_argument(
        "--target-book",
        default=None,
        help="If set, bet only at this book (proper soft-vs-sharp test)",
    )
    parser.add_argument(
        "--no-projection",
        action="store_true",
        help="Skip projection blend; use pure sharp-consensus",
    )
    args = parser.parse_args()
    result = asyncio.run(
        run_backtest(
            args.sport,
            threshold=args.threshold,
            min_books=args.min_books,
            target_book=args.target_book,
            use_projection=not args.no_projection,
        )
    )

    s = result["summary"]
    print(f"\nBACKTEST · sport={args.sport} · edge_threshold={args.threshold*100:.1f}%")
    print(f"  bets made: {s['n']}  ({s['wins']}W-{s['losses']}L-{s['pushes']}P)")
    print(f"  win rate:  {s['win_rate']*100:5.2f}%")
    print(f"  ROI:       {_format_pct(s['roi_pct'])}")
    print(f"  avg edge:  {_format_pct(s['avg_edge_pct'])}")
    print(f"  skipped:   {result['skipped']}")
    print(f"\nPer market:")
    for m, sm in sorted(result["per_market"].items()):
        print(
            f"  {m:25s} n={sm['n']:4}  wr={sm['win_rate']*100:5.2f}%  "
            f"ROI={_format_pct(sm['roi_pct'])}  avg_edge={_format_pct(sm['avg_edge_pct'])}"
        )

    # Top 10 winning + losing bets
    bets = result["bets"]
    if bets:
        print(f"\nTop 10 BEST bets (by edge):")
        for b in sorted(bets, key=lambda x: -x.edge)[:10]:
            status = "W" if b.won and not b.pushed else "L" if not b.won and not b.pushed else "P"
            print(
                f"  {status}  {b.player:25s}  {b.market.replace('player_','')+' '+b.side:18s} "
                f"line={b.line:5.1f} actual={b.actual_stat:3d}  edge={b.edge*100:+5.2f}%  "
                f"return={b.return_per_unit:+.2f}"
            )


if __name__ == "__main__":
    _main()
