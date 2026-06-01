# Plan 1 — Foundation + Math + Kalshi + Pinnacle + Minimal Dashboard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local-running end-to-end MVP: scrape Pinnacle + read Kalshi every 30s, devig + compute EV, write opportunities to Postgres, display them in a Next.js dashboard. Proves the math works on real data before we add projections, more books, news, or deployment.

**Architecture:** Python scanner service (asyncio, 30s tick) writes to Postgres. Next.js dashboard reads via Drizzle. CloakBrowser routes Pinnacle requests through IPRoyal residential proxies. Kalshi client lifted from `ryanfrigo/kalshi-ai-trading-bot`. All math TDD'd as pure functions.

**Tech Stack:**
- Python 3.12, uv (package mgmt), pytest, hypothesis, ruff, structlog, asyncpg, alembic, pydantic, scipy, numpy, httpx
- TypeScript 5, Next.js 15 (App Router), React 19, Tailwind 4, shadcn/ui, Drizzle ORM, TanStack Query 5, pnpm
- Postgres 16 (local: Docker Compose)
- CloakBrowser, IPRoyal residential proxies
- Conventional Commits

**Scope NOT in this plan (explicit YAGNI for Plan 1):**
- NBA stats / projections (`projections` table written but always empty in Plan 1 — pipeline falls back to consensus-only)
- Additional sharp books (NoVig, BetOnline, DraftKings deferred to Plan 2)
- News ingestion (`news_events` table written but unused in Plan 1)
- Vercel / Railway deployment (local only)
- Performance / bets / proof pages (just `/`, `/opportunity/[id]`, `/health` for Plan 1)
- Discord alerts (Plan 3)
- Brier weight calculation (uses `COLD_START_WEIGHTS` hardcoded — Plan 2 adds nightly recompute)

---

## File Structure

```
kalshi-ev-scanner/
├── README.md                                    # quick-start
├── docker-compose.yml                           # local Postgres
├── .gitignore                                   # Python + Next + envs
├── .env.example
│
├── scanner/                                     # Python service
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── ruff.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 001_initial_schema.py
│   ├── src/
│   │   ├── __init__.py
│   │   ├── config.py                            # env + constants
│   │   ├── db.py                                # asyncpg pool
│   │   ├── logger.py                            # structlog setup
│   │   ├── math/
│   │   │   ├── __init__.py
│   │   │   ├── devig.py
│   │   │   ├── consensus.py
│   │   │   ├── distributions.py
│   │   │   ├── ev.py
│   │   │   ├── kelly.py
│   │   │   ├── projection_weight.py
│   │   │   └── blend.py
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                          # OddsQuote, OddsProvider ABC
│   │   │   └── pinnacle.py
│   │   ├── kalshi/
│   │   │   ├── __init__.py
│   │   │   ├── client.py                        # LIFTED from ryanfrigo
│   │   │   ├── ws.py                            # LIFTED from ryanfrigo
│   │   │   └── adapter.py
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── markets.py
│   │   │   ├── snapshots.py
│   │   │   ├── opportunities.py
│   │   │   ├── bankroll.py
│   │   │   └── telemetry.py
│   │   ├── pipeline.py                          # one tick
│   │   └── scheduler.py                         # 30s loop
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       │   ├── test_devig.py
│       │   ├── test_consensus.py
│       │   ├── test_distributions.py
│       │   ├── test_ev.py
│       │   ├── test_kelly.py
│       │   ├── test_projection_weight.py
│       │   ├── test_blend.py
│       │   └── test_math_properties.py
│       ├── integration/
│       │   ├── conftest.py
│       │   ├── test_repositories.py
│       │   └── test_pipeline_tick.py
│       └── e2e/
│           ├── test_pinnacle_smoke.py
│           └── test_kalshi_sandbox.py
│
├── dashboard/                                   # Next.js
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── postcss.config.mjs
│   ├── next.config.mjs
│   ├── drizzle.config.ts
│   ├── components.json
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── globals.css
│   │   │   ├── page.tsx
│   │   │   ├── opportunity/[id]/page.tsx
│   │   │   ├── health/page.tsx
│   │   │   └── api/
│   │   │       ├── opportunities/route.ts
│   │   │       ├── opportunity/[id]/route.ts
│   │   │       └── health/route.ts
│   │   ├── components/
│   │   │   ├── ui/                              # shadcn primitives
│   │   │   ├── OpportunityTable.tsx
│   │   │   ├── OpportunityRow.tsx
│   │   │   ├── EvBadge.tsx
│   │   │   └── HealthCard.tsx
│   │   ├── lib/
│   │   │   ├── db.ts
│   │   │   ├── schema.ts
│   │   │   ├── queries.ts
│   │   │   └── format.ts
│   │   └── types/
│   │       └── opportunity.ts
│   └── tests/
│       └── (Playwright deferred to Plan 3)
│
└── docs/
    └── superpowers/
        ├── specs/
        │   └── 2026-05-29-kalshi-ev-scanner-design.md
        └── plans/
            └── 2026-05-29-plan-1-foundation-mvp.md
```

---

## Phase 0: Project Scaffolding

### Task 1: Create root scaffolding files

**Files:**
- Create: `kalshi-ev-scanner/.gitignore`
- Create: `kalshi-ev-scanner/README.md`
- Create: `kalshi-ev-scanner/.env.example`
- Create: `kalshi-ev-scanner/docker-compose.yml`

- [ ] **Step 1: Write `.gitignore`**

Contents:
```gitignore
# Python
__pycache__/
*.py[cod]
*.so
.venv/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/

# Node
node_modules/
.next/
out/
dist/

# Env
.env
.env.local
.env.*.local

# IDE
.vscode/
.idea/
.DS_Store

# Logs
*.log

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 2: Write `README.md`**

Contents:
```markdown
# Kalshi EV Scanner

Personal +EV (positive expected value) sports betting scanner targeting Kalshi prediction markets.

See `docs/superpowers/specs/2026-05-29-kalshi-ev-scanner-design.md` for the full design.

## Local development

```bash
# 1. Start Postgres
docker compose up -d

# 2. Copy env and edit
cp .env.example .env

# 3. Scanner setup
cd scanner
uv sync
uv run alembic upgrade head
uv run python -m src.scheduler

# 4. Dashboard setup (separate terminal)
cd dashboard
pnpm install
pnpm dev
# open http://localhost:3000
```
```

- [ ] **Step 3: Write `.env.example`**

Contents:
```bash
# Postgres
DATABASE_URL=postgresql://kalshi:kalshi@localhost:5432/kalshi_ev

# Kalshi
KALSHI_API_BASE=https://demo-api.kalshi.co/trade-api/v2
KALSHI_KEY_ID=
KALSHI_PRIVATE_KEY=

# IPRoyal residential proxy
IPROYAL_PROXY_URL=http://USERNAME:PASSWORD@geo.iproyal.com:12321

# Scanner settings
INITIAL_BANKROLL_CENTS=80000
SCAN_INTERVAL_SECONDS=30
LOG_LEVEL=INFO
```

- [ ] **Step 4: Write `docker-compose.yml`**

Contents:
```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: kalshi
      POSTGRES_PASSWORD: kalshi
      POSTGRES_DB: kalshi_ev
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U kalshi"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

- [ ] **Step 5: Commit**

```bash
cd kalshi-ev-scanner
git add .gitignore README.md .env.example docker-compose.yml
git commit -m "chore: initial root scaffolding"
```

---

### Task 2: Initialize Python scanner project

**Files:**
- Create: `kalshi-ev-scanner/scanner/pyproject.toml`
- Create: `kalshi-ev-scanner/scanner/ruff.toml`
- Create: `kalshi-ev-scanner/scanner/src/__init__.py`
- Create: `kalshi-ev-scanner/scanner/tests/__init__.py`
- Create: `kalshi-ev-scanner/scanner/tests/unit/__init__.py`

- [ ] **Step 1: Initialize uv project**

Run:
```bash
cd kalshi-ev-scanner/scanner
uv init --name scanner --python 3.12 --no-readme
```

- [ ] **Step 2: Replace generated `pyproject.toml` with full version**

Contents:
```toml
[project]
name = "scanner"
version = "0.1.0"
description = "Kalshi EV scanner — Python service"
requires-python = ">=3.12"
dependencies = [
    "asyncpg>=0.30.0",
    "alembic>=1.13.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "scipy>=1.14.0",
    "numpy>=2.1.0",
    "httpx>=0.27.0",
    "cryptography>=43.0.0",
    "websockets>=13.1",
    "playwright>=1.48.0",
    "tenacity>=9.0.0",
    "sqlalchemy>=2.0.36",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "hypothesis>=6.115.0",
    "ruff>=0.7.0",
    "pytest-cov>=5.0.0",
    "respx>=0.21.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = "test_*.py"
markers = [
    "integration: requires Postgres",
    "e2e: requires network",
]

[tool.coverage.run]
source = ["src/math", "src/providers", "src/kalshi"]
omit = ["*/tests/*"]
```

- [ ] **Step 3: Write `ruff.toml`**

Contents:
```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "W", "I", "B", "UP", "ASYNC"]
ignore = ["E501"]  # line length enforced by formatter

[format]
quote-style = "double"
```

- [ ] **Step 4: Create empty `__init__.py` files**

Run:
```bash
mkdir -p src tests/unit tests/integration tests/e2e
touch src/__init__.py tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/e2e/__init__.py
```

- [ ] **Step 5: Install dependencies**

Run:
```bash
uv sync
```

Expected: `Resolved N packages` then `Installed N packages`. No errors.

- [ ] **Step 6: Verify Python imports work**

Run:
```bash
uv run python -c "import asyncpg, scipy, numpy, structlog; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
cd ..
git add scanner/
git commit -m "feat(scanner): initialize Python project with uv"
```

---

### Task 3: Postgres + Alembic setup

**Files:**
- Create: `kalshi-ev-scanner/scanner/alembic.ini`
- Create: `kalshi-ev-scanner/scanner/alembic/env.py`
- Create: `kalshi-ev-scanner/scanner/alembic/script.py.mako`
- Create: `kalshi-ev-scanner/scanner/src/config.py`

- [ ] **Step 1: Start Postgres**

Run:
```bash
cd kalshi-ev-scanner
docker compose up -d
docker compose ps
```

Expected: postgres container running, healthy.

- [ ] **Step 2: Write `src/config.py`**

Contents:
```python
"""Application configuration sourced from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global settings. Reads from .env, env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://kalshi:kalshi@localhost:5432/kalshi_ev"

    kalshi_api_base: str = "https://demo-api.kalshi.co/trade-api/v2"
    kalshi_key_id: str = ""
    kalshi_private_key: str = ""

    iproyal_proxy_url: str = ""

    initial_bankroll_cents: int = 80_000
    scan_interval_seconds: int = 30
    log_level: str = "INFO"

    # Math constants (Section 7 of spec)
    min_ev_threshold: float = 0.01
    suspicious_ev_threshold: float = 0.15
    min_sharp_books: int = 2
    min_kalshi_depth_cents: int = 5000
    kelly_fraction: float = 0.25
    kelly_cap_pct: float = 0.05
    projection_weight_start: float = 0.20
    projection_weight_end: float = 0.40


settings = Settings()
```

- [ ] **Step 3: Initialize Alembic**

Run:
```bash
cd scanner
uv run alembic init alembic
```

Expected: `alembic.ini` and `alembic/` directory created.

- [ ] **Step 4: Replace `alembic.ini` `sqlalchemy.url`**

Edit `alembic.ini`, replace the existing `sqlalchemy.url` line with:
```ini
sqlalchemy.url = postgresql+psycopg2://kalshi:kalshi@localhost:5432/kalshi_ev
```

(We use psycopg2-style DSN for Alembic migrations; the runtime uses asyncpg separately.)

- [ ] **Step 5: Verify Alembic connects**

Run:
```bash
uv run alembic current
```

Expected: Empty output (no migration applied yet), no errors.

- [ ] **Step 6: Add psycopg2-binary to alembic deps**

Run:
```bash
uv add --group dev psycopg2-binary
```

- [ ] **Step 7: Re-verify**

Run:
```bash
uv run alembic current
```

Expected: prints database URL banner with no error.

- [ ] **Step 8: Commit**

```bash
cd ..
git add scanner/alembic.ini scanner/alembic/ scanner/src/config.py scanner/pyproject.toml scanner/uv.lock
git commit -m "feat(scanner): postgres + alembic setup"
```

---

### Task 4: Initial schema migration (all 10 tables)

**Files:**
- Create: `kalshi-ev-scanner/scanner/alembic/versions/001_initial_schema.py`

- [ ] **Step 1: Generate empty revision**

Run:
```bash
cd scanner
uv run alembic revision -m "initial schema"
```

Note the generated filename (e.g., `alembic/versions/abc123_initial_schema.py`). Rename to `001_initial_schema.py`:
```bash
mv alembic/versions/*_initial_schema.py alembic/versions/001_initial_schema.py
```

- [ ] **Step 2: Replace contents of migration file**

Write to `alembic/versions/001_initial_schema.py`:
```python
"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-29

Implements the 10 tables defined in
docs/superpowers/specs/2026-05-29-kalshi-ev-scanner-design.md Section 6.
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("sport", sa.Text, nullable=False),
        sa.Column("kalshi_ticker", sa.Text, nullable=False, unique=True),
        sa.Column("market_type", sa.Text, nullable=False),
        sa.Column("player_name", sa.Text, nullable=True),
        sa.Column("stat_type", sa.Text, nullable=True),
        sa.Column("line", sa.Numeric(6, 2), nullable=True),
        sa.Column("game_id", sa.Text, nullable=False),
        sa.Column("game_starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_markets_game", "markets", ["game_id", "is_active"])
    op.create_index(
        "idx_markets_starts",
        "markets",
        ["game_starts_at"],
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("book", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("decimal_odds", sa.Numeric(10, 4), nullable=False),
        sa.Column("implied_prob", sa.Numeric(7, 6), nullable=False),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_snapshots_market_time", "odds_snapshots", ["market_id", sa.text("fetched_at DESC")])
    op.create_index("idx_snapshots_book_time", "odds_snapshots", ["book", sa.text("fetched_at DESC")])

    op.create_table(
        "projections",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("mean", sa.Numeric(8, 3), nullable=False),
        sa.Column("std_dev", sa.Numeric(8, 3), nullable=False),
        sa.Column("distribution", sa.Text, nullable=False),
        sa.Column("fair_prob_over", sa.Numeric(7, 6), nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("news_adjusted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_projections_market_time", "projections", ["market_id", sa.text("computed_at DESC")])

    op.create_table(
        "news_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("player_name", sa.Text, nullable=False),
        sa.Column("team", sa.Text, nullable=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("posted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
    )
    op.create_index("idx_news_player_recent", "news_events", ["player_name", sa.text("posted_at DESC")])

    op.create_table(
        "opportunities",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("kalshi_side", sa.Text, nullable=False),
        sa.Column("kalshi_decimal_odds", sa.Numeric(10, 4), nullable=False),
        sa.Column("consensus_fair_prob", sa.Numeric(7, 6), nullable=False),
        sa.Column("projection_fair_prob", sa.Numeric(7, 6), nullable=True),
        sa.Column("blended_fair_prob", sa.Numeric(7, 6), nullable=False),
        sa.Column("ev_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column("kelly_fraction", sa.Numeric(6, 4), nullable=True),
        sa.Column("num_sharp_books", sa.SmallInteger, nullable=False),
        sa.Column("suspicious", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("scan_tick_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_opps_recent", "opportunities", [sa.text("scan_tick_at DESC")])
    op.create_index("idx_opps_market_recent", "opportunities", ["market_id", sa.text("scan_tick_at DESC")])

    op.create_table(
        "bets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("opportunity_id", sa.BigInteger, sa.ForeignKey("opportunities.id"), nullable=True),
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("stake_cents", sa.Integer, nullable=False),
        sa.Column("decimal_odds", sa.Numeric(10, 4), nullable=False),
        sa.Column("ev_pct_at_bet", sa.Numeric(6, 4), nullable=False),
        sa.Column("placed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "bet_results",
        sa.Column("bet_id", sa.BigInteger, sa.ForeignKey("bets.id"), primary_key=True),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("payout_cents", sa.Integer, nullable=False),
        sa.Column("actual_value", sa.Numeric(8, 3), nullable=True),
        sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "market_outcomes",
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), primary_key=True),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("actual_value", sa.Numeric(8, 3), nullable=True),
        sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "bankroll_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("delta_cents", sa.Integer, nullable=False),
        sa.Column("balance_cents", sa.Integer, nullable=False),
        sa.Column("related_bet_id", sa.BigInteger, sa.ForeignKey("bets.id"), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_bankroll_user_time", "bankroll_events", ["user_id", sa.text("created_at DESC")])

    op.create_table(
        "scan_telemetry",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tick_id", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("status_detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_telemetry_source_time", "scan_telemetry", ["source", sa.text("created_at DESC")])
    op.create_index("idx_telemetry_tick", "scan_telemetry", ["tick_id"])


def downgrade() -> None:
    op.drop_table("scan_telemetry")
    op.drop_table("bankroll_events")
    op.drop_table("market_outcomes")
    op.drop_table("bet_results")
    op.drop_table("bets")
    op.drop_table("opportunities")
    op.drop_table("news_events")
    op.drop_table("projections")
    op.drop_table("odds_snapshots")
    op.drop_table("markets")
```

