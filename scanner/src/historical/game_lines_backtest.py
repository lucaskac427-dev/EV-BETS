"""Game-lines backtest: h2h (moneyline), totals, spreads.

Unlike player props, the outcome is the final score, derived from the stats
tables we already have:
  - NBA: sum player points per team per game in player_game_logs.
  - Soccer: sum player goals per team per match in soccer_player_match_stats.

Strategy mirrors the prop backtest: consensus from the books (devig the two
or three sides), bet the side with edge over the best available price.

Markets:
  - h2h:     2-way (NBA) or 3-way (soccer: home/away/draw). Devig across all
             sides. Outcome = which team won (or draw).
  - totals:  Over/Under combined score. Devig over/under. Outcome = total.
  - spreads: Team ± handicap. Devig the two sides. Outcome = did the team
             cover (margin + handicap > 0).

Run:
    python -m src.historical.game_lines_backtest --sport basketball_nba --market totals
    python -m src.historical.game_lines_backtest --sport basketball_nba --market h2h
"""

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass

from nba_api.stats.static import teams as nba_static_teams

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

NBA_NAME_TO_ABBR: dict[str, str] = {
    t["full_name"]: t["abbreviation"] for t in nba_static_teams.get_teams()
}


@dataclass
class GameBet:
    market: str
    selection: str       # team name or 'Over'/'Under'
    line: float | None
    decimal_odds: float
    fair_prob: float
    edge: float
    won: bool
    pushed: bool
    return_per_unit: float
    book: str


def _decimal_from_american(american: int) -> float:
    if american > 0:
        return american / 100.0 + 1.0
    return 100.0 / abs(american) + 1.0


async def _nba_score(pool, home_team: str, away_team: str, game_date) -> tuple[int, int] | None:
    """(home_score, away_score) summed from player points, matched on the game
    where both teams appear. Tries +/- 1 day for UTC↔ET rollover."""
    home_abbr = NBA_NAME_TO_ABBR.get(home_team)
    away_abbr = NBA_NAME_TO_ABBR.get(away_team)
    if not home_abbr or not away_abbr:
        return None
    from datetime import timedelta

    for gd in (game_date, game_date - timedelta(days=1), game_date + timedelta(days=1)):
        rows = await pool.fetch(
            """
            SELECT team_abbr, SUM(points) AS score
            FROM player_game_logs
            WHERE game_id IN (
                SELECT game_id FROM player_game_logs
                WHERE game_date = $1 AND team_abbr = $2
                INTERSECT
                SELECT game_id FROM player_game_logs
                WHERE game_date = $1 AND team_abbr = $3
            )
            GROUP BY team_abbr
            """,
            gd, home_abbr, away_abbr,
        )
        if len(rows) == 2:
            scores = {r["team_abbr"]: int(r["score"]) for r in rows}
            if home_abbr in scores and away_abbr in scores:
                return scores[home_abbr], scores[away_abbr]
    return None


