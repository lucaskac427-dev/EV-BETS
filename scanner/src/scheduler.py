"""30-second scheduler loop with graceful shutdown.

Run as a module: `python -m src.scheduler`
"""

import asyncio
import signal
from datetime import datetime, timezone

from src.calibration.brier import compute_brier_weights
from src.config import settings
from src.db import close_pool, get_pool
from src.kalshi.adapter import KalshiAdapter
from src.kalshi.client import KalshiClient
from src.logger import configure_logging, log
from src.math.consensus import COLD_START_WEIGHTS
from src.pipeline import run_scan_tick
from src.providers.base import OddsProvider
from src.providers.pinnacle import PinnacleScraper
from src.providers.the_odds_api import OddsAPIProvider

LAUNCH_DATE = datetime(2026, 5, 29, tzinfo=timezone.utc)


def _days_since_launch() -> int:
    return max(0, (datetime.now(timezone.utc) - LAUNCH_DATE).days)


async def main_loop() -> None:
    configure_logging(level=settings.log_level)
    pool = await get_pool()

    brier_weights = await compute_brier_weights(pool)
    consensus_weights = brier_weights or COLD_START_WEIGHTS
    log.info("consensus_weights_selected",
             source="brier" if brier_weights else "cold_start",
             weights=consensus_weights)

    # The Odds API single-handedly delivers 7 US books (DK/FanDuel/BetMGM/
    # Caesars/BetRivers/Bovada/Fanatics). Pinnacle stays in as the sharpest
    # signal (not US-regulated, not on the aggregator).
    sharp: list[OddsProvider] = [
        OddsAPIProvider(),
        PinnacleScraper(),
    ]

    # KalshiClient reads kalshi_key_id and kalshi_private_key from settings internally.
    # api_key param overrides settings.kalshi_key_id; base URL is always from settings.
    kclient = KalshiClient(api_key=settings.kalshi_key_id)
    kalshi = KalshiAdapter(client=kclient)

    stop_event = asyncio.Event()

    def _on_signal(sig, frame):
        log.info("scheduler_signal", signal=sig)
        stop_event.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    log.info("scheduler_start", interval_seconds=settings.scan_interval_seconds)
    while not stop_event.is_set():
        try:
            await run_scan_tick(
                pool=pool, sharp_providers=sharp, kalshi=kalshi,
                days_since_launch=_days_since_launch(),
                consensus_weights=consensus_weights,
            )
        except Exception as e:
            log.error("tick_unhandled_error", error=str(e))

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.scan_interval_seconds)
        except asyncio.TimeoutError:
            pass

    log.info("scheduler_shutdown")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main_loop())