- [ ] **Step 3: Apply migration**

Run:
```bash
uv run alembic upgrade head
```

Expected: `Running upgrade  -> 001, initial schema`

- [ ] **Step 4: Verify tables exist**

Run:
```bash
docker compose exec postgres psql -U kalshi -d kalshi_ev -c "\dt"
```

Expected: 10 tables + `alembic_version` listed.

- [ ] **Step 5: Insert initial bankroll seed**

Run:
```bash
docker compose exec postgres psql -U kalshi -d kalshi_ev -c "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents, notes) VALUES ('deposit', 80000, 80000, 'initial seed');"
```

Expected: `INSERT 0 1`

- [ ] **Step 6: Commit**

```bash
cd ..
git add scanner/alembic/versions/001_initial_schema.py
git commit -m "feat(scanner): initial DB schema migration"
```

---

## Phase 1: Math Library (Strict TDD)

### Task 5: `devig` function

**Files:**
- Test: `scanner/tests/unit/test_devig.py`
- Create: `scanner/src/math/__init__.py`
- Create: `scanner/src/math/devig.py`

- [ ] **Step 1: Write failing test**

Write to `scanner/tests/unit/test_devig.py`:
```python
"""Tests for multiplicative devig — removing the vig from a two-sided market."""

import math

import pytest

from src.math.devig import devig


def test_devig_balanced_minus_110():
    # -110 / -110 → implied 0.524 / 0.524 → fair 0.5 / 0.5
    fair_over, fair_under = devig(0.524, 0.524)
    assert math.isclose(fair_over, 0.5, abs_tol=1e-9)
    assert math.isclose(fair_under, 0.5, abs_tol=1e-9)


def test_devig_skewed_favorite():
    # -150 / +130 → 0.6 / 0.435 (raw) → fair ~0.580 / ~0.420
    fair_over, fair_under = devig(0.6, 0.435)
    assert math.isclose(fair_over + fair_under, 1.0, abs_tol=1e-9)
    assert fair_over > fair_under


def test_devig_sums_to_one():
    fair_over, fair_under = devig(0.55, 0.5)
    assert math.isclose(fair_over + fair_under, 1.0, abs_tol=1e-9)


def test_devig_zero_inputs_raises():
    with pytest.raises(ValueError):
        devig(0.0, 0.0)
```

- [ ] **Step 2: Run test — verify it fails**

Run from `scanner/`:
```bash
uv run pytest tests/unit/test_devig.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.math.devig'` or similar.

- [ ] **Step 3: Implement `src/math/devig.py`**

First create the package init:
```bash
mkdir -p src/math
touch src/math/__init__.py
```

Write to `src/math/devig.py`:
```python
"""Multiplicative devig — strip the vig from a two-sided implied probability pair."""


def devig(implied_over: float, implied_under: float) -> tuple[float, float]:
    """Return (fair_over, fair_under) probabilities that sum to 1.0.

    Standard multiplicative method. Equivalent to:
        fair_over = implied_over / (implied_over + implied_under)

    Raises:
        ValueError: If both inputs are zero (no market).
    """
    total = implied_over + implied_under
    if total <= 0:
        raise ValueError("at least one implied probability must be > 0")
    return implied_over / total, implied_under / total
```

- [ ] **Step 4: Run tests — verify they pass**

Run:
```bash
uv run pytest tests/unit/test_devig.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/math/__init__.py scanner/src/math/devig.py scanner/tests/unit/test_devig.py
git commit -m "feat(math): multiplicative devig"
```

---

### Task 6: Brier-weighted consensus

**Files:**
- Test: `scanner/tests/unit/test_consensus.py`
- Create: `scanner/src/math/consensus.py`

- [ ] **Step 1: Write failing test**

Write to `scanner/tests/unit/test_consensus.py`:
```python
"""Tests for Brier-weighted consensus across multiple books."""

import math

import pytest

from src.math.consensus import COLD_START_WEIGHTS, brier_weighted_consensus


def test_single_book_returns_its_probability():
    result = brier_weighted_consensus(
        fair_probs={"pinnacle": 0.55},
        weights={"pinnacle": 1.0},
    )
    assert math.isclose(result, 0.55, abs_tol=1e-9)


def test_equal_weights_returns_arithmetic_mean():
    result = brier_weighted_consensus(
        fair_probs={"pinnacle": 0.6, "novig": 0.5},
        weights={"pinnacle": 1.0, "novig": 1.0},
    )
    assert math.isclose(result, 0.55, abs_tol=1e-9)


def test_higher_weight_pulls_result():
    # Pinnacle weight 10x → result much closer to 0.6 than 0.5
    result = brier_weighted_consensus(
        fair_probs={"pinnacle": 0.6, "draftkings": 0.5},
        weights={"pinnacle": 1.0, "draftkings": 0.1},
    )
    assert result > 0.58


def test_unknown_book_in_probs_raises():
    with pytest.raises(ValueError, match="weight missing"):
        brier_weighted_consensus(
            fair_probs={"pinnacle": 0.55, "betonline": 0.56},
            weights={"pinnacle": 1.0},
        )


def test_empty_input_raises():
    with pytest.raises(ValueError, match="no books"):
        brier_weighted_consensus(fair_probs={}, weights={})


def test_cold_start_weights_pinnacle_highest():
    assert COLD_START_WEIGHTS["pinnacle"] >= COLD_START_WEIGHTS["novig"]
    assert COLD_START_WEIGHTS["novig"] >= COLD_START_WEIGHTS["betonline"]
    assert COLD_START_WEIGHTS["betonline"] >= COLD_START_WEIGHTS["draftkings"]
```

- [ ] **Step 2: Run test — verify it fails**

Run:
```bash
cd scanner
uv run pytest tests/unit/test_consensus.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/math/consensus.py`**

Write to `src/math/consensus.py`:
```python
"""Brier-weighted consensus blending across multiple books.

Brier score = mean squared error of (predicted_prob - actual_outcome)
over the rolling 60-day window. Lower = more accurate book.
Weight = 1 / brier; we normalize across input books.

Plan 1 uses the cold-start weights below until Brier scores exist
(Plan 2 implements the rolling recompute).
"""

COLD_START_WEIGHTS: dict[str, float] = {
    "pinnacle": 1.00,
    "novig": 0.90,
    "betonline": 0.70,
    "draftkings": 0.40,
}


def brier_weighted_consensus(
    fair_probs: dict[str, float],
    weights: dict[str, float],
) -> float:
    """Weighted average of fair probabilities across books.

    Args:
        fair_probs: book name -> devigged fair probability for the side we care about
        weights: book name -> weight (typically COLD_START_WEIGHTS or 1/brier)

    Returns:
        Single consensus probability in [0, 1].

    Raises:
        ValueError: If fair_probs is empty or a book has no weight.
    """
    if not fair_probs:
        raise ValueError("no books in fair_probs")
    for book in fair_probs:
        if book not in weights:
            raise ValueError(f"weight missing for book {book!r}")

    total_weight = sum(weights[b] for b in fair_probs)
    if total_weight <= 0:
        raise ValueError("total weight must be > 0")

    return sum(fair_probs[b] * weights[b] for b in fair_probs) / total_weight
```

- [ ] **Step 4: Run tests — verify they pass**

Run:
```bash
uv run pytest tests/unit/test_consensus.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/math/consensus.py scanner/tests/unit/test_consensus.py
git commit -m "feat(math): brier-weighted consensus + cold-start weights"
```

---

### Task 7: Distribution conversions (Normal + NegBin)

**Files:**
- Test: `scanner/tests/unit/test_distributions.py`
- Create: `scanner/src/math/distributions.py`

- [ ] **Step 1: Write failing test**

Write to `scanner/tests/unit/test_distributions.py`:
```python
"""Tests for distribution → P(actual > line) conversion."""

import math

import pytest

from src.math.distributions import STAT_DISTRIBUTIONS, fair_prob_over


def test_normal_at_mean_is_half():
    # If line == mean (with continuity correction at line+0.5),
    # P(over) should be slightly below 0.5.
    p = fair_prob_over(mean=25.0, std=5.0, line=25.0, distribution="normal")
    assert 0.4 < p < 0.5


def test_normal_far_below_line_is_low():
    p = fair_prob_over(mean=10.0, std=2.0, line=25.0, distribution="normal")
    assert p < 0.01


def test_normal_far_above_line_is_high():
    p = fair_prob_over(mean=40.0, std=2.0, line=25.0, distribution="normal")
    assert p > 0.99


def test_negbin_at_low_line_high_prob():
    # μ=8 rebounds, line 3.5 → very likely over
    p = fair_prob_over(mean=8.0, std=3.0, line=3.5, distribution="negative_binomial")
    assert p > 0.85


def test_negbin_at_high_line_low_prob():
    p = fair_prob_over(mean=8.0, std=3.0, line=15.5, distribution="negative_binomial")
    assert p < 0.05


def test_unknown_distribution_raises():
    with pytest.raises(ValueError, match="unsupported distribution"):
        fair_prob_over(mean=10.0, std=2.0, line=5.0, distribution="cauchy")


def test_stat_distributions_mapping():
    assert STAT_DISTRIBUTIONS["points"] == "normal"
    assert STAT_DISTRIBUTIONS["pra"] == "normal"
    assert STAT_DISTRIBUTIONS["rebounds"] == "negative_binomial"
    assert STAT_DISTRIBUTIONS["assists"] == "negative_binomial"
    assert STAT_DISTRIBUTIONS["threes"] == "negative_binomial"
```

- [ ] **Step 2: Run test — verify it fails**

Run:
```bash
cd scanner
uv run pytest tests/unit/test_distributions.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `src/math/distributions.py`**

Write to `src/math/distributions.py`:
```python
"""Distribution → P(actual_stat > line) conversions.

Normal: continuous stats (points, PRA, minutes).
Negative Binomial: discrete counting stats with overdispersion
(rebounds, assists, threes, blocks, steals).
"""

from scipy.stats import nbinom, norm

STAT_DISTRIBUTIONS: dict[str, str] = {
    "points": "normal",
    "pra": "normal",
    "minutes": "normal",
    "rebounds": "negative_binomial",
    "assists": "negative_binomial",
    "threes": "negative_binomial",
    "blocks": "negative_binomial",
    "steals": "negative_binomial",
}


def fair_prob_over(*, mean: float, std: float, line: float, distribution: str) -> float:
    """Return P(actual_stat > line) given the projection parameters.

    Args:
        mean: projected stat value (e.g. 24.7 points)
        std: projection standard deviation
        line: the betting line (e.g. 24.5)
        distribution: "normal" or "negative_binomial"

    Raises:
        ValueError: If distribution is unsupported or std <= 0.
    """
    if std <= 0:
        raise ValueError("std must be > 0")

    if distribution == "normal":
        # Continuity correction: P(X > line) using line + 0.5
        return float(1.0 - norm.cdf(line + 0.5, loc=mean, scale=std))

    if distribution == "negative_binomial":
        var = std**2
        # Fit NegBin to (mean, var). Requires var > mean.
        # If under-dispersed in data, clamp p near 1 (degenerate Poisson-like).
        if var > mean:
            p = mean / var
        else:
            p = 0.99
        n = mean * p / (1 - p)
        return float(1.0 - nbinom.cdf(int(line), n, p))

    raise ValueError(f"unsupported distribution: {distribution!r}")
```

- [ ] **Step 4: Run tests — verify they pass**

Run:
```bash
uv run pytest tests/unit/test_distributions.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/math/distributions.py scanner/tests/unit/test_distributions.py
git commit -m "feat(math): normal + negbin distribution → P(over line)"
```

---

### Task 8: Kalshi EV (with fee adjustment)

**Files:**
- Test: `scanner/tests/unit/test_ev.py`
- Create: `scanner/src/math/ev.py`

- [ ] **Step 1: Write failing test**

Write to `scanner/tests/unit/test_ev.py`:
```python
"""Tests for Kalshi EV calculation with fee adjustment.

Kalshi fee = 0.07 * yes_price * (1 - yes_price) per winning contract.
"""

import math

import pytest

from src.math.ev import kalshi_ev


def test_zero_edge_returns_zero():
    # Fair = 0.50, YES = 50¢ → no edge
    ev = kalshi_ev(fair_prob_yes=0.50, yes_price_cents=50)
    assert ev < 0  # slightly negative due to fee
    assert ev > -0.05


def test_positive_edge():
    # Fair = 0.60, YES = 50¢ → strong +EV
    ev = kalshi_ev(fair_prob_yes=0.60, yes_price_cents=50)
    assert ev > 0.15


def test_negative_edge():
    ev = kalshi_ev(fair_prob_yes=0.40, yes_price_cents=50)
    assert ev < -0.15


def test_fee_eats_some_edge():
    ev_with_fee = kalshi_ev(fair_prob_yes=0.55, yes_price_cents=50)
    # Without fee, EV would be (0.55 * 1.0) / 0.50 - 1 = +10.0%
    # With 0.07 * 0.5 * 0.5 = 0.0175 fee per win, payout = 0.9825
    # EV = 0.55 * 0.9825 / 0.50 - 1 = +8.08%
    assert math.isclose(ev_with_fee, 0.55 * 0.9825 / 0.50 - 1, abs_tol=1e-6)


def test_invalid_yes_price_raises():
    with pytest.raises(ValueError):
        kalshi_ev(fair_prob_yes=0.5, yes_price_cents=0)
    with pytest.raises(ValueError):
        kalshi_ev(fair_prob_yes=0.5, yes_price_cents=100)


