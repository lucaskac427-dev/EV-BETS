"""PrizePicks scan pipeline.

Sport-aware. Each tick is parametrized by:
  - A PrizePicksLeagueConfig telling us which projections to pull
  - A list of OddsApiSportConfig telling us which sportsbook events to scan

For NBA the list is one entry (basketball_nba). For soccer we want UCL + WC
+ whatever else is active, all of which share the same SOCCER sport_tag so
quotes join across them.

Each tick:
  1. Pull PrizePicks lines for the league, upsert to dfs_lines.
  2. Pull sharp-book quotes for every Odds API sport config.
  3. For each PrizePicks line, find matching synth-ticker sharp quotes,
     devig per book, average to consensus, score every bettable side.

Run with defaults (NBA): `python -m src.prizepicks.pipeline`
Run for soccer:          `python -m src.prizepicks.pipeline --sport soccer`
"""

import argparse
import asyncio
from collections import defaultdict
from typing import Any

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.providers._player_props import synthesize_ticker
from src.providers.prizepicks import (
    PrizePicksLine,
    fetch_league_projections,
    league_by_sport,
)
from src.providers.sport_config import (
    MLB_ODDS,
    NBA_ODDS,
    WNBA_ODDS,
    SOCCER_ODDS_BRAZIL_SERIE_A,
    SOCCER_ODDS_COPA_SUDAMERICANA,
    SOCCER_ODDS_J_LEAGUE,
    SOCCER_ODDS_UCL,
    SOCCER_ODDS_WORLD_CUP,
    OddsApiSportConfig,
    PrizePicksLeagueConfig,
)
from src.providers.the_odds_api import OddsAPIProvider
from src.projections.soccer import project_over, projection_sample_size
from src.repositories.dfs_lines import (
    fetch_active_dfs_lines,
    insert_dfs_opportunity,
    sweep_inactive_lines,
    upsert_dfs_line,
)


# Blend weight on the projection model when both sharp consensus and a
# projection are available. Matches the reference (60% market / 40% projection)
# from the friend's site. Untuned — sweep against backtest data later.
PROJECTION_BLEND_WEIGHT = 0.40

# Standard Power Play breakeven per leg (3-pick, 6x multiplier) ≈ 55%.
# PrizePicks only lets you bet MORE on demon/goblin lines (LESS is not
# offered). Standards are bettable both ways. Edges for unbettable sides
# are filtered out — see is_bettable().
DEFAULT_BREAKEVEN = 0.55

# US sportsbooks generally post OVER-only quotes on soccer player props (no
# matching UNDER market). When we can't devig the proper way, we estimate
# fair P(over) = implied_over − vig_haircut. ~3% covers the typical US-book
# vig at near-50/50 outcomes; the estimate degrades on extreme outcomes but
# stays usable as a coarse filter.
OVER_ONLY_VIG_HAIRCUT = 0.03

# Some sports (soccer) have spotty single-sided coverage. Allow a sport-tag
# allowlist to score on one book if that's all we have.
SINGLE_BOOK_ALLOWED_SPORTS = {"soccer"}


def _fair_over_for_book(over_quote, under_quote) -> float | None:
    """Compute one book's fair P(over) from its over/under quotes. If only
    over is present, fall back to implied minus a vig haircut. Returns None
    when nothing usable is on offer."""
    o_imp = float(over_quote.implied_prob) if over_quote else None
    u_imp = float(under_quote.implied_prob) if under_quote else None
    if o_imp is not None and u_imp is not None:
        total = o_imp + u_imp
        if total <= 0:
            return None
        return o_imp / total
    if o_imp is not None:
        return max(0.0, min(1.0, o_imp - OVER_ONLY_VIG_HAIRCUT))
    if u_imp is not None:
        return max(0.0, min(1.0, 1.0 - (u_imp - OVER_ONLY_VIG_HAIRCUT)))
    return None


SPORT_PIPELINE_PRESETS: dict[str, tuple[PrizePicksLeagueConfig, list[OddsApiSportConfig]]] = {
    "nba": (league_by_sport("nba"), [NBA_ODDS]),
    "mlb": (league_by_sport("mlb"), [MLB_ODDS]),
    "wnba": (league_by_sport("wnba"), [WNBA_ODDS]),
    "soccer": (
        league_by_sport("soccer"),
        [
            SOCCER_ODDS_UCL,
            SOCCER_ODDS_WORLD_CUP,
            SOCCER_ODDS_BRAZIL_SERIE_A,
            SOCCER_ODDS_J_LEAGUE,
            SOCCER_ODDS_COPA_SUDAMERICANA,
        ],
    ),
}


