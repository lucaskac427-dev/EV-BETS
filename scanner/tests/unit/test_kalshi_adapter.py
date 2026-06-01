"""Tests for KalshiAdapter — translates Kalshi market responses into OddsQuotes
on the canonical synth-ticker namespace."""

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.kalshi.adapter import KalshiAdapter
from src.repositories.markets import Market


def _wemby_market(line: float = 25.0) -> Market:
    return Market(
        id=1,
        sport="nba",
        kalshi_ticker=f"KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-{int(line)}",
        market_type="player_prop",
        player_name="Victor Wembanyama",
        stat_type="points",
        line=line,
        game_id="26MAY30SASOKC",
        game_starts_at=datetime(2026, 5, 30, 23, 30, tzinfo=timezone.utc),
        is_active=True,
    )


@pytest.fixture
def fake_client():
    client = AsyncMock()
    client.get_market.return_value = {
        "market": {
            "ticker": "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-25",
            "yes_ask_dollars": "0.6300",
            "yes_bid_dollars": "0.6200",
            "no_ask_dollars": "0.3800",
            "no_bid_dollars": "0.3700",
            "last_price_dollars": "0.6300",
        }
    }
    return client


async def test_emits_yes_and_no_on_synth_ticker(fake_client):
    adapter = KalshiAdapter(client=fake_client)
    quotes = await adapter.fetch_odds([_wemby_market(line=25.0)])

    assert len(quotes) == 2
    # Threshold 25 -> shifted line 24.5 (matches sharp-book Over 24.5)
    assert all(q.market_kalshi_ticker == "SYN-NBA-VICTORWEMBANYAMA-POINTS-24.5"
               for q in quotes)
    assert all(q.book == "kalshi" for q in quotes)


async def test_parses_dollar_fields_correctly(fake_client):
    adapter = KalshiAdapter(client=fake_client)
    quotes = await adapter.fetch_odds([_wemby_market()])
    yes = next(q for q in quotes if q.side == "yes")
    no = next(q for q in quotes if q.side == "no")
    # 0.63 USD -> 63 cents -> decimal 100/63 ≈ 1.587
    assert math.isclose(float(yes.decimal_odds), 100 / 63, abs_tol=1e-4)
    # 0.38 USD -> 38 cents -> decimal 100/38 ≈ 2.632
    assert math.isclose(float(no.decimal_odds), 100 / 38, abs_tol=1e-4)


async def test_skips_when_prices_missing():
    client = AsyncMock()
    client.get_market.return_value = {
        "market": {
            "ticker": "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35",
            "yes_ask_dollars": None,
            "no_ask_dollars": None,
        }
    }
    adapter = KalshiAdapter(client=client)
    quotes = await adapter.fetch_odds([_wemby_market(line=35.0)])
    assert quotes == []


async def test_skips_on_fetch_exception():
    client = AsyncMock()
    client.get_market.side_effect = Exception("503")
    adapter = KalshiAdapter(client=client)
    quotes = await adapter.fetch_odds([_wemby_market()])
    assert quotes == []


def test_synth_ticker_shifts_threshold_by_half():
    """Kalshi 'N+' should synth to the same ticker as a sharp book at 'Over N-0.5'."""
    assert (
        KalshiAdapter.synth_ticker_for(_wemby_market(line=25.0))
        == "SYN-NBA-VICTORWEMBANYAMA-POINTS-24.5"
    )
    assert (
        KalshiAdapter.synth_ticker_for(_wemby_market(line=30.0))
        == "SYN-NBA-VICTORWEMBANYAMA-POINTS-29.5"
    )