def test_invalid_prob_raises():
    with pytest.raises(ValueError):
        kalshi_ev(fair_prob_yes=-0.1, yes_price_cents=50)
    with pytest.raises(ValueError):
        kalshi_ev(fair_prob_yes=1.1, yes_price_cents=50)
```

- [ ] **Step 2: Run test — verify it fails**

Run:
```bash
cd scanner
uv run pytest tests/unit/test_ev.py -v
```

- [ ] **Step 3: Implement `src/math/ev.py`**

Write to `src/math/ev.py`:
```python
"""Expected-value calculation for Kalshi contracts.

Kalshi YES contract: pay `yes_price` cents, win $1 if YES, $0 if NO.
Kalshi fee (per winning contract): 0.07 * yes_price_dollars * (1 - yes_price_dollars).
"""

KALSHI_FEE_COEFFICIENT = 0.07


def kalshi_ev(*, fair_prob_yes: float, yes_price_cents: int) -> float:
    """Return expected value as a fraction of stake, after Kalshi fees.

    EV > 0 means positive expected value (we'd profit on average).
    EV is expressed as a fraction of stake — e.g. 0.063 == +6.3%.

    Args:
        fair_prob_yes: our blended fair probability for YES outcome, in [0, 1]
        yes_price_cents: Kalshi YES contract price in cents, exclusive (0, 100)

    Raises:
        ValueError: If inputs are out of range.
    """
    if not 0.0 <= fair_prob_yes <= 1.0:
        raise ValueError(f"fair_prob_yes out of range: {fair_prob_yes}")
    if not 0 < yes_price_cents < 100:
        raise ValueError(f"yes_price_cents must be in (0, 100): {yes_price_cents}")

    yes_price = yes_price_cents / 100.0
    fee_per_winning_contract = KALSHI_FEE_COEFFICIENT * yes_price * (1.0 - yes_price)
    payout_if_win = 1.0 - fee_per_winning_contract
    expected_profit_per_contract = fair_prob_yes * payout_if_win - yes_price
    return expected_profit_per_contract / yes_price
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/unit/test_ev.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/math/ev.py scanner/tests/unit/test_ev.py
git commit -m "feat(math): kalshi EV with fee adjustment"
```

---

### Task 9: Quarter-Kelly stake sizing

**Files:**
- Test: `scanner/tests/unit/test_kelly.py`
- Create: `scanner/src/math/kelly.py`

- [ ] **Step 1: Write failing test**

Write to `scanner/tests/unit/test_kelly.py`:
```python
"""Tests for fractional Kelly stake sizing with cap."""

import math

import pytest

from src.math.kelly import kelly_stake_cents


def test_no_edge_zero_stake():
    stake = kelly_stake_cents(
        fair_prob=0.5, decimal_odds=2.0, bankroll_cents=100_000
    )
    assert stake == 0


def test_negative_edge_zero_stake():
    stake = kelly_stake_cents(
        fair_prob=0.4, decimal_odds=2.0, bankroll_cents=100_000
    )
    assert stake == 0


def test_positive_edge_quarter_kelly_default():
    # Full Kelly: (b*p - q) / b
    # b = decimal_odds - 1 = 1.0
    # p = 0.55, q = 0.45
    # kelly = (1.0 * 0.55 - 0.45) / 1.0 = 0.10
    # quarter = 0.025 → 2.5% of $1000 = $25 = 2500c
    stake = kelly_stake_cents(
        fair_prob=0.55, decimal_odds=2.0, bankroll_cents=100_000, fraction=0.25
    )
    assert stake == 2500


def test_cap_enforces_max():
    # Huge edge — full Kelly would say bet more than cap
    # cap = 5% of 100k cents = 5000c
    stake = kelly_stake_cents(
        fair_prob=0.95, decimal_odds=2.0, bankroll_cents=100_000,
        fraction=0.25, cap_pct=0.05,
    )
    assert stake == 5000


def test_zero_bankroll_zero_stake():
    stake = kelly_stake_cents(
        fair_prob=0.9, decimal_odds=2.0, bankroll_cents=0
    )
    assert stake == 0


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        kelly_stake_cents(fair_prob=1.5, decimal_odds=2.0, bankroll_cents=100_000)
    with pytest.raises(ValueError):
        kelly_stake_cents(fair_prob=0.5, decimal_odds=0.5, bankroll_cents=100_000)
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd scanner
uv run pytest tests/unit/test_kelly.py -v
```

- [ ] **Step 3: Implement `src/math/kelly.py`**

Write to `src/math/kelly.py`:
```python
"""Fractional Kelly stake sizing with hard cap."""


def kelly_stake_cents(
    *,
    fair_prob: float,
    decimal_odds: float,
    bankroll_cents: int,
    fraction: float = 0.25,
    cap_pct: float = 0.05,
) -> int:
    """Return the recommended stake in cents.

    Full Kelly = (b*p - q) / b, where b = decimal_odds - 1, q = 1 - p.
    Then we scale by `fraction` (quarter-Kelly default) and clamp at `cap_pct` of bankroll.

    Args:
        fair_prob: our fair probability the bet wins, in [0, 1]
        decimal_odds: > 1.0 (e.g. 2.0 for +100, 1.91 for -110)
        bankroll_cents: integer bankroll in cents
        fraction: fraction of full Kelly to deploy (0.25 default)
        cap_pct: max fraction of bankroll per bet (0.05 default)

    Returns:
        Stake in cents (integer, floor).

    Raises:
        ValueError: If inputs are out of range.
    """
    if not 0.0 <= fair_prob <= 1.0:
        raise ValueError(f"fair_prob out of range: {fair_prob}")
    if decimal_odds <= 1.0:
        raise ValueError(f"decimal_odds must be > 1.0: {decimal_odds}")
    if bankroll_cents < 0:
        raise ValueError(f"bankroll_cents must be >= 0: {bankroll_cents}")

    b = decimal_odds - 1.0
    p = fair_prob
    q = 1.0 - p
    full_kelly_pct = (b * p - q) / b
    if full_kelly_pct <= 0:
        return 0

    sized_pct = min(full_kelly_pct * fraction, cap_pct)
    return int(bankroll_cents * sized_pct)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/unit/test_kelly.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/math/kelly.py scanner/tests/unit/test_kelly.py
git commit -m "feat(math): quarter-kelly stake sizer with cap"
```

---

### Task 10: Projection weight ramp

**Files:**
- Test: `scanner/tests/unit/test_projection_weight.py`
- Create: `scanner/src/math/projection_weight.py`

- [ ] **Step 1: Write failing test**

Write to `scanner/tests/unit/test_projection_weight.py`:
```python
"""Tests for linear projection weight ramp 0.20 → 0.40 over 90 days."""

import math

from src.math.projection_weight import current_projection_weight


def test_day_zero_is_start():
    assert math.isclose(current_projection_weight(0), 0.20, abs_tol=1e-9)


def test_day_ninety_is_end():
    assert math.isclose(current_projection_weight(90), 0.40, abs_tol=1e-9)


def test_day_forty_five_is_midpoint():
    assert math.isclose(current_projection_weight(45), 0.30, abs_tol=1e-9)


def test_after_ninety_stays_end():
    assert math.isclose(current_projection_weight(120), 0.40, abs_tol=1e-9)


def test_negative_days_clamps_to_start():
    assert math.isclose(current_projection_weight(-5), 0.20, abs_tol=1e-9)
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd scanner
uv run pytest tests/unit/test_projection_weight.py -v
```

- [ ] **Step 3: Implement `src/math/projection_weight.py`**

Write to `src/math/projection_weight.py`:
```python
"""Linear ramp of projection weight from 0.20 (day 0) to 0.40 (day 90)."""

PROJECTION_WEIGHT_START = 0.20
PROJECTION_WEIGHT_END = 0.40
PROJECTION_RAMP_DAYS = 90


def current_projection_weight(days_since_launch: int) -> float:
    """Linearly interpolated projection blend weight.

    Clamped at both ends (negative → start, >=90 → end).
    """
    if days_since_launch <= 0:
        return PROJECTION_WEIGHT_START
    if days_since_launch >= PROJECTION_RAMP_DAYS:
        return PROJECTION_WEIGHT_END
    pct = days_since_launch / PROJECTION_RAMP_DAYS
    return PROJECTION_WEIGHT_START + pct * (PROJECTION_WEIGHT_END - PROJECTION_WEIGHT_START)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/unit/test_projection_weight.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/math/projection_weight.py scanner/tests/unit/test_projection_weight.py
git commit -m "feat(math): linear projection weight ramp"
```

---

### Task 11: Blend function (consensus + projection)

**Files:**
- Test: `scanner/tests/unit/test_blend.py`
- Create: `scanner/src/math/blend.py`

- [ ] **Step 1: Write failing test**

Write to `scanner/tests/unit/test_blend.py`:
```python
"""Tests for blending consensus probability with projection probability."""

import math

import pytest

from src.math.blend import blended_fair_prob


def test_no_projection_returns_consensus():
    result = blended_fair_prob(
        consensus_prob=0.55, projection_prob=None, projection_weight=0.4
    )
    assert math.isclose(result, 0.55, abs_tol=1e-9)


def test_full_blend_at_weight_zero_returns_consensus():
    result = blended_fair_prob(
        consensus_prob=0.55, projection_prob=0.65, projection_weight=0.0
    )
    assert math.isclose(result, 0.55, abs_tol=1e-9)


def test_full_blend_at_weight_one_returns_projection():
    result = blended_fair_prob(
        consensus_prob=0.55, projection_prob=0.65, projection_weight=1.0
    )
    assert math.isclose(result, 0.65, abs_tol=1e-9)


def test_blend_at_weight_point_four():
    # 0.6 * 0.55 + 0.4 * 0.65 = 0.33 + 0.26 = 0.59
    result = blended_fair_prob(
        consensus_prob=0.55, projection_prob=0.65, projection_weight=0.4
    )
    assert math.isclose(result, 0.59, abs_tol=1e-9)


def test_invalid_weight_raises():
    with pytest.raises(ValueError):
        blended_fair_prob(consensus_prob=0.5, projection_prob=0.6, projection_weight=-0.1)
    with pytest.raises(ValueError):
        blended_fair_prob(consensus_prob=0.5, projection_prob=0.6, projection_weight=1.1)
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd scanner
uv run pytest tests/unit/test_blend.py -v
```

- [ ] **Step 3: Implement `src/math/blend.py`**

Write to `src/math/blend.py`:
```python
"""Blend market consensus probability with projection probability."""


def blended_fair_prob(
    *,
    consensus_prob: float,
    projection_prob: float | None,
    projection_weight: float,
) -> float:
    """Return the blended fair probability for the YES/over side.

    Formula:  (1 - w) * consensus + w * projection
    If projection_prob is None, returns consensus_prob unchanged.

    Raises:
        ValueError: If projection_weight is outside [0, 1].
    """
    if not 0.0 <= projection_weight <= 1.0:
        raise ValueError(f"projection_weight out of range: {projection_weight}")

    if projection_prob is None:
        return consensus_prob

    return (1.0 - projection_weight) * consensus_prob + projection_weight * projection_prob
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/unit/test_blend.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/math/blend.py scanner/tests/unit/test_blend.py
git commit -m "feat(math): blend consensus + projection probability"
```

---

### Task 12: Property-based test sweep over the math module

**Files:**
- Test: `scanner/tests/unit/test_math_properties.py`

- [ ] **Step 1: Write hypothesis-based property tests**

Write to `scanner/tests/unit/test_math_properties.py`:
```python
"""Property-based tests for math module invariants."""

import math

from hypothesis import given, strategies as st

from src.math.blend import blended_fair_prob
from src.math.consensus import COLD_START_WEIGHTS, brier_weighted_consensus
from src.math.devig import devig
from src.math.kelly import kelly_stake_cents


@given(
    over=st.floats(min_value=0.01, max_value=0.99),
    under=st.floats(min_value=0.01, max_value=0.99),
)
def test_devig_outputs_sum_to_one(over, under):
    fair_over, fair_under = devig(over, under)
    assert math.isclose(fair_over + fair_under, 1.0, abs_tol=1e-9)


@given(
    over=st.floats(min_value=0.01, max_value=0.99),
    under=st.floats(min_value=0.01, max_value=0.99),
)
def test_devig_outputs_in_unit_interval(over, under):
    fair_over, fair_under = devig(over, under)
    assert 0.0 <= fair_over <= 1.0
    assert 0.0 <= fair_under <= 1.0


@given(
    pinnacle=st.floats(min_value=0.01, max_value=0.99),
    novig=st.floats(min_value=0.01, max_value=0.99),
)
def test_consensus_in_unit_interval(pinnacle, novig):
    result = brier_weighted_consensus(
        fair_probs={"pinnacle": pinnacle, "novig": novig},
        weights=COLD_START_WEIGHTS,
    )
    assert 0.0 <= result <= 1.0


@given(
    consensus=st.floats(min_value=0.01, max_value=0.99),
    projection=st.floats(min_value=0.01, max_value=0.99),
    weight=st.floats(min_value=0.0, max_value=1.0),
)
def test_blend_in_unit_interval(consensus, projection, weight):
    result = blended_fair_prob(
        consensus_prob=consensus,
        projection_prob=projection,
        projection_weight=weight,
    )
    assert 0.0 <= result <= 1.0


@given(
    fair_prob=st.floats(min_value=0.0, max_value=1.0),
    decimal_odds=st.floats(min_value=1.01, max_value=20.0),
    bankroll=st.integers(min_value=0, max_value=10_000_000),
)
def test_kelly_stake_never_exceeds_cap(fair_prob, decimal_odds, bankroll):
    cap_pct = 0.05
    stake = kelly_stake_cents(
        fair_prob=fair_prob,
        decimal_odds=decimal_odds,
        bankroll_cents=bankroll,
        cap_pct=cap_pct,
    )
    assert stake <= int(bankroll * cap_pct) + 1  # +1 for int rounding
```

- [ ] **Step 2: Run tests**

```bash
cd scanner
uv run pytest tests/unit/test_math_properties.py -v
```

Expected: 5 passed (each runs hundreds of generated inputs).

- [ ] **Step 3: Commit**

```bash
cd ..
git add scanner/tests/unit/test_math_properties.py
git commit -m "test(math): property-based invariant sweep with hypothesis"
```

---

### Task 13: Run full math module test suite + coverage

**Files:** none (verification only)

- [ ] **Step 1: Run all math tests with coverage**

```bash
cd scanner
uv run pytest tests/unit/ --cov=src.math --cov-report=term-missing
```

Expected: All tests pass. Coverage ≥ 95% on `src.math`.

- [ ] **Step 2: If coverage gaps, add tests**

If `--cov-report=term-missing` shows any uncovered lines in `src/math/`, add tests to cover them in the relevant `tests/unit/test_*.py`. Re-run.

- [ ] **Step 3: No commit needed (verification only)**

---

## Phase 2: Repositories (DB access layer)

### Task 14: Async DB connection pool

**Files:**
- Create: `scanner/src/db.py`
- Create: `scanner/src/logger.py`

- [ ] **Step 1: Write `src/logger.py`**

Write to `src/logger.py`:
```python
"""structlog configuration — JSON output to stdout."""

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Set up structlog with JSON output."""
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()
```

- [ ] **Step 2: Write `src/db.py`**

Write to `src/db.py`:
```python
"""asyncpg connection pool — single global pool for the scanner service."""

import asyncpg

from src.config import settings
from src.logger import log

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Lazy-init the pool the first time it's requested."""
    global _pool
    if _pool is None:
        # asyncpg expects DSN with `postgresql://` (no `+driver`)
        dsn = settings.database_url.replace("postgresql+psycopg2://", "postgresql://")
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=10,
            command_timeout=10,
        )
        log.info("db_pool_initialized", dsn=dsn)
    return _pool


