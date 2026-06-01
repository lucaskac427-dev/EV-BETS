# Plan 2 — Projection Engine + Additional Sharp Books + Brier Calibration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 40%-weight projection engine (NBA stats → per-player distributions), wire it into the pipeline, add NoVig/BetOnline/DraftKings scrapers, and replace cold-start consensus weights with a rolling Brier calibration loop.

**Architecture:** A nightly `projections-cron` ingests player game logs + team defense via `nba_api` into cache tables, computes baseline projections (rolling mean/std + opponent/pace/rest adjustments) and writes them to the `projections` table. The 30s pipeline reads the latest projection per market and blends it at the ramped weight. A second nightly job reconciles actual game outcomes into `market_outcomes` and recomputes per-book Brier weights, which the pipeline uses in place of `COLD_START_WEIGHTS` once enough data exists.

**Tech Stack:** Same as Plan 1 (Python 3.12 / uv / pytest / asyncpg / scipy). Adds `nba_api` (player stats). Scrapers reuse cloakbrowser + IPRoyal.

**Prerequisite:** Plan 1 complete (tagged `plan-1-mvp`). Builds on existing `src/math/`, `src/repositories/`, `src/providers/`, `src/pipeline.py`.

---

## Scope

**In Plan 2:**
- `nba_api` ingestion → `player_game_logs` + `team_defense_ratings` cache tables
- Baseline projection engine (rolling window + opponent defense + pace + rest adjustments)
- `projections` repository + nightly projection job
- Pipeline reads + blends projections (no longer always `None`)
- NoVig, BetOnline, DraftKings scrapers (mirror the Pinnacle pattern)
- `market_outcomes` reconciliation job
- Rolling 60-day Brier weight computation, used by pipeline with cold-start fallback

**NOT in Plan 2 (deferred to Plan 3):**
- News ingestion (Twitter/SportsDataIO/LLM) — projections in Plan 2 ignore injury news; the engine accepts a `news_events` arg but Plan 2 always passes empty
- Performance / Bets / Proof dashboard pages
- Vercel/Railway deployment
- Discord alerts

---

## File Structure

```
scanner/
├── alembic/versions/
│   └── 002_projection_cache_tables.py        # NEW: player_game_logs, team_defense_ratings
├── src/
│   ├── nba_stats/
│   │   ├── __init__.py
│   │   ├── client.py                         # nba_api wrapper: rate-limited, retried
│   │   └── ingest.py                         # nightly fetch → cache tables
│   ├── projections/
│   │   ├── __init__.py
│   │   ├── engine.py                         # baseline projection math
│   │   └── job.py                            # nightly: compute projections for active markets
│   ├── calibration/
│   │   ├── __init__.py
│   │   ├── reconcile.py                      # actual outcomes → market_outcomes
│   │   └── brier.py                          # rolling Brier weights
│   ├── repositories/
│   │   ├── game_logs.py                      # NEW: cache read/write
│   │   ├── projections.py                    # NEW: write/read projections table
│   │   └── outcomes.py                       # NEW: market_outcomes + brier inputs
│   ├── providers/
│   │   ├── novig.py                          # NEW scraper
│   │   ├── betonline.py                      # NEW scraper
│   │   └── draftkings.py                     # NEW scraper
│   ├── pipeline.py                           # MODIFY: read projections, use brier weights
│   └── scheduler.py                          # MODIFY: register new sharp providers
└── tests/
    ├── unit/
    │   ├── test_projection_engine.py
    │   ├── test_brier.py
    │   ├── test_novig_parser.py
    │   ├── test_betonline_parser.py
    │   └── test_draftkings_parser.py
    └── integration/
        ├── test_game_logs_repo.py
        ├── test_projections_repo.py
        ├── test_outcomes_repo.py
        └── test_pipeline_with_projections.py
```

---

## Phase 1: NBA stats ingestion

### Task 1: Add nba_api dependency + cache table migration

**Files:**
- Modify: `scanner/pyproject.toml` (add `nba_api`)
- Create: `scanner/alembic/versions/002_projection_cache_tables.py`

