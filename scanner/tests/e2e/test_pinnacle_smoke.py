"""End-to-end smoke test — hits real Pinnacle.com via cloakbrowser.

Skipped by default. Run explicitly with: pytest -m e2e
"""

import pytest

from src.providers.pinnacle import PinnacleScraper

pytestmark = pytest.mark.e2e


async def test_pinnacle_scraper_runs_without_crashing():
    """Just verify the scraper can launch a browser and complete a navigation.

    During NBA offseason or if Pinnacle blocks us, quote count may be 0 —
    that's OK for this smoke test. We only care that we don't crash."""
    scraper = PinnacleScraper()
    try:
        quotes = await scraper.fetch_odds([])
    except Exception as e:
        pytest.fail(f"scraper raised: {e}")

    # Sanity check: if we got anything, it should be well-formed
    for q in quotes:
        assert q.book == "pinnacle"
        assert q.side in ("over", "under")
        assert float(q.decimal_odds) > 1.0