async def close_pool() -> None:
    """Cleanup hook for graceful shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

- [ ] **Step 3: Commit**

```bash
cd ..
git add scanner/src/db.py scanner/src/logger.py
git commit -m "feat(scanner): async DB pool + structlog setup"
```

---

### Task 15: Integration test fixture for Postgres

**Files:**
- Create: `scanner/tests/conftest.py`
- Create: `scanner/tests/integration/__init__.py`
- Create: `scanner/tests/integration/conftest.py`

- [ ] **Step 1: Write `tests/conftest.py`**

Write to `tests/conftest.py`:
```python
"""Root pytest config."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://kalshi:kalshi@localhost:5432/kalshi_ev")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
```

- [ ] **Step 2: Create integration tests dir**

```bash
cd scanner
mkdir -p tests/integration
touch tests/integration/__init__.py
```

- [ ] **Step 3: Write `tests/integration/conftest.py`**

Write to `tests/integration/conftest.py`:
```python
"""Integration test fixtures — require a running Postgres on localhost:5432.

Run docker compose up -d before invoking these tests.
"""

import pytest_asyncio

from src.db import close_pool, get_pool


@pytest_asyncio.fixture
async def pool():
    """Yields the asyncpg pool. Cleans up at end of session."""
    p = await get_pool()
    yield p
    # Truncate test data between tests so they don't interfere.
    async with p.acquire() as conn:
        await conn.execute(
            "TRUNCATE markets, odds_snapshots, projections, news_events, "
            "opportunities, bets, bet_results, market_outcomes, "
            "scan_telemetry RESTART IDENTITY CASCADE"
        )


@pytest_asyncio.fixture(autouse=True, scope="session")
async def _teardown_pool():
    yield
    await close_pool()
```

- [ ] **Step 4: Verify smoke test**

Run:
```bash
uv run pytest tests/integration/ -v --tb=short
```

Expected: 0 tests, but no fixture errors. (We'll add tests in next task.)

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/tests/conftest.py scanner/tests/integration/
git commit -m "test: integration test fixtures (Postgres)"
```

---

### Task 16: Markets repository

**Files:**
- Create: `scanner/src/repositories/__init__.py`
- Create: `scanner/src/repositories/markets.py`
- Test: `scanner/tests/integration/test_repositories.py`

- [ ] **Step 1: Create package init**

```bash
cd scanner
mkdir -p src/repositories
touch src/repositories/__init__.py
```

- [ ] **Step 2: Write `src/repositories/markets.py`**

Write to `src/repositories/markets.py`:
```python
"""Markets repository — CRUD for the markets table."""

from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True, slots=True)
class Market:
    id: int
    sport: str
    kalshi_ticker: str
    market_type: str
    player_name: str | None
    stat_type: str | None
    line: float | None
    game_id: str
    game_starts_at: datetime
    is_active: bool


async def upsert_market(
    pool: asyncpg.Pool,
    *,
    sport: str,
    kalshi_ticker: str,
    market_type: str,
    game_id: str,
    game_starts_at: datetime,
    player_name: str | None = None,
    stat_type: str | None = None,
    line: float | None = None,
) -> Market:
    """Insert market or return existing by kalshi_ticker."""
    row = await pool.fetchrow(
        """
        INSERT INTO markets (sport, kalshi_ticker, market_type, player_name,
                             stat_type, line, game_id, game_starts_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (kalshi_ticker) DO UPDATE SET game_starts_at = EXCLUDED.game_starts_at
        RETURNING id, sport, kalshi_ticker, market_type, player_name, stat_type,
                  line, game_id, game_starts_at, is_active
        """,
        sport, kalshi_ticker, market_type, player_name, stat_type,
        line, game_id, game_starts_at,
    )
    return Market(**dict(row))


async def fetch_active_markets(pool: asyncpg.Pool) -> list[Market]:
    """All markets with is_active=true."""
    rows = await pool.fetch(
        """
        SELECT id, sport, kalshi_ticker, market_type, player_name, stat_type,
               line, game_id, game_starts_at, is_active
        FROM markets
        WHERE is_active = true
        ORDER BY game_starts_at
        """
    )
    return [Market(**dict(r)) for r in rows]
```

- [ ] **Step 3: Write integration test**

Write to `tests/integration/test_repositories.py`:
```python
"""Integration tests for repositories — requires Postgres."""

from datetime import datetime, timezone

import pytest

from src.repositories.markets import fetch_active_markets, upsert_market

pytestmark = pytest.mark.integration


async def test_upsert_market_inserts_new(pool):
    market = await upsert_market(
        pool,
        sport="NBA",
        kalshi_ticker="KXNBAGAME-25NOV20-LAL-POINTS-LEBRON",
        market_type="player_prop",
        player_name="LeBron James",
        stat_type="points",
        line=24.5,
        game_id="LAL-BOS-2025-11-20",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    assert market.id > 0
    assert market.kalshi_ticker == "KXNBAGAME-25NOV20-LAL-POINTS-LEBRON"


async def test_fetch_active_markets_returns_inserted(pool):
    await upsert_market(
        pool,
        sport="NBA",
        kalshi_ticker="KXNBAGAME-25NOV20-LAL-POINTS-LEBRON",
        market_type="player_prop",
        game_id="LAL-BOS-2025-11-20",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    markets = await fetch_active_markets(pool)
    assert len(markets) == 1
    assert markets[0].kalshi_ticker.startswith("KXNBAGAME")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/integration/test_repositories.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/repositories/ scanner/tests/integration/test_repositories.py
git commit -m "feat(repositories): markets upsert + fetch active"
```

---

### Task 17: Snapshots + Opportunities + Bankroll + Telemetry repos

**Files:**
- Create: `scanner/src/repositories/snapshots.py`
- Create: `scanner/src/repositories/opportunities.py`
- Create: `scanner/src/repositories/bankroll.py`
- Create: `scanner/src/repositories/telemetry.py`
- Modify: `scanner/tests/integration/test_repositories.py`

- [ ] **Step 1: Write `src/repositories/snapshots.py`**

```python
"""Odds snapshots repository — append-only bulk insert."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import asyncpg


@dataclass(frozen=True, slots=True)
class OddsSnapshot:
    market_id: int
    book: str
    side: str
    decimal_odds: Decimal
    implied_prob: Decimal


async def bulk_insert_snapshots(
    pool: asyncpg.Pool, snapshots: list[OddsSnapshot]
) -> int:
    """Bulk insert; returns count inserted."""
    if not snapshots:
        return 0
    records = [
        (s.market_id, s.book, s.side, s.decimal_odds, s.implied_prob)
        for s in snapshots
    ]
    await pool.executemany(
        """
        INSERT INTO odds_snapshots (market_id, book, side, decimal_odds, implied_prob)
        VALUES ($1, $2, $3, $4, $5)
        """,
        records,
    )
    return len(records)


async def latest_snapshot_per_book(
    pool: asyncpg.Pool, market_id: int
) -> dict[str, tuple[str, Decimal, Decimal]]:
    """For a given market, return latest (side, decimal_odds, implied_prob) per book.

    Useful for verifying snapshots wrote correctly. Plan 1 actually uses
    in-memory values from the current tick — this is for inspection/tests.
    """
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (book, side)
            book, side, decimal_odds, implied_prob, fetched_at
        FROM odds_snapshots
        WHERE market_id = $1
        ORDER BY book, side, fetched_at DESC
        """,
        market_id,
    )
    out: dict[str, tuple[str, Decimal, Decimal]] = {}
    for r in rows:
        out[f"{r['book']}:{r['side']}"] = (r["side"], r["decimal_odds"], r["implied_prob"])
    return out
```

- [ ] **Step 2: Write `src/repositories/opportunities.py`**

```python
"""Opportunities repository — append-only inserts; latest-per-market reads."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import asyncpg


@dataclass(frozen=True, slots=True)
class Opportunity:
    id: int
    market_id: int
    kalshi_side: str
    kalshi_decimal_odds: Decimal
    consensus_fair_prob: Decimal
    projection_fair_prob: Decimal | None
    blended_fair_prob: Decimal
    ev_pct: Decimal
    kelly_fraction: Decimal | None
    num_sharp_books: int
    suspicious: bool
    scan_tick_at: datetime


async def insert_opportunity(
    pool: asyncpg.Pool,
    *,
    market_id: int,
    kalshi_side: str,
    kalshi_decimal_odds: Decimal,
    consensus_fair_prob: Decimal,
    projection_fair_prob: Decimal | None,
    blended_fair_prob: Decimal,
    ev_pct: Decimal,
    kelly_fraction: Decimal | None,
    num_sharp_books: int,
    suspicious: bool,
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO opportunities (
            market_id, kalshi_side, kalshi_decimal_odds,
            consensus_fair_prob, projection_fair_prob, blended_fair_prob,
            ev_pct, kelly_fraction, num_sharp_books, suspicious
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """,
        market_id, kalshi_side, kalshi_decimal_odds,
        consensus_fair_prob, projection_fair_prob, blended_fair_prob,
        ev_pct, kelly_fraction, num_sharp_books, suspicious,
    )
    return row["id"]


async def fetch_latest_opportunities(
    pool: asyncpg.Pool, *, min_ev: float = 0.01, limit: int = 100
) -> list[Opportunity]:
    """Latest opportunity per market, sorted by EV descending."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (market_id)
            id, market_id, kalshi_side, kalshi_decimal_odds,
            consensus_fair_prob, projection_fair_prob, blended_fair_prob,
            ev_pct, kelly_fraction, num_sharp_books, suspicious, scan_tick_at
        FROM opportunities
        WHERE ev_pct >= $1
        ORDER BY market_id, scan_tick_at DESC
        """,
        Decimal(str(min_ev)),
    )
    opps = [Opportunity(**dict(r)) for r in rows]
    opps.sort(key=lambda o: o.ev_pct, reverse=True)
    return opps[:limit]
```

- [ ] **Step 3: Write `src/repositories/bankroll.py`**

```python
"""Bankroll repository — current balance from latest event row."""

import asyncpg


async def current_bankroll_cents(pool: asyncpg.Pool, user_id: int = 1) -> int:
    """Return latest balance_cents for the user. 0 if no events yet."""
    row = await pool.fetchrow(
        """
        SELECT balance_cents FROM bankroll_events
        WHERE user_id = $1
        ORDER BY id DESC LIMIT 1
        """,
        user_id,
    )
    return int(row["balance_cents"]) if row else 0
```

- [ ] **Step 4: Write `src/repositories/telemetry.py`**

```python
"""Scan telemetry repository — append-only event log."""

from datetime import datetime
from typing import Literal

import asyncpg


async def record_event(
    pool: asyncpg.Pool,
    *,
    tick_id: str,
    source: str,
    event_type: Literal["fetch_success", "fetch_failure", "tick_complete", "opps_written"],
    latency_ms: int | None = None,
    status_detail: str | None = None,
) -> None:
    await pool.execute(
        """
        INSERT INTO scan_telemetry (tick_id, source, event_type, latency_ms, status_detail)
        VALUES ($1, $2, $3, $4, $5)
        """,
        tick_id, source, event_type, latency_ms, status_detail,
    )


async def latest_fetch_per_source(pool: asyncpg.Pool) -> dict[str, datetime]:
    """Map source → latest successful fetch timestamp. Used by /health."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (source) source, created_at
        FROM scan_telemetry
        WHERE event_type = 'fetch_success'
        ORDER BY source, created_at DESC
        """
    )
    return {r["source"]: r["created_at"] for r in rows}
```

- [ ] **Step 5: Extend `tests/integration/test_repositories.py`**

Append to the existing file:
```python
from decimal import Decimal

from src.repositories.bankroll import current_bankroll_cents
from src.repositories.opportunities import fetch_latest_opportunities, insert_opportunity
from src.repositories.snapshots import OddsSnapshot, bulk_insert_snapshots
from src.repositories.telemetry import latest_fetch_per_source, record_event


async def _make_market(pool):
    return await upsert_market(
        pool,
        sport="NBA",
        kalshi_ticker="KXTEST-1",
        market_type="player_prop",
        game_id="TEST",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )


async def test_bulk_insert_snapshots(pool):
    m = await _make_market(pool)
    snapshots = [
        OddsSnapshot(m.id, "pinnacle", "over", Decimal("1.91"), Decimal("0.524")),
        OddsSnapshot(m.id, "pinnacle", "under", Decimal("1.91"), Decimal("0.524")),
    ]
    count = await bulk_insert_snapshots(pool, snapshots)
    assert count == 2


async def test_insert_and_fetch_opportunity(pool):
    m = await _make_market(pool)
    opp_id = await insert_opportunity(
        pool,
        market_id=m.id,
        kalshi_side="yes",
        kalshi_decimal_odds=Decimal("2.0833"),
        consensus_fair_prob=Decimal("0.580000"),
        projection_fair_prob=None,
        blended_fair_prob=Decimal("0.580000"),
        ev_pct=Decimal("0.0630"),
        kelly_fraction=Decimal("0.0140"),
        num_sharp_books=2,
        suspicious=False,
    )
    assert opp_id > 0

    opps = await fetch_latest_opportunities(pool, min_ev=0.01)
    assert len(opps) == 1
    assert float(opps[0].ev_pct) > 0.05


async def test_current_bankroll_zero_if_no_events(pool):
    assert await current_bankroll_cents(pool) == 0


async def test_current_bankroll_returns_latest_balance(pool):
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )
    assert await current_bankroll_cents(pool) == 80_000


async def test_telemetry_record_and_read(pool):
    await record_event(
        pool, tick_id="abc", source="pinnacle",
        event_type="fetch_success", latency_ms=420,
    )
    latest = await latest_fetch_per_source(pool)
    assert "pinnacle" in latest
```

- [ ] **Step 6: Run integration tests**

```bash
uv run pytest tests/integration/test_repositories.py -v
```

Expected: All passing.

- [ ] **Step 7: Commit**

```bash
cd ..
git add scanner/src/repositories/snapshots.py scanner/src/repositories/opportunities.py scanner/src/repositories/bankroll.py scanner/src/repositories/telemetry.py scanner/tests/integration/test_repositories.py
git commit -m "feat(repositories): snapshots, opportunities, bankroll, telemetry"
```

---

## Phase 3: OddsProvider interface + Kalshi lift

### Task 18: OddsProvider abstract base + OddsQuote

**Files:**
- Create: `scanner/src/providers/__init__.py`
- Create: `scanner/src/providers/base.py`
- Test: `scanner/tests/unit/test_provider_base.py`

- [ ] **Step 1: Create package**

```bash
cd scanner
mkdir -p src/providers
touch src/providers/__init__.py
```

- [ ] **Step 2: Write `src/providers/base.py`**

```python
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
```

- [ ] **Step 3: Write `tests/unit/test_provider_base.py`**

```python
"""Tests for odds conversion helpers."""

import math
from decimal import Decimal

from src.providers.base import american_to_decimal, decimal_to_implied


def test_american_plus_100_is_2():
    assert math.isclose(float(american_to_decimal(100)), 2.0)


def test_american_minus_110():
    # -110 → decimal 1.909...
    assert math.isclose(float(american_to_decimal(-110)), 1.9090909, abs_tol=1e-5)


def test_american_minus_200_is_1_5():
    assert math.isclose(float(american_to_decimal(-200)), 1.5)


def test_decimal_to_implied():
    assert math.isclose(float(decimal_to_implied(Decimal("2.0"))), 0.5)
    assert math.isclose(float(decimal_to_implied(Decimal("1.91"))), 0.5235602, abs_tol=1e-5)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_provider_base.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/providers/ scanner/tests/unit/test_provider_base.py
git commit -m "feat(providers): OddsProvider base + odds conversion helpers"
```