async def run_game_lines_backtest(
    sport: str = "basketball_nba",
    *,
    market: str = "totals",
    threshold: float = 0.02,
    min_books: int = 3,
) -> dict:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT event_id, event_start, home_team, away_team,
                   array_agg(book ORDER BY book)          AS books,
                   array_agg(side ORDER BY book)          AS sides,
                   array_agg(line ORDER BY book)          AS lines,
                   array_agg(american_odds ORDER BY book) AS odds
            FROM historical_odds_snapshots
            WHERE sport_key = $1 AND market_key = $2
              AND home_team IS NOT NULL AND away_team IS NOT NULL
            GROUP BY event_id, event_start, home_team, away_team
            """,
            sport, market,
        )
        log.info("game_lines_opps_loaded", market=market, count=len(rows))

        bets: list[GameBet] = []
        skipped = defaultdict(int)

        for r in rows:
            home, away = r["home_team"], r["away_team"]
            if sport == "basketball_nba":
                score = await _nba_score(pool, home, away, r["event_start"].date())
            else:
                score = None  # soccer derivation TODO (needs goals-per-team join)
            if score is None:
                skipped["no_outcome"] += 1
                continue
            home_score, away_score = score
            total = home_score + away_score
            margin = home_score - away_score  # home perspective

            # Build per (selection, line) -> {book: decimal}
            per_sel: dict[tuple[str, float | None], dict[str, float]] = defaultdict(dict)
            for b, s, ln, o in zip(r["books"], r["sides"], r["lines"], r["odds"]):
                key = (s, float(ln) if ln is not None else None)
                per_sel[key][b] = _decimal_from_american(o)

            made = _evaluate_market(
                market, per_sel, home, away, total, margin,
                home_score, away_score, threshold, min_books,
            )
            bets.extend(made)
            if not made:
                skipped["no_edge"] += 1

        summary = _summarize(bets)
        log.info("game_lines_backtest_complete", market=market,
                 opportunities=len(rows), bets=len(bets), **summary)
        return {"summary": summary, "bets": bets, "skipped": dict(skipped)}
    finally:
        await close_pool()


def _devig_two_way(sides: dict[str, float]) -> dict[str, float] | None:
    """sides: {selection: decimal_odds}. Returns devigged fair probs."""
    imps = {k: 1.0 / v for k, v in sides.items()}
    total = sum(imps.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in imps.items()}


def _evaluate_market(
    market, per_sel, home, away, total, margin, home_score, away_score,
    threshold, min_books,
) -> list[GameBet]:
    bets: list[GameBet] = []

    if market == "totals":
        # Group over/under by their shared line.
        by_line: dict[float, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
        for (side, line), book_odds in per_sel.items():
            if line is None or side not in ("over", "under"):
                continue
            for b, dec in book_odds.items():
                by_line[line][side][b] = dec
        for line, sides in by_line.items():
            if "over" not in sides or "under" not in sides:
                continue
            # consensus per book then average
            fair_overs = []
            for b in set(sides["over"]) & set(sides["under"]):
                dv = _devig_two_way({"over": sides["over"][b], "under": sides["under"][b]})
                if dv:
                    fair_overs.append(dv["over"])
            if len(fair_overs) < min_books:
                continue
            consensus_over = sum(fair_overs) / len(fair_overs)
            for side, fair in (("over", consensus_over), ("under", 1 - consensus_over)):
                quotes = sides[side]
                if not quotes:
                    continue
                book, best = max(quotes.items(), key=lambda t: t[1])
                edge = fair - 1.0 / best
                if edge < threshold:
                    continue
                pushed = total == line
                won = (total > line) if side == "over" else (total < line)
                ret = 0.0 if pushed else ((best - 1) if won else -1.0)
                bets.append(GameBet(market, side.title(), line, best, fair, edge,
                                    won, pushed, ret, book))

    elif market == "h2h":
        # 2-way (NBA). selection is the team name; no line.
        sides = {sel: max(bo.items(), key=lambda t: t[1]) for (sel, _l), bo in per_sel.items()}
        # consensus across books, per selection
        per_book_sel: dict[str, dict[str, float]] = defaultdict(dict)
        for (sel, _l), bo in per_sel.items():
            for b, dec in bo.items():
                per_book_sel[b][sel] = dec
        fair_accum: dict[str, list[float]] = defaultdict(list)
        for b, sels in per_book_sel.items():
            dv = _devig_two_way(sels)
            if dv:
                for sel, p in dv.items():
                    fair_accum[sel].append(p)
        n_books = max((len(v) for v in fair_accum.values()), default=0)
        if n_books < min_books:
            return bets
        for sel, ps in fair_accum.items():
            fair = sum(ps) / len(ps)
            quotes = {b: per_book_sel[b][sel] for b in per_book_sel if sel in per_book_sel[b]}
            if not quotes:
                continue
            book, best = max(quotes.items(), key=lambda t: t[1])
            edge = fair - 1.0 / best
            if edge < threshold:
                continue
            # Win if this team won.
            if sel == home:
                won = home_score > away_score
            elif sel == away:
                won = away_score > home_score
            else:
                continue
            ret = (best - 1) if won else -1.0
            bets.append(GameBet(market, sel, None, best, fair, edge, won, False, ret, book))

    elif market == "spreads":
        by_line: dict[tuple[str, float], dict[str, float]] = {}
        per_book_sel: dict[str, dict[tuple[str, float], float]] = defaultdict(dict)
        for (sel, line), bo in per_sel.items():
            if line is None:
                continue
            for b, dec in bo.items():
                per_book_sel[b][(sel, line)] = dec
        # Pair each book's two spread sides (home+line, away-line) for devig.
        fair_accum: dict[tuple[str, float], list[float]] = defaultdict(list)
        for b, sels in per_book_sel.items():
            if len(sels) == 2:
                dv = _devig_two_way({k: v for k, v in sels.items()})
                if dv:
                    for k, p in dv.items():
                        fair_accum[k].append(p)
        for (sel, line), ps in fair_accum.items():
            if len(ps) < min_books:
                continue
            fair = sum(ps) / len(ps)
            quotes = {b: per_book_sel[b][(sel, line)] for b in per_book_sel if (sel, line) in per_book_sel[b]}
            if not quotes:
                continue
            book, best = max(quotes.items(), key=lambda t: t[1])
            edge = fair - 1.0 / best
            if edge < threshold:
                continue
            # Covered if (team margin + line) > 0.
            if sel == home:
                covered_margin = margin + line
            elif sel == away:
                covered_margin = -margin + line
            else:
                continue
            pushed = covered_margin == 0
            won = covered_margin > 0
            ret = 0.0 if pushed else ((best - 1) if won else -1.0)
            bets.append(GameBet(market, sel, line, best, fair, edge, won, pushed, ret, book))

    return bets


def _summarize(bets: list[GameBet]) -> dict:
    if not bets:
        return {"n": 0, "win_rate": 0.0, "roi_pct": 0.0, "avg_edge_pct": 0.0}
    wins = sum(1 for b in bets if b.won and not b.pushed)
    losses = sum(1 for b in bets if not b.won and not b.pushed)
    total_return = sum(b.return_per_unit for b in bets)
    decided = wins + losses
    return {
        "n": len(bets),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / decided, 4) if decided else 0.0,
        "roi_pct": round(100.0 * total_return / len(bets), 2),
        "avg_edge_pct": round(100.0 * sum(b.edge for b in bets) / len(bets), 2),
    }


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="basketball_nba")
    parser.add_argument("--market", default="totals", choices=["totals", "h2h", "spreads"])
    parser.add_argument("--threshold", type=float, default=0.02)
    parser.add_argument("--min-books", type=int, default=3)
    args = parser.parse_args()
    result = asyncio.run(
        run_game_lines_backtest(
            args.sport, market=args.market,
            threshold=args.threshold, min_books=args.min_books,
        )
    )
    s = result["summary"]
    print(f"\nGAME-LINES BACKTEST · {args.sport} · {args.market} · edge≥{args.threshold*100:.1f}%")
    print(f"  bets: {s['n']}  ({s.get('wins',0)}W-{s.get('losses',0)}L)")
    print(f"  win rate: {s['win_rate']*100:.2f}%")
    print(f"  ROI: {s['roi_pct']:+.2f}%")
    print(f"  avg edge: {s['avg_edge_pct']:+.2f}%")
    print(f"  skipped: {result['skipped']}")


if __name__ == "__main__":
    _main()
