"""DraftKings Pick 6 provider — DK's PrizePicks-style pick'em board.

DK only publishes the FEATURED sport's pickGroupId on the public JSON endpoint:

  GET /pick6/v1/pickgroups/main
      -> only the in-focus sport (MLB during MLB season); NBA et al. are absent.
  GET /pick6/v1/pickgroups/{pickGroupId}/category/pickcards
      -> pickCardByPickableId, pickSixMarketById (stat map), entityInfoByDkId
         (players), competitionById (game start). PUBLIC once you know the id.

So for a non-featured in-season sport (NBA during MLB season) the only missing
piece is its pickGroupId. DK server-renders the board — pickGroupId included —
straight into the sport's page HTML, and a plain GET of that page is NOT blocked
(no browser, no proxy needed). We fetch the page, pull the pickGroupId out of the
rendered payload, then hit the public pickcards GET. Two cheap HTTP calls.

Each pickable card holds activePickableMarkets[] with a pickSixMarketId (the
stat), a targetValue (the line), and a promoPickTypeId (1 = standard pick'em;
2 = Gimme promo, skipped — different payout math). We emit one standard line per
active market as a PrizePicksLine (source 'dk_pick6') so the existing dfs_lines +
consensus scorer works unchanged.
"""

import re
from datetime import datetime, timedelta, timezone

import httpx

from src.logger import log
from src.providers.prizepicks import PrizePicksLine

DK_BASE = "https://api.draftkings.com/pick6/v1"
DK_PICK6_PAGE = "https://pick6.draftkings.com/?sport={sport}"

# DK server-renders `...,"pickGroupId","148510",...` into the page payload.
_PGID_RE = re.compile(r'pickGroupId[\\",:\s]{1,8}(\d{4,7})')

_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}
_JSON_HEADERS = {
    "User-Agent": _PAGE_HEADERS["User-Agent"],
    "Accept": "application/json",
    "Referer": "https://pick6.draftkings.com/",
}

# Normalized DK stat name / abbreviation -> internal stat key (must match the
# keys the Odds API emits so synth tickers join). Keyed on _norm_stat() output.
_STAT_MAP_NBA: dict[str, str] = {
    "points": "points", "pts": "points",
    "rebounds": "rebounds", "reb": "rebounds", "totalrebounds": "rebounds",
    "assists": "assists", "ast": "assists",
    "3pointersmade": "threes", "threepointersmade": "threes",
    "3ptmade": "threes", "3pm": "threes", "threes": "threes",
    "blocks": "blocks", "blk": "blocks",
    "steals": "steals", "stl": "steals",
    "ptsrebast": "pra", "ptsrebsasts": "pra", "pra": "pra",
    "pointsreboundsassists": "pra",
}
_STAT_MAP_SOCCER: dict[str, str] = {
    "shots": "shots",
    "shotsontarget": "shots_on_target", "shotsongoal": "shots_on_target", "sog": "shots_on_target",
    "assists": "assists",
    "goals": "goals",
    "passes": "passes", "passesattempted": "passes",
    "tackles": "tackles",
    "goaliesaves": "goalie_saves", "saves": "goalie_saves",
}


_STAT_MAP_MLB: dict[str, str] = {
    "pitcherstrikeouts": "strikeouts", "strikeouts": "strikeouts",
    "totalbases": "total_bases",
    "pitchingouts": "pitcher_outs", "outs": "pitcher_outs",
    "hits": "hits",
    "homeruns": "home_runs",
    "rbis": "rbis", "rbi": "rbis",
    "hitsallowed": "hits_allowed",
    "singles": "singles", "doubles": "doubles",
    "earnedrunsallowed": "earned_runs", "earnedruns": "earned_runs",
    "stolenbases": "stolen_bases",
    "runs": "runs",
    "walks": "batter_walks", "walksallowed": "pitcher_walks",
}


def _stat_map(sport_tag: str) -> dict[str, str]:
    t = sport_tag.upper()
    if t == "SOCCER":
        return _STAT_MAP_SOCCER
    if t == "MLB":
        return _STAT_MAP_MLB
    return _STAT_MAP_NBA


