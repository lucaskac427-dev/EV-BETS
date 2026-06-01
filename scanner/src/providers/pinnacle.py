"""Pinnacle scraper.

Uses cloakbrowser to bypass bot detection, optionally routed through IPRoyal
residential proxies, to load Pinnacle's NBA page and intercept its arcadia API.

Real API shape (verified live 2026-05-30): Pinnacle's guest arcadia API exposes
two list endpoints that must be joined:
  - /0.1/leagues/487/matchups        -> list of matchup objects
  - /0.1/leagues/487/markets/straight -> list of market objects (prices/lines)
Player props are matchups with type == "special" and
special.category == "Player Props", e.g.
  special.description = "Nikola Jokic (DEN) Total Assists"
Markets join to matchups via market["matchupId"] == matchup["id"]; the line is
prices[].points and the odds are prices[].price (American).
"""

import re
from decimal import Decimal

from cloakbrowser import launch_async

from src.config import settings
from src.logger import log
from src.providers._player_props import synthesize_kalshi_ticker
from src.providers.base import (
    OddsProvider,
    OddsQuote,
    american_to_decimal,
    decimal_to_implied,
)

PINNACLE_NBA_URL = "https://www.pinnacle.com/en/basketball/nba/matchups"

# Map Pinnacle's stat phrasing -> our internal stat keys.
_STAT_MAP = {
    "points": "points",
    "assists": "assists",
    "rebounds": "rebounds",
    "3 point fg": "threes",
    "threes": "threes",
    "threes made": "threes",
    "3-pointers made": "threes",
    "blocks": "blocks",
    "steals": "steals",
    "pts+reb+ast": "pra",
    "pts+rebs+asts": "pra",
    "pts & rebs & asts": "pra",
}

# Description shapes Pinnacle has used:
#   "Nikola Jokic (DEN) Total Assists"   (team-in-parens form)
#   "De'Aaron Fox Total Rebounds"        (no team)
#   "Dylan Harper Total Pts & Rebs & Asts"
# The (TEAM) chunk is optional.
_DESC_RE = re.compile(
    r"^(.+?)(?:\s*\([A-Z]{2,4}\))?\s+Total\s+(.+)$", re.IGNORECASE
)


def parse_pinnacle_description(desc: str) -> tuple[str | None, str | None]:
    """Parse 'Player (TEAM) Total Stat' -> (player, internal_stat_key)."""
    m = _DESC_RE.match(desc.strip())
    if not m:
        return None, None
    player = m.group(1).strip()
    stat_phrase = m.group(2).strip().lower()
    stat = _STAT_MAP.get(stat_phrase)
    return (player, stat) if stat else (None, None)


def parse_pinnacle_player_props(
    matchups: list[dict], markets: list[dict]
) -> list[OddsQuote]:
    """Join matchups + markets into player-prop OddsQuotes.

    matchups: list from /leagues/{id}/matchups
    markets:  list from /leagues/{id}/markets/straight

    Side identification: each special matchup carries a participants list with
    {id, name: "Over"|"Under"}; markets reference these via prices[].participantId.
    Older payloads used prices[].designation directly; both formats are accepted.
    """
    # matchup_id -> (player, stat) for special player-prop matchups only
    prop_matchups: dict[int, tuple[str, str]] = {}
    # participant_id -> "over"/"under" for sides inside prop matchups
    participant_sides: dict[int, str] = {}

    for mu in matchups:
        if not isinstance(mu, dict) or mu.get("type") != "special":
            continue
        special = mu.get("special") or {}
        if special.get("category") != "Player Props":
            continue
        player, stat = parse_pinnacle_description(special.get("description", ""))
        if not (player and stat and mu.get("id") is not None):
            continue
        prop_matchups[int(mu["id"])] = (player, stat)
        for p in mu.get("participants") or []:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            name = (p.get("name") or "").strip().lower()
            if pid is not None and name in ("over", "under"):
                participant_sides[int(pid)] = name

    # Pinnacle's page fires matchups/markets more than once on load; dedupe
    # by (ticker, side) — first occurrence wins.
    seen: set[tuple[str, str]] = set()
    quotes: list[OddsQuote] = []
    for mk in markets:
        if not isinstance(mk, dict):
            continue
        mid = mk.get("matchupId")
        if mid is None or int(mid) not in prop_matchups:
            continue
        player, stat = prop_matchups[int(mid)]
        for price in mk.get("prices", []):
            # New shape (participantId lookup), fall back to legacy "designation".
            pid = price.get("participantId")
            side: str | None = None
            if pid is not None:
                side = participant_sides.get(int(pid))
            if side is None:
                side = price.get("designation")
            american = price.get("price")
            line = price.get("points")
            if side not in ("over", "under") or american is None or line is None:
                continue
            ticker = synthesize_kalshi_ticker(player, stat, float(line))
            if (ticker, side) in seen:
                continue
            seen.add((ticker, side))
            decimal_odds = american_to_decimal(int(american))
            quotes.append(
                OddsQuote(
                    market_kalshi_ticker=ticker,
                    book="pinnacle",
                    side=side,
                    decimal_odds=decimal_odds,
                    implied_prob=decimal_to_implied(decimal_odds),
                )
            )
    return quotes


class PinnacleScraper(OddsProvider):
    name = "pinnacle"

    async def fetch_odds(self, kalshi_tickers: list[str]) -> list[OddsQuote]:
        """Load Pinnacle NBA via cloakbrowser, capture the matchups + markets
        XHRs, join them. The kalshi_tickers param is unused — we return all
        player props and the pipeline joins by synthetic ticker."""
        del kalshi_tickers
        matchups: list[dict] = []
        markets: list[dict] = []

        browser = await launch_async(
            proxy=settings.iproyal_proxy_url or None,
            humanize=True,
            headless=True,
        )
        try:
            page = await browser.new_page()

            async def on_response(resp):
                url = resp.url
                try:
                    if url.endswith("/matchups"):
                        data = await resp.json()
                        if isinstance(data, list):
                            matchups.extend(data)
                    elif url.endswith("/markets/straight"):
                        data = await resp.json()
                        if isinstance(data, list):
                            markets.extend(data)
                except Exception:
                    pass

            page.on("response", on_response)
            try:
                await page.goto(PINNACLE_NBA_URL, timeout=45_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(8000)
            except Exception as e:
                log.warning("pinnacle_navigation_failed", error=str(e))
        finally:
            await browser.close()

        quotes = parse_pinnacle_player_props(matchups, markets)
        log.info(
            "pinnacle_fetched",
            quote_count=len(quotes),
            matchups=len(matchups),
            markets=len(markets),
        )
        return quotes
