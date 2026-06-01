# Kalshi EV Scanner

Personal +EV (positive expected value) sports betting scanner targeting Kalshi prediction markets.

**Status:** Plan 2 complete. Adds the projection engine (nba_api → per-player distributions), NoVig/BetOnline/DraftKings scrapers, and the Brier calibration loop. Projections now blend into EV; consensus weights auto-calibrate once enough markets settle. The nba_api ingest is live-verified (10k+ game logs + 30 teams pulled successfully). Live scraping + Kalshi verification still pending user infra (IPRoyal funding + Kalshi keys).

## What's in it

- **Scanner (`scanner/`)** — Python 3.12 async service. 30s tick loop. Devig + Brier-weighted consensus + EV + quarter-Kelly. Writes opportunities to Postgres.
- **Dashboard (`dashboard/`)** — Next.js 15 + Drizzle ORM. Live opportunity table, detail view, scanner health page.
- **Math library (`scanner/src/math/`)** — Pure functions, fully TDD'd. devig, consensus, distributions, EV (with Kalshi fees), Kelly sizing, blend, projection weight ramp.
- **Providers (`scanner/src/providers/`, `scanner/src/kalshi/`)** — Pinnacle scraper via cloakbrowser; Kalshi client (RSA-signed REST + WS) lifted from [ryanfrigo/kalshi-ai-trading-bot](https://github.com/ryanfrigo/kalshi-ai-trading-bot).

See [docs/superpowers/specs/2026-05-29-kalshi-ev-scanner-design.md](docs/superpowers/specs/2026-05-29-kalshi-ev-scanner-design.md) for the full design spec.
See [docs/superpowers/plans/2026-05-29-plan-1-foundation-mvp.md](docs/superpowers/plans/2026-05-29-plan-1-foundation-mvp.md) for Plan 1 task breakdown.

## Local development

```bash
# 1. Start Postgres
docker compose up -d

# 2. Set up env
cp .env.example .env
# Edit .env: fill in KALSHI_KEY_ID, KALSHI_PRIVATE_KEY, IPROYAL_PROXY_URL

# 3. Scanner setup
cd scanner
uv sync
uv run alembic upgrade head
# Seed bankroll once (skip if already done):
docker compose exec postgres psql -U kalshi -d kalshi_ev \
  -c "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) VALUES ('deposit', 80000, 80000);"
uv run python -m src.scheduler

# 4. Dashboard (separate terminal)
cd dashboard
pnpm install
pnpm dev
# open http://localhost:3000
```

## Running tests

```bash
cd scanner
uv run pytest tests/unit/                                # pure math (44 tests, no infra)
uv run pytest tests/integration/                         # Postgres-backed (13 tests)
uv run pytest tests/e2e/ -m e2e                          # live Pinnacle scrape (manual)
uv run pytest --cov=src.math --cov-report=term-missing   # math coverage (>=95%)
```

## What's required before live verification (Task 32)

1. **Kalshi API access** — Generate API key + private key from your Kalshi account. Put them in `.env` as `KALSHI_KEY_ID` and `KALSHI_PRIVATE_KEY`.
2. **IPRoyal funded** — Load $20-25 onto your IPRoyal residential proxy account. Put credentials in `.env` as `IPROYAL_PROXY_URL`.
3. **NBA games active** — During offseason, Pinnacle will have no NBA player props. v1 is NBA-only.

Without these, the scheduler runs but logs `provider_fetch_failed` for both Pinnacle and Kalshi. The dashboard shows empty / stale.

## Remaining work (Plan 3)

- News ingestion (Twitter API + SportsDataIO + LLM classifier) — projections currently ignore injury news
- Performance / Bets / Proof dashboard pages
- Vercel + Railway deployment
- Discord alerts
- Nightly cron wiring for `src.nba_stats.ingest`, `src.projections.job`, `src.calibration.reconcile`

## References

Lifted/used code:
- [ryanfrigo/kalshi-ai-trading-bot](https://github.com/ryanfrigo/kalshi-ai-trading-bot) — Kalshi REST + WS client (MIT)
- [CloakHQ/CloakBrowser](https://github.com/CloakHQ/CloakBrowser) — stealth Chromium for scrapers
- [swar/nba_api](https://github.com/swar/nba_api) — NBA stats (Plan 2)
