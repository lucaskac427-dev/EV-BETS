"""PrizePicks public projections API client.

PrizePicks publishes its DFS pick'em lines through a public JSON:API endpoint
at api.prizepicks.com/projections. No auth required. The response embeds
related entities (players, stat types, leagues) in an `included` array; the
parser joins them by (type, id).

Each projection has:
  - line_score   : the threshold (e.g. 24.5 points)
  - stat_type    : 'Points', 'Shots On Target', etc. — varies by league
  - odds_type    : 'standard' | 'demon' | 'goblin'
  - start_time   : ISO8601 game start
  - relationships.new_player.id → joined to included `new_player`

The parser is sport-aware: the PrizePicksLeagueConfig passed in says which
stat names to keep and how to map them to the internal stat key namespace.
"""

import asyncio
from datetime import datetime
from typing import Any

import httpx

from src.logger import log
from src.providers.sport_config import (
    PRIZEPICKS_LEAGUES,
    NBA_PRIZEPICKS,
    PrizePicksLeagueConfig,
)

PRIZEPICKS_BASE = "https://api.prizepicks.com"


class PrizePicksLine:
    """Parsed PrizePicks projection."""

    __slots__ = (
        "external_id",
        "sport",
        "player_name",
        "team",
        "stat_type",
        "line",
        "odds_type",
        "game_starts_at",
    )

    def __init__(
        self,
        *,
        external_id: str,
        sport: str,
        player_name: str,
        team: str | None,
        stat_type: str,
        line: float,
        odds_type: str,
        game_starts_at: datetime,
    ) -> None:
        self.external_id = external_id
        self.sport = sport
        self.player_name = player_name
        self.team = team
        self.stat_type = stat_type
        self.line = line
        self.odds_type = odds_type
        self.game_starts_at = game_starts_at


def parse_projections(
    payload: dict[str, Any], config: PrizePicksLeagueConfig
) -> list[PrizePicksLine]:
    """Walk a PrizePicks /projections response into PrizePicksLine objects.
    Filters to stat types tracked by `config`."""
    included = {(x["type"], x["id"]): x for x in payload.get("included", [])}
    stat_map = config.stat_to_internal
    sport_tag = config.sport_tag.lower()
    out: list[PrizePicksLine] = []

    for p in payload.get("data", []):
        if p.get("type") != "projection":
            continue
        attrs = p.get("attributes", {}) or {}
        rels = p.get("relationships", {}) or {}

        stat_label = attrs.get("stat_type") or attrs.get("stat_display_name")
        stat_key = stat_map.get(stat_label)
        if not stat_key:
            continue  # not tracked for this sport

        line_score = attrs.get("line_score")
        if line_score is None:
            continue
        try:
            line = float(line_score)
        except (TypeError, ValueError):
            continue

        odds_type = attrs.get("odds_type") or "standard"

        starts_raw = attrs.get("start_time")
        if not starts_raw:
            continue
        try:
            game_starts_at = datetime.fromisoformat(starts_raw)
        except ValueError:
            continue

        player_rel = (rels.get("new_player") or {}).get("data") or {}
        player_inc = included.get(("new_player", player_rel.get("id"))) if player_rel else None
        if not player_inc:
            continue
        player_attrs = player_inc.get("attributes", {}) or {}
        player_name = player_attrs.get("name")
        if not player_name:
            continue
        team = player_attrs.get("team")

        out.append(
            PrizePicksLine(
                external_id=str(p.get("id")),
                sport=sport_tag,
                player_name=player_name,
                team=team,
                stat_type=stat_key,
                line=line,
                odds_type=odds_type,
                game_starts_at=game_starts_at,
            )
        )
    return out


async def fetch_league_projections(
    config: PrizePicksLeagueConfig,
    *,
    per_page: int = 250,
    max_pages: int = 12,
) -> list[PrizePicksLine]:
    """Pull all paginated projections for a league from PrizePicks."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    lines: list[PrizePicksLine] = []
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        for page in range(1, max_pages + 1):
            try:
                r = await client.get(
                    f"{PRIZEPICKS_BASE}/projections",
                    params={
                        "league_id": config.league_id,
                        "per_page": per_page,
                        "page": page,
                    },
                )
                r.raise_for_status()
            except Exception as e:
                log.warning(
                    "prizepicks_fetch_failed",
                    sport=config.sport_tag,
                    page=page,
                    error=str(e),
                )
                break

            payload = r.json()
            page_lines = parse_projections(payload, config)
            lines.extend(page_lines)
            data = payload.get("data") or []
            if len(data) < per_page:
                break
            await asyncio.sleep(0.2)
    log.info(
        "prizepicks_fetched",
        sport=config.sport_tag,
        line_count=len(lines),
    )
    return lines


# Backwards-compat alias for the NBA pipeline call site.
async def fetch_nba_projections(*, per_page: int = 250, max_pages: int = 8):
    return await fetch_league_projections(
        NBA_PRIZEPICKS, per_page=per_page, max_pages=max_pages
    )


def league_by_sport(sport: str) -> PrizePicksLeagueConfig:
    if sport not in PRIZEPICKS_LEAGUES:
        raise ValueError(
            f"Unknown PrizePicks sport '{sport}'. Known: {list(PRIZEPICKS_LEAGUES)}"
        )
    return PRIZEPICKS_LEAGUES[sport]
