"""The Odds API provider.

One HTTP-based provider per sport. The factory function for_sport(key) returns
a configured provider for an entry in sport_config.ODDS_API_SPORTS — NBA,
soccer UCL, soccer World Cup, etc. — so the same pipeline runs across sports.

Quota model: a request costs len(markets) × len(regions) units. With ~7 prop
markets in 1 region per event, an event scan costs ~7 units. The /events list
is free.
"""

from typing import Any

import httpx

from src.config import settings
from src.logger import log
from src.providers._player_props import synthesize_ticker
from src.providers.base import (
    OddsProvider,
    OddsQuote,
    american_to_decimal,
    decimal_to_implied,
)
from src.providers.sport_config import (
    ODDS_API_SPORTS,
    NBA_ODDS,
    OddsApiSportConfig,
)


# US state codes the Odds API appends to regional book variants in the us2
# region. Hard Rock arrives as hardrockbet / hardrockbet_az / hardrockbet_fl —
# all ONE operator. Collapsing them to a single canonical key keeps consensus
# and num_sharp_books honest (one book, one vote) instead of triple-counting
# the same price and skewing EV.
_US_STATE_SUFFIXES = frozenset(
    "az co ct dc de fl ia il in ks ky la ma md me mi mo mt nc nd ne nh nj nm nv "
    "ny oh or pa ri sd tn va vt wa wi wv wy".split()
)


def canonical_book(key: str) -> str:
    base, sep, suffix = key.rpartition("_")
    if base and sep and suffix in _US_STATE_SUFFIXES:
        return base
    return key


def parse_event_odds(payload: dict, config: OddsApiSportConfig) -> list[OddsQuote]:
    """Convert one /events/{id}/odds response into a flat list of OddsQuotes.
    Each bookmaker's prices become its own quotes; the pipeline groups by
    `book` to compute per-book devigged fair, then consensus across books."""
    quotes: list[OddsQuote] = []
    market_to_stat = config.market_to_stat
    sport_tag = config.sport_tag

    for bm in payload.get("bookmakers", []):
        book = canonical_book(bm.get("key") or "")
        if not book:
            continue
        for market in bm.get("markets", []):
            stat = market_to_stat.get(market.get("key", ""))
            if not stat:
                continue
            for outcome in market.get("outcomes", []):
                side = (outcome.get("name") or "").lower()
                player = outcome.get("description")
                price = outcome.get("price")
                line = outcome.get("point")
                if side not in ("over", "under"):
                    continue
                if player is None or price is None or line is None:
                    continue
                ticker = synthesize_ticker(sport_tag, player, stat, float(line))
                decimal_odds = american_to_decimal(int(price))
                quotes.append(
                    OddsQuote(
                        market_kalshi_ticker=ticker,
                        book=book,
                        side=side,
                        decimal_odds=decimal_odds,
                        implied_prob=decimal_to_implied(decimal_odds),
                    )
                )
    return quotes


class OddsAPIProvider(OddsProvider):
    """Wraps the-odds-api.com for one sport. The provider's `name` is logged;
    the actual book identity on each emitted quote is the per-bookmaker key
    (e.g. 'draftkings', 'fanduel') so per-book consensus stays correct."""

    name = "odds_api"

    def __init__(self, *, config: OddsApiSportConfig = NBA_ODDS) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=settings.odds_api_base, timeout=15.0
        )

    @classmethod
    def for_sport(cls, sport_key: str) -> "OddsAPIProvider":
        """Construct from a key in sport_config.ODDS_API_SPORTS."""
        if sport_key not in ODDS_API_SPORTS:
            raise ValueError(
                f"Unknown sport '{sport_key}'. Known: {list(ODDS_API_SPORTS)}"
            )
        return cls(config=ODDS_API_SPORTS[sport_key])

    async def fetch_odds(self, kalshi_tickers: list[str]) -> list[OddsQuote]:
        del kalshi_tickers
        if not settings.odds_api_key:
            log.warning("odds_api_key_missing")
            return []

        try:
            events = await self._list_events()
        except Exception as e:
            log.warning(
                "odds_api_events_fetch_failed",
                sport=self._config.sport_key,
                error=str(e),
            )
            return []

        quotes: list[OddsQuote] = []
        markets_csv = ",".join(self._config.market_to_stat.keys())
        if not markets_csv:
            return []
        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue
            try:
                payload = await self._get_event_odds(event_id, markets_csv)
            except Exception as e:
                log.warning(
                    "odds_api_event_odds_failed",
                    sport=self._config.sport_key,
                    event_id=event_id,
                    error=str(e),
                )
                continue
            quotes.extend(parse_event_odds(payload, self._config))

        log.info(
            "odds_api_fetched",
            sport=self._config.sport_key,
            quote_count=len(quotes),
            events=len(events),
        )
        return quotes

    async def _list_events(self) -> list[dict[str, Any]]:
        r = await self._client.get(
            f"/sports/{self._config.sport_key}/events",
            params={"apiKey": settings.odds_api_key},
        )
        r.raise_for_status()
        return r.json()

    async def _get_event_odds(self, event_id: str, markets_csv: str) -> dict[str, Any]:
        r = await self._client.get(
            f"/sports/{self._config.sport_key}/events/{event_id}/odds",
            params={
                "apiKey": settings.odds_api_key,
                "regions": self._config.regions,
                "markets": markets_csv,
                "oddsFormat": "american",
            },
        )
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