---

### Task 19: Lift Kalshi client from ryanfrigo

**Files:**
- Create: `scanner/src/kalshi/__init__.py`
- Create: `scanner/src/kalshi/client.py`
- Create: `scanner/src/kalshi/ws.py`
- Create: `scanner/src/kalshi/LICENSE_NOTICE.md`

- [ ] **Step 1: Create package**

```bash
cd scanner
mkdir -p src/kalshi
touch src/kalshi/__init__.py
```

- [ ] **Step 2: Read the source files we're lifting**

Run:
```bash
cat ../../_resources/sports-betting-refs/kalshi-ai-trading-bot/src/clients/kalshi_client.py | head -100
cat ../../_resources/sports-betting-refs/kalshi-ai-trading-bot/src/clients/kalshi_ws.py | head -50
```

(Engineer note: read these in full before lifting. They use specific dependencies and patterns — preserve them as-is.)

- [ ] **Step 3: Copy `kalshi_client.py` and `kalshi_ws.py`**

```bash
cp ../../_resources/sports-betting-refs/kalshi-ai-trading-bot/src/clients/kalshi_client.py src/kalshi/client.py
cp ../../_resources/sports-betting-refs/kalshi-ai-trading-bot/src/clients/kalshi_ws.py src/kalshi/ws.py
```

- [ ] **Step 4: Adjust imports if needed**

Open `src/kalshi/client.py` and `src/kalshi/ws.py`. If they import from `src.clients.*` or similar, update to imports that resolve within `src/kalshi/*`.

Run `uv run python -c "from src.kalshi.client import *"` — if import errors appear, fix them by:
- Removing imports of modules from ryanfrigo's project that we don't have (telemetry, OpenRouter, etc.)
- Stubbing or removing methods that depend on those (e.g., LLM scoring methods)
- Keeping only: authenticated client (REST), market read endpoints, order placement (we'll use sandbox in Plan 1)

- [ ] **Step 5: Add MIT attribution**

Write to `src/kalshi/LICENSE_NOTICE.md`:
```markdown
# Attribution

`client.py` and `ws.py` in this directory are derived from
https://github.com/ryanfrigo/kalshi-ai-trading-bot
licensed under the MIT License.

We use them as starting infrastructure for the authenticated Kalshi REST + WebSocket clients.
```

- [ ] **Step 6: Add `pyjwt` dependency for Kalshi RSA signing (if not already)**

Run:
```bash
uv run python -c "import jwt" 2>&1 | head -1
```

If ModuleNotFoundError:
```bash
uv add "pyjwt[crypto]>=2.9.0"
```

- [ ] **Step 7: Verify smoke import**

```bash
uv run python -c "from src.kalshi import client, ws; print('ok')"
```

Expected: `ok` (no exception).

- [ ] **Step 8: Commit**

```bash
cd ..
git add scanner/src/kalshi/ scanner/pyproject.toml scanner/uv.lock
git commit -m "feat(kalshi): lift authenticated client + WS from ryanfrigo (MIT)"
```

---

### Task 20: Kalshi adapter — wraps client, normalizes to OddsQuote

**Files:**
- Create: `scanner/src/kalshi/adapter.py`
- Test: `scanner/tests/unit/test_kalshi_adapter.py`

- [ ] **Step 1: Write failing test (against mocked client output)**

Write to `tests/unit/test_kalshi_adapter.py`:
```python
"""Tests for KalshiAdapter — transforms client responses into OddsQuotes.

The actual KalshiClient response shape varies; we test the adapter against
a representative shape we encode in this test. Adjust if the lifted client
returns differently.
"""

import math
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.kalshi.adapter import KalshiAdapter


@pytest.fixture
def fake_client():
    client = AsyncMock()
    # The .get_market() shape we assume below
    client.get_market.return_value = {
        "ticker": "KXNBAGAME-25NOV20-LAL-POINTS-LEBRON",
        "yes_bid": 48,
        "yes_ask": 50,
        "no_bid": 50,
        "no_ask": 52,
        "open_interest": 12_000,  # cents of contract value
        "liquidity": 8_000,
    }
    return client


async def test_adapter_returns_yes_and_no_quotes(fake_client):
    adapter = KalshiAdapter(client=fake_client)
    quotes = await adapter.fetch_odds(["KXNBAGAME-25NOV20-LAL-POINTS-LEBRON"])
    assert len(quotes) == 2  # one for YES, one for NO

    yes = next(q for q in quotes if q.side == "yes")
    no = next(q for q in quotes if q.side == "no")

    # We use the ask side as the "price you'd pay"
    # YES ask 50 → decimal odds 2.0 (pay 50¢ to win $1)
    assert math.isclose(float(yes.decimal_odds), 2.0, abs_tol=1e-4)
    # NO ask 52 → decimal odds = 100/52 ≈ 1.923
    assert math.isclose(float(no.decimal_odds), 100 / 52, abs_tol=1e-3)
    assert yes.book == "kalshi"


async def test_adapter_skips_missing_market(fake_client):
    fake_client.get_market.side_effect = Exception("404 not found")
    adapter = KalshiAdapter(client=fake_client)
    quotes = await adapter.fetch_odds(["MISSING-TICKER"])
    assert quotes == []
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd scanner
uv run pytest tests/unit/test_kalshi_adapter.py -v
```

- [ ] **Step 3: Implement `src/kalshi/adapter.py`**

```python
"""Adapter wrapping the Kalshi REST client into the OddsProvider shape.

NOTE: The exact KalshiClient method names depend on what was lifted from ryanfrigo.
We assume `await client.get_market(ticker)` returns a dict with at minimum:
    {"ticker": str, "yes_ask": int (cents), "no_ask": int (cents), ...}
If the lifted client uses different names, adjust this adapter accordingly.
"""

from decimal import Decimal
from typing import Any

from src.logger import log
from src.providers.base import OddsQuote


class KalshiAdapter:
    name = "kalshi"

    def __init__(self, *, client: Any):
        self._client = client

    async def fetch_odds(self, kalshi_tickers: list[str]) -> list[OddsQuote]:
        quotes: list[OddsQuote] = []
        for ticker in kalshi_tickers:
            try:
                m = await self._client.get_market(ticker)
            except Exception as e:
                log.warning("kalshi_market_fetch_failed", ticker=ticker, error=str(e))
                continue

            yes_ask = m.get("yes_ask")
            no_ask = m.get("no_ask")
            if yes_ask is None or no_ask is None:
                log.warning("kalshi_market_missing_prices", ticker=ticker)
                continue

            quotes.append(self._make_quote(ticker, "yes", yes_ask))
            quotes.append(self._make_quote(ticker, "no", no_ask))

        return quotes

    @staticmethod
    def _make_quote(ticker: str, side: str, ask_cents: int) -> OddsQuote:
        # Decimal odds at which you'd buy 1 contract at the ask:
        #   pay ask_cents/100 to win $1 → decimal = 100 / ask_cents
        decimal_odds = Decimal(100) / Decimal(ask_cents)
        implied = Decimal(ask_cents) / Decimal(100)
        return OddsQuote(
            market_kalshi_ticker=ticker,
            book="kalshi",
            side=side,
            decimal_odds=decimal_odds,
            implied_prob=implied,
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_kalshi_adapter.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/kalshi/adapter.py scanner/tests/unit/test_kalshi_adapter.py
git commit -m "feat(kalshi): adapter normalizing client responses to OddsQuotes"
```

---

## Phase 4: Pinnacle scraper (CloakBrowser + IPRoyal)

### Task 21: CloakBrowser + Playwright setup

**Files:** none (verification only)

- [ ] **Step 1: Install Playwright browsers**

Run:
```bash
cd scanner
uv run playwright install chromium
```

Expected: Chromium downloads and installs.

- [ ] **Step 2: Verify CloakBrowser availability**

CloakBrowser is a Chromium fork — read its installation docs:
```bash
cat ../../_resources/sports-betting-refs/CloakBrowser/README.md | head -100
```

Look for the macOS install instructions. Typical pattern: download a prebuilt binary, point Playwright at it.

- [ ] **Step 3: Download the macOS CloakBrowser binary**

Follow the repo's instructions (typically `./scripts/download-binary.sh mac` or similar). Place at a known path, e.g., `~/.cloakbrowser/chromium`.

- [ ] **Step 4: Smoke test CloakBrowser via Playwright**

Run this one-liner to verify:
```bash
uv run python -c "
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/Users/luke/.cloakbrowser/chromium',
            headless=False,
        )
        page = await browser.new_page()
        await page.goto('https://bot.sannysoft.com/')
        await page.screenshot(path='/tmp/cloakbrowser-smoke.png')
        await browser.close()
        print('OK')

asyncio.run(main())
"
```

Open `/tmp/cloakbrowser-smoke.png` and verify the bot-detection checks all pass (green/expected values, not "headless detected").

If detection fails: the `executable_path` may be wrong, or the binary download was incomplete. Don't proceed — this proves the scraping pipeline works at all.

- [ ] **Step 5: No commit (verification only)**

---

### Task 22: Pinnacle scraper

**Files:**
- Create: `scanner/src/providers/pinnacle.py`
- Test: `scanner/tests/unit/test_pinnacle_parser.py`
- Test: `scanner/tests/e2e/test_pinnacle_smoke.py`

- [ ] **Step 1: Write parser unit test against fixture HTML**

Pinnacle's NBA player-prop page is a JSON-driven SPA — the page calls an internal API. We scrape by:
- Loading the page in CloakBrowser (via Playwright)
- Intercepting the XHR that returns markets JSON
- Parsing player-prop entries

Write to `tests/unit/test_pinnacle_parser.py`:
```python
"""Tests for the Pinnacle markets JSON parser."""

from decimal import Decimal

from src.providers.pinnacle import parse_pinnacle_player_props


SAMPLE_PINNACLE_PAYLOAD = {
    "matchups": [
        {
            "id": 1234,
            "starts": "2025-11-20T19:30:00Z",
            "participants": [
                {"name": "Los Angeles Lakers"},
                {"name": "Boston Celtics"},
            ],
            "special": {
                "category": "player_props",
                "description": "LeBron James (Total Points)",
            },
            "markets": [
                {
                    "type": "total",
                    "points": 24.5,
                    "prices": [
                        {"designation": "over", "price": -118},
                        {"designation": "under", "price": -102},
                    ],
                }
            ],
        }
    ]
}


def test_parses_lebron_points_over_under():
    quotes = parse_pinnacle_player_props(SAMPLE_PINNACLE_PAYLOAD)
    assert len(quotes) == 2
    over = next(q for q in quotes if q.side == "over")
    under = next(q for q in quotes if q.side == "under")
    assert over.book == "pinnacle"
    # -118 → decimal 1 + 100/118 = 1.847
    assert abs(float(over.decimal_odds) - (1 + 100 / 118)) < 1e-4
    # -102 → decimal 1 + 100/102 = 1.980
    assert abs(float(under.decimal_odds) - (1 + 100 / 102)) < 1e-4


def test_skips_non_player_props():
    payload = {
        "matchups": [
            {
                "id": 5555,
                "starts": "2025-11-20T19:30:00Z",
                "participants": [{"name": "LAL"}, {"name": "BOS"}],
                # No 'special' or 'special.category' != 'player_props'
                "markets": [{"type": "moneyline"}],
            }
        ]
    }
    assert parse_pinnacle_player_props(payload) == []
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd scanner
uv run pytest tests/unit/test_pinnacle_parser.py -v
```

- [ ] **Step 3: Implement parser + scraper in `src/providers/pinnacle.py`**

```python
"""Pinnacle scraper.

Uses CloakBrowser via Playwright, routed through IPRoyal residential proxies,
to load Pinnacle's NBA page and intercept the markets JSON XHR.

Public surface:
    PinnacleScraper.fetch_odds(kalshi_tickers) -> list[OddsQuote]
        Note: Pinnacle doesn't know about Kalshi tickers. We map by matching
        the player_name + stat_type + line embedded in the Kalshi ticker
        against parsed Pinnacle player-prop entries.
"""

import asyncio
import json
import re
from decimal import Decimal
from typing import Any

from playwright.async_api import async_playwright

from src.config import settings
from src.logger import log
from src.providers.base import OddsProvider, OddsQuote, american_to_decimal, decimal_to_implied

CLOAK_EXECUTABLE = "/Users/luke/.cloakbrowser/chromium"  # adjust per Task 21
PINNACLE_NBA_URL = "https://www.pinnacle.com/en/basketball/nba/matchups"
MARKETS_XHR_PATTERN = re.compile(r"/api/.*/sports/.*/markets")


def parse_pinnacle_player_props(payload: dict) -> list[OddsQuote]:
    """Parse a Pinnacle markets JSON payload into OddsQuotes.

    Returns ONLY player-prop quotes. Game lines (h2h/spread/total) are skipped
    in Plan 1 — Plan 2 will extend.

    The Pinnacle ticker mapping to Kalshi happens at a higher layer; here we
    just emit the raw quote with a synthetic `market_kalshi_ticker` derived
    from the player name + stat + line so the pipeline can match.
    """
    quotes: list[OddsQuote] = []
    for m in payload.get("matchups", []):
        special = m.get("special") or {}
        if special.get("category") != "player_props":
            continue

        description = special.get("description", "")  # e.g. "LeBron James (Total Points)"
        player, stat = _parse_description(description)
        if not player:
            continue

        for market in m.get("markets", []):
            line = market.get("points")
            if line is None:
                continue
            synthetic = _synthesize_kalshi_ticker(player, stat, float(line))
            for price in market.get("prices", []):
                side = price.get("designation")
                american = price.get("price")
                if side not in ("over", "under") or american is None:
                    continue
                decimal_odds = american_to_decimal(int(american))
                quotes.append(
                    OddsQuote(
                        market_kalshi_ticker=synthetic,
                        book="pinnacle",
                        side=side,
                        decimal_odds=decimal_odds,
                        implied_prob=decimal_to_implied(decimal_odds),
                    )
                )
    return quotes


def _parse_description(desc: str) -> tuple[str | None, str | None]:
    # "LeBron James (Total Points)" → ("LeBron James", "points")
    match = re.match(r"^(.+?)\s*\(Total\s+(\w+)\)$", desc, re.IGNORECASE)
    if not match:
        return None, None
    name = match.group(1).strip()
    stat = match.group(2).lower()
    return name, stat


def _synthesize_kalshi_ticker(player: str, stat: str | None, line: float) -> str:
    """Reproducibly construct a synthetic ticker the pipeline can match against
    actual Kalshi markets at join time."""
    slug = re.sub(r"[^A-Za-z]+", "", player).upper()
    return f"SYN-NBA-{slug}-{stat.upper() if stat else 'UNK'}-{line}"


class PinnacleScraper(OddsProvider):
    name = "pinnacle"

    async def fetch_odds(self, kalshi_tickers: list[str]) -> list[OddsQuote]:
        """Load Pinnacle NBA, capture markets XHR, parse. Ignores tickers
        parameter in Plan 1 — returns ALL player props found and pipeline
        joins them by synthetic ticker."""
        del kalshi_tickers  # unused in Plan 1

        captured: list[dict] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path=CLOAK_EXECUTABLE,
                headless=True,
                proxy=({"server": settings.iproyal_proxy_url} if settings.iproyal_proxy_url else None),
            )
            context = await browser.new_context()
            page = await context.new_page()

            async def on_response(resp):
                if MARKETS_XHR_PATTERN.search(resp.url):
                    try:
                        data = await resp.json()
                        captured.append(data)
                    except Exception:
                        pass

            page.on("response", on_response)

            try:
                await page.goto(PINNACLE_NBA_URL, timeout=30_000, wait_until="networkidle")
            except Exception as e:
                log.warning("pinnacle_navigation_failed", error=str(e))

            await browser.close()

        # Aggregate parsed quotes from all captured XHR payloads
        all_quotes: list[OddsQuote] = []
        for payload in captured:
            all_quotes.extend(parse_pinnacle_player_props(payload))

        log.info("pinnacle_fetched", quote_count=len(all_quotes))
        return all_quotes
```

- [ ] **Step 4: Run parser tests**

```bash
uv run pytest tests/unit/test_pinnacle_parser.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Write e2e smoke test**

Write to `tests/e2e/test_pinnacle_smoke.py`:
```python
"""End-to-end smoke test — hits real Pinnacle.com.

Skipped by default. Run explicitly with: pytest -m e2e
"""

import pytest

from src.providers.pinnacle import PinnacleScraper

pytestmark = pytest.mark.e2e


async def test_pinnacle_returns_some_quotes_during_nba_season():
    scraper = PinnacleScraper()
    quotes = await scraper.fetch_odds([])
    # During NBA season, expect at least a few player props.
    # During offseason, this may legitimately return 0. Warn but don't fail.
    if not quotes:
        pytest.skip("no quotes returned — Pinnacle may be empty (offseason)")
    assert all(q.book == "pinnacle" for q in quotes)
    assert all(q.side in ("over", "under") for q in quotes)
```

- [ ] **Step 6: Run smoke test manually**

```bash
uv run pytest tests/e2e/test_pinnacle_smoke.py -v -m e2e
```

(May fail if NBA offseason or scraper layout changed. If it fails with a `TimeoutError` or empty captured list, the page selectors / XHR pattern need adjustment. Inspect with `headless=False` temporarily.)

- [ ] **Step 7: Commit**

```bash
cd ..
git add scanner/src/providers/pinnacle.py scanner/tests/unit/test_pinnacle_parser.py scanner/tests/e2e/test_pinnacle_smoke.py
git commit -m "feat(providers): Pinnacle scraper (CloakBrowser + IPRoyal)"
```

---

## Phase 5: Pipeline orchestrator

### Task 23: Pipeline tick — single end-to-end function

**Files:**
- Create: `scanner/src/pipeline.py`
- Test: `scanner/tests/integration/test_pipeline_tick.py`

- [ ] **Step 1: Write `src/pipeline.py`**

```python
"""Single-tick orchestrator.

Calls all providers in parallel, devigs each sharp book's two-sided market,
computes Brier-weighted consensus, blends with projection (None in Plan 1),
computes Kalshi EV after fees, sizes Kelly stake, writes opportunity.
"""

import asyncio
import time
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from src.config import settings
from src.kalshi.adapter import KalshiAdapter
from src.logger import log
from src.math.blend import blended_fair_prob
from src.math.consensus import COLD_START_WEIGHTS, brier_weighted_consensus
from src.math.devig import devig
from src.math.ev import kalshi_ev
from src.math.kelly import kelly_stake_cents
from src.math.projection_weight import current_projection_weight
from src.providers.base import OddsProvider, OddsQuote
from src.repositories.bankroll import current_bankroll_cents
from src.repositories.markets import fetch_active_markets
from src.repositories.opportunities import insert_opportunity
from src.repositories.snapshots import OddsSnapshot, bulk_insert_snapshots
from src.repositories.telemetry import record_event


async def run_scan_tick(
    *,
    pool,
    sharp_providers: list[OddsProvider],
    kalshi: KalshiAdapter,
    days_since_launch: int = 0,
) -> int:
    """Execute one full scan tick.

    Returns number of opportunities written.
    """
    tick_id = uuid.uuid4().hex
    tick_start = time.monotonic()
    log.info("tick_start", tick_id=tick_id)

    markets = await fetch_active_markets(pool)
    if not markets:
        log.info("tick_no_markets", tick_id=tick_id)
        await record_event(pool, tick_id=tick_id, source="pipeline", event_type="tick_complete")
        return 0

    kalshi_tickers = [m.kalshi_ticker for m in markets]

    # Fan out all providers + Kalshi in parallel
    tasks = [
        _provider_call(pool, tick_id, p, kalshi_tickers) for p in sharp_providers
    ] + [_provider_call(pool, tick_id, kalshi, kalshi_tickers)]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # results is list[list[OddsQuote]] — flatten
    all_quotes: list[OddsQuote] = [q for sub in results for q in sub]

    # Persist raw snapshots immediately
    market_by_ticker = {m.kalshi_ticker: m for m in markets}
    snapshots: list[OddsSnapshot] = []
    for q in all_quotes:
        m = market_by_ticker.get(q.market_kalshi_ticker)
        if m is None:
            continue
        snapshots.append(
            OddsSnapshot(
                market_id=m.id,
                book=q.book,
                side=q.side,
                decimal_odds=q.decimal_odds,
                implied_prob=q.implied_prob,
            )
        )
    if snapshots:
        await bulk_insert_snapshots(pool, snapshots)

    # Group quotes by market for EV computation
    quotes_by_market: dict[str, list[OddsQuote]] = defaultdict(list)
    for q in all_quotes:
        quotes_by_market[q.market_kalshi_ticker].append(q)

    bankroll = await current_bankroll_cents(pool)
    proj_weight = current_projection_weight(days_since_launch)

    opps_written = 0
    for ticker, quotes in quotes_by_market.items():
        market = market_by_ticker.get(ticker)
        if market is None:
            continue

        ev_result = _compute_market_ev(quotes, proj_weight)
        if ev_result is None:
            continue

        ev_pct, side, kalshi_decimal_odds, consensus_prob, blended_prob, num_books = ev_result
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
            projection_fair_prob=None,  # Plan 2 fills this
            blended_fair_prob=Decimal(str(round(blended_prob, 6))),
            ev_pct=Decimal(str(round(ev_pct, 4))),
            kelly_fraction=kelly_fraction,
            num_sharp_books=num_books,
            suspicious=suspicious,
        )
        opps_written += 1

    latency_ms = int((time.monotonic() - tick_start) * 1000)
    await record_event(
        pool, tick_id=tick_id, source="pipeline",
        event_type="tick_complete", latency_ms=latency_ms,
        status_detail=f"opps={opps_written}",
    )
    log.info("tick_complete", tick_id=tick_id, opps_written=opps_written, latency_ms=latency_ms)
    return opps_written