- [ ] **Step 1: Add nba_api**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner/scanner
uv add "nba_api>=1.11.0"
```

- [ ] **Step 2: Generate migration**

```bash
uv run alembic revision -m "projection cache tables"
mv alembic/versions/*_projection_cache_tables.py alembic/versions/002_projection_cache_tables.py
```

- [ ] **Step 3: Write migration content**

Replace the file body (keep the generated `revision` value, set `down_revision = "001"`):
```python
"""projection cache tables

Revision ID: 002
Revises: 001
Create Date: 2026-05-29

Adds caches populated nightly by nba_stats.ingest, read by the projection engine.
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-player per-game box score rows (rolling window source).
    op.create_table(
        "player_game_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger, nullable=False),
        sa.Column("player_name", sa.Text, nullable=False),
        sa.Column("team_abbr", sa.Text, nullable=False),
        sa.Column("game_id", sa.Text, nullable=False),
        sa.Column("game_date", sa.Date, nullable=False),
        sa.Column("matchup", sa.Text, nullable=False),       # e.g. "LAL @ BOS"
        sa.Column("minutes", sa.Numeric(5, 2), nullable=True),
        sa.Column("points", sa.Integer, nullable=True),
        sa.Column("rebounds", sa.Integer, nullable=True),
        sa.Column("assists", sa.Integer, nullable=True),
        sa.Column("threes", sa.Integer, nullable=True),
        sa.Column("blocks", sa.Integer, nullable=True),
        sa.Column("steals", sa.Integer, nullable=True),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("player_id", "game_id", name="uq_player_game"),
    )
    op.create_index("idx_game_logs_player_date", "player_game_logs", ["player_id", sa.text("game_date DESC")])

    # Team defensive ratings (opponent adjustment source). One row per team per refresh.
    op.create_table(
        "team_defense_ratings",
        sa.Column("team_abbr", sa.Text, primary_key=True),
        sa.Column("def_rating", sa.Numeric(6, 2), nullable=False),     # points allowed per 100 poss
        sa.Column("pace", sa.Numeric(6, 2), nullable=False),           # possessions per 48
        sa.Column("opp_pts_per_game", sa.Numeric(6, 2), nullable=False),
        sa.Column("refreshed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # League-average reference, single row keyed by season for normalizing adjustments.
    op.create_table(
        "league_averages",
        sa.Column("season", sa.Text, primary_key=True),
        sa.Column("avg_def_rating", sa.Numeric(6, 2), nullable=False),
        sa.Column("avg_pace", sa.Numeric(6, 2), nullable=False),
        sa.Column("refreshed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("league_averages")
    op.drop_table("team_defense_ratings")
    op.drop_table("player_game_logs")
```

- [ ] **Step 4: Apply**

```bash
uv run alembic upgrade head
```
Expected: `Running upgrade 001 -> 002, projection cache tables`

- [ ] **Step 5: Verify**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
docker compose exec postgres psql -U kalshi -d kalshi_ev -c "\dt" | grep -E "(player_game_logs|team_defense_ratings|league_averages)"
```
Expected: 3 new tables listed.

- [ ] **Step 6: Commit**

```bash
git add scanner/pyproject.toml scanner/uv.lock scanner/alembic/versions/002_projection_cache_tables.py
git commit -m "feat(scanner): nba_api dep + projection cache tables migration"
```

---

### Task 2: nba_api client wrapper (rate-limited, retried)

**Files:**
- Create: `scanner/src/nba_stats/__init__.py` (empty)
- Create: `scanner/src/nba_stats/client.py`
- Test: `scanner/tests/unit/test_nba_client.py`

- [ ] **Step 1: Write the test (mock nba_api endpoint classes)**

`tests/unit/test_nba_client.py`:
```python
"""Tests for the nba_api wrapper — verifies parsing of endpoint dataframes.

We mock the nba_api endpoint classes so tests don't hit the network.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from src.nba_stats.client import fetch_player_game_logs, fetch_team_defense


@patch("src.nba_stats.client.PlayerGameLogs")
def test_fetch_player_game_logs_parses_rows(mock_endpoint):
    df = pd.DataFrame(
        {
            "PLAYER_ID": [2544, 2544],
            "PLAYER_NAME": ["LeBron James", "LeBron James"],
            "TEAM_ABBREVIATION": ["LAL", "LAL"],
            "GAME_ID": ["0022500001", "0022500002"],
            "GAME_DATE": ["2025-11-18", "2025-11-20"],
            "MATCHUP": ["LAL @ BOS", "LAL vs. DEN"],
            "MIN": [35.0, 33.0],
            "PTS": [28, 31],
            "REB": [8, 7],
            "AST": [9, 11],
            "FG3M": [2, 3],
            "BLK": [1, 0],
            "STL": [2, 1],
        }
    )
    instance = MagicMock()
    instance.get_data_frames.return_value = [df]
    mock_endpoint.return_value = instance

    rows = fetch_player_game_logs(season="2025-26", last_n_games=20)
    assert len(rows) == 2
    assert rows[0]["player_id"] == 2544
    assert rows[0]["points"] == 28
    assert rows[0]["threes"] == 2
    assert rows[0]["matchup"] == "LAL @ BOS"


@patch("src.nba_stats.client.LeagueDashTeamStats")
def test_fetch_team_defense_parses_rows(mock_endpoint):
    df = pd.DataFrame(
        {
            "TEAM_ABBREVIATION": ["BOS", "DEN"],
            "DEF_RATING": [110.5, 114.2],
            "PACE": [98.5, 100.1],
            "OPP_PTS": [108.0, 115.0],
        }
    )
    instance = MagicMock()
    instance.get_data_frames.return_value = [df]
    mock_endpoint.return_value = instance

    rows = fetch_team_defense(season="2025-26")
    assert len(rows) == 2
    assert rows[0]["team_abbr"] == "BOS"
    assert rows[0]["def_rating"] == 110.5
    assert rows[0]["pace"] == 98.5
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/unit/test_nba_client.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Write `src/nba_stats/client.py`**

```python
"""Thin wrapper over nba_api endpoints.

nba_api hits NBA.com's undocumented stats API. It can rate-limit or change
shape without notice, so every call is retried with backoff and returns plain
dicts (not dataframes) so the rest of the system never imports pandas.

Column names come from nba_api's `expected_data` — see
_resources/sports-betting-refs/nba_api/src/nba_api/stats/endpoints/playergamelogs.py
"""

from typing import Any

from nba_api.stats.endpoints import LeagueDashTeamStats, PlayerGameLogs
from tenacity import retry, stop_after_attempt, wait_exponential

from src.logger import log


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_player_game_logs(*, season: str, last_n_games: int = 20) -> list[dict[str, Any]]:
    """Return recent player game-log rows as dicts. One row per (player, game)."""
    endpoint = PlayerGameLogs(
        season_nullable=season,
        last_n_games_nullable=last_n_games,
    )
    df = endpoint.get_data_frames()[0]
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append(
            {
                "player_id": int(r["PLAYER_ID"]),
                "player_name": str(r["PLAYER_NAME"]),
                "team_abbr": str(r["TEAM_ABBREVIATION"]),
                "game_id": str(r["GAME_ID"]),
                "game_date": str(r["GAME_DATE"])[:10],
                "matchup": str(r["MATCHUP"]),
                "minutes": _num(r.get("MIN")),
                "points": _int(r.get("PTS")),
                "rebounds": _int(r.get("REB")),
                "assists": _int(r.get("AST")),
                "threes": _int(r.get("FG3M")),
                "blocks": _int(r.get("BLK")),
                "steals": _int(r.get("STL")),
            }
        )
    log.info("nba_player_logs_fetched", count=len(rows), season=season)
    return rows


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_team_defense(*, season: str) -> list[dict[str, Any]]:
    """Return per-team defensive metrics as dicts."""
    endpoint = LeagueDashTeamStats(
        season=season,
        measure_type_detailed_defense="Advanced",
    )
    df = endpoint.get_data_frames()[0]
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append(
            {
                "team_abbr": str(r["TEAM_ABBREVIATION"]),
                "def_rating": _num(r.get("DEF_RATING")),
                "pace": _num(r.get("PACE")),
                "opp_pts_per_game": _num(r.get("OPP_PTS", r.get("PTS"))),
            }
        )
    log.info("nba_team_defense_fetched", count=len(rows), season=season)
    return rows


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run tests, verify pass**

```bash
uv run pytest tests/unit/test_nba_client.py -v
```
Expected: 2 passed.

Note: `LeagueDashTeamStats` may expose the opponent-points column as `OPP_PTS` only under certain measure types. The `.get("OPP_PTS", r.get("PTS"))` fallback keeps the parser from crashing; live verification in Task 19 confirms the real column. If the live dataframe lacks both, default to 0.0 there.

- [ ] **Step 5: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/nba_stats/__init__.py scanner/src/nba_stats/client.py scanner/tests/unit/test_nba_client.py
git commit -m "feat(nba_stats): rate-limited nba_api client wrapper"
```

---

### Task 3: Game logs + team defense repositories

**Files:**
- Create: `scanner/src/repositories/game_logs.py`
- Test: `scanner/tests/integration/test_game_logs_repo.py`

- [ ] **Step 1: Write `src/repositories/game_logs.py`**

```python
"""Repository for nba_api cache tables: player_game_logs, team_defense_ratings,
league_averages."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import asyncpg


@dataclass(frozen=True, slots=True)
class GameLog:
    player_id: int
    player_name: str
    team_abbr: str
    game_date: date
    minutes: float | None
    points: int | None
    rebounds: int | None
    assists: int | None
    threes: int | None
    blocks: int | None
    steals: int | None


async def upsert_game_logs(pool: asyncpg.Pool, rows: list[dict[str, Any]]) -> int:
    """Insert game-log rows, ignoring duplicates by (player_id, game_id)."""
    if not rows:
        return 0
    records = [
        (
            r["player_id"], r["player_name"], r["team_abbr"], r["game_id"],
            r["game_date"], r["matchup"], r["minutes"], r["points"],
            r["rebounds"], r["assists"], r["threes"], r["blocks"], r["steals"],
        )
        for r in rows
    ]
    await pool.executemany(
        """
        INSERT INTO player_game_logs (
            player_id, player_name, team_abbr, game_id, game_date, matchup,
            minutes, points, rebounds, assists, threes, blocks, steals
        )
        VALUES ($1,$2,$3,$4,$5::date,$6,$7,$8,$9,$10,$11,$12,$13)
        ON CONFLICT (player_id, game_id) DO NOTHING
        """,
        records,
    )
    return len(records)


async def recent_logs_for_player(
    pool: asyncpg.Pool, player_id: int, limit: int = 20
) -> list[GameLog]:
    """Most recent N game logs for a player, newest first."""
    rows = await pool.fetch(
        """
        SELECT player_id, player_name, team_abbr, game_date,
               minutes, points, rebounds, assists, threes, blocks, steals
        FROM player_game_logs
        WHERE player_id = $1
        ORDER BY game_date DESC
        LIMIT $2
        """,
        player_id, limit,
    )
    return [GameLog(**dict(r)) for r in rows]


async def player_id_by_name(pool: asyncpg.Pool, player_name: str) -> int | None:
    """Resolve a player_id from the most recent log with this exact name."""
    row = await pool.fetchrow(
        "SELECT player_id FROM player_game_logs WHERE player_name = $1 "
        "ORDER BY game_date DESC LIMIT 1",
        player_name,
    )
    return int(row["player_id"]) if row else None


async def upsert_team_defense(pool: asyncpg.Pool, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    for r in rows:
        await pool.execute(
            """
            INSERT INTO team_defense_ratings (team_abbr, def_rating, pace, opp_pts_per_game)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (team_abbr) DO UPDATE SET
                def_rating = EXCLUDED.def_rating,
                pace = EXCLUDED.pace,
                opp_pts_per_game = EXCLUDED.opp_pts_per_game,
                refreshed_at = now()
            """,
            r["team_abbr"], r["def_rating"], r["pace"], r["opp_pts_per_game"],
        )
    return len(rows)


async def team_defense(pool: asyncpg.Pool, team_abbr: str) -> dict[str, float] | None:
    row = await pool.fetchrow(
        "SELECT def_rating, pace, opp_pts_per_game FROM team_defense_ratings WHERE team_abbr = $1",
        team_abbr,
    )
    if not row:
        return None
    return {
        "def_rating": float(row["def_rating"]),
        "pace": float(row["pace"]),
        "opp_pts_per_game": float(row["opp_pts_per_game"]),
    }


async def upsert_league_averages(
    pool: asyncpg.Pool, *, season: str, avg_def_rating: float, avg_pace: float
) -> None:
    await pool.execute(
        """
        INSERT INTO league_averages (season, avg_def_rating, avg_pace)
        VALUES ($1, $2, $3)
        ON CONFLICT (season) DO UPDATE SET
            avg_def_rating = EXCLUDED.avg_def_rating,
            avg_pace = EXCLUDED.avg_pace,
            refreshed_at = now()
        """,
        season, avg_def_rating, avg_pace,
    )


async def league_averages(pool: asyncpg.Pool, season: str) -> dict[str, float] | None:
    row = await pool.fetchrow(
        "SELECT avg_def_rating, avg_pace FROM league_averages WHERE season = $1",
        season,
    )
    if not row:
        return None
    return {"avg_def_rating": float(row["avg_def_rating"]), "avg_pace": float(row["avg_pace"])}
```

- [ ] **Step 2: Write `tests/integration/test_game_logs_repo.py`**

```python
"""Integration tests for the game-logs cache repository."""

import pytest

from src.repositories.game_logs import (
    league_averages,
    player_id_by_name,
    recent_logs_for_player,
    team_defense,
    upsert_game_logs,
    upsert_league_averages,
    upsert_team_defense,
)

pytestmark = pytest.mark.integration


def _log(game_id: str, date_str: str, pts: int) -> dict:
    return {
        "player_id": 2544, "player_name": "LeBron James", "team_abbr": "LAL",
        "game_id": game_id, "game_date": date_str, "matchup": "LAL @ BOS",
        "minutes": 34.0, "points": pts, "rebounds": 8, "assists": 9,
        "threes": 2, "blocks": 1, "steals": 1,
    }


async def test_upsert_and_fetch_logs(pool):
    n = await upsert_game_logs(pool, [_log("G1", "2025-11-18", 28), _log("G2", "2025-11-20", 31)])
    assert n == 2
    logs = await recent_logs_for_player(pool, 2544, limit=20)
    assert len(logs) == 2
    assert logs[0].points == 31  # newest first


async def test_upsert_dedupes_by_game(pool):
    await upsert_game_logs(pool, [_log("G1", "2025-11-18", 28)])
    await upsert_game_logs(pool, [_log("G1", "2025-11-18", 99)])  # same game, ignored
    logs = await recent_logs_for_player(pool, 2544)
    assert len(logs) == 1
    assert logs[0].points == 28


async def test_player_id_by_name(pool):
    await upsert_game_logs(pool, [_log("G1", "2025-11-18", 28)])
    assert await player_id_by_name(pool, "LeBron James") == 2544
    assert await player_id_by_name(pool, "Nobody") is None


async def test_team_defense_roundtrip(pool):
    await upsert_team_defense(pool, [
        {"team_abbr": "BOS", "def_rating": 110.5, "pace": 98.5, "opp_pts_per_game": 108.0},
    ])
    d = await team_defense(pool, "BOS")
    assert d["def_rating"] == 110.5
    assert await team_defense(pool, "ZZZ") is None


async def test_league_averages_roundtrip(pool):
    await upsert_league_averages(pool, season="2025-26", avg_def_rating=113.0, avg_pace=99.0)
    avg = await league_averages(pool, "2025-26")
    assert avg["avg_def_rating"] == 113.0
```

- [ ] **Step 3: Add truncate targets to the integration fixture**

In `tests/integration/conftest.py`, the TRUNCATE list must include the new cache tables. Update the TRUNCATE statement to:
```python
        await conn.execute(
            "TRUNCATE markets, odds_snapshots, projections, news_events, "
            "opportunities, bets, bet_results, market_outcomes, "
            "scan_telemetry, player_game_logs, team_defense_ratings, "
            "league_averages RESTART IDENTITY CASCADE"
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/integration/test_game_logs_repo.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/repositories/game_logs.py scanner/tests/integration/test_game_logs_repo.py scanner/tests/integration/conftest.py
git commit -m "feat(repositories): game logs + team defense cache repo"
```

---

### Task 4: NBA stats ingest job

**Files:**
- Create: `scanner/src/nba_stats/ingest.py`

- [ ] **Step 1: Write `src/nba_stats/ingest.py`**

```python
"""Nightly NBA stats ingest.

Fetches recent player game logs + team defense via nba_api, writes them to the
cache tables. Run as: `python -m src.nba_stats.ingest`. Scheduled nightly by
the projections-cron service (Plan 3 wires the cron; Plan 2 runs it manually).
"""

import asyncio

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.nba_stats.client import fetch_player_game_logs, fetch_team_defense
from src.repositories.game_logs import (
    upsert_game_logs,
    upsert_league_averages,
    upsert_team_defense,
)

CURRENT_SEASON = "2025-26"


async def run_ingest(*, season: str = CURRENT_SEASON) -> dict[str, int]:
    pool = await get_pool()

    logs = await asyncio.to_thread(fetch_player_game_logs, season=season, last_n_games=20)
    log_count = await upsert_game_logs(pool, logs)

    defense = await asyncio.to_thread(fetch_team_defense, season=season)
    def_count = await upsert_team_defense(pool, defense)

    # League averages = mean of per-team metrics we just fetched.
    if defense:
        avg_def = sum(d["def_rating"] or 0 for d in defense) / len(defense)
        avg_pace = sum(d["pace"] or 0 for d in defense) / len(defense)
        await upsert_league_averages(
            pool, season=season, avg_def_rating=avg_def, avg_pace=avg_pace
        )

    log.info("nba_ingest_complete", logs=log_count, teams=def_count)
    return {"logs": log_count, "teams": def_count}


async def main() -> None:
    configure_logging(level=settings.log_level)
    try:
        await run_ingest()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify it imports**

```bash
uv run python -c "from src.nba_stats.ingest import run_ingest; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/nba_stats/ingest.py
git commit -m "feat(nba_stats): nightly ingest job (logs + team defense)"
```

(Live nba_api run happens in Task 19 verification — do not run against the live API here.)

---

## Phase 2: Projection engine

### Task 5: Baseline projection engine

**Files:**
- Create: `scanner/src/projections/__init__.py` (empty)
- Create: `scanner/src/projections/engine.py`
- Test: `scanner/tests/unit/test_projection_engine.py`

The engine is a pure function: game logs + matchup context → (mean, std, distribution, fair_prob_over). No DB, no I/O — fully unit-testable. News adjustments are NOT in Plan 2 (Plan 3 adds them when the news system exists).

- [ ] **Step 1: Write `tests/unit/test_projection_engine.py`**

```python
"""Tests for the baseline projection engine."""

import math

import pytest

from src.projections.engine import StatSample, project

# Synthetic samples: 10 games of points for a ~25 PPG scorer.
POINTS_SAMPLES = [
    StatSample(points=24, rebounds=8, assists=7, threes=2, blocks=1, steals=1),
    StatSample(points=28, rebounds=7, assists=9, threes=3, blocks=0, steals=2),
    StatSample(points=22, rebounds=9, assists=6, threes=1, blocks=1, steals=0),
    StatSample(points=30, rebounds=6, assists=8, threes=4, blocks=2, steals=1),
    StatSample(points=26, rebounds=8, assists=7, threes=2, blocks=1, steals=1),
    StatSample(points=20, rebounds=10, assists=5, threes=1, blocks=0, steals=2),
    StatSample(points=27, rebounds=7, assists=9, threes=3, blocks=1, steals=1),
    StatSample(points=25, rebounds=8, assists=8, threes=2, blocks=1, steals=0),
    StatSample(points=23, rebounds=9, assists=6, threes=2, blocks=0, steals=1),
    StatSample(points=29, rebounds=6, assists=10, threes=4, blocks=2, steals=1),
]

# Neutral matchup: opponent exactly league-average, normal pace, not B2B.
NEUTRAL = dict(
    opp_def_rating=113.0, league_avg_def_rating=113.0,
    opp_pace=99.0, league_avg_pace=99.0, is_b2b=False,
)


def test_points_projection_mean_near_sample_mean():
    # sample mean = 25.4
    result = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **NEUTRAL)
    assert math.isclose(result.mean, 25.4, abs_tol=0.1)
    assert result.distribution == "normal"
    assert 0.5 < result.fair_prob_over < 0.65  # mean above line → over likelier


def test_rebounds_use_negative_binomial():
    result = project(samples=POINTS_SAMPLES, stat="rebounds", line=7.5, **NEUTRAL)
    assert result.distribution == "negative_binomial"
    # rebounds sample mean = 7.8 → slightly over 7.5
    assert result.fair_prob_over > 0.5


def test_pra_sums_three_stats():
    # PRA mean = points(25.4) + reb(7.8) + ast(7.5) = 40.7
    result = project(samples=POINTS_SAMPLES, stat="pra", line=39.5, **NEUTRAL)
    assert math.isclose(result.mean, 40.7, abs_tol=0.2)
    assert result.distribution == "normal"


def test_tough_defense_lowers_scoring_projection():
    # Opponent allows FEWER points (lower def_rating) → projection drops below neutral.
    tough = dict(NEUTRAL, opp_def_rating=105.0)  # better defense than 113 avg
    neutral = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **NEUTRAL)
    vs_tough = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **tough)
    assert vs_tough.mean < neutral.mean


def test_back_to_back_lowers_projection():
    b2b = dict(NEUTRAL, is_b2b=True)
    rested = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **NEUTRAL)
    tired = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **b2b)
    assert tired.mean < rested.mean
    assert math.isclose(tired.mean, rested.mean * 0.96, abs_tol=0.01)


def test_high_pace_raises_projection():
    fast = dict(NEUTRAL, opp_pace=104.0)  # faster than 99 avg
    neutral = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **NEUTRAL)
    vs_fast = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **fast)
    assert vs_fast.mean > neutral.mean


def test_too_few_samples_returns_none():
    result = project(samples=POINTS_SAMPLES[:2], stat="points", line=24.5, **NEUTRAL)
    assert result is None  # need >= MIN_SAMPLES


def test_unknown_stat_raises():
    with pytest.raises(ValueError, match="unknown stat"):
        project(samples=POINTS_SAMPLES, stat="dunks", line=1.5, **NEUTRAL)
```

- [ ] **Step 2: Run, verify failure**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner/scanner
uv run pytest tests/unit/test_projection_engine.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Write `src/projections/engine.py`**

```python
"""Baseline projection engine.

Pure function: recent game samples + matchup context → projected (mean, std,
distribution, P(over line)). No I/O.

Adjustments (baseline v1):
  - Opponent defense: scoring stats only (points, pra, threes). factor =
    opp_def_rating / league_avg_def_rating. Higher opp def_rating = weaker
    defense (more points allowed) = boost.
  - Pace: all stats. factor = opp_pace / league_avg_pace. More possessions =
    more counting events.
  - Rest: 0.96 multiplier on a back-to-back.

News adjustments (injury_out etc.) are NOT handled here — Plan 3 adds them.
"""

import statistics
from dataclasses import dataclass

from src.math.distributions import STAT_DISTRIBUTIONS, fair_prob_over

MIN_SAMPLES = 5
B2B_MULTIPLIER = 0.96
SCORING_STATS = {"points", "pra", "threes"}


@dataclass(frozen=True, slots=True)
class StatSample:
    points: int
    rebounds: int
    assists: int
    threes: int
    blocks: int
    steals: int


@dataclass(frozen=True, slots=True)
class Projection:
    mean: float
    std: float
    distribution: str
    fair_prob_over: float


def _extract(sample: StatSample, stat: str) -> float:
    if stat == "pra":
        return sample.points + sample.rebounds + sample.assists
    if stat in ("points", "rebounds", "assists", "threes", "blocks", "steals"):
        return getattr(sample, stat)
    raise ValueError(f"unknown stat: {stat!r}")


def project(
    *,
    samples: list[StatSample],
    stat: str,
    line: float,
    opp_def_rating: float,
    league_avg_def_rating: float,
    opp_pace: float,
    league_avg_pace: float,
    is_b2b: bool,
) -> Projection | None:
    """Return a Projection, or None if not enough samples."""
    if stat not in STAT_DISTRIBUTIONS and stat != "pra":
        raise ValueError(f"unknown stat: {stat!r}")
    if len(samples) < MIN_SAMPLES:
        return None

    values = [_extract(s, stat) for s in samples]
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 1.0
    if std <= 0:
        std = 1.0

    # Pace adjustment (all stats)
    if league_avg_pace > 0:
        mean *= opp_pace / league_avg_pace

    # Opponent defense adjustment (scoring stats only)
    if stat in SCORING_STATS and league_avg_def_rating > 0:
        mean *= opp_def_rating / league_avg_def_rating

    # Rest
    if is_b2b:
        mean *= B2B_MULTIPLIER

    distribution = STAT_DISTRIBUTIONS["points"] if stat == "pra" else STAT_DISTRIBUTIONS[stat]
    prob = fair_prob_over(mean=mean, std=std, line=line, distribution=distribution)
    return Projection(mean=mean, std=std, distribution=distribution, fair_prob_over=prob)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
uv run pytest tests/unit/test_projection_engine.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/projections/__init__.py scanner/src/projections/engine.py scanner/tests/unit/test_projection_engine.py
git commit -m "feat(projections): baseline projection engine"
```

---

### Task 6: Projections repository

**Files:**
- Create: `scanner/src/repositories/projections.py`
- Test: `scanner/tests/integration/test_projections_repo.py`

- [ ] **Step 1: Write `src/repositories/projections.py`**

```python
"""Repository for the projections table (written nightly, read by pipeline)."""

from dataclasses import dataclass
from decimal import Decimal

import asyncpg


@dataclass(frozen=True, slots=True)
class StoredProjection:
    market_id: int
    fair_prob_over: float
    model_version: str


async def insert_projection(
    pool: asyncpg.Pool,
    *,
    market_id: int,
    mean: float,
    std_dev: float,
    distribution: str,
    fair_prob_over: float,
    model_version: str,
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO projections (market_id, mean, std_dev, distribution,
                                 fair_prob_over, model_version)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        market_id, Decimal(str(round(mean, 3))), Decimal(str(round(std_dev, 3))),
        distribution, Decimal(str(round(fair_prob_over, 6))), model_version,
    )
    return row["id"]


async def latest_projection_prob(pool: asyncpg.Pool, market_id: int) -> float | None:
    """Most recent projection's fair_prob_over for a market, or None."""
    row = await pool.fetchrow(
        """
        SELECT fair_prob_over FROM projections
        WHERE market_id = $1
        ORDER BY computed_at DESC LIMIT 1
        """,
        market_id,
    )
    return float(row["fair_prob_over"]) if row else None
```

- [ ] **Step 2: Write `tests/integration/test_projections_repo.py`**

```python
"""Integration tests for the projections repository."""

from datetime import datetime, timezone

import pytest

from src.repositories.markets import upsert_market
from src.repositories.projections import insert_projection, latest_projection_prob

pytestmark = pytest.mark.integration


async def _market(pool):
    return await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-X-POINTS-24.5",
        market_type="player_prop", game_id="G",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )


async def test_insert_and_read_latest(pool):
    m = await _market(pool)
    await insert_projection(
        pool, market_id=m.id, mean=25.4, std_dev=3.2,
        distribution="normal", fair_prob_over=0.58, model_version="baseline-v1",
    )
    assert abs(await latest_projection_prob(pool, m.id) - 0.58) < 1e-6


async def test_latest_returns_newest(pool):
    m = await _market(pool)
    await insert_projection(pool, market_id=m.id, mean=25.0, std_dev=3.0,
                            distribution="normal", fair_prob_over=0.50, model_version="v1")
    await insert_projection(pool, market_id=m.id, mean=26.0, std_dev=3.0,
                            distribution="normal", fair_prob_over=0.62, model_version="v1")
    assert abs(await latest_projection_prob(pool, m.id) - 0.62) < 1e-6


async def test_none_when_no_projection(pool):
    m = await _market(pool)
    assert await latest_projection_prob(pool, m.id) is None
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/integration/test_projections_repo.py -v
```
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/repositories/projections.py scanner/tests/integration/test_projections_repo.py
git commit -m "feat(repositories): projections write/read"
```

---

### Task 7: Projection job

**Files:**
- Create: `scanner/src/projections/job.py`
- Test: `scanner/tests/integration/test_projection_job.py`

The job reads active markets, resolves each player's recent logs + opponent defense from the cache, runs the engine, and writes a projection row. It parses the opponent abbreviation from the market's `game_id` (format `AWAY-HOME` e.g. `LAL-BOS`). The player's own team comes from their latest game log; the opponent is the other team in `game_id`.

- [ ] **Step 1: Write `tests/integration/test_projection_job.py`**

```python
"""Integration test for the nightly projection job."""

from datetime import datetime, timezone

import pytest

from src.projections.job import run_projection_job
from src.repositories.game_logs import (
    upsert_game_logs,
    upsert_league_averages,
    upsert_team_defense,
)
from src.repositories.markets import upsert_market
from src.repositories.projections import latest_projection_prob

pytestmark = pytest.mark.integration


def _log(gid: str, date_str: str, pts: int) -> dict:
    return {
        "player_id": 2544, "player_name": "LeBron James", "team_abbr": "LAL",
        "game_id": gid, "game_date": date_str, "matchup": "LAL @ BOS",
        "minutes": 34.0, "points": pts, "rebounds": 8, "assists": 8,
        "threes": 2, "blocks": 1, "steals": 1,
    }


async def test_job_writes_projection_for_player_prop(pool):
    # Seed 10 game logs for LeBron
    logs = [_log(f"G{i}", f"2025-11-{10+i:02d}", 24 + (i % 5)) for i in range(10)]
    await upsert_game_logs(pool, logs)
    # Seed team defense for opponent BOS + league averages
    await upsert_team_defense(pool, [
        {"team_abbr": "BOS", "def_rating": 113.0, "pace": 99.0, "opp_pts_per_game": 110.0},
    ])
    await upsert_league_averages(pool, season="2025-26", avg_def_rating=113.0, avg_pace=99.0)
    # Market: LeBron points 24.5, game LAL @ BOS (game_id "LAL-BOS")
    await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-LEBRONJAMES-POINTS-24.5",
        market_type="player_prop", player_name="LeBron James", stat_type="points",
        line=24.5, game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 21, 19, 30, tzinfo=timezone.utc),
    )

    written = await run_projection_job(pool, season="2025-26")
    assert written >= 1

    m_id_row = await pool.fetchrow(
        "SELECT id FROM markets WHERE kalshi_ticker = 'SYN-NBA-LEBRONJAMES-POINTS-24.5'"
    )
    prob = await latest_projection_prob(pool, m_id_row["id"])
    assert prob is not None
    assert 0.0 < prob < 1.0


async def test_job_skips_market_without_logs(pool):
    await upsert_league_averages(pool, season="2025-26", avg_def_rating=113.0, avg_pace=99.0)
    await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-NOBODY-POINTS-10.5",
        market_type="player_prop", player_name="Nobody", stat_type="points",
        line=10.5, game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 21, 19, 30, tzinfo=timezone.utc),
    )
    written = await run_projection_job(pool, season="2025-26")
    assert written == 0
```

- [ ] **Step 2: Write `src/projections/job.py`**

```python
"""Nightly projection job: active markets → projection rows.

Run as `python -m src.projections.job`. Scheduled by projections-cron (Plan 3).
"""

import asyncio

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.engine import StatSample, project
from src.repositories.game_logs import (
    league_averages,
    player_id_by_name,
    recent_logs_for_player,
    team_defense,
)
from src.repositories.markets import Market, fetch_active_markets
from src.repositories.projections import insert_projection

MODEL_VERSION = "baseline-v1"


def _opponent_abbr(market: Market) -> str | None:
    """game_id is 'AWAY-HOME' (e.g. 'LAL-BOS'). The opponent is whichever side
    is NOT the player's team. We don't know the player's team here, so the job
    passes both candidates and picks the one with team_defense data."""
    parts = market.game_id.split("-")
    return parts if len(parts) == 2 else None


async def run_projection_job(pool, *, season: str) -> int:
    markets = await fetch_active_markets(pool)
    avg = await league_averages(pool, season)
    if avg is None:
        log.warning("projection_job_no_league_avg", season=season)
        return 0

    written = 0
    for market in markets:
        if market.market_type != "player_prop" or not market.player_name or not market.stat_type:
            continue
        if market.line is None:
            continue

        player_id = await player_id_by_name(pool, market.player_name)
        if player_id is None:
            continue

        logs = await recent_logs_for_player(pool, player_id, limit=20)
        if not logs:
            continue

        player_team = logs[0].team_abbr
        candidates = _opponent_abbr(market)
        if not candidates:
            continue
        opp_abbr = next((c for c in candidates if c != player_team), None)
        if opp_abbr is None:
            continue
        opp = await team_defense(pool, opp_abbr)
        if opp is None:
            continue

        samples = [
            StatSample(
                points=l.points or 0, rebounds=l.rebounds or 0, assists=l.assists or 0,
                threes=l.threes or 0, blocks=l.blocks or 0, steals=l.steals or 0,
            )
            for l in logs
        ]
        proj = project(
            samples=samples,
            stat=market.stat_type,
            line=float(market.line),
            opp_def_rating=opp["def_rating"],
            league_avg_def_rating=avg["avg_def_rating"],
            opp_pace=opp["pace"],
            league_avg_pace=avg["avg_pace"],
            is_b2b=False,  # Plan 2 doesn't compute rest; Plan 3 can add schedule lookup
        )
        if proj is None:
            continue

        await insert_projection(
            pool, market_id=market.id, mean=proj.mean, std_dev=proj.std,
            distribution=proj.distribution, fair_prob_over=proj.fair_prob_over,
            model_version=MODEL_VERSION,
        )
        written += 1

    log.info("projection_job_complete", written=written)
    return written


async def main() -> None:
    configure_logging(level=settings.log_level)
    try:
        pool = await get_pool()
        await run_projection_job(pool, season="2025-26")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/integration/test_projection_job.py -v
```
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/projections/job.py scanner/tests/integration/test_projection_job.py
git commit -m "feat(projections): nightly projection job"
```

---

## Phase 3: Wire projections into the pipeline

### Task 8: Pipeline reads + blends projections

**Files:**
- Modify: `scanner/src/pipeline.py`
- Test: `scanner/tests/integration/test_pipeline_with_projections.py`

In Plan 1, `run_scan_tick` always passed `projection_prob=None` and `_compute_market_ev` hardcoded `projection_prob=None`. Now `_compute_market_ev` takes a `projection_prob_over` arg, and `run_scan_tick` fetches the latest projection per market before computing EV.

- [ ] **Step 1: Change `_compute_market_ev` signature in `src/pipeline.py`**

Find the current function:
```python
def _compute_market_ev(
    quotes: list[OddsQuote], projection_weight: float
) -> tuple[float, str, Decimal, float, float, int] | None:
```
Replace its signature and the two `blended_fair_prob(...)` calls inside it. The full replacement function:
```python
def _compute_market_ev(
    quotes: list[OddsQuote],
    projection_weight: float,
    projection_prob_over: float | None,
) -> tuple[float, str, Decimal, float, float, float | None, int] | None:
    """For one market's quotes, return (ev_pct, kalshi_side, kalshi_decimal_odds,
    consensus_prob, blended_prob, projection_prob_for_side, num_sharp_books) for
    the side with positive edge, or None if no edge / not enough data.
    """
    sharp_quotes: dict[str, dict[str, OddsQuote]] = defaultdict(dict)
    kalshi_yes: OddsQuote | None = None
    kalshi_no: OddsQuote | None = None

    for q in quotes:
        if q.book == "kalshi":
            if q.side == "yes":
                kalshi_yes = q
            elif q.side == "no":
                kalshi_no = q
        else:
            sharp_quotes[q.book][q.side] = q

    if kalshi_yes is None or kalshi_no is None:
        return None

    fair_over_per_book: dict[str, float] = {}
    for book, sides in sharp_quotes.items():
        if "over" not in sides or "under" not in sides:
            continue
        try:
            fair_over, _ = devig(
                float(sides["over"].implied_prob),
                float(sides["under"].implied_prob),
            )
            fair_over_per_book[book] = fair_over
        except ValueError:
            continue

    num_books = len(fair_over_per_book)
    if num_books < settings.min_sharp_books:
        return None

    consensus_over = brier_weighted_consensus(
        fair_probs=fair_over_per_book,
        weights=COLD_START_WEIGHTS,
    )
    consensus_under = 1.0 - consensus_over

    blended_over = blended_fair_prob(
        consensus_prob=consensus_over,
        projection_prob=projection_prob_over,
        projection_weight=projection_weight,
    )
    blended_under = 1.0 - blended_over
    projection_under = (1.0 - projection_prob_over) if projection_prob_over is not None else None

    yes_ev = kalshi_ev(
        fair_prob_yes=blended_over,
        yes_price_cents=int(round(float(kalshi_yes.implied_prob) * 100)),
    )
    no_ev = kalshi_ev(
        fair_prob_yes=blended_under,
        yes_price_cents=int(round(float(kalshi_no.implied_prob) * 100)),
    )

    if yes_ev >= no_ev:
        return (yes_ev, "yes", kalshi_yes.decimal_odds, consensus_over,
                blended_over, projection_prob_over, num_books)
    return (no_ev, "no", kalshi_no.decimal_odds, consensus_under,
            blended_under, projection_under, num_books)
```

- [ ] **Step 2: Update the caller in `run_scan_tick`**

Add the import near the other repository imports at the top of `src/pipeline.py`:
```python
from src.repositories.projections import latest_projection_prob
```

Then find the per-market loop body in `run_scan_tick`. Replace the block from `ev_result = _compute_market_ev(...)` through the `insert_opportunity(...)` call with:
```python
        projection_prob = await latest_projection_prob(pool, market.id)
        ev_result = _compute_market_ev(quotes, proj_weight, projection_prob)
        if ev_result is None:
            continue

        (ev_pct, side, kalshi_decimal_odds, consensus_prob,
         blended_prob, projection_for_side, num_books) = ev_result
        if ev_pct < settings.min_ev_threshold:
            continue

        suspicious = ev_pct > settings.suspicious_ev_threshold
        stake = kelly_stake_cents(
            fair_prob=blended_prob,
            decimal_odds=float(kalshi_decimal_odds),
            bankroll_cents=bankroll,
            fraction=settings.kelly_fraction,
            cap_pct=settings.kelly_cap_pct,
        )
        kelly_fraction = Decimal(stake) / Decimal(bankroll) if bankroll > 0 else None

        await insert_opportunity(
            pool,
            market_id=market.id,
            kalshi_side=side,
            kalshi_decimal_odds=kalshi_decimal_odds,
            consensus_fair_prob=Decimal(str(round(consensus_prob, 6))),
            projection_fair_prob=(
                Decimal(str(round(projection_for_side, 6)))
                if projection_for_side is not None else None
            ),
            blended_fair_prob=Decimal(str(round(blended_prob, 6))),
            ev_pct=Decimal(str(round(ev_pct, 4))),
            kelly_fraction=kelly_fraction,
            num_sharp_books=num_books,
            suspicious=suspicious,
        )
        opps_written += 1
```

- [ ] **Step 3: Write `tests/integration/test_pipeline_with_projections.py`**

```python
"""Pipeline test verifying projections are blended into the opportunity."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.kalshi.adapter import KalshiAdapter
from src.pipeline import run_scan_tick
from src.providers.base import OddsQuote
from src.repositories.markets import upsert_market
from src.repositories.projections import insert_projection

pytestmark = pytest.mark.integration


class FakeProvider:
    def __init__(self, name, quotes):
        self.name = name
        self._quotes = quotes

    async def fetch_odds(self, _):
        return self._quotes


async def test_projection_recorded_on_opportunity(pool):
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-LBJ-POINTS-24.5",
        market_type="player_prop", player_name="LeBron James", stat_type="points",
        line=24.5, game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )
    # Projection says 'over' is 60% likely
    await insert_projection(
        pool, market_id=m.id, mean=26.0, std_dev=4.0,
        distribution="normal", fair_prob_over=0.60, model_version="baseline-v1",
    )

    sharp = FakeProvider("pinnacle", [
        OddsQuote("SYN-NBA-LBJ-POINTS-24.5", "pinnacle", "over", Decimal("1.90"), Decimal("0.526")),
        OddsQuote("SYN-NBA-LBJ-POINTS-24.5", "pinnacle", "under", Decimal("1.90"), Decimal("0.526")),
    ])
    sharp2 = FakeProvider("novig", [
        OddsQuote("SYN-NBA-LBJ-POINTS-24.5", "novig", "over", Decimal("1.91"), Decimal("0.524")),
        OddsQuote("SYN-NBA-LBJ-POINTS-24.5", "novig", "under", Decimal("1.91"), Decimal("0.524")),
    ])
    adapter = KalshiAdapter(client=AsyncMock())
    adapter.fetch_odds = AsyncMock(return_value=[
        OddsQuote("SYN-NBA-LBJ-POINTS-24.5", "kalshi", "yes", Decimal(100)/Decimal(45), Decimal("0.45")),
        OddsQuote("SYN-NBA-LBJ-POINTS-24.5", "kalshi", "no", Decimal(100)/Decimal(55), Decimal("0.55")),
    ])

    # days_since_launch=90 → projection weight 0.40 (full)
    n = await run_scan_tick(pool=pool, sharp_providers=[sharp, sharp2], kalshi=adapter,
                            days_since_launch=90)
    assert n >= 1

    row = await pool.fetchrow("SELECT * FROM opportunities ORDER BY id DESC LIMIT 1")
    # projection_fair_prob must be populated now (not NULL)
    assert row["projection_fair_prob"] is not None
    # Blended must sit between consensus (~0.50) and projection (0.60) for the 'yes'/over side
    assert row["kalshi_side"] == "yes"
    assert 0.50 < float(row["blended_fair_prob"]) <= 0.60
```

- [ ] **Step 4: Run the new test + the existing pipeline test (ensure no regression)**

```bash
uv run pytest tests/integration/test_pipeline_with_projections.py tests/integration/test_pipeline_tick.py -v
```
Expected: 3 passed (1 new + 2 from Plan 1).

- [ ] **Step 5: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/pipeline.py scanner/tests/integration/test_pipeline_with_projections.py
git commit -m "feat(pipeline): blend latest projection into EV"
```

---

## Phase 4: Additional sharp books

Each scraper mirrors the Pinnacle structure from Plan 1: a pure `parse_*` function (unit-tested against a fixture payload) plus a `Scraper` class that drives cloakbrowser. The parsers emit the same synthetic ticker (`SYN-NBA-{PLAYER}-{STAT}-{LINE}`) so the pipeline joins all books on the same market.

> **Reuse helper:** All three parsers use `_synthesize_kalshi_ticker` and `_parse_description`. To avoid duplicating them in three files, Task 9 first extracts them from `src/providers/pinnacle.py` into `src/providers/_player_props.py`, and Pinnacle imports from there.

### Task 9: Extract shared parser helpers + NoVig scraper

**Files:**
- Create: `scanner/src/providers/_player_props.py`
- Modify: `scanner/src/providers/pinnacle.py` (import helpers from new module)
- Create: `scanner/src/providers/novig.py`
- Test: `scanner/tests/unit/test_novig_parser.py`

- [ ] **Step 1: Create `src/providers/_player_props.py` with the shared helpers**

```python
"""Shared helpers for player-prop scrapers: player/stat parsing + synthetic
ticker construction. All sharp-book scrapers emit the same synthetic ticker so
the pipeline can join quotes across books."""

import re


def parse_player_stat_description(desc: str) -> tuple[str | None, str | None]:
    """'LeBron James (Total Points)' -> ('LeBron James', 'points')."""
    match = re.match(r"^(.+?)\s*\(Total\s+(\w+)\)$", desc, re.IGNORECASE)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).lower()


def synthesize_kalshi_ticker(player: str, stat: str | None, line: float) -> str:
    slug = re.sub(r"[^A-Za-z]+", "", player).upper()
    return f"SYN-NBA-{slug}-{stat.upper() if stat else 'UNK'}-{line}"
```

- [ ] **Step 2: Update `src/providers/pinnacle.py` to import the helpers**

Remove the local `_parse_description` and `_synthesize_kalshi_ticker` function definitions from `pinnacle.py`. Add this import near the top:
```python
from src.providers._player_props import (
    parse_player_stat_description as _parse_description,
    synthesize_kalshi_ticker as _synthesize_kalshi_ticker,
)
```
(Keeping the same local names means the rest of `pinnacle.py` is unchanged.)

- [ ] **Step 3: Verify Pinnacle tests still pass after the refactor**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner/scanner
uv run pytest tests/unit/test_pinnacle_parser.py -v
```
Expected: 3 passed (no behavior change).

- [ ] **Step 4: Write `tests/unit/test_novig_parser.py`**

NoVig exposes a JSON API of "markets" where each market has a `player`, `stat`, `line`, and `outcomes` array with `name` ("Over"/"Under") and decimal `price`. We parse that shape.

```python
"""Tests for the NoVig markets parser."""

from src.providers.novig import parse_novig_player_props

SAMPLE = {
    "markets": [
        {
            "player": "LeBron James",
            "stat": "points",
            "line": 24.5,
            "outcomes": [
                {"name": "Over", "price": 1.95},
                {"name": "Under", "price": 1.87},
            ],
        },
        {
            "player": "Jayson Tatum",
            "stat": "rebounds",
            "line": 8.5,
            "outcomes": [
                {"name": "Over", "price": 1.90},
                {"name": "Under", "price": 1.90},
            ],
        },
    ]
}


def test_parses_two_markets_four_quotes():
    quotes = parse_novig_player_props(SAMPLE)
    assert len(quotes) == 4
    assert all(q.book == "novig" for q in quotes)
    over = next(q for q in quotes if "LEBRONJAMES" in q.market_kalshi_ticker and q.side == "over")
    assert abs(float(over.decimal_odds) - 1.95) < 1e-9
    # implied = 1/1.95
    assert abs(float(over.implied_prob) - (1 / 1.95)) < 1e-6


def test_synthetic_ticker_matches_pinnacle_format():
    quotes = parse_novig_player_props(SAMPLE)
    tickers = {q.market_kalshi_ticker for q in quotes}
    assert "SYN-NBA-LEBRONJAMES-POINTS-24.5" in tickers


def test_empty_payload():
    assert parse_novig_player_props({}) == []
```

- [ ] **Step 5: Run, verify failure**

```bash
uv run pytest tests/unit/test_novig_parser.py -v
```

- [ ] **Step 6: Write `src/providers/novig.py`**

```python
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
                await page.goto(NOVIG_NBA_URL, timeout=30_000, wait_until="networkidle")
            except Exception as e:
                log.warning("novig_navigation_failed", error=str(e))
        finally:
            await browser.close()

        quotes: list[OddsQuote] = []
        for payload in captured:
            quotes.extend(parse_novig_player_props(payload))
        log.info("novig_fetched", quote_count=len(quotes))
        return quotes
```

- [ ] **Step 7: Run NoVig parser tests**

```bash
uv run pytest tests/unit/test_novig_parser.py -v
```
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/providers/_player_props.py scanner/src/providers/pinnacle.py scanner/src/providers/novig.py scanner/tests/unit/test_novig_parser.py
git commit -m "feat(providers): extract shared helpers + NoVig scraper"
```

---

### Task 10: BetOnline scraper

**Files:**
- Create: `scanner/src/providers/betonline.py`
- Test: `scanner/tests/unit/test_betonline_parser.py`

BetOnline returns American odds in a nested `events[].props[]` shape.

- [ ] **Step 1: Write `tests/unit/test_betonline_parser.py`**

```python
"""Tests for the BetOnline props parser."""

from src.providers.betonline import parse_betonline_player_props

SAMPLE = {
    "events": [
        {
            "props": [
                {
                    "playerName": "LeBron James",
                    "category": "points",
                    "line": 24.5,
                    "over": -110,
                    "under": -110,
                },
                {
                    "playerName": "Anthony Davis",
                    "category": "rebounds",
                    "line": 11.5,
                    "over": -120,
                    "under": 100,
                },
            ]
        }
    ]
}


def test_parses_props():
    quotes = parse_betonline_player_props(SAMPLE)
    assert len(quotes) == 4
    assert all(q.book == "betonline" for q in quotes)
    over = next(q for q in quotes if "LEBRONJAMES" in q.market_kalshi_ticker and q.side == "over")
    # -110 → decimal 1 + 100/110
    assert abs(float(over.decimal_odds) - (1 + 100 / 110)) < 1e-4


def test_synthetic_ticker_format():
    quotes = parse_betonline_player_props(SAMPLE)
    assert "SYN-NBA-LEBRONJAMES-POINTS-24.5" in {q.market_kalshi_ticker for q in quotes}


def test_empty():
    assert parse_betonline_player_props({}) == []
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/unit/test_betonline_parser.py -v
```

- [ ] **Step 3: Write `src/providers/betonline.py`**

```python
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
                await page.goto(BETONLINE_NBA_URL, timeout=30_000, wait_until="networkidle")
            except Exception as e:
                log.warning("betonline_navigation_failed", error=str(e))
        finally:
            await browser.close()

        quotes: list[OddsQuote] = []
        for payload in captured:
            quotes.extend(parse_betonline_player_props(payload))
        log.info("betonline_fetched", quote_count=len(quotes))
        return quotes
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_betonline_parser.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/providers/betonline.py scanner/tests/unit/test_betonline_parser.py
git commit -m "feat(providers): BetOnline scraper"
```

---

### Task 11: DraftKings scraper

**Files:**
- Create: `scanner/src/providers/draftkings.py`
- Test: `scanner/tests/unit/test_draftkings_parser.py`

DraftKings uses a `selections[]` shape: each selection has `label` ("Over"/"Under"), `participant` (player), `points` (line), and American `oddsAmerican`. We group by (participant, points).

- [ ] **Step 1: Write `tests/unit/test_draftkings_parser.py`**

```python
"""Tests for the DraftKings selections parser."""

from src.providers.draftkings import parse_draftkings_player_props

SAMPLE = {
    "selections": [
        {"participant": "LeBron James", "marketStat": "points", "label": "Over",
         "points": 24.5, "oddsAmerican": "-115"},
        {"participant": "LeBron James", "marketStat": "points", "label": "Under",
         "points": 24.5, "oddsAmerican": "-105"},
        {"participant": "Luka Doncic", "marketStat": "assists", "label": "Over",
         "points": 8.5, "oddsAmerican": "+100"},
        {"participant": "Luka Doncic", "marketStat": "assists", "label": "Under",
         "points": 8.5, "oddsAmerican": "-120"},
    ]
}


def test_parses_grouped_selections():
    quotes = parse_draftkings_player_props(SAMPLE)
    assert len(quotes) == 4
    assert all(q.book == "draftkings" for q in quotes)
    over = next(q for q in quotes if "LEBRONJAMES" in q.market_kalshi_ticker and q.side == "over")
    assert abs(float(over.decimal_odds) - (1 + 100 / 115)) < 1e-4


def test_plus_odds_parse():
    quotes = parse_draftkings_player_props(SAMPLE)
    luka_over = next(q for q in quotes if "LUKADONCIC" in q.market_kalshi_ticker and q.side == "over")
    assert abs(float(luka_over.decimal_odds) - 2.0) < 1e-9  # +100


def test_empty():
    assert parse_draftkings_player_props({}) == []
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/unit/test_draftkings_parser.py -v
```

- [ ] **Step 3: Write `src/providers/draftkings.py`**

```python
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
                await page.goto(DK_NBA_URL, timeout=30_000, wait_until="networkidle")
            except Exception as e:
                log.warning("draftkings_navigation_failed", error=str(e))
        finally:
            await browser.close()

        quotes: list[OddsQuote] = []
        for payload in captured:
            quotes.extend(parse_draftkings_player_props(payload))
        log.info("draftkings_fetched", quote_count=len(quotes))
        return quotes
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_draftkings_parser.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/providers/draftkings.py scanner/tests/unit/test_draftkings_parser.py
git commit -m "feat(providers): DraftKings scraper"
```

---

### Task 12: Register new providers in the scheduler

**Files:**
- Modify: `scanner/src/scheduler.py`

- [ ] **Step 1: Add imports + register the new scrapers**

In `src/scheduler.py`, find:
```python
from src.providers.pinnacle import PinnacleScraper
```
Add below it:
```python
from src.providers.betonline import BetOnlineScraper
from src.providers.draftkings import DraftKingsScraper
from src.providers.novig import NoVigScraper
```

Then find:
```python
    sharp: list[OddsProvider] = [PinnacleScraper()]
```
Replace with:
```python
    sharp: list[OddsProvider] = [
        PinnacleScraper(),
        NoVigScraper(),
        BetOnlineScraper(),
        DraftKingsScraper(),
    ]
```

- [ ] **Step 2: Verify imports**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner/scanner
uv run python -c "from src.scheduler import main_loop; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/scheduler.py
git commit -m "feat(scanner): register NoVig/BetOnline/DraftKings scrapers"
```

---

## Phase 5: Brier calibration loop

The loop closes the feedback cycle: actual game results settle markets into `market_outcomes`, then per-book Brier scores are computed from how well each book's pre-game devigged probability predicted reality. Until ≥100 settled markets exist per book, the pipeline keeps using `COLD_START_WEIGHTS`.

### Task 13: Outcomes repository + reconciliation job

**Files:**
- Create: `scanner/src/repositories/outcomes.py`
- Create: `scanner/src/calibration/__init__.py` (empty)
- Create: `scanner/src/calibration/reconcile.py`
- Test: `scanner/tests/integration/test_outcomes_repo.py`

- [ ] **Step 1: Write `src/repositories/outcomes.py`**

```python
"""Repository for market_outcomes + the snapshot lookups Brier scoring needs."""

from dataclasses import dataclass

import asyncpg

from src.math.devig import devig


@dataclass(frozen=True, slots=True)
class SettledMarket:
    market_id: int
    outcome: str  # 'over' | 'under'


async def upsert_market_outcome(
    pool: asyncpg.Pool, *, market_id: int, outcome: str, actual_value: float | None
) -> None:
    await pool.execute(
        """
        INSERT INTO market_outcomes (market_id, outcome, actual_value)
        VALUES ($1, $2, $3)
        ON CONFLICT (market_id) DO UPDATE SET
            outcome = EXCLUDED.outcome, actual_value = EXCLUDED.actual_value,
            settled_at = now()
        """,
        market_id, outcome, actual_value,
    )


async def settled_over_under_since(pool: asyncpg.Pool, days: int) -> list[SettledMarket]:
    """Markets settled in the last `days` whose outcome is over/under (excludes push/void)."""
    rows = await pool.fetch(
        """
        SELECT market_id, outcome FROM market_outcomes
        WHERE outcome IN ('over', 'under')
          AND settled_at >= now() - ($1::text || ' days')::interval
        """,
        str(days),
    )
    return [SettledMarket(market_id=r["market_id"], outcome=r["outcome"]) for r in rows]


async def book_fair_prob_over(
    pool: asyncpg.Pool, market_id: int, book: str
) -> float | None:
    """Devig a book's latest over/under snapshot pair for a market. None if the
    book didn't quote both sides."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (side) side, implied_prob
        FROM odds_snapshots
        WHERE market_id = $1 AND book = $2 AND side IN ('over', 'under')
        ORDER BY side, fetched_at DESC
        """,
        market_id, book,
    )
    by_side = {r["side"]: float(r["implied_prob"]) for r in rows}
    if "over" not in by_side or "under" not in by_side:
        return None
    fair_over, _ = devig(by_side["over"], by_side["under"])
    return fair_over


async def markets_needing_settlement(pool: asyncpg.Pool) -> list[dict]:
    """Player-prop markets whose game has started but have no outcome yet."""
    rows = await pool.fetch(
        """
        SELECT m.id, m.player_name, m.stat_type, m.line, m.game_starts_at
        FROM markets m
        LEFT JOIN market_outcomes o ON o.market_id = m.id
        WHERE o.market_id IS NULL
          AND m.market_type = 'player_prop'
          AND m.game_starts_at < now()
        """
    )
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Write `src/calibration/reconcile.py`**

```python
"""Reconcile finished games into market_outcomes.

For each player-prop market whose game has started and isn't settled, look up the
player's game log on that game's date and compare the actual stat to the line.

Matching is by player_id + game_date (the date portion of game_starts_at). This
is a baseline heuristic; Plan 3 can tighten it with explicit game_id mapping.
"""

import asyncio

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.engine import StatSample, _extract
from src.repositories.game_logs import player_id_by_name, recent_logs_for_player
from src.repositories.outcomes import markets_needing_settlement, upsert_market_outcome


async def reconcile_outcomes(pool) -> int:
    pending = await markets_needing_settlement(pool)
    settled = 0
    for m in pending:
        player_name = m["player_name"]
        stat = m["stat_type"]
        line = float(m["line"]) if m["line"] is not None else None
        if not player_name or not stat or line is None:
            continue

        player_id = await player_id_by_name(pool, player_name)
        if player_id is None:
            continue

        game_date = m["game_starts_at"].date()
        logs = await recent_logs_for_player(pool, player_id, limit=40)
        match = next((l for l in logs if l.game_date == game_date), None)
        if match is None:
            continue  # game log not ingested yet — try again next run

        sample = StatSample(
            points=match.points or 0, rebounds=match.rebounds or 0,
            assists=match.assists or 0, threes=match.threes or 0,
            blocks=match.blocks or 0, steals=match.steals or 0,
        )
        try:
            actual = _extract(sample, stat)
        except ValueError:
            continue

        outcome = "over" if actual > line else "under"
        await upsert_market_outcome(
            pool, market_id=m["id"], outcome=outcome, actual_value=float(actual)
        )
        settled += 1

    log.info("reconcile_complete", settled=settled, pending=len(pending))
    return settled


async def main() -> None:
    configure_logging(level=settings.log_level)
    try:
        pool = await get_pool()
        await reconcile_outcomes(pool)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
```

Note: this imports `_extract` from the projection engine. Since it's used across modules now, in Step 2 also remove the leading underscore — rename `_extract` to `extract_stat` in `src/projections/engine.py` and update its internal caller + this import. (A name shared across modules shouldn't be private.)

- [ ] **Step 3: Rename `_extract` → `extract_stat` in `src/projections/engine.py`**

In `src/projections/engine.py`, rename the function `_extract` to `extract_stat` and update the call inside `project` (`values = [extract_stat(s, stat) for s in samples]`). Update the import in `reconcile.py` to `from src.projections.engine import StatSample, extract_stat` and the call to `extract_stat(sample, stat)`.

- [ ] **Step 4: Write `tests/integration/test_outcomes_repo.py`**

```python
"""Integration tests for outcomes repo + reconciliation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.calibration.reconcile import reconcile_outcomes
from src.repositories.game_logs import upsert_game_logs
from src.repositories.markets import upsert_market
from src.repositories.outcomes import (
    book_fair_prob_over,
    settled_over_under_since,
    upsert_market_outcome,
)
from src.repositories.snapshots import OddsSnapshot, bulk_insert_snapshots

pytestmark = pytest.mark.integration


async def test_upsert_and_query_settled(pool):
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-T-1", market_type="player_prop",
        game_id="LAL-BOS", game_starts_at=datetime(2025, 11, 20, tzinfo=timezone.utc),
    )
    await upsert_market_outcome(pool, market_id=m.id, outcome="over", actual_value=27.0)
    settled = await settled_over_under_since(pool, days=60)
    assert len(settled) == 1
    assert settled[0].outcome == "over"


async def test_book_fair_prob_over_devigs_snapshots(pool):
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-T-2", market_type="player_prop",
        game_id="LAL-BOS", game_starts_at=datetime(2025, 11, 20, tzinfo=timezone.utc),
    )
    await bulk_insert_snapshots(pool, [
        OddsSnapshot(m.id, "pinnacle", "over", Decimal("1.91"), Decimal("0.524")),
        OddsSnapshot(m.id, "pinnacle", "under", Decimal("1.91"), Decimal("0.524")),
    ])
    p = await book_fair_prob_over(pool, m.id, "pinnacle")
    assert abs(p - 0.5) < 1e-6


async def test_reconcile_settles_from_game_log(pool):
    game_dt = datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc)
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-LBJ-POINTS-24.5",
        market_type="player_prop", player_name="LeBron James", stat_type="points",
        line=24.5, game_id="LAL-BOS", game_starts_at=game_dt,
    )
    await upsert_game_logs(pool, [{
        "player_id": 2544, "player_name": "LeBron James", "team_abbr": "LAL",
        "game_id": "0022500099", "game_date": "2025-11-20", "matchup": "LAL @ BOS",
        "minutes": 35.0, "points": 30, "rebounds": 8, "assists": 9,
        "threes": 2, "blocks": 1, "steals": 1,
    }])
    # game_starts_at is in the past relative to the test only if we backdate it;
    # markets_needing_settlement filters game_starts_at < now(). Backdate it:
    await pool.execute(
        "UPDATE markets SET game_starts_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(hours=4), m.id,
    )
    # game_date on the log must match the (now backdated) market date:
    await pool.execute(
        "UPDATE player_game_logs SET game_date = $1 WHERE player_id = 2544",
        (datetime.now(timezone.utc) - timedelta(hours=4)).date(),
    )

    settled = await reconcile_outcomes(pool)
    assert settled == 1
    row = await pool.fetchrow("SELECT outcome, actual_value FROM market_outcomes WHERE market_id = $1", m.id)
    assert row["outcome"] == "over"   # 30 > 24.5
    assert float(row["actual_value"]) == 30.0
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/integration/test_outcomes_repo.py tests/unit/test_projection_engine.py -v
```
Expected: 3 integration + 8 unit = 11 passed (the projection tests confirm the `extract_stat` rename didn't break anything).

- [ ] **Step 6: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/repositories/outcomes.py scanner/src/calibration/__init__.py scanner/src/calibration/reconcile.py scanner/src/projections/engine.py scanner/tests/integration/test_outcomes_repo.py
git commit -m "feat(calibration): market outcome reconciliation"
```

---

### Task 14: Brier weight computation

**Files:**
- Create: `scanner/src/calibration/brier.py`
- Test: `scanner/tests/integration/test_brier.py`

- [ ] **Step 1: Write `src/calibration/brier.py`**

```python
"""Rolling per-book Brier weights.

Brier score for a book = mean over settled over/under markets of
(book_fair_prob_over - actual)^2, where actual = 1.0 if the market went over
else 0.0. Lower Brier = better calibrated. Weight = 1 / brier.

Returns {} when no book has >= MIN_SETTLED settled markets — the pipeline then
falls back to COLD_START_WEIGHTS.
"""

import asyncpg

from src.logger import log
from src.repositories.outcomes import book_fair_prob_over, settled_over_under_since

SHARP_BOOKS = ["pinnacle", "novig", "betonline", "draftkings"]
MIN_SETTLED = 100
LOOKBACK_DAYS = 60


async def compute_brier_weights(
    pool: asyncpg.Pool, *, lookback_days: int = LOOKBACK_DAYS, min_settled: int = MIN_SETTLED
) -> dict[str, float]:
    settled = await settled_over_under_since(pool, days=lookback_days)
    if not settled:
        return {}

    sum_sq: dict[str, float] = {b: 0.0 for b in SHARP_BOOKS}
    counts: dict[str, int] = {b: 0 for b in SHARP_BOOKS}

    for market in settled:
        actual = 1.0 if market.outcome == "over" else 0.0
        for book in SHARP_BOOKS:
            prob = await book_fair_prob_over(pool, market.market_id, book)
            if prob is None:
                continue
            sum_sq[book] += (prob - actual) ** 2
            counts[book] += 1

    weights: dict[str, float] = {}
    for book in SHARP_BOOKS:
        if counts[book] < min_settled:
            continue
        brier = sum_sq[book] / counts[book]
        if brier <= 0:
            brier = 1e-6
        weights[book] = 1.0 / brier

    log.info("brier_weights_computed", weights=weights, counts=counts)
    return weights
```

- [ ] **Step 2: Write `tests/integration/test_brier.py`**

```python
"""Integration test for Brier weight computation."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.calibration.brier import compute_brier_weights
from src.repositories.markets import upsert_market
from src.repositories.outcomes import upsert_market_outcome
from src.repositories.snapshots import OddsSnapshot, bulk_insert_snapshots

pytestmark = pytest.mark.integration


async def test_insufficient_data_returns_empty(pool):
    # Only a handful of settled markets → below MIN_SETTLED → {}
    weights = await compute_brier_weights(pool, lookback_days=60, min_settled=100)
    assert weights == {}


async def test_better_book_gets_higher_weight(pool):
    # Build 20 settled markets. Pinnacle predicts perfectly; DraftKings predicts
    # the opposite. With min_settled lowered to 10, Pinnacle weight >> DraftKings.
    for i in range(20):
        went_over = i % 2 == 0
        m = await upsert_market(
            pool, sport="NBA", kalshi_ticker=f"SYN-T-{i}", market_type="player_prop",
            game_id="LAL-BOS", game_starts_at=datetime(2025, 11, 20, tzinfo=timezone.utc),
        )
        # Pinnacle: confident & correct (0.99 over when it went over, else 0.01)
        p_over = 0.99 if went_over else 0.01
        # DraftKings: confident & WRONG
        d_over = 0.01 if went_over else 0.99
        await bulk_insert_snapshots(pool, [
            OddsSnapshot(m.id, "pinnacle", "over", Decimal("1.0"), Decimal(str(p_over))),
            OddsSnapshot(m.id, "pinnacle", "under", Decimal("1.0"), Decimal(str(1 - p_over))),
            OddsSnapshot(m.id, "draftkings", "over", Decimal("1.0"), Decimal(str(d_over))),
            OddsSnapshot(m.id, "draftkings", "under", Decimal("1.0"), Decimal(str(1 - d_over))),
        ])
        await upsert_market_outcome(
            pool, market_id=m.id, outcome="over" if went_over else "under", actual_value=1.0
        )

    weights = await compute_brier_weights(pool, lookback_days=60, min_settled=10)
    assert "pinnacle" in weights
    assert "draftkings" in weights
    assert weights["pinnacle"] > weights["draftkings"] * 100  # vastly better
```

Note: the devig of (0.99, 0.01) yields exactly 0.99, so Pinnacle's fair_prob_over equals its confident prediction — the test math holds.

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/integration/test_brier.py -v
```
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/calibration/brier.py scanner/tests/integration/test_brier.py
git commit -m "feat(calibration): rolling Brier weight computation"
```

---

### Task 15: Wire Brier weights into the pipeline (cold-start fallback)

**Files:**
- Modify: `scanner/src/pipeline.py`
- Modify: `scanner/src/scheduler.py`
- Test: `scanner/tests/integration/test_pipeline_with_projections.py` (extend)

- [ ] **Step 1: Thread `consensus_weights` through the pipeline**

In `src/pipeline.py`, change `run_scan_tick`'s signature to accept weights:
```python
async def run_scan_tick(
    *,
    pool,
    sharp_providers: list[OddsProvider],
    kalshi: KalshiAdapter,
    days_since_launch: int = 0,
    consensus_weights: dict[str, float] | None = None,
) -> int:
```

At the top of the function body (after `tick_id` is set), add:
```python
    weights = consensus_weights or COLD_START_WEIGHTS
```

Change the `_compute_market_ev` call to pass weights:
```python
        ev_result = _compute_market_ev(quotes, proj_weight, projection_prob, weights)
```

In `_compute_market_ev`, add the `weights` parameter and use it:
```python
def _compute_market_ev(
    quotes: list[OddsQuote],
    projection_weight: float,
    projection_prob_over: float | None,
    weights: dict[str, float],
) -> tuple[float, str, Decimal, float, float, float | None, int] | None:
```
And change the consensus call inside from `weights=COLD_START_WEIGHTS` to `weights=weights`.

Important: `brier_weighted_consensus` raises if a book in `fair_over_per_book` is missing from `weights`. Computed Brier weights only include books with ≥100 settled markets, so a freshly-added book could be missing. Guard it — before the consensus call, filter to books present in `weights`, falling back to cold-start for any missing book:
```python
    safe_weights = dict(weights)
    for book in fair_over_per_book:
        if book not in safe_weights:
            safe_weights[book] = COLD_START_WEIGHTS.get(book, 0.5)
    consensus_over = brier_weighted_consensus(
        fair_probs=fair_over_per_book,
        weights=safe_weights,
    )
```

- [ ] **Step 2: Compute weights at scheduler startup**

In `src/scheduler.py`, add import:
```python
from src.calibration.brier import compute_brier_weights
from src.math.consensus import COLD_START_WEIGHTS
```

In `main_loop`, after `pool = await get_pool()`, compute weights once:
```python
    brier_weights = await compute_brier_weights(pool)
    consensus_weights = brier_weights or COLD_START_WEIGHTS
    log.info("consensus_weights_selected",
             source="brier" if brier_weights else "cold_start",
             weights=consensus_weights)
```

Pass them into the tick call:
```python
            await run_scan_tick(
                pool=pool, sharp_providers=sharp, kalshi=kalshi,
                days_since_launch=_days_since_launch(),
                consensus_weights=consensus_weights,
            )
```

- [ ] **Step 3: Extend the projections pipeline test to cover custom weights**

Append to `tests/integration/test_pipeline_with_projections.py`:
```python
async def test_tick_accepts_custom_consensus_weights(pool):
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-WTS-POINTS-20.5",
        market_type="player_prop", player_name="Test Guy", stat_type="points",
        line=20.5, game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )
    sharp = FakeProvider("pinnacle", [
        OddsQuote("SYN-NBA-WTS-POINTS-20.5", "pinnacle", "over", Decimal("1.90"), Decimal("0.526")),
        OddsQuote("SYN-NBA-WTS-POINTS-20.5", "pinnacle", "under", Decimal("1.90"), Decimal("0.526")),
    ])
    sharp2 = FakeProvider("novig", [
        OddsQuote("SYN-NBA-WTS-POINTS-20.5", "novig", "over", Decimal("1.90"), Decimal("0.526")),
        OddsQuote("SYN-NBA-WTS-POINTS-20.5", "novig", "under", Decimal("1.90"), Decimal("0.526")),
    ])
    adapter = KalshiAdapter(client=AsyncMock())
    adapter.fetch_odds = AsyncMock(return_value=[
        OddsQuote("SYN-NBA-WTS-POINTS-20.5", "kalshi", "yes", Decimal(100)/Decimal(44), Decimal("0.44")),
        OddsQuote("SYN-NBA-WTS-POINTS-20.5", "kalshi", "no", Decimal(100)/Decimal(56), Decimal("0.56")),
    ])
    # Custom weights that only mention pinnacle — novig must get a cold-start fallback,
    # NOT raise a KeyError.
    n = await run_scan_tick(
        pool=pool, sharp_providers=[sharp, sharp2], kalshi=adapter,
        days_since_launch=0, consensus_weights={"pinnacle": 5.0},
    )
    assert n >= 1
```

- [ ] **Step 4: Run the pipeline tests**

```bash
uv run pytest tests/integration/test_pipeline_with_projections.py tests/integration/test_pipeline_tick.py -v
```
Expected: 4 passed (2 projection tests + 2 Plan 1 tests, all green).

- [ ] **Step 5: Verify scheduler still imports**

```bash
uv run python -c "from src.scheduler import main_loop; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add scanner/src/pipeline.py scanner/src/scheduler.py scanner/tests/integration/test_pipeline_with_projections.py
git commit -m "feat(pipeline): use Brier weights with cold-start fallback"
```

---

## Phase 6: Verification + wrap-up

### Task 16: Full suite + live nba_api smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner/scanner
uv run pytest tests/unit/ tests/integration/ -v
```
Expected: All pass. Plan 1 had 62; Plan 2 adds ~30 (projection engine 8, nba client 2, game logs 5, projections repo 3, projection job 2, novig 3, betonline 3, draftkings 3, outcomes 3, brier 2, pipeline-with-projections 2). Target ~92 passing.

- [ ] **Step 2: Live nba_api smoke (real network)**

```bash
uv run python -m src.nba_stats.ingest
```
Expected: logs `nba_ingest_complete` with non-zero `logs` and `teams` counts (during NBA season). Then verify:
```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
docker compose exec postgres psql -U kalshi -d kalshi_ev -c "SELECT COUNT(*) FROM player_game_logs;"
docker compose exec postgres psql -U kalshi -d kalshi_ev -c "SELECT COUNT(*) FROM team_defense_ratings;"
```
Expected: both > 0.

If `LeagueDashTeamStats` raised a `KeyError` on a column, fix the column name in `src/nba_stats/client.py` to match the live dataframe (use `print(df.columns.tolist())` to inspect), then re-run. Commit any such fix as `fix(nba_stats): correct live column name`.

- [ ] **Step 3: Run the projection job against the freshly ingested data**

```bash
cd scanner
uv run python -m src.projections.job
```
Expected: logs `projection_job_complete`. (`written` may be 0 if no active markets exist yet — that's fine; this just proves the job runs end-to-end without error.)

- [ ] **Step 4: No commit unless a live-shape fix was needed**

---

### Task 17: Plan 2 wrap-up

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the status section of `README.md`**

Replace the `**Status:**` line near the top with:
```markdown
**Status:** Plan 2 complete. Adds the projection engine (nba_api → per-player distributions), NoVig/BetOnline/DraftKings scrapers, and the Brier calibration loop. Projections now blend into EV; consensus weights auto-calibrate once enough markets settle. Live verification (real scraping + Kalshi) still pending user infra (IPRoyal funding + Kalshi keys).
```

And under "Plan 1 limitations (addressed in subsequent plans)", remove the Plan 2 bullet (now done) leaving just the Plan 3 bullet.

- [ ] **Step 2: Commit + tag**

```bash
cd /Users/luke/Documents/DEV/kalshi-ev-scanner
git add README.md
git commit -m "docs: Plan 2 complete — update README"
git tag -a plan-2-projections -m "Plan 2: projections + additional books + Brier calibration"
```

---

## Plan 2 — Self-review

**Spec coverage (design spec Sections 6-8):**
- ✓ Projection engine baseline (Section 7) — Tasks 5-7. News adjustments explicitly deferred to Plan 3.
- ✓ `projections` table populated + read by pipeline (Section 6/7) — Tasks 6, 8.
- ✓ Additional sharp books NoVig/BetOnline/DraftKings (Section 5/7) — Tasks 9-12.
- ✓ `market_outcomes` reconciliation (Section 6) — Task 13.
- ✓ Brier weight rolling computation + cold-start fallback (Section 7) — Tasks 14-15.
- ✓ `player_game_logs` / `team_defense_ratings` caches (Section 20 open Q #6) — Task 1.
- ✗ News ingestion (Section 8) — explicitly deferred to Plan 3.
- ✗ Performance/proof pages, deployment, alerts — Plan 3.

**Placeholder scan:** No TBD/TODO. Scraper JSON shapes (NoVig/BetOnline/DraftKings) and the `LeagueDashTeamStats` opponent-points column are explicitly flagged as live-verify points (Tasks 9-11, 16) with concrete fix instructions — consistent with how Plan 1 handled Pinnacle.

**Type consistency:**
- `StatSample` fields (points/rebounds/assists/threes/blocks/steals) consistent across engine (Task 5), job (Task 7), reconcile (Task 13).
- `project(...)` keyword signature matches between definition (Task 5) and caller (Task 7).
- `extract_stat` rename (Task 13) updates both the engine caller and reconcile import.
- `_compute_market_ev` return tuple grows from 6-tuple (Plan 1) to 7-tuple (Task 8); the caller unpack in Task 8 matches the new arity, and Task 15 adds the `weights` param consistently in both signature and call site.
- `compute_brier_weights` returns `dict[str,float]`; scheduler (Task 15) and pipeline `consensus_weights` param (Task 15) agree.

---

## Execution handoff

Plan 2 is ready (17 tasks). Two execution options:

**1. Subagent-driven (recommended)** — fresh subagent per task, two-stage review.

**2. Inline execution** — sequential with checkpoints.

Which approach?
