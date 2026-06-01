"""Sleeper Picks provider — public DFS pick'em over/under lines.

api.sleeper.app/lines/available is open (no auth). Each line has options[]
with {subject_id, outcome, wager_type, outcome_value, payout_multiplier}.
subject_id joins to api.sleeper.app/v1/players/{sport} for the name.

Emits PrizePicksLine-shaped objects (source 'sleeper') for the dfs_lines
pipeline. payout_multiplier flags boosts (multiplier != ~1.85 standard).
"""

import asyncio

import httpx

from src.logger import log
from src.providers.prizepicks import PrizePicksLine
from datetime import datetime, timedelta, timezone

LINES_URL = "https://api.sleeper.app/lines/available?dynamic=true&include_preset=true"
PLAYERS_URL = "https://api.sleeper.app/v1/players/{sport}"

_STAT_MAP_NBA = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "three_points_made": "threes",
    "3_pointers_made": "threes",
    "blocks": "blocks",
    "steals": "steals",
    "pts_reb_ast": "pra",
    "points_rebounds_assists": "pra",
}
_STAT_MAP_SOCCER = {
    "shots": "shots",
    "shots_on_target": "shots_on_target",
    "assists": "assists",
    "goals": "goals",
}


_STAT_MAP_MLB = {
    "hits": "hits",
    "rbis": "rbis",
    "total_bases": "total_bases",
    "singles": "singles",
    "bat_walks": "batter_walks",
    "home_runs": "home_runs",
    "hits_allowed": "hits_allowed",
    "strike_outs": "strikeouts",
    "outs": "pitcher_outs",
    "earned_runs": "earned_runs",
    "runs": "runs",
}


def _stat_map(sport_tag: str) -> dict[str, str]:
    t = sport_tag.upper()
    if t == "SOCCER":
        return _STAT_MAP_SOCCER
    if t == "MLB":
        return _STAT_MAP_MLB
    return _STAT_MAP_NBA


def parse_sleeper(lines: list[dict], players: dict, sport_tag: str) -> list[PrizePicksLine]:
    stat_map = _stat_map(sport_tag)
    sport_lc = sport_tag.lower()
    out: list[PrizePicksLine] = []
    seen: set[str] = set()
    for ln in lines:
        for opt in ln.get("options", []):
            if (opt.get("sport") or "").lower() != sport_lc:
                continue
            if opt.get("outcome") != "over":  # one row per line; over carries it
                continue
            stat_key = stat_map.get(opt.get("wager_type") or "")
            if not stat_key:
                continue
            try:
                line_val = float(opt.get("outcome_value"))
            except (TypeError, ValueError):
                continue
            sid = str(opt.get("subject_id"))
            p = players.get(sid)
            if not p:
                continue
            name = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
            if not name:
                continue
            ext = str(ln.get("line_id") or opt.get("line_id") or f"{sid}-{stat_key}-{line_val}")
            if ext in seen:
                continue
            seen.add(ext)
            try:
                mult = float(opt.get("payout_multiplier") or 1.85)
            except (TypeError, ValueError):
                mult = 1.85
            odds_type = "demon" if mult > 2.0 else ("goblin" if mult < 1.5 else "standard")
            # Sleeper gives game_status, not a start time. Keep pre-game lines
            # alive (future-date them); anything live/final gets a past time so the
            # sweep deactivates it — never a stale post-tip line.
            status = (opt.get("game_status") or ln.get("game_status") or "").lower()
            starts = (datetime.now(timezone.utc) + timedelta(hours=12)
                      if status == "pre_game"
                      else datetime.now(timezone.utc) - timedelta(minutes=1))
            out.append(PrizePicksLine(
                external_id=ext, sport=sport_lc, player_name=name, team=None,
                stat_type=stat_key, line=line_val, odds_type=odds_type,
                game_starts_at=starts,
            ))
    return out


async def fetch_sleeper_lines(sport_tag: str = "NBA") -> list[PrizePicksLine]:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            lines_r, players_r = await asyncio.gather(
                client.get(LINES_URL),
                client.get(PLAYERS_URL.format(sport=sport_tag.lower())),
            )
            lines_r.raise_for_status()
            players_r.raise_for_status()
            lines = parse_sleeper(lines_r.json(), players_r.json(), sport_tag)
    except Exception as e:
        log.warning("sleeper_fetch_failed", error=str(e)[:120])
        return []
    log.info("sleeper_fetched", sport=sport_tag, line_count=len(lines))
    return lines
