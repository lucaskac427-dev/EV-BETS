"""DraftKings scraper. selections[] shape with American odds as strings."""

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

DK_NBA_URL = "https://sportsbook.draftkings.com/leagues/basketball/nba"
MARKETS_XHR_PATTERN = re.compile(r"/(api|sportscontent).*(selections|markets|eventgroup)")


def parse_draftkings_player_props(payload: dict) -> list[OddsQuote]:
    quotes: list[OddsQuote] = []
    for sel in payload.get("selections", []):
        player = sel.get("participant")
        stat = sel.get("marketStat")
        line = sel.get("points")
        label = (sel.get("label") or "").lower()
        american_raw = sel.get("oddsAmerican")
        if not player or stat is None or line is None:
            continue
        if label not in ("over", "under") or american_raw is None:
            continue
        try:
            american = int(str(american_raw).replace("+", ""))
        except ValueError:
            continue
        ticker = synthesize_kalshi_ticker(player, stat, float(line))
        decimal_odds = american_to_decimal(american)
        quotes.append(
            OddsQuote(
                market_kalshi_ticker=ticker,
                book="draftkings",
                side=label,
                decimal_odds=decimal_odds,
                implied_prob=decimal_to_implied(decimal_odds),
            )
        )
    return quotes


class DraftKingsScraper(OddsProvider):
    name = "draftkings"

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
                await page.goto(DK_NBA_URL, timeout=45_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(8000)
            except Exception as e:
                log.warning("draftkings_navigation_failed", error=str(e))
        finally:
            await browser.close()

        quotes: list[OddsQuote] = []
        for payload in captured:
            quotes.extend(parse_draftkings_player_props(payload))
        log.info("draftkings_fetched", quote_count=len(quotes))
        return quotes
