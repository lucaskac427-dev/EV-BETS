"""NoVig scraper.

NoVig publishes a JSON markets feed. We load it via cloakbrowser (some endpoints
are bot-protected) and parse player-prop markets into OddsQuotes.

Live JSON shape may differ from the parser's assumed shape — verified in Task 19.
"""

import re
from decimal import Decimal

from cloakbrowser import launch_async

from src.config import settings
from src.logger import log
from src.providers._player_props import synthesize_kalshi_ticker
from src.providers.base import OddsProvider, OddsQuote, decimal_to_implied

NOVIG_NBA_URL = "https://novig.us/sports/basketball/nba"
MARKETS_XHR_PATTERN = re.compile(r"/api/.*(markets|odds)")


def parse_novig_player_props(payload: dict) -> list[OddsQuote]:
    quotes: list[OddsQuote] = []
    for m in payload.get("markets", []):
        player = m.get("player")
        stat = m.get("stat")
        line = m.get("line")
        if not player or stat is None or line is None:
            continue
        ticker = synthesize_kalshi_ticker(player, stat, float(line))
        for o in m.get("outcomes", []):
            name = (o.get("name") or "").lower()
            price = o.get("price")
            if name not in ("over", "under") or price is None:
                continue
            decimal_odds = Decimal(str(price))
            quotes.append(
                OddsQuote(
                    market_kalshi_ticker=ticker,
                    book="novig",
                    side=name,
                    decimal_odds=decimal_odds,
                    implied_prob=decimal_to_implied(decimal_odds),
                )
            )
    return quotes


class NoVigScraper(OddsProvider):
    name = "novig"

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
                await page.goto(NOVIG_NBA_URL, timeout=45_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(8000)
            except Exception as e:
                log.warning("novig_navigation_failed", error=str(e))
        finally:
            await browser.close()

        quotes: list[OddsQuote] = []
        for payload in captured:
            quotes.extend(parse_novig_player_props(payload))
        log.info("novig_fetched", quote_count=len(quotes))
        return quotes