async def _provider_call(
    pool, tick_id: str, provider, kalshi_tickers: list[str]
) -> list[OddsQuote]:
    start = time.monotonic()
    try:
        quotes = await provider.fetch_odds(kalshi_tickers)
        latency_ms = int((time.monotonic() - start) * 1000)
        await record_event(
            pool, tick_id=tick_id, source=provider.name,
            event_type="fetch_success", latency_ms=latency_ms,
        )
        return quotes
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        await record_event(
            pool, tick_id=tick_id, source=provider.name,
            event_type="fetch_failure", latency_ms=latency_ms,
            status_detail=str(e)[:500],
        )
        log.warning("provider_fetch_failed", source=provider.name, error=str(e))
        return []


def _compute_market_ev(
    quotes: list[OddsQuote], projection_weight: float
) -> tuple[float, str, Decimal, float, float, int] | None:
    """For one market's quotes, return (ev_pct, kalshi_side, kalshi_decimal_odds,
    consensus_prob, blended_prob, num_sharp_books) for the side with positive edge,
    or None if no edge / not enough data.
    """
    # Group sharp quotes by book → {book: {over: q, under: q}}
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
        return None  # Kalshi not in market — can't bet

    # Devig each sharp book that has both sides
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
        projection_prob=None,  # Plan 1
        projection_weight=projection_weight,
    )
    blended_under = 1.0 - blended_over

    # For Kalshi YES we treat YES as "over"; NO as "under"
    yes_ev = kalshi_ev(
        fair_prob_yes=blended_over,
        yes_price_cents=int(round(float(kalshi_yes.implied_prob) * 100)),
    )
    no_ev = kalshi_ev(
        fair_prob_yes=blended_under,  # treating NO ask as a YES on the under side
        yes_price_cents=int(round(float(kalshi_no.implied_prob) * 100)),
    )

    if yes_ev >= no_ev:
        return yes_ev, "yes", kalshi_yes.decimal_odds, consensus_over, blended_over, num_books
    return no_ev, "no", kalshi_no.decimal_odds, consensus_under, blended_under, num_books
```

- [ ] **Step 2: Write integration test with mocked providers**

Write to `tests/integration/test_pipeline_tick.py`:
```python
"""End-to-end pipeline tick test against Postgres with mocked providers."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.kalshi.adapter import KalshiAdapter
from src.pipeline import run_scan_tick
from src.providers.base import OddsQuote
from src.repositories.markets import upsert_market

pytestmark = pytest.mark.integration


class FakeProvider:
    def __init__(self, name: str, quotes: list[OddsQuote]):
        self.name = name
        self._quotes = quotes

    async def fetch_odds(self, _: list[str]) -> list[OddsQuote]:
        return self._quotes


async def test_full_tick_writes_opportunity_when_positive_ev(pool):
    # Seed a market
    await upsert_market(
        pool,
        sport="NBA",
        kalshi_ticker="SYN-NBA-LEBRONJAMES-POINTS-24.5",
        market_type="player_prop",
        player_name="LeBron James",
        stat_type="points",
        line=24.5,
        game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    # Seed bankroll
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )

    # Build quotes: sharp consensus says LeBron over 24.5 @ ~55% fair
    # Kalshi YES price = 45¢ → strong +EV on YES (over)
    sharp_quotes = [
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "pinnacle", "over",
                  Decimal("1.85"), Decimal("0.541")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "pinnacle", "under",
                  Decimal("1.95"), Decimal("0.513")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "novig", "over",
                  Decimal("1.88"), Decimal("0.532")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "novig", "under",
                  Decimal("1.92"), Decimal("0.521")),
    ]
    kalshi_quotes = [
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "kalshi", "yes",
                  Decimal(100) / Decimal(45), Decimal("0.45")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "kalshi", "no",
                  Decimal(100) / Decimal(55), Decimal("0.55")),
    ]

    sharp = FakeProvider("pinnacle", [q for q in sharp_quotes if q.book == "pinnacle"])
    sharp2 = FakeProvider("novig", [q for q in sharp_quotes if q.book == "novig"])

    fake_kalshi_client = AsyncMock()
    adapter = KalshiAdapter(client=fake_kalshi_client)
    # Inject the kalshi_quotes directly by mocking the adapter's fetch
    adapter.fetch_odds = AsyncMock(return_value=kalshi_quotes)

    n = await run_scan_tick(
        pool=pool, sharp_providers=[sharp, sharp2], kalshi=adapter,
        days_since_launch=0,
    )
    assert n >= 1

    row = await pool.fetchrow("SELECT * FROM opportunities ORDER BY id DESC LIMIT 1")
    assert row["kalshi_side"] == "yes"
    assert float(row["ev_pct"]) > 0.01
    assert row["num_sharp_books"] == 2


async def test_tick_skips_market_with_only_one_sharp_book(pool):
    await upsert_market(
        pool, sport="NBA",
        kalshi_ticker="SYN-NBA-XYZ-POINTS-10.5",
        market_type="player_prop",
        game_id="X-Y",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )

    sharp = FakeProvider("pinnacle", [
        OddsQuote("SYN-NBA-XYZ-POINTS-10.5", "pinnacle", "over",
                  Decimal("1.85"), Decimal("0.541")),
        OddsQuote("SYN-NBA-XYZ-POINTS-10.5", "pinnacle", "under",
                  Decimal("1.95"), Decimal("0.513")),
    ])
    adapter = KalshiAdapter(client=AsyncMock())
    adapter.fetch_odds = AsyncMock(return_value=[
        OddsQuote("SYN-NBA-XYZ-POINTS-10.5", "kalshi", "yes",
                  Decimal(100) / Decimal(45), Decimal("0.45")),
        OddsQuote("SYN-NBA-XYZ-POINTS-10.5", "kalshi", "no",
                  Decimal(100) / Decimal(55), Decimal("0.55")),
    ])

    n = await run_scan_tick(
        pool=pool, sharp_providers=[sharp], kalshi=adapter, days_since_launch=0,
    )
    assert n == 0
```

- [ ] **Step 3: Run integration tests**

```bash
cd scanner
uv run pytest tests/integration/test_pipeline_tick.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
cd ..
git add scanner/src/pipeline.py scanner/tests/integration/test_pipeline_tick.py
git commit -m "feat(scanner): pipeline tick orchestrator with EV + Kelly"
```

---

### Task 24: Scheduler — 30s loop

**Files:**
- Create: `scanner/src/scheduler.py`

- [ ] **Step 1: Write `src/scheduler.py`**

```python
"""30-second scheduler loop with graceful shutdown.