def _norm_stat(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _pickgroup_ids(main: dict, sport_tag: str) -> list[int]:
    """Resolve the pickGroupId(s) for a sport from /pickgroups/main.
    NBA matches leagueAbbreviation 'NBA' (excludes WNBA); SOCCER matches sportId 12."""
    want = sport_tag.upper()
    out: list[int] = []
    for pg in main.get("pickGroups", []):
        pgid = pg.get("pickGroupId")
        if pgid is None:
            continue
        leagues = pg.get("leagues") or [{}]
        abbr = (leagues[0].get("leagueAbbreviation") or "").upper()
        sport_id = pg.get("sportId")
        if want == "SOCCER":
            if sport_id == 12:
                out.append(pgid)
        elif abbr == want:
            out.append(pgid)
    return out


def parse_pickcards(payload: dict, sport_tag: str) -> list[PrizePicksLine]:
    stat_map = _stat_map(sport_tag)
    markets = payload.get("pickSixMarketById", {}) or {}
    entities = payload.get("entityInfoByDkId", {}) or {}
    comps = payload.get("competitionById", {}) or {}
    sport = sport_tag.lower()

    seen: set[tuple[str, str, float]] = set()
    out: list[PrizePicksLine] = []

    for card in (payload.get("pickCardByPickableId", {}) or {}).values():
        ents = card.get("entities") or []
        if not ents:
            continue
        ent = ents[0]
        dk_id = ent.get("dkId")
        info = entities.get(str(dk_id)) or entities.get(dk_id) or {}
        player_name = info.get("fullName") or info.get("name")
        if not player_name:
            continue

        # Game start from the player's competition, if resolvable. Fallback is a
        # FUTURE time (not now()) so an unresolved line isn't instantly swept stale.
        starts = datetime.now(timezone.utc) + timedelta(hours=12)
        comp_ids = ent.get("compIds") or []
        if comp_ids:
            comp = comps.get(str(comp_ids[0])) or comps.get(comp_ids[0]) or {}
            raw = comp.get("startTime")
            if raw:
                try:
                    starts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

        for mk in card.get("activePickableMarkets", []):
            if mk.get("isPaused"):
                continue
            if mk.get("promoPickTypeId") != 1:  # standard pick'em only
                continue
            target = mk.get("targetValue")
            if target is None:
                continue
            mkt = markets.get(str(mk.get("pickSixMarketId"))) or markets.get(mk.get("pickSixMarketId")) or {}
            stat_key = stat_map.get(_norm_stat(mkt.get("name", ""))) or stat_map.get(_norm_stat(mkt.get("abbreviation", "")))
            if not stat_key:
                continue
            try:
                line = float(target)
            except (TypeError, ValueError):
                continue

            dedupe = (player_name, stat_key, line)
            if dedupe in seen:
                continue
            seen.add(dedupe)

            out.append(
                PrizePicksLine(
                    external_id=str(mk.get("pickableMarketId")),
                    sport=sport,
                    player_name=player_name,
                    team=None,
                    stat_type=stat_key,
                    line=line,
                    odds_type="standard",
                    game_starts_at=starts,
                )
            )
    return out


async def _resolve_pickgroup_id(sport_tag: str, client: httpx.AsyncClient) -> str | None:
    """Pull the sport's pickGroupId out of its server-rendered Pick6 page.
    DK gates the id off /pickgroups/main but renders it into the page HTML, which
    a plain GET reaches — no browser/proxy needed."""
    url = DK_PICK6_PAGE.format(sport=sport_tag.upper())
    r = await client.get(url, headers=_PAGE_HEADERS)
    r.raise_for_status()
    m = _PGID_RE.search(r.text)
    return m.group(1) if m else None


async def _fetch_pickcards(pgid: str, sport_tag: str, client: httpx.AsyncClient) -> list[PrizePicksLine]:
    """Public pickcards GET for a known pickGroupId."""
    r = await client.get(f"{DK_BASE}/pickgroups/{pgid}/category/pickcards", headers=_JSON_HEADERS)
    r.raise_for_status()
    return parse_pickcards(r.json(), sport_tag)


async def fetch_dk_pick6_lines(sport_tag: str = "NBA") -> list[PrizePicksLine]:
    """Standard DK Pick6 pick'em lines for the sport: resolve the pickGroupId
    from the rendered page, then fetch its pickcards. Two cheap HTTP GETs."""
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            pgid = await _resolve_pickgroup_id(sport_tag, client)
            if not pgid:
                log.warning("dk_pick6_no_pickgroup", sport=sport_tag)
                return []
            lines = await _fetch_pickcards(pgid, sport_tag, client)
    except Exception as e:
        log.warning("dk_pick6_fetch_failed", sport=sport_tag, error=str(e)[:120])
        return []
    log.info("dk_pick6_fetched", sport=sport_tag, line_count=len(lines), pickgroup_id=pgid)
    return lines
