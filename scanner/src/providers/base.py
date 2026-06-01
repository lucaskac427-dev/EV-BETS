"""Odds provider abstract interface.

Each book (Pinnacle, NoVig, BetOnline, DraftKings, Kalshi) implements this
interface. The pipeline calls .fetch_odds() and aggregates results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class OddsQuote:
    """A single (book, market, side) odds reading from one provider call."""

    market_kalshi_ticker: str        # Maps back to markets.kalshi_ticker
    book: str                        # 'pinnacle' | 'novig' | 'kalshi' | ...
    side: str                        # 'over' | 'under' | 'home' | 'away' | 'yes' | 'no'
    decimal_odds: Decimal
    implied_prob: Decimal            # 1 / decimal_odds


def american_to_decimal(american: int) -> Decimal:
    """Convert American odds to decimal odds."""
    if american > 0:
        return Decimal(american) / Decimal(100) + Decimal(1)
    return Decimal(100) / Decimal(abs(american)) + Decimal(1)


def decimal_to_implied(decimal_odds: Decimal) -> Decimal:
    """Raw implied probability (not devigged)."""
    return Decimal(1) / decimal_odds


class OddsProvider(ABC):
    """Abstract base. Subclasses fetch odds for a list of markets and return
    a flat list of OddsQuotes — one per (market, side) pair successfully fetched.
    Failures should raise to let the pipeline orchestrator handle them.
    """

    name: str  # subclass sets

    @abstractmethod
    async def fetch_odds(self, kalshi_tickers: list[str]) -> list[OddsQuote]:
        """Fetch all available quotes for the given markets. May raise on failure."""
        ...
