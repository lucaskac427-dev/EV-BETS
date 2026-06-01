"""Adapter wrapping the Kalshi REST client into an OddsProvider-shaped object.

Kalshi's player-prop markets are binary thresholds ("25+ points") priced in
cents. The pipeline joins quotes across books by a synthetic ticker; this
adapter maps each Kalshi market onto that namespace.

Convention: a Kalshi market at integer threshold N (e.g. "25+ points") is the
same event as the sharp-book "Over (N - 0.5)" since the stat is integer-valued
— both describe P(stat >= N). The adapter synthesizes the canonical ticker
with the shifted line so it matches sharp-book quotes.
"""

from decimal import Decimal
from typing import Any

from src.logger import log
from src.providers._player_props import synthesize_kalshi_ticker
from src.providers.base import OddsQuote
from src.repositories.markets import Market


def _parse_dollar_field(value: Any) -> int | None:
    """Convert a Kalshi '_dollars' field (e.g. '0.6300' or 0.63) to cent int."""
    if value is None:
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


class KalshiAdapter:
    name = "kalshi"

    def __init__(self, *, client: Any):
        self._client = client

    async def fetch_odds(self, markets: list[Market]) -> list[OddsQuote]:
        """Fetch yes/no quotes for each market and emit them on the canonical
        synth-ticker namespace so they join with sharp-book quotes."""
        quotes: list[OddsQuote] = []
        for market in markets:
            try:
                raw = await self._client.get_market(market.kalshi_ticker)
            except Exception as e:
                log.warning(
                    "kalshi_market_fetch_failed",
                    ticker=market.kalshi_ticker,
                    error=str(e),
                )
                continue

            m = raw.get("market", raw) if isinstance(raw, dict) else raw

            yes_ask = _parse_dollar_field(m.get("yes_ask_dollars"))
            no_ask = _parse_dollar_field(m.get("no_ask_dollars"))
            if yes_ask is None or no_ask is None or yes_ask <= 0 or no_ask <= 0:
                log.warning(
                    "kalshi_market_missing_prices",
                    ticker=market.kalshi_ticker,
                    yes_ask=yes_ask,
                    no_ask=no_ask,
                )
                continue

            synth = self.synth_ticker_for(market)
            quotes.append(self._make_quote(synth, "yes", yes_ask))
            quotes.append(self._make_quote(synth, "no", no_ask))
        return quotes

    @staticmethod
    def synth_ticker_for(market: Market) -> str:
        """Canonical synth ticker for a Kalshi market — shifted by 0.5 so a
        Kalshi 'N+' threshold matches a sharp-book 'Over (N - 0.5)' line.
        market.line may arrive as Decimal from asyncpg; cast to float."""
        line = (float(market.line) - 0.5) if market.line is not None else 0.0
        return synthesize_kalshi_ticker(
            market.player_name or "", market.stat_type, line
        )

    @staticmethod
    def _make_quote(synth_ticker: str, side: str, ask_cents: int) -> OddsQuote:
        decimal_odds = Decimal(100) / Decimal(ask_cents)
        implied = Decimal(ask_cents) / Decimal(100)
        return OddsQuote(
            market_kalshi_ticker=synth_ticker,
            book="kalshi",
            side=side,
            decimal_odds=decimal_odds,
            implied_prob=implied,
        )