def is_bettable(odds_type: str, pick_side: str) -> bool:
    if odds_type in ("demon", "goblin"):
        return pick_side == "over"
    return True


def breakeven_for(odds_type: str, pick_side: str) -> float:
    if odds_type == "demon" and pick_side == "over":
        return 0.44  # 1.25x boost on the MORE direction
    if odds_type == "goblin" and pick_side == "over":
        return 1.10  # 0.5x penalty makes goblin MORE almost always -EV
    return DEFAULT_BREAKEVEN


async def sync_lines(
    pool,
    *,
    league_config: PrizePicksLeagueConfig,
    source: str = "prizepicks",
) -> int:
    lines = await fetch_league_projections(league_config)
    seen: list[str] = []
    for line in lines:
        await upsert_dfs_line(
            pool,
            source=source,
            external_id=line.external_id,
            sport=line.sport,
            player_name=line.player_name,
            team=line.team,
            stat_type=line.stat_type,
            line=line.line,
            odds_type=line.odds_type,
            game_starts_at=line.game_starts_at,
        )
        seen.append(line.external_id)
    swept = await sweep_inactive_lines(
        pool, source=source, sport=league_config.sport_tag,
        seen_external_ids=seen, full_fetch=len(seen) > 0,
    )
    log.info(
        "dfs_lines_synced",
        source=source,
        sport=league_config.sport_tag,
        count=len(seen),
        deactivated=swept,
    )
    return len(seen)


