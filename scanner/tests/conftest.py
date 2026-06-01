"""Root pytest config."""

import os

# Force tests onto a DEDICATED test database. The integration suite TRUNCATEs
# tables (including the expensive ingested ones: player_game_logs, soccer data,
# historical odds), so it must NEVER point at the real kalshi_ev DB. Override
# with TEST_DATABASE_URL for a different test instance — but it must contain
# 'test' (the _clean_db fixture refuses to truncate otherwise).
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://kalshi:kalshi@localhost:5432/kalshi_ev_test"
)
os.environ.setdefault("LOG_LEVEL", "DEBUG")