Run as a module: `python -m src.scheduler`
"""

import asyncio
import signal
from datetime import datetime, timezone

from src.config import settings
from src.db import close_pool, get_pool
from src.kalshi.adapter import KalshiAdapter
from src.kalshi.client import KalshiClient  # adjust import to match lifted client
from src.logger import configure_logging, log
from src.pipeline import run_scan_tick
from src.providers.base import OddsProvider
from src.providers.pinnacle import PinnacleScraper

# Launch date used for projection_weight ramp
LAUNCH_DATE = datetime(2026, 5, 29, tzinfo=timezone.utc)


def _days_since_launch() -> int:
    return max(0, (datetime.now(timezone.utc) - LAUNCH_DATE).days)


async def main_loop() -> None:
    configure_logging(level=settings.log_level)
    pool = await get_pool()

    # Sharp providers (Plan 1: just Pinnacle)
    sharp: list[OddsProvider] = [PinnacleScraper()]

    # Kalshi — adjust this constructor to match what was lifted
    kclient = KalshiClient(
        key_id=settings.kalshi_key_id,
        private_key_pem=settings.kalshi_private_key,
        api_base=settings.kalshi_api_base,
    )
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
```

- [ ] **Step 2: Adjust `KalshiClient` import to match what was actually lifted**

Open the lifted `src/kalshi/client.py`. If the class is named differently (e.g. `Client`, `KalshiAPIClient`), update the import + constructor call in `scheduler.py`. If the constructor takes different args, adjust to match.

- [ ] **Step 3: Smoke run the scheduler for a few seconds**

```bash
cd scanner
uv run python -m src.scheduler &
SCHEDULER_PID=$!
sleep 35
kill $SCHEDULER_PID 2>/dev/null
wait 2>/dev/null
```

Expected: At least one `tick_start` and `tick_complete` log line in JSON form. If Pinnacle / Kalshi credentials aren't set, expect `provider_fetch_failed` logs but no crash.

- [ ] **Step 4: Verify telemetry recorded a tick**

```bash
docker compose exec postgres psql -U kalshi -d kalshi_ev -c \
  "SELECT source, event_type, COUNT(*) FROM scan_telemetry GROUP BY source, event_type ORDER BY source;"
```

Expected: rows showing fetch attempts.

- [ ] **Step 5: Commit**

```bash
cd ..
git add scanner/src/scheduler.py
git commit -m "feat(scanner): 30s scheduler loop with graceful shutdown"
```

---

## Phase 6: Next.js Dashboard

### Task 25: Initialize Next.js project

**Files:**
- Create: `dashboard/` (Next.js scaffold)

- [ ] **Step 1: Create with create-next-app**

```bash
cd kalshi-ev-scanner
pnpm create next-app@latest dashboard --typescript --tailwind --app --src-dir --eslint --no-import-alias
```

Accept defaults for everything not flagged. When prompted "Use Turbopack?" — choose No (Vercel deploys with Webpack by default, we match locally).

- [ ] **Step 2: Install runtime dependencies**

```bash
cd dashboard
pnpm add drizzle-orm postgres @tanstack/react-query
pnpm add -D drizzle-kit @types/node
```

- [ ] **Step 3: Install shadcn/ui**

```bash
pnpm dlx shadcn@latest init -d
```

Accept defaults: Slate base color, src dir confirmed.

- [ ] **Step 4: Add baseline shadcn components we'll use**

```bash
pnpm dlx shadcn@latest add badge button card table separator
```

- [ ] **Step 5: Smoke test dev server**

```bash
pnpm dev
```

Open http://localhost:3000. Should show default Next welcome page. Stop with Ctrl-C.

- [ ] **Step 6: Commit**

```bash
cd ..
git add dashboard/
git commit -m "feat(dashboard): initialize Next.js + Tailwind + shadcn"
```

---

### Task 26: Drizzle ORM setup mirroring scanner schema

**Files:**
- Create: `dashboard/drizzle.config.ts`
- Create: `dashboard/src/lib/db.ts`
- Create: `dashboard/src/lib/schema.ts`
- Create: `dashboard/.env.local`

- [ ] **Step 1: Write `.env.local`**

```bash
DATABASE_URL=postgresql://kalshi:kalshi@localhost:5432/kalshi_ev
```

(Add `.env.local` to `dashboard/.gitignore` — Next's defaults already do this.)

- [ ] **Step 2: Write `drizzle.config.ts`**

```typescript
import type { Config } from "drizzle-kit";

export default {
  schema: "./src/lib/schema.ts",
  dialect: "postgresql",
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "postgresql://kalshi:kalshi@localhost:5432/kalshi_ev",
  },
} satisfies Config;
```

- [ ] **Step 3: Write `src/lib/schema.ts`**

```typescript
/**
 * Drizzle schema mirroring the Alembic-managed Postgres schema.
 *
 * The Python scanner owns migrations. This file is hand-maintained to match
 * what Alembic produced. If migrations change, update this file in lockstep.
 *
 * Reference: scanner/alembic/versions/001_initial_schema.py
 */

import {
  bigint,
  boolean,
  index,
  integer,
  numeric,
  pgTable,
  smallint,
  text,
  timestamp,
  uniqueIndex,
} from "drizzle-orm/pg-core";

export const markets = pgTable("markets", {
  id: bigint("id", { mode: "number" }).primaryKey(),
  userId: bigint("user_id", { mode: "number" }).notNull().default(1),
  sport: text("sport").notNull(),
  kalshiTicker: text("kalshi_ticker").notNull().unique(),
  marketType: text("market_type").notNull(),
  playerName: text("player_name"),
  statType: text("stat_type"),
  line: numeric("line", { precision: 6, scale: 2 }),
  gameId: text("game_id").notNull(),
  gameStartsAt: timestamp("game_starts_at", { withTimezone: true }).notNull(),
  isActive: boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const opportunities = pgTable("opportunities", {
  id: bigint("id", { mode: "number" }).primaryKey(),
  userId: bigint("user_id", { mode: "number" }).notNull().default(1),
  marketId: bigint("market_id", { mode: "number" }).notNull(),
  kalshiSide: text("kalshi_side").notNull(),
  kalshiDecimalOdds: numeric("kalshi_decimal_odds", { precision: 10, scale: 4 }).notNull(),
  consensusFairProb: numeric("consensus_fair_prob", { precision: 7, scale: 6 }).notNull(),
  projectionFairProb: numeric("projection_fair_prob", { precision: 7, scale: 6 }),
  blendedFairProb: numeric("blended_fair_prob", { precision: 7, scale: 6 }).notNull(),
  evPct: numeric("ev_pct", { precision: 6, scale: 4 }).notNull(),
  kellyFraction: numeric("kelly_fraction", { precision: 6, scale: 4 }),
  numSharpBooks: smallint("num_sharp_books").notNull(),
  suspicious: boolean("suspicious").notNull().default(false),
  scanTickAt: timestamp("scan_tick_at", { withTimezone: true }).notNull().defaultNow(),
});

export const scanTelemetry = pgTable("scan_telemetry", {
  id: bigint("id", { mode: "number" }).primaryKey(),
  tickId: text("tick_id").notNull(),
  source: text("source").notNull(),
  eventType: text("event_type").notNull(),
  latencyMs: integer("latency_ms"),
  statusDetail: text("status_detail"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});
```

- [ ] **Step 4: Write `src/lib/db.ts`**

```typescript
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "./schema";

const url = process.env.DATABASE_URL;
if (!url) {
  throw new Error("DATABASE_URL is not set");
}

// One global client for the Next runtime; postgres-js handles pooling.
const client = postgres(url, { max: 5 });
export const db = drizzle(client, { schema });
```

- [ ] **Step 5: Verify Drizzle compiles**

```bash
cd dashboard
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd ..
git add dashboard/drizzle.config.ts dashboard/src/lib/
git commit -m "feat(dashboard): drizzle setup mirroring scanner schema"
```

---

### Task 27: API routes — `/api/opportunities`, `/api/opportunity/[id]`, `/api/health`

**Files:**
- Create: `dashboard/src/lib/queries.ts`
- Create: `dashboard/src/app/api/opportunities/route.ts`
- Create: `dashboard/src/app/api/opportunity/[id]/route.ts`
- Create: `dashboard/src/app/api/health/route.ts`

- [ ] **Step 1: Write `src/lib/queries.ts`**

```typescript
import { sql } from "drizzle-orm";
import { db } from "./db";

export type OpportunityRow = {
  id: number;
  marketId: number;
  kalshiTicker: string;
  sport: string;
  playerName: string | null;
  statType: string | null;
  line: number | null;
  gameStartsAt: string;
  kalshiSide: string;
  kalshiDecimalOdds: number;
  consensusFairProb: number;
  projectionFairProb: number | null;
  blendedFairProb: number;
  evPct: number;
  kellyFraction: number | null;
  numSharpBooks: number;
  suspicious: boolean;
  scanTickAt: string;
};

/**
 * Latest opportunity per market, sorted by EV descending.
 */
export async function getLatestOpportunities(minEv = 0.01, limit = 100): Promise<OpportunityRow[]> {
  const rows = await db.execute(sql`
    SELECT DISTINCT ON (o.market_id)
      o.id, o.market_id, m.kalshi_ticker, m.sport, m.player_name, m.stat_type, m.line,
      m.game_starts_at, o.kalshi_side, o.kalshi_decimal_odds, o.consensus_fair_prob,
      o.projection_fair_prob, o.blended_fair_prob, o.ev_pct, o.kelly_fraction,
      o.num_sharp_books, o.suspicious, o.scan_tick_at
    FROM opportunities o
    JOIN markets m ON m.id = o.market_id
    WHERE o.ev_pct >= ${minEv} AND m.is_active = true
    ORDER BY o.market_id, o.scan_tick_at DESC
    LIMIT ${limit * 4}
  `);

  const opps: OpportunityRow[] = rows.map((r: any) => ({
    id: Number(r.id),
    marketId: Number(r.market_id),
    kalshiTicker: r.kalshi_ticker,
    sport: r.sport,
    playerName: r.player_name,
    statType: r.stat_type,
    line: r.line !== null ? Number(r.line) : null,
    gameStartsAt: r.game_starts_at,
    kalshiSide: r.kalshi_side,
    kalshiDecimalOdds: Number(r.kalshi_decimal_odds),
    consensusFairProb: Number(r.consensus_fair_prob),
    projectionFairProb: r.projection_fair_prob !== null ? Number(r.projection_fair_prob) : null,
    blendedFairProb: Number(r.blended_fair_prob),
    evPct: Number(r.ev_pct),
    kellyFraction: r.kelly_fraction !== null ? Number(r.kelly_fraction) : null,
    numSharpBooks: Number(r.num_sharp_books),
    suspicious: r.suspicious,
    scanTickAt: r.scan_tick_at,
  }));

  return opps.sort((a, b) => b.evPct - a.evPct).slice(0, limit);
}

export async function getOpportunityById(id: number): Promise<OpportunityRow | null> {
  const rows = await db.execute(sql`
    SELECT o.id, o.market_id, m.kalshi_ticker, m.sport, m.player_name, m.stat_type, m.line,
      m.game_starts_at, o.kalshi_side, o.kalshi_decimal_odds, o.consensus_fair_prob,
      o.projection_fair_prob, o.blended_fair_prob, o.ev_pct, o.kelly_fraction,
      o.num_sharp_books, o.suspicious, o.scan_tick_at
    FROM opportunities o
    JOIN markets m ON m.id = o.market_id
    WHERE o.id = ${id}
    LIMIT 1
  `);
  if (rows.length === 0) return null;
  const r: any = rows[0];
  return {
    id: Number(r.id),
    marketId: Number(r.market_id),
    kalshiTicker: r.kalshi_ticker,
    sport: r.sport,
    playerName: r.player_name,
    statType: r.stat_type,
    line: r.line !== null ? Number(r.line) : null,
    gameStartsAt: r.game_starts_at,
    kalshiSide: r.kalshi_side,
    kalshiDecimalOdds: Number(r.kalshi_decimal_odds),
    consensusFairProb: Number(r.consensus_fair_prob),
    projectionFairProb: r.projection_fair_prob !== null ? Number(r.projection_fair_prob) : null,
    blendedFairProb: Number(r.blended_fair_prob),
    evPct: Number(r.ev_pct),
    kellyFraction: r.kelly_fraction !== null ? Number(r.kelly_fraction) : null,
    numSharpBooks: Number(r.num_sharp_books),
    suspicious: r.suspicious,
    scanTickAt: r.scan_tick_at,
  };
}

export type HealthRow = { source: string; lastFetchAt: string | null };

export async function getHealth(): Promise<HealthRow[]> {
  const rows = await db.execute(sql`
    SELECT DISTINCT ON (source) source, created_at
    FROM scan_telemetry
    WHERE event_type = 'fetch_success'
    ORDER BY source, created_at DESC
  `);
  return rows.map((r: any) => ({ source: r.source, lastFetchAt: r.created_at }));
}
```

- [ ] **Step 2: Write `src/app/api/opportunities/route.ts`**

```typescript
import { NextResponse } from "next/server";
import { getLatestOpportunities } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const minEv = Number(url.searchParams.get("minEv") ?? "0.01");
  const limit = Number(url.searchParams.get("limit") ?? "100");
  const opps = await getLatestOpportunities(minEv, limit);
  return NextResponse.json({ opportunities: opps, generatedAt: new Date().toISOString() });
}
```

- [ ] **Step 3: Write `src/app/api/opportunity/[id]/route.ts`**

```typescript
import { NextResponse } from "next/server";
import { getOpportunityById } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const numericId = Number(id);
  if (!Number.isFinite(numericId)) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  const opp = await getOpportunityById(numericId);
  if (!opp) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json({ opportunity: opp });
}
```

- [ ] **Step 4: Write `src/app/api/health/route.ts`**

```typescript
import { NextResponse } from "next/server";
import { getHealth } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const sources = await getHealth();
  return NextResponse.json({ sources, checkedAt: new Date().toISOString() });
}
```

- [ ] **Step 5: Verify routes compile + respond**

```bash
cd dashboard
pnpm dev
```

In another terminal:
```bash
curl -s http://localhost:3000/api/opportunities | head -20
curl -s http://localhost:3000/api/health
```

Expected: JSON responses, possibly empty `opportunities` array. Stop dev server (Ctrl-C).

- [ ] **Step 6: Commit**

```bash
cd ..
git add dashboard/src/lib/queries.ts dashboard/src/app/api/
git commit -m "feat(dashboard): API routes for opportunities + health"
```

---

### Task 28: TanStack Query provider + format helpers

**Files:**
- Create: `dashboard/src/lib/format.ts`
- Create: `dashboard/src/app/providers.tsx`
- Modify: `dashboard/src/app/layout.tsx`

- [ ] **Step 1: Write `src/lib/format.ts`**

```typescript
export function formatEvPct(ev: number): string {
  const sign = ev >= 0 ? "+" : "";
  return `${sign}${(ev * 100).toFixed(2)}%`;
}

export function formatDecimalAsAmerican(decimal: number): string {
  if (decimal >= 2.0) {
    return `+${Math.round((decimal - 1) * 100)}`;
  }
  return `-${Math.round(100 / (decimal - 1))}`;
}

export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function formatStartsAt(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function evColor(ev: number): string {
  if (ev >= 0.03) return "text-emerald-400";
  if (ev >= 0.01) return "text-amber-400";
  return "text-zinc-400";
}
```

- [ ] **Step 2: Write `src/app/providers.tsx`**

```typescript
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({
      defaultOptions: {
        queries: {
          refetchInterval: 5000,
          refetchOnWindowFocus: true,
        },
      },
    }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

- [ ] **Step 3: Update `src/app/layout.tsx`**

Replace contents with:
```typescript
import type { Metadata } from "next";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kalshi EV Scanner",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-zinc-950 text-zinc-100 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

- [ ] **Step 4: Verify compiles**

```bash
cd dashboard
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
cd ..
git add dashboard/src/app/providers.tsx dashboard/src/app/layout.tsx dashboard/src/lib/format.ts
git commit -m "feat(dashboard): TanStack Query provider + format helpers"
```

---

### Task 29: Main opportunity table page (`/`)

**Files:**
- Create: `dashboard/src/components/OpportunityTable.tsx`
- Create: `dashboard/src/components/EvBadge.tsx`
- Modify: `dashboard/src/app/page.tsx`

- [ ] **Step 1: Write `src/components/EvBadge.tsx`**

```typescript
import { evColor, formatEvPct } from "@/lib/format";

export function EvBadge({ ev }: { ev: number }) {
  return (
    <span className={`font-mono tabular-nums ${evColor(ev)}`}>
      {formatEvPct(ev)}
    </span>
  );
}
```

- [ ] **Step 2: Write `src/components/OpportunityTable.tsx`**

```typescript
"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { EvBadge } from "./EvBadge";
import type { OpportunityRow } from "@/lib/queries";
import {
  formatDecimalAsAmerican,
  formatStartsAt,
} from "@/lib/format";

async function fetchOpportunities(): Promise<{
  opportunities: OpportunityRow[];
  generatedAt: string;
}> {
  const res = await fetch("/api/opportunities");
  if (!res.ok) throw new Error("fetch failed");
  return res.json();
}

export function OpportunityTable() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["opportunities"],
    queryFn: fetchOpportunities,
  });

  if (isLoading) return <div className="p-6 text-zinc-400">Loading…</div>;
  if (error) return <div className="p-6 text-red-400">Error: {String(error)}</div>;
  if (!data || data.opportunities.length === 0) {
    return <div className="p-6 text-zinc-400">No +EV opportunities right now.</div>;
  }

  const generatedAge = (Date.now() - new Date(data.generatedAt).getTime()) / 1000;
  const isStale = generatedAge > 90;

  return (
    <div>
      <div className="px-6 py-3 text-xs text-zinc-500">
        Updated {Math.round(generatedAge)}s ago
        {isStale && <span className="ml-2 text-amber-400">⚠ stale</span>}
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-zinc-500">
          <tr className="border-b border-zinc-800">
            <th className="px-6 py-3 text-left">Game</th>
            <th className="px-6 py-3 text-left">Player</th>
            <th className="px-6 py-3 text-left">Market</th>
            <th className="px-6 py-3 text-left">Pick</th>
            <th className="px-6 py-3 text-right">Kalshi</th>
            <th className="px-6 py-3 text-right">Fair</th>
            <th className="px-6 py-3 text-right">EV</th>
            <th className="px-6 py-3 text-right">Books</th>
          </tr>
        </thead>
        <tbody>
          {data.opportunities.map((o) => (
            <tr
              key={o.id}
              className="border-b border-zinc-900 hover:bg-zinc-900/50 transition-colors"
            >
              <td className="px-6 py-3">
                <div className="font-medium text-zinc-200">{o.sport}</div>
                <div className="text-xs text-zinc-500">
                  {formatStartsAt(o.gameStartsAt)}
                </div>
              </td>
              <td className="px-6 py-3">
                <Link
                  href={`/opportunity/${o.id}`}
                  className="text-zinc-100 hover:text-emerald-300 underline-offset-2 hover:underline"
                >
                  {o.playerName ?? "—"}
                </Link>
              </td>
              <td className="px-6 py-3 text-zinc-400">{o.statType ?? "—"}</td>
              <td className="px-6 py-3 font-mono tabular-nums text-zinc-300">
                {o.kalshiSide === "yes" ? "Over" : "Under"} {o.line ?? ""}
              </td>
              <td className="px-6 py-3 text-right font-mono tabular-nums">
                {formatDecimalAsAmerican(o.kalshiDecimalOdds)}
              </td>
              <td className="px-6 py-3 text-right font-mono tabular-nums text-zinc-400">
                {(o.blendedFairProb * 100).toFixed(1)}%
              </td>
              <td className="px-6 py-3 text-right">
                <EvBadge ev={o.evPct} />
              </td>
              <td className="px-6 py-3 text-right text-zinc-400">
                {o.numSharpBooks}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Update `src/app/page.tsx`**

```typescript
import { OpportunityTable } from "@/components/OpportunityTable";

export default function HomePage() {
  return (
    <main>
      <header className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-lg font-semibold">Kalshi EV Scanner</h1>
        <p className="text-xs text-zinc-500">Sorted by edge, polling every 5s</p>
      </header>
      <OpportunityTable />
    </main>
  );
}
```

- [ ] **Step 4: Verify dev server renders**

```bash
cd dashboard
pnpm dev
```

Open http://localhost:3000. Expected: "No +EV opportunities right now." (assuming DB is empty).

Insert a fake opportunity for visual check:
```bash
docker compose exec postgres psql -U kalshi -d kalshi_ev <<SQL
INSERT INTO markets (sport, kalshi_ticker, market_type, player_name, stat_type, line, game_id, game_starts_at)
VALUES ('NBA', 'TEST-MKT', 'player_prop', 'Test Player', 'points', 24.5, 'G1', NOW() + INTERVAL '3 hours');

INSERT INTO opportunities (market_id, kalshi_side, kalshi_decimal_odds, consensus_fair_prob,
                           blended_fair_prob, ev_pct, kelly_fraction, num_sharp_books, suspicious)
VALUES ((SELECT id FROM markets WHERE kalshi_ticker='TEST-MKT'),
        'yes', 2.0833, 0.580000, 0.580000, 0.0630, 0.0140, 2, false);
SQL
```

Refresh — should see one row with green "+6.30%" EV. Stop dev server.

- [ ] **Step 5: Commit**

```bash
cd ..
git add dashboard/src/components/OpportunityTable.tsx dashboard/src/components/EvBadge.tsx dashboard/src/app/page.tsx
git commit -m "feat(dashboard): main opportunity table view"
```

---

### Task 30: Opportunity detail page (`/opportunity/[id]`)

**Files:**
- Create: `dashboard/src/app/opportunity/[id]/page.tsx`

- [ ] **Step 1: Write the detail page**

```typescript
import { notFound } from "next/navigation";

import { EvBadge } from "@/components/EvBadge";
import { getOpportunityById } from "@/lib/queries";
import {
  formatCents,
  formatDecimalAsAmerican,
  formatStartsAt,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const opp = await getOpportunityById(Number(id));
  if (!opp) notFound();

  const stake = opp.kellyFraction !== null ? `${(opp.kellyFraction * 100).toFixed(2)}% of bankroll` : "—";

  return (
    <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">
      <a href="/" className="text-xs text-zinc-500 hover:text-zinc-300">
        ← back
      </a>

      <header>
        <h1 className="text-2xl font-semibold text-zinc-100">
          {opp.playerName} — {opp.statType} {opp.kalshiSide === "yes" ? "Over" : "Under"} {opp.line}
        </h1>
        <div className="mt-1 text-sm text-zinc-500">
          {opp.sport} · {formatStartsAt(opp.gameStartsAt)}
        </div>
      </header>

      <section className="rounded border border-zinc-800 bg-zinc-900/40 p-5 space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
          Math
        </h2>
        <Row label="Consensus fair prob" value={`${(opp.consensusFairProb * 100).toFixed(2)}%`} />
        <Row
          label="Projection fair prob"
          value={
            opp.projectionFairProb !== null
              ? `${(opp.projectionFairProb * 100).toFixed(2)}%`
              : "— (not yet available)"
          }
        />
        <Row
          label="Blended fair prob"
          value={`${(opp.blendedFairProb * 100).toFixed(2)}%`}
        />
        <Row
          label="Kalshi price"
          value={
            <>
              {formatDecimalAsAmerican(opp.kalshiDecimalOdds)} (
              {(((1 / opp.kalshiDecimalOdds) * 100).toFixed(1))}¢ implied)
            </>
          }
        />
        <Row label="EV" value={<EvBadge ev={opp.evPct} />} />
        <Row label="Recommended stake" value={stake} />
        <Row label="Sharp books used" value={opp.numSharpBooks.toString()} />
        {opp.suspicious && (
          <div className="text-xs text-amber-400">
            ⚠ EV unusually high — verify Kalshi quote isn't stale before betting.
          </div>
        )}
      </section>

      <section className="flex gap-3">
        <a
          href={`https://kalshi.com/markets/${opp.kalshiTicker}`}
          target="_blank"
          rel="noopener noreferrer"
          className="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 text-zinc-100 rounded text-sm"
        >
          Open on Kalshi →
        </a>
      </section>
    </main>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between text-sm">
      <span className="text-zinc-500">{label}</span>
      <span className="font-mono tabular-nums text-zinc-100">{value}</span>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd dashboard
pnpm dev
```

Click the player name in the main table → should navigate to detail page showing all math. Stop dev server.

- [ ] **Step 3: Commit**

```bash
cd ..
git add dashboard/src/app/opportunity/
git commit -m "feat(dashboard): opportunity detail page"
```

---

### Task 31: Health page (`/health`)

**Files:**
- Create: `dashboard/src/app/health/page.tsx`
- Create: `dashboard/src/components/HealthCard.tsx`

- [ ] **Step 1: Write `src/components/HealthCard.tsx`**

```typescript
"use client";

import { useQuery } from "@tanstack/react-query";

type HealthData = {
  sources: { source: string; lastFetchAt: string | null }[];
  checkedAt: string;
};

async function fetchHealth(): Promise<HealthData> {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error("fetch failed");
  return res.json();
}

export function HealthCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  if (isLoading) return <div className="p-6 text-zinc-400">Loading…</div>;
  if (!data) return null;

  return (
    <div className="space-y-2">
      {data.sources.length === 0 && (
        <div className="text-sm text-amber-400">
          No fetch successes recorded yet — scanner may not be running.
        </div>
      )}
      {data.sources.map((s) => {
        const last = s.lastFetchAt ? new Date(s.lastFetchAt) : null;
        const ageSec = last ? (Date.now() - last.getTime()) / 1000 : null;
        const status =
          ageSec === null
            ? "unknown"
            : ageSec < 60
            ? "ok"
            : ageSec < 300
            ? "warn"
            : "fail";
        const color =
          status === "ok" ? "text-emerald-400"
          : status === "warn" ? "text-amber-400"
          : "text-red-400";
        return (
          <div
            key={s.source}
            className="flex justify-between border-b border-zinc-900 px-4 py-3"
          >
            <span className="text-zinc-300">{s.source}</span>
            <span className={`font-mono tabular-nums ${color}`}>
              {ageSec !== null ? `${Math.round(ageSec)}s ago` : "never"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Write `src/app/health/page.tsx`**

```typescript
import { HealthCard } from "@/components/HealthCard";

export default function HealthPage() {
  return (
    <main className="max-w-2xl mx-auto px-6 py-8 space-y-6">
      <a href="/" className="text-xs text-zinc-500 hover:text-zinc-300">
        ← back
      </a>
      <h1 className="text-lg font-semibold">Scanner health</h1>
      <HealthCard />
    </main>
  );
}
```

- [ ] **Step 3: Verify**

Refresh, navigate to http://localhost:3000/health. Should show the sources (or empty state).

- [ ] **Step 4: Commit**

```bash
cd ..
git add dashboard/src/components/HealthCard.tsx dashboard/src/app/health/
git commit -m "feat(dashboard): scanner health page"
```

---

## Phase 7: End-to-end verification

### Task 32: Run scheduler for 5 minutes, verify end-to-end flow

**Files:** none (verification only)

- [ ] **Step 1: Start everything fresh**

```bash
cd kalshi-ev-scanner

# Reset DB
docker compose down -v
docker compose up -d
sleep 3
cd scanner
uv run alembic upgrade head

# Seed bankroll
docker compose exec -T postgres psql -U kalshi -d kalshi_ev <<SQL
INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) VALUES ('deposit', 80000, 80000);
SQL
```

- [ ] **Step 2: Start dashboard in background**

```bash
cd ../dashboard
pnpm dev &
DASH_PID=$!
```

- [ ] **Step 3: Start scheduler in foreground**

```bash
cd ../scanner
uv run python -m src.scheduler
```

Let it run for 5 minutes. Observe JSON logs.

- [ ] **Step 4: While it's running, open http://localhost:3000**

- If Pinnacle scraper is working and there are NBA games, opportunities should start appearing.
- If NBA is off-season or scrapers can't reach prices, the main page will be empty but `/health` should still show recent fetches.

- [ ] **Step 5: Stop scheduler, stop dashboard**

```bash
# Ctrl-C scheduler
kill $DASH_PID
```

- [ ] **Step 6: Sanity-check ONE opportunity by hand**

Pick an opportunity row from the DB:
```bash
docker compose exec postgres psql -U kalshi -d kalshi_ev -c \
  "SELECT id, market_id, kalshi_side, kalshi_decimal_odds, consensus_fair_prob, blended_fair_prob, ev_pct
   FROM opportunities ORDER BY ev_pct DESC LIMIT 1;"
```

Manually verify the math:
1. Pull all snapshots for that market (`SELECT * FROM odds_snapshots WHERE market_id = ? ORDER BY fetched_at DESC LIMIT 20`)
2. Devig the sharp book quotes by hand
3. Average them with `COLD_START_WEIGHTS`
4. Compute EV using the Kalshi price
5. Confirm the value matches `ev_pct` in the opportunities row

If math matches → Plan 1 MVP is real and working. ✓
If math doesn't match → identify which step differs, file a bug, return to relevant Task.

- [ ] **Step 7: No commit (verification only)**

---

### Task 33: Plan 1 wrap-up

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README with current state**

Replace `README.md` contents with:
```markdown
# Kalshi EV Scanner

Personal +EV sports betting scanner targeting Kalshi prediction markets.

**Current status:** Plan 1 MVP complete. Local-only. Scrapes Pinnacle + reads Kalshi every 30s. Computes EV. Surfaces opportunities in a Next.js dashboard.

See:
- `docs/superpowers/specs/2026-05-29-kalshi-ev-scanner-design.md` — full design
- `docs/superpowers/plans/2026-05-29-plan-1-foundation-mvp.md` — Plan 1 tasks

## Local development

```bash
# 1. Postgres
docker compose up -d

# 2. Scanner (Python)
cd scanner
uv sync
uv run alembic upgrade head
# Seed bankroll once:
docker compose exec postgres psql -U kalshi -d kalshi_ev \
  -c "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) VALUES ('deposit', 80000, 80000);"
uv run python -m src.scheduler

# 3. Dashboard (Next.js, separate terminal)
cd dashboard
pnpm install
pnpm dev
# open http://localhost:3000
```

## Plan 1 limitations (addressed in subsequent plans)

- Only Pinnacle is scraped (other sharp books deferred to Plan 2)
- No projections — pipeline uses consensus only (Plan 2)
- No news ingestion (Plan 3)
- No deployment — local Postgres + local services (Plan 3)
- No `/performance`, `/bets`, `/proof` pages (Plan 3)

## Math reference

See [docs/superpowers/specs](docs/superpowers/specs/2026-05-29-kalshi-ev-scanner-design.md) Section 7.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: Plan 1 MVP complete — update README"
```

- [ ] **Step 3: Tag the milestone**

```bash
git tag -a plan-1-mvp -m "Plan 1 MVP: foundation + math + Kalshi + Pinnacle + dashboard"
```

---

## Plan 1 — Self-review

**Spec coverage:**

- ✓ Architecture (Section 4): Vercel/Railway/Postgres split implemented as local-only equivalents; Vercel/Railway deploy deferred to Plan 3 by explicit YAGNI.
- ✓ Data model (Section 6): all 10 tables migrated in Task 4.
- ✓ Math (Section 7): devig, consensus, distributions, EV, Kelly, projection ramp, blend — Tasks 5-12.
- ✓ Pipeline (Section 7): tick orchestrator + scheduler — Tasks 23-24.
- ✗ NBA stats / projections (Section 7): explicitly deferred to Plan 2.
- ✗ News ingestion (Section 8): explicitly deferred to Plan 3.
- ✓ Frontend main + detail + health (Section 9): Tasks 25-31.
- ✗ Performance / bets / proof pages (Section 9): explicitly deferred to Plan 3.
- ✓ Error handling (Section 10): per-provider failures non-fatal, recorded in `scan_telemetry` (Task 23).
- ✓ Testing (Section 11): unit math TDD, integration with Postgres, e2e smoke for Pinnacle.
- ✗ Deployment + observability (Sections 12-13): explicitly deferred to Plan 3.

**Placeholder scan:** No "TBD" or "TODO" in tasks. All code complete. The Kalshi client paths in Tasks 19, 20, 24 require minor adjustment because the lifted code's exact class/method names depend on what's in the upstream repo — this is documented inline in those tasks.

**Type consistency:** `OddsQuote.implied_prob` and `OddsQuote.decimal_odds` are `Decimal` throughout (defined in Task 18, used in Tasks 20, 22, 23). `kelly_stake_cents` signature matches between definition (Task 9) and usage (Task 23). `current_projection_weight(int)` consistent between Task 10 definition and Task 23 caller.

---

## Execution handoff

Plan 1 is ready. Two execution options:

**1. Subagent-driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
