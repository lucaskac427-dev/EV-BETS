"""Underdog Fantasy provider — public pick'em over/under lines.

api.underdogfantasy.com/beta/v5/over_under_lines is open (no auth). Response
has parallel arrays joined by id:
  over_under_lines[].over_under.appearance_stat -> {stat, appearance_id}
  over_under_lines[].stat_value                 -> the line
  over_under_lines[].options[]                  -> higher/lower + american_price
  appearances[id]  -> player_id, match_id
  players[id]      -> first_name, last_name, sport_id

Emits PrizePicksLine-shaped objects (source tagged 'underdog') so the existing
dfs_lines + scoring pipeline works unchanged. Underdog prices its sides, so a
'balanced' line maps to odds_type 'standard'; boosts/discounts are flagged.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from src.logger import log
from src.providers.prizepicks import PrizePicksLine

UNDERDOG_URL = "https://api.underdogfantasy.com/beta/v5/over_under_lines"


def _parse_ts(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None

# Underdog stat key -> internal stat key (per sport tag)
_STAT_MAP_NBA: dict[str, str] = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "3_pointers_made": "threes",
    "three_points_made": "threes",
    "blocks": "blocks",
    "steals": "steals",
    "pts_rebs_asts": "pra",
    "points_rebounds_assists": "pra",
}
_STAT_MAP_SOCCER: dict[str, str] = {
    "shots": "shots",
    "shots_on_target": "shots_on_target",
    "assists": "assists",
    "goals": "goals",
    "passes": "passes",
    "tackles": "tackles",
}


_STAT_MAP_MLB: dict[str, str] = {
    "strikeouts": "strikeouts",      # Underdog tags pitcher Ks as 'strikeouts'
    "outs": "pitcher_outs",
    "hits_allowed": "hits_allowed",
    "walks_allowed": "pitcher_walks",
    "earned_runs": "earned_runs",
    "hits": "hits",
    "total_bases": "total_bases",
    "rbis": "rbis",
    "runs": "runs",
    "singles": "singles",
    "doubles": "doubles",
    "home_runs": "home_runs",
    "stolen_bases": "stolen_bases",
    "walks": "batter_walks",
    # 'runs_allowed' (total, not earned) has no sharp market — left unmapped.
}


def _stat_map(sport_tag: str) -> dict[str, str]:
    t = sport_tag.upper()
    if t == "SOCCER":
        return _STAT_MAP_SOCCER
    if t == "MLB":
        return _STAT_MAP_MLB
    return _STAT_MAP_NBA


def parse_underdog(payload: dict, sport_tag: str) -> list[PrizePicksLine]:
    appearances = {a["id"]: a for a in payload.get("appearances", [])}
    players = {p["id"]: p for p in payload.get("players", [])}
    games = {g.get("id"): g for g in payload.get("games", [])}
    stat_map = _stat_map(sport_tag)
    out: list[PrizePicksLine] = []

    for ln in payload.get("over_under_lines", []):
        ou = ln.get("over_under") or {}
        ap_stat = ou.get("appearance_stat") or {}
        stat_raw = ap_stat.get("stat")
        stat_key = stat_map.get(stat_raw or "")
        if not stat_key:
            continue
        try:
            line = float(ln.get("stat_value"))
        except (TypeError, ValueError):
            continue

        appearance_id = ap_stat.get("appearance_id")
        app = appearances.get(appearance_id)
        if not app:
            continue
        player = players.get(app.get("player_id"))
        if not player:
            continue
        if (player.get("sport_id") or "").upper() != sport_tag.upper():
            continue
        name = f"{player.get('first_name','')} {player.get('last_name','')}".strip()
        if not name:
            continue

        # 'balanced' = standard pick; boosts carry a 'boost' object
        odds_type = "standard"
        if ou.get("boost"):
            odds_type = "demon"  # Underdog boost ~ PrizePicks demon (better payout)

        # Real game start (from games[match_id]) — NOT now(), or the sweep instantly
        # marks every line stale. Future fallback keeps a line alive if unparseable.
        game = games.get((app or {}).get("match_id"))
        starts = _parse_ts((game or {}).get("scheduled_at")) or (
            datetime.now(timezone.utc) + timedelta(hours=12))

        out.append(
            PrizePicksLine(
                external_id=str(ln.get("id")),
                sport=sport_tag.lower(),
                player_name=name,
                team=None,
                stat_type=stat_key,
                line=line,
                odds_type=odds_type,
                game_starts_at=starts,
            )
        )
    return out


async def fetch_underdog_lines(sport_tag: str = "NBA") -> list[PrizePicksLine]:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            r = await client.get(UNDERDOG_URL)
            r.raise_for_status()
            lines = parse_underdog(r.json(), sport_tag)
    except Exception as e:
        log.warning("underdog_fetch_failed", error=str(e)[:120])
        return []
    log.info("underdog_fetched", sport=sport_tag, line_count=len(lines))
    await asyncio.sleep(0)
    return lines