def _index_quotes(quotes: list[Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Build {synth_ticker: {book: {side: OddsQuote}}}."""
    by_ticker: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    for q in quotes:
        by_ticker[q.market_kalshi_ticker][q.book][q.side] = q
    return by_ticker


async def _fetch_all_sharp_quotes(odds_configs: list[OddsApiSportConfig]) -> list[Any]:
    """Hit Odds API in parallel for every configured sport / league."""
    providers = [OddsAPIProvider(config=c) for c in odds_configs]
    try:
        results = await asyncio.gather(
            *[p.fetch_odds([]) for p in providers], return_exceptions=False
        )
    finally:
        for p in providers:
            await p.aclose()
    all_quotes: list[Any] = []
    for quotes in results:
        all_quotes.extend(quotes)
    return all_quotes


async def _sync_dfs_source(pool, sport_tag: str, source: str, fetch_fn) -> int:
    """Sync any PrizePicksLine-shaped DFS provider into dfs_lines."""
    lines = await fetch_fn(sport_tag)
    seen: list[str] = []
    for line in lines:
        await upsert_dfs_line(
            pool, source=source, external_id=line.external_id,
            sport=line.sport, player_name=line.player_name, team=line.team,
            stat_type=line.stat_type, line=line.line, odds_type=line.odds_type,
            game_starts_at=line.game_starts_at,
        )
        seen.append(line.external_id)
    swept = await sweep_inactive_lines(
        pool, source=source, sport=sport_tag,
        seen_external_ids=seen, full_fetch=len(seen) > 0,
    )
    log.info("dfs_source_synced", source=source, sport=sport_tag,
             count=len(seen), deactivated=swept)
    return len(seen)


async def _sync_extra_dfs(pool, sport_tag: str) -> None:
    """Sync the non-PrizePicks DFS platforms (Underdog, Sleeper, DK Pick 6)."""
    from src.providers.underdog import fetch_underdog_lines
    from src.providers.sleeper import fetch_sleeper_lines
    from src.providers.dk_pick6 import fetch_dk_pick6_lines
    await _sync_dfs_source(pool, sport_tag, "underdog", fetch_underdog_lines)
    await _sync_dfs_source(pool, sport_tag, "sleeper", fetch_sleeper_lines)
    await _sync_dfs_source(pool, sport_tag, "dk_pick6", fetch_dk_pick6_lines)


async def run_prizepicks_tick(
    pool,
    *,
    league_config: PrizePicksLeagueConfig,
    odds_configs: list[OddsApiSportConfig],
) -> int:
    """Sync PrizePicks + Underdog lines for the league, fetch sharp quotes for
    every configured Odds-API sport, score every line, persist edges. Returns
    the number of dfs_opportunities written this tick."""
    await sync_lines(pool, league_config=league_config)
    await _sync_extra_dfs(pool, league_config.sport_tag)
    sport_tag = league_config.sport_tag.lower()
    # All DFS platforms (PrizePicks + Underdog + Sleeper) for this sport.
    lines = [
        line
        for line in await fetch_active_dfs_lines(pool, source=None)
        if line.sport == sport_tag
    ]
    log.info("dfs_lines_active", sport=sport_tag, count=len(lines))

    sharp_quotes = await _fetch_all_sharp_quotes(odds_configs)
    by_ticker = _index_quotes(sharp_quotes)

    n_written = 0
    for line in lines:
        ticker = synthesize_ticker(
            league_config.sport_tag, line.player_name, line.stat_type, line.line
        )
        per_book = by_ticker.get(ticker)
        if not per_book:
            continue

        fair_overs: dict[str, float] = {}
        for book, sides in per_book.items():
            over = sides.get("over")
            under = sides.get("under")
            fair = _fair_over_for_book(over, under)
            if fair is not None:
                fair_overs[book] = fair

        num_books = len(fair_overs)
        min_books = settings.min_sharp_books
        # Sports with single-sided coverage (soccer in the US) get a 1-book floor.
        if line.sport in SINGLE_BOOK_ALLOWED_SPORTS:
            min_books = 1
        if num_books < min_books:
            continue

        consensus_over = sum(fair_overs.values()) / num_books
        consensus_under = 1.0 - consensus_over

        # Per-book breakdown for the dashboard — what each book is pricing,
        # so the stale platform vs sharp books is visible at a glance.
        import json as _json

        def _amer(q):
            if q is None:
                return None
            d = float(q.decimal_odds)
            return f"+{round((d-1)*100)}" if d >= 2 else f"-{round(100/(d-1))}"

        breakdown = []
        for book, sides in per_book.items():
            breakdown.append({
                "book": book,
                "over": _amer(sides.get("over")),
                "under": _amer(sides.get("under")),
                "fair_over": round(fair_overs[book], 4) if book in fair_overs else None,
            })
        breakdown.sort(key=lambda b: (b["fair_over"] is None, -(b["fair_over"] or 0)))
        breakdown_json = _json.dumps(breakdown)

        # Projection model — only wired for soccer right now (NBA needs its
        # own historical priors before the projection function will return).
        projection_over: float | None = None
        proj_n: int | None = None
        if line.sport == "soccer":
            projection_over = await project_over(
                pool,
                player_name=line.player_name,
                stat=line.stat_type,
                line=line.line,
            )
            if projection_over is not None:
                proj_n = await projection_sample_size(
                    pool, player_name=line.player_name
                )

        # SEPARATION OF CONCERNS: the DFS player-prop edge is PURE sharp
        # consensus. Projection models (game lines, etc.) are a completely
        # separate system and must NEVER move the DFS edge/EV. We still record
        # the projection alongside as a non-binding reference, but the edge that
        # drives every DFS bet is consensus-only.
        blended_over = consensus_over
        blended_under = consensus_under

        if is_bettable(line.odds_type, "over"):
            be_over = breakeven_for(line.odds_type, "over")
            edge_over = consensus_over - be_over
            await insert_dfs_opportunity(
                pool,
                dfs_line_id=line.id,
                pick_side="over",
                consensus_fair_prob=consensus_over,
                breakeven_per_leg=be_over,
                edge_pct=edge_over,
                num_sharp_books=num_books,
                projection_fair_prob=projection_over,
                blended_fair_prob=blended_over,
                projection_sample_size=proj_n,
                book_breakdown=breakdown_json,
            )
            n_written += 1

        if is_bettable(line.odds_type, "under"):
            be_under = breakeven_for(line.odds_type, "under")
            edge_under = consensus_under - be_under
            proj_under = (1.0 - projection_over) if projection_over is not None else None
            await insert_dfs_opportunity(
                pool,
                dfs_line_id=line.id,
                pick_side="under",
                consensus_fair_prob=consensus_under,
                breakeven_per_leg=be_under,
                edge_pct=edge_under,
                num_sharp_books=num_books,
                projection_fair_prob=proj_under,
                blended_fair_prob=blended_under,
                projection_sample_size=proj_n,
                book_breakdown=breakdown_json,
            )
            n_written += 1

    log.info(
        "prizepicks_tick_complete",
        sport=sport_tag,
        edges_written=n_written,
        lines_scanned=len(lines),
    )
    return n_written


async def main(sport: str = "nba") -> None:
    if sport not in SPORT_PIPELINE_PRESETS:
        raise ValueError(
            f"Unknown sport preset '{sport}'. Known: {list(SPORT_PIPELINE_PRESETS)}"
        )
    league_config, odds_configs = SPORT_PIPELINE_PRESETS[sport]
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        n = await run_prizepicks_tick(
            pool, league_config=league_config, odds_configs=odds_configs
        )
        print(f"sport={sport} edges_written={n}")
    finally:
        await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sport",
        default="nba",
        choices=sorted(SPORT_PIPELINE_PRESETS.keys()),
    )
    args = parser.parse_args()
    asyncio.run(main(args.sport))
