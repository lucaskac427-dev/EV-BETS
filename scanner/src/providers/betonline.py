"""BetOnline scraper. American-odds props in events[].props[] shape."""

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

BETONLINE_NBA_URL = "https://www.betonline.ag/sportsbook/basketball/nba"
MARKETS_XHR_PATTERN = re.compile(r"/api/.*(props|markets|offering)")


def parse_betonline_player_props(payload: dict) -> list[OddsQuote]:
    quotes: list[OddsQuote] = []
    for event in payload.get("events", []):
        for prop in event.get("props", []):
            player = prop.get("playerName")
            stat = prop.get("category")
            line = prop.get("line")
            if not player or stat is None or line is None:
                continue
            ticker = synthesize_kalshi_ticker(player, stat, float(line))
            for side, key in (("over", "over"), ("under", "under")):
                american = prop.get(key)
                if american is None:
                    continue
                decimal_odds = american_to_decimal(int(american))
                quotes.append(
                    OddsQuote(
                        market_kalshi_ticker=ticker,
                        book="betonline",
                        side=side,
                        decimal_odds=decimal_odds,
                        implied_prob=decimal_to_implied(decimal_odds),
                    )
                )
    return quotes


class BetOnlineScraper(OddsProvider):
    name = "betonline"

    async def fetch_odds(self, kalshi_tickers: list[str]) -> list[OddsQuote]:
        del kalshi_tickers
        captured: list[dict] = []
        browser = await launch_async(
            proxy=settings.iproyal_proxy_url or None, humanize=True, headless=True
        )
        try:
            page = await browser.new_page()

            async def on_response(resp):
                if MARKETS_XHR_PATTERN.search(resp.url):
                    try:
                        captured.append(await resp.json())
                    except Exception:
                        pass

            page.on("response", on_response)
            try:
                await page.goto(BETONLINE_NBA_URL, timeout=45_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(8000)
            except Exception as e:
                log.warning("betonline_navigation_failed", error=str(e))
        finally:
            await browser.close()

        quotes: list[OddsQuote] = []
        for payload in captured:
            quotes.extend(parse_betonline_player_props(payload))
        log.info("betonline_fetched", quote_count=len(quotes))
        return quotes
