# Kalshi EV Scanner — Design Spec

**Date:** 2026-05-29
**Author:** Luke (with Claude)
**Status:** Approved for implementation planning

---

## 1. Goal

Build a personal +EV (positive expected value) sports betting scanner targeting Kalshi prediction markets. The scanner continuously compares Kalshi's prices against a sharp-book consensus + statistical projections to surface bets with a mathematical edge. NBA player props and game lines for v1.

The product is a personal tool for Luke. Architecture is SaaS-ready (auth-shaped, multi-user-clean schema) but no auth or billing is shipped in v1.

## 2. Why Kalshi (and not DraftKings)

Traditional sportsbooks (DraftKings, FanDuel, BetMGM, Hard Rock) detect and limit winning bettors within weeks — accounts get capped to $5 max bets or closed entirely. Kalshi is legally a prediction market: their revenue comes from trading fees, not from house-vs-bettor margin. **They do not ban winners.** This makes Kalshi the only viable venue for a +EV strategy that compounds over time.

## 3. User profile and constraints

- Starting bankroll: **<$1,000** → forces quarter-Kelly sizing and 5% cap per bet
- Has Kalshi account; needs to set up API access during implementation
- Accepts ~$330/mo data costs as proof-of-concept "tuition" — willing to lose net money in months 1-3 to learn definitively whether the system has edge
- Will scale bankroll to $5k+ only if 90-day proof-of-concept review passes (see Section 14)

## 4. Architecture overview

Three deployable units, communicating through Postgres:

```
┌─────────────────────────┐         ┌─────────────────────────┐
│  Next.js Dashboard      │◀── HTTP─│  Vercel                 │
│  (Vercel)               │         │  /api/* edge routes     │
└──────────┬──────────────┘         └─────────────────────────┘
           │ reads opportunities
           ▼
┌─────────────────────────┐
│  Postgres (Railway)     │
│  - markets              │
│  - odds_snapshots       │
│  - projections          │
│  - news_events          │
│  - opportunities        │
│  - bets / bet_results   │
└──────────▲──────────────┘
           │ writes every 30s
┌──────────┴──────────────┐
│  Python Scanner         │
│  (Railway)              │
│                         │
│  - OddsProvider IF      │  ← CloakBrowser scrapers (v1)
│  - Kalshi adapter       │  ← lifted from ryanfrigo bot
│  - News ingester        │  ← Twitter API + RSS + LLM
│  - Devig engine         │
│  - Projection engine    │  ← nba_api + news adjustments
│  - EV calculator        │
│  - Kelly sizer          │
└─────────────────────────┘
```

**Tick cycle (every 30 seconds):**
1. Fan out to all odds providers + Kalshi in parallel
2. Persist raw snapshots to `odds_snapshots` (audit trail)
3. For each market: devig per book → Brier-weighted consensus → blend with projection → compute Kalshi EV (after fees) → Kelly sizing
4. Write `opportunities` row if EV ≥ threshold
5. Frontend polls `/api/opportunities` every 5s

**Why Postgres as the bus (not Redis/queues):** Simpler, debuggable, fully backtestable. Scanner writes, frontend reads. The full snapshot history is the proving ground for the math.

## 5. Decisions log

| Decision | Choice | Reason |
|---|---|---|
| Product scope | Personal scanner now, SaaS-ready later | Ship fast; prove math before productizing |
| Market scope | NBA game lines + player props | Most liquid prop market; Luke's interest |
| Projections | Build calibrated, start with baseline | Real edge lives here; can't fully outsource |
| Stack | Next.js + Python | Python's stats libs (scipy/numpy) drastically simpler |
| Hosting | Vercel + Railway | Simplest split; cheap to start |
| Odds source | CloakBrowser scrapers v1, swappable to The Odds API | Free start, architected for paid upgrade |
| Scanner cadence | 30s batch (Approach A) | Kalshi lines are sticky on minute-scale; B/C overkill |
| Projection weight | Start 80/20, ratchet to 60/40 as proven | Don't trust unproven model |
| News data | Full stack from day 1 (Twitter API + SportsDataIO) | Luke accepts ~$330/mo to prove edge cleanly |
| Bankroll strategy | Quarter-Kelly, 5% bet cap | <$1k bankroll = conservative discipline |
| Go/no-go gate | 90-day hard review (Section 14) | Data-driven scale decision, not emotional |

## 6. Data model

Postgres on Railway. All times UTC. All money in integer cents. Schema:

```sql
-- 1. Markets we scan (refreshed nightly from Kalshi)
CREATE TABLE markets (
  id              BIGSERIAL PRIMARY KEY,
  user_id         BIGINT NOT NULL DEFAULT 1,    -- SaaS-ready, single user for now
  sport           TEXT NOT NULL,                 -- 'NBA' for v1
  kalshi_ticker   TEXT UNIQUE NOT NULL,
  market_type     TEXT NOT NULL,                 -- 'h2h'|'spread'|'total'|'player_prop'
  player_name     TEXT,                          -- NULL for game lines
  stat_type       TEXT,                          -- 'points'|'rebounds'|'assists'|'pra'|NULL
  line            NUMERIC(6,2),
  game_id         TEXT NOT NULL,
  game_starts_at  TIMESTAMPTZ NOT NULL,
  is_active       BOOLEAN DEFAULT true,
  created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_markets_game ON markets(game_id, is_active);
CREATE INDEX idx_markets_starts ON markets(game_starts_at) WHERE is_active;

-- 2. Raw odds (append-only, full audit trail for backtesting)
CREATE TABLE odds_snapshots (
  id              BIGSERIAL PRIMARY KEY,
  market_id       BIGINT NOT NULL REFERENCES markets(id),
  book            TEXT NOT NULL,                 -- 'pinnacle'|'novig'|'betonline'|'draftkings'|'kalshi'
  side            TEXT NOT NULL,                 -- 'over'|'under'|'home'|'away'|'yes'|'no'
  decimal_odds    NUMERIC(10,4) NOT NULL,
  implied_prob    NUMERIC(7,6) NOT NULL,         -- raw, NOT devigged
  fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_snapshots_market_time ON odds_snapshots(market_id, fetched_at DESC);
CREATE INDEX idx_snapshots_book_time   ON odds_snapshots(book, fetched_at DESC);

-- 3. Projections (refreshed nightly + on news events)
CREATE TABLE projections (
  id              BIGSERIAL PRIMARY KEY,
  market_id       BIGINT NOT NULL REFERENCES markets(id),
  mean            NUMERIC(8,3) NOT NULL,
  std_dev         NUMERIC(8,3) NOT NULL,
  distribution    TEXT NOT NULL,                 -- 'normal'|'negative_binomial'|'poisson'
  fair_prob_over  NUMERIC(7,6) NOT NULL,
  model_version   TEXT NOT NULL,                 -- 'baseline-v1', 'calibrated-v1' etc.
  news_adjusted   BOOLEAN DEFAULT false,         -- TRUE if news events influenced this
  computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_projections_market_time ON projections(market_id, computed_at DESC);

-- 4. News events (from Twitter API + RSS + LLM classifier)
CREATE TABLE news_events (
  id            BIGSERIAL PRIMARY KEY,
  player_name   TEXT NOT NULL,
  team          TEXT,
  event_type    TEXT NOT NULL,                   -- 'injury_out'|'injury_questionable'|'lineup_change'|'rest_day'|'return_from_injury'|'personal'
  raw_text      TEXT NOT NULL,
  source        TEXT NOT NULL,                   -- 'twitter:@ChrisBHaynes'|'rss:espn'|'sportsdataio'
  posted_at     TIMESTAMPTZ NOT NULL,
  ingested_at   TIMESTAMPTZ DEFAULT now(),
  confidence    NUMERIC(3,2)                     -- LLM certainty 0-1
);
CREATE INDEX idx_news_player_recent ON news_events(player_name, posted_at DESC);

-- 5. Opportunities (frontend reads from this; append-only per tick)
CREATE TABLE opportunities (
  id                  BIGSERIAL PRIMARY KEY,
  user_id             BIGINT NOT NULL DEFAULT 1,
  market_id           BIGINT NOT NULL REFERENCES markets(id),
  kalshi_side         TEXT NOT NULL,             -- 'yes'|'no'
  kalshi_decimal_odds NUMERIC(10,4) NOT NULL,
  consensus_fair_prob NUMERIC(7,6) NOT NULL,
  projection_fair_prob NUMERIC(7,6),
  blended_fair_prob   NUMERIC(7,6) NOT NULL,
  ev_pct              NUMERIC(6,4) NOT NULL,     -- after Kalshi fees
  kelly_fraction      NUMERIC(6,4),
  num_sharp_books     SMALLINT NOT NULL,
  suspicious          BOOLEAN DEFAULT false,     -- TRUE if EV > 15% (likely stale quote)
  scan_tick_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_opps_recent ON opportunities(scan_tick_at DESC);
CREATE INDEX idx_opps_market_recent ON opportunities(market_id, scan_tick_at DESC);

-- 6. Bets actually placed (manual log v1)
CREATE TABLE bets (
  id              BIGSERIAL PRIMARY KEY,
  user_id         BIGINT NOT NULL DEFAULT 1,
  opportunity_id  BIGINT REFERENCES opportunities(id),
  market_id       BIGINT NOT NULL REFERENCES markets(id),
  side            TEXT NOT NULL,
  stake_cents     INTEGER NOT NULL,
  decimal_odds    NUMERIC(10,4) NOT NULL,
  ev_pct_at_bet   NUMERIC(6,4) NOT NULL,
  placed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes           TEXT
);

-- 7. Settled bet results (closed-loop calibration for OUR bets)
CREATE TABLE bet_results (
  bet_id          BIGINT PRIMARY KEY REFERENCES bets(id),
  outcome         TEXT NOT NULL,                 -- 'win'|'loss'|'push'|'void'
  payout_cents    INTEGER NOT NULL,
  actual_value    NUMERIC(8,3),
  settled_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. Market outcomes (for ALL markets we scanned — feeds Brier scoring)
-- Populated by a nightly job that reconciles actual game/player results
-- against every market in odds_snapshots, not just markets we bet on.
CREATE TABLE market_outcomes (
  market_id       BIGINT PRIMARY KEY REFERENCES markets(id),
  outcome         TEXT NOT NULL,                 -- 'over'|'under'|'home'|'away'|'yes'|'no'|'push'|'void'
  actual_value    NUMERIC(8,3),                  -- raw stat (e.g. 27 points)
  settled_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 9. Bankroll state (single-row append log)
-- Source of truth for the BANKROLL value the Kelly sizer reads.
-- Updated when (a) user deposits/withdraws, (b) bet settles.
CREATE TABLE bankroll_events (
  id              BIGSERIAL PRIMARY KEY,
  user_id         BIGINT NOT NULL DEFAULT 1,
  event_type      TEXT NOT NULL,                 -- 'deposit'|'withdraw'|'bet_placed'|'bet_settled'|'manual_adjust'
  delta_cents     INTEGER NOT NULL,              -- negative for stake/withdraw, positive for payout/deposit
  balance_cents   INTEGER NOT NULL,              -- running balance AFTER this event
  related_bet_id  BIGINT REFERENCES bets(id),
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_bankroll_user_time ON bankroll_events(user_id, created_at DESC);

-- 10. Scanner telemetry (app-level metrics, polled by /health view)
CREATE TABLE scan_telemetry (
  id                  BIGSERIAL PRIMARY KEY,
  tick_id             TEXT NOT NULL,             -- UUID per scan tick
  source              TEXT NOT NULL,             -- 'pinnacle'|'novig'|'kalshi'|'pipeline'|'projections'|...
  event_type          TEXT NOT NULL,             -- 'fetch_success'|'fetch_failure'|'tick_complete'|'opps_written'
  latency_ms          INTEGER,
  status_detail       TEXT,                      -- error message, count, etc.
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_telemetry_source_time ON scan_telemetry(source, created_at DESC);
CREATE INDEX idx_telemetry_tick ON scan_telemetry(tick_id);
```

**Design notes:**

- `odds_snapshots` and `opportunities` are append-only — every tick preserved → full backtest capability
- `bankroll_events` is also append-only — current bankroll = `(SELECT balance_cents FROM bankroll_events WHERE user_id=? ORDER BY id DESC LIMIT 1)`. The Kelly sizer reads this value at the start of each tick (not cached). Initial seed: a `deposit` event for the user's starting amount.
- `market_outcomes` is the Brier-scoring data source — it covers *every market we ever scanned* (settled by a nightly reconciliation job that fetches actual stat lines from `nba_api`), independent of which markets we actually bet on. This means Brier weights are computed from the full sample, not the small subset we bet.
- `bet_results` is the *narrower* table used only for our actual P/L and ROI tracking.
- `user_id` on every user-scoped table → SaaS-ready without schema rewrite
- All money in integer cents → no floating-point bugs
- Indices designed for "latest per market" queries (the hot path)
- Storage estimate: ~26M `odds_snapshots` rows/month for NBA alone. Add monthly partitioning when we expand to multiple sports.

## 7. Scanner pipeline

Python service, single async loop, 30s cadence.

**Directory structure:**

```
scanner/
├── providers/
│   ├── base.py           # OddsProvider abstract interface
│   ├── pinnacle.py       # CloakBrowser scraper
│   ├── novig.py          # CloakBrowser scraper
│   ├── betonline.py      # CloakBrowser scraper
│   ├── draftkings.py     # CloakBrowser scraper
│   └── odds_api.py       # The Odds API adapter (swap-in)
├── kalshi/
│   ├── client.py         # LIFTED: ryanfrigo/src/clients/kalshi_client.py
│   ├── ws.py             # LIFTED: ryanfrigo/src/clients/kalshi_ws.py
│   └── adapter.py        # wraps Kalshi → OddsQuote shape
├── news/
│   ├── twitter_client.py # Twitter API Basic tier
│   ├── twitter_scrape.py # snscrape fallback for tail reporters
│   ├── rss_client.py     # ESPN, NBA.com, Athletic, Reddit
│   ├── sportsdataio.py   # structured injury feed
│   ├── classifier.py     # GPT-4o-mini event extraction
│   └── reporters.yml     # 30 paid + 30 fallback reporter handles
├── math/
│   ├── devig.py
│   ├── consensus.py
│   ├── projection.py
│   ├── distributions.py
│   ├── ev.py
│   └── kelly.py
├── nba_stats/
│   └── ingest.py         # nightly: nba_api → player log cache
├── pipeline.py           # one tick orchestrator
└── scheduler.py          # 30s loop with locking
```

**Math (the 7 core functions):**

```python
# 1. Devig — single book → fair probabilities
def devig(imp_over: float, imp_under: float) -> tuple[float, float]:
    total = imp_over + imp_under
    return imp_over / total, imp_under / total

# 2. Brier-weighted consensus across sharp books
def consensus(fair_probs: dict[str, float], briers: dict[str, float]) -> float:
    weights = {book: 1 / briers[book] for book in fair_probs}
    total_w = sum(weights.values())
    return sum(fair_probs[b] * weights[b] for b in fair_probs) / total_w

# Cold-start weights (first 60 days, before settled-bet Brier scores exist)
COLD_START_WEIGHTS = {
    'pinnacle': 1.00, 'novig': 0.90, 'betonline': 0.70, 'draftkings': 0.40
}

# 3. Projection (baseline v1)
def project_player_prop(player_id, stat, line, opponent, is_b2b, news_events):
    logs = nba_stats.last_n_games(player_id, n=20)
    mean = logs[stat].mean()
    std = logs[stat].std()

    mean *= opponent_def_rating(opponent, stat) / league_avg(stat)
    if is_b2b: mean *= 0.96
    mean *= pace_factor(opponent)

    # News adjustments
    for event in news_events:
        if event.event_type == 'injury_out':
            return None  # exclude completely
        if event.event_type == 'injury_questionable':
            std *= 1.5    # widen uncertainty
        if event.event_type == 'lineup_change':
            mean *= 1.10  # teammate out → usage bump

    return mean, std

# 4. Distribution → P(actual > line)
from scipy.stats import norm, nbinom
def fair_prob_over(mean, std, line, distribution):
    if distribution == 'normal':
        return 1 - norm.cdf(line + 0.5, loc=mean, scale=std)
    elif distribution == 'negative_binomial':
        var = std ** 2
        p = mean / var if var > mean else 0.99
        n = mean * p / (1 - p)
        return 1 - nbinom.cdf(int(line), n, p)

# Distribution by stat type
STAT_DISTRIBUTIONS = {
    'points': 'normal', 'pra': 'normal', 'minutes': 'normal',
    'rebounds': 'negative_binomial', 'assists': 'negative_binomial',
    'threes': 'negative_binomial', 'blocks': 'negative_binomial',
    'steals': 'negative_binomial'
}

# 5. Blend
def blended_fair_prob(consensus_prob, projection_prob, projection_weight):
    if projection_prob is None:
        return consensus_prob
    return (1 - projection_weight) * consensus_prob + projection_weight * projection_prob

# 6. Kalshi EV (with fees)
def kalshi_ev(fair_prob_yes, yes_price_cents):
    yes_price = yes_price_cents / 100
    fee_per_winning_contract = 0.07 * yes_price * (1 - yes_price)
    payout_if_win = 1.0 - fee_per_winning_contract
    expected_value = fair_prob_yes * payout_if_win - yes_price
    return expected_value / yes_price

# 7. Quarter-Kelly stake with cap
def kelly_stake(fair_prob, decimal_odds, bankroll, fraction=0.25, cap_pct=0.05):
    b = decimal_odds - 1
    p = fair_prob
    q = 1 - p
    kelly_pct = max(0, (b * p - q) / b)
    sized_pct = min(kelly_pct * fraction, cap_pct)
    return bankroll * sized_pct
```

**Pipeline tick:**

```python
async def run_scan_tick():
    markets = await db.fetch_active_markets()

    odds_results = await asyncio.gather(
        *[provider.fetch_odds(markets) for provider in SHARP_PROVIDERS],
        kalshi.fetch_prices(markets),
        return_exceptions=True
    )

    await db.bulk_insert_snapshots(flatten(odds_results))

    for market in markets:
        sharp_quotes = collect_book_quotes(market, odds_results)
        if len(sharp_quotes) < MIN_SHARP_BOOKS:
            continue

        fair_probs = {b: devig(*q) for b, q in sharp_quotes.items()}
        consensus_p = consensus(fair_probs, current_briers())

        projection = await db.latest_projection(market.id)
        blended = blended_fair_prob(
            consensus_p,
            projection.fair_prob_over if projection else None,
            current_projection_weight()  # ramps from 0.2 → 0.4 over 90 days
        )

        kalshi_quote = kalshi_quotes.get(market.id)
        if not kalshi_quote or kalshi_quote.depth_cents < MIN_KALSHI_DEPTH:
            continue

        ev = kalshi_ev(blended, kalshi_quote.yes_price)
        if ev < MIN_EV_THRESHOLD:
            continue

        stake = kelly_stake(blended, kalshi_quote.decimal_odds, BANKROLL)
        suspicious = ev > SUSPICIOUS_EV_THRESHOLD

        await db.insert_opportunity(
            market.id, blended, ev, stake, len(sharp_quotes), suspicious
        )
```

**Configuration constants (v1 starting values):**

```python
MIN_EV_THRESHOLD = 0.01            # 1% minimum surfaceable EV
SUSPICIOUS_EV_THRESHOLD = 0.15     # 15% — flag as likely stale
MIN_SHARP_BOOKS = 2                # need ≥2 sharp books or skip
MIN_KALSHI_DEPTH = 5000            # min $50 of contracts available (cents)
SCAN_INTERVAL_SECONDS = 30
KELLY_FRACTION = 0.25              # quarter-Kelly
KELLY_CAP_PCT = 0.05               # max 5% of bankroll per bet
BACKTEST_LOOKBACK_DAYS = 60        # Brier weight rolling window
PROJECTION_WEIGHT_START = 0.20     # day 0
PROJECTION_WEIGHT_END = 0.40       # day 90+
```

**Projection weight ramp:** Linear interpolation from `PROJECTION_WEIGHT_START` on day 0 to `PROJECTION_WEIGHT_END` on day 90. After day 90, weight is fixed at `PROJECTION_WEIGHT_END` unless the proof-of-concept review (Section 14) recommends adjustment.

```python
def current_projection_weight(days_since_launch: int) -> float:
    if days_since_launch >= 90:
        return PROJECTION_WEIGHT_END
    pct = days_since_launch / 90
    return PROJECTION_WEIGHT_START + pct * (PROJECTION_WEIGHT_END - PROJECTION_WEIGHT_START)
```

**Brier weight calculation:** A rolling 60-day window over `market_outcomes` joined with `odds_snapshots` (devigged). For each (book, market, settled outcome), compute squared error of the book's pre-game fair probability vs the binary outcome (1.0 for hit, 0.0 for miss). Mean over the rolling window = the book's Brier score. Weights = `1 / brier_score` then normalized. Recomputed nightly by the `projections-cron` service. Falls back to `COLD_START_WEIGHTS` until the rolling window contains ≥100 settled outcomes per book.

## 8. News ingestion system

Three data sources feeding `news_events`:

**Tier 1 — Twitter API (Basic tier, $200/mo)**
- 10,000 tweet reads/month → 333/day budget
- Track top 30 NBA beat reporters (curated in `reporters.yml`)
- Server-side filter by keywords (`injury`, `out`, `questionable`, `OUT`, player names) to stay within quota
- Time-gated polling: high frequency 3pm-1am ET, throttled otherwise
- Each matched tweet → LLM classifier → event extraction

**Tier 2 — snscrape fallback (free)**
- Next 30 reporters by priority
- Unreliable (X blocks aggressively) but free
- Soft-fail: missing tweets logged as warnings, not errors

**Tier 3 — SportsDataIO injury feed ($50/mo)**
- Structured injury status per player
- ~5-15 min latency
- The authoritative source for "official" status
- Polled every 60s

**Tier 4 — Free RSS (ESPN, NBA.com, Athletic, Reddit r/nba)**
- Supplementary coverage
- 5-30 min latency
- LLM classifier processes headlines

**LLM classifier** (~$10-15/mo via GPT-4o-mini):
- Prompt: "Given this tweet/headline, extract any player news. Output JSON with `player_name`, `team`, `event_type`, `confidence` (0-1). Event types: injury_out, injury_questionable, lineup_change, rest_day, return_from_injury, personal. Return null if not relevant."
- Confidence threshold: 0.7 to write to `news_events`

**How projection engine uses news_events:**

Query last 4 hours of events for the player. Apply adjustments in order of severity:
- `injury_out` → projection returns `None` → opportunity filtered out
- `injury_questionable` → multiply std by 1.5 (more uncertainty)
- `return_from_injury` → halve weight in blend until 3 games elapsed
- `lineup_change` (teammate out) → boost mean by 8-12%
- `rest_day` → exclude
- `personal` → log only, no adjustment (judgment call)

## 9. Frontend (Next.js dashboard)

Stack: Next.js 15 App Router + React 19 + TypeScript + Tailwind + shadcn/ui + TanStack Query. Drizzle ORM for read-only Postgres access. Hosted on Vercel.

**Routes:**

```
app/
├── page.tsx                     # / → live opportunities table
├── opportunity/[id]/page.tsx    # detail: devig breakdown, line chart, log-bet
├── bets/page.tsx                # manual bet log + status
├── performance/page.tsx         # P/L, ROI, Brier scores, CLV
├── proof/page.tsx               # 90-day go/no-go review (auto-renders at day 90)
├── health/page.tsx              # scanner uptime + last-fetch per source
└── api/
    ├── opportunities/route.ts
    ├── opportunity/[id]/route.ts
    ├── bets/route.ts
    ├── bets/[id]/route.ts       # PATCH to settle
    ├── performance/route.ts
    └── health/route.ts
```

**Main view (`/`):** Dense, dark, OddsJam-style table. Columns: game, player, market, pick, Kalshi price, fair prob, EV%, recommended stake, books used. Sortable. Filters: sport, market type, min EV, min books, time-to-game. EV color-coded (green ≥3%, yellow 1-3%, gray <1%). Polls `/api/opportunities` every 5s. Stale indicator if last scan > 90s old.

**Opportunity detail (`/opportunity/[id]`):** Shows the full math: devig per book, projection breakdown (μ/σ, opponent/pace/rest adjustments, news events applied), the blend computation, Kalshi fee math, Kelly stake, line movement sparkline. Two CTAs: "Open on Kalshi →" (deeplinks the ticker), "Log this bet" (records to `bets` table).

**Performance (`/performance`):**
- Cumulative P/L curve
- ROI overall and bucketed by EV (1-2%, 2-3%, 3-5%, 5%+)
- Hit rate vs predicted (calibration plot)
- Per-book Brier scores over time
- Closing Line Value (CLV) — leading indicator of model alpha

**Proof (`/proof`):** Auto-renders at day 90 with go/no-go recommendation. See Section 14.

**Health (`/health`):** Scanner status, last-fetch timestamp per provider, Kalshi WS heartbeat, projection job last-run, news pipeline status.

**Data flow:** Frontend reads Postgres via Drizzle. Never talks directly to Python scanner. Scanner writes, frontend reads.

**Auth (SaaS-ready, off in v1):** `user_id` on every user-scoped table, defaults to 1. When ready: drop in Clerk or Supabase Auth middleware, populate `user_id` from session. No schema rewrite.

## 10. Error handling

Three tiers, each with explicit behavior:

| Tier | Examples | Behavior |
|---|---|---|
| Transient | Network blip, 503, scrape timeout | Exponential backoff (3 attempts). Log warn, continue. |
| Degraded | One sharp book down >3 ticks; projection stale >24h | Drop affected source, mark in `/health`, Discord webhook ping. Scanner continues. |
| Critical | Kalshi auth fails; DB unreachable; all sharp books down | Halt opportunity writes. Discord page. No auto-restart — human investigates. |

**Principles:**
- No silent failures. Every drop logs reason.
- No swallowed exceptions. Recovery is explicit; otherwise propagate.
- Scanner tick failures recorded as failed ticks in telemetry (don't crash the loop).

## 11. Testing strategy

```
tests/
├── unit/                          # Pure math. Fast. No I/O. Run on save.
│   ├── test_devig.py
│   ├── test_consensus.py
│   ├── test_distributions.py
│   ├── test_ev.py
│   └── test_kelly.py
├── integration/                   # Pipeline pieces + Docker Postgres.
│   ├── test_pipeline_tick.py
│   ├── test_failure_modes.py
│   ├── test_projections.py
│   └── test_news_pipeline.py
└── e2e/                           # Live against Kalshi sandbox.
    ├── test_kalshi_auth.py
    └── test_kalshi_market.py
```

**Property-based tests** via `hypothesis`:
- Devig outputs sum to 1.0 ± ε for any valid input pair
- Consensus output ∈ [0, 1] for any input
- Kelly stake never exceeds `cap_pct * bankroll`

**Backtest as CI test:** `scripts/backtest.py` replays 30 days of `odds_snapshots` through the pipeline code. Build fails if predicted ROI drops >10% vs the previous baseline.

**Coverage:** ≥95% on `math/` (pure functions, no excuse). Provider tests dominated by integration coverage.

## 12. Deployment

**Frontend (Vercel):**
- GitHub → auto-deploy `main` to production, PR previews
- Env: `DATABASE_URL` (Railway pooler), `NEXT_PUBLIC_SCAN_INTERVAL`
- `vercel.json`: Edge runtime for `/api/*` routes

**Python services (Railway):**
- Two services in one project:
  - `scanner-worker`: `python -m scanner.scheduler` (30s loop)
  - `projections-cron`: nightly 4am ET, regenerates projections from nba_api
- Postgres add-on shared by both Python services + Vercel
- PgBouncer in front of Postgres (or Railway's built-in pooler)
- Env via Railway secrets: `KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY`, `DATABASE_URL`, `DISCORD_WEBHOOK`, `TWITTER_BEARER_TOKEN`, `SPORTSDATAIO_KEY`, `OPENAI_API_KEY`, `BRIGHTDATA_PROXY_URL`

**Migrations:** Alembic for Python-side schema. `alembic upgrade head` as Railway pre-deploy hook. Drizzle is read-only.

**Secrets:** `.env.example` committed; real `.env` gitignored.

## 13. Observability

**Logs:** structlog (Python) and pino (TS) → JSON stdout → Railway/Vercel log aggregators. Required fields: `tick_id`, `market_id`, `book`, `latency_ms`, `status`.

**Metrics:** App-level metrics stored in `scan_telemetry` table (v1). BetterStack or Grafana Cloud later (~$30/mo) when justified. Key metrics:
- `scan_tick_latency_ms` (p50, p99)
- `provider_fetch_success_rate` per book
- `opportunities_per_tick`
- `ev_distribution` histogram
- `kalshi_market_count`
- `twitter_api_quota_used` (don't blow the 10k/month cap)

**Alerts (Discord webhook):**
- Sharp book fails 3 consecutive ticks
- No opportunities written for 5 minutes
- Kalshi auth failure (page immediately)
- Suspicious EV (>15%) detected
- Settled bet result diverges sharply from prediction (model drift signal)
- Twitter API quota >80% with >5 days left in month

**Cost tracking:** Hard budget alert at $400/mo total (vs ~$330 expected). Degrade gracefully (longer scan intervals) before adding cost.

## 14. 90-day proof-of-concept gate

A `/proof` page that auto-renders at day 90 with a data-driven go/no-go recommendation.

**Required for PROCEED:**
- ≥200 settled bets
- Actual ROI within ±50% of predicted ROI (i.e., predicted +4% → actual must be ≥+2%)
- Mean Brier score below threshold (≤0.24 for binary outcomes)
- Average Closing Line Value ≥ 0 (market agreed with our picks)

**If passing:** Recommend scaling bankroll to $5,000. Phase 2 data costs become trivial overhead.

**If failing:** Recommend HALT. Show which markets dragged ROI most. Suggest lowering projection weight or focusing on game lines only.

This is a hard rule baked into the UI — prevents emotional "let me try a little more" decisions when the data says stop.

## 15. Backtest framework

`scripts/backtest.py` replays `odds_snapshots` history through current pipeline code:

```python
def backtest(start_date, end_date, model_version='baseline-v1'):
    for tick_at in tick_range(start_date, end_date):
        snapshots = load_snapshots_at(tick_at)
        opps = compute_opportunities(snapshots, model_version)
        for opp in opps:
            actual = lookup_actual_outcome(opp.market_id)
            track(predicted=opp.fair_prob, actual=actual.outcome, ev=opp.ev_pct)

    return {
        'roi': calc_roi(),
        'sharpe': calc_sharpe(),
        'brier': calc_brier(),
        'calibration_curve': bucket_predictions_vs_actuals(),
        'clv': calc_closing_line_value()
    }
```

Used for: pre-deploy validation, model-version comparison (e.g., baseline-v1 vs calibrated-v1), parameter sweeps (e.g., what projection weight maximizes Sharpe?), the 90-day proof gate calculations.

## 16. Cost budget

| Item | Monthly |
|---|---|
| Vercel | $0 |
| Railway (Postgres + 2 Python services) | ~$15 |
| Residential proxies (Bright Data starter) | ~$20 |
| Twitter API Basic | $200 |
| SportsDataIO injury feed | $50 |
| GPT-4o-mini (LLM classifier) | ~$15 |
| The Odds API (fallback) | $30 (optional) |
| **Total** | **~$330/mo** |

Tuition framing: at <$1k bankroll with quarter-Kelly sizing, expected betting profit is $50-150/mo if the system works perfectly. Net cost in months 1-3 is realistically -$150-280/mo. Total proof-of-concept investment: ~$500-800. If 90-day gate passes, scale bankroll to $5k+ where data costs become noise against profit.

## 17. What's NOT in v1 (YAGNI)

- Auto-bet placement (manual log only)
- Mobile-optimized UI (desktop-first; works on mobile but not pretty)
- Push notifications (Discord webhooks only)
- Frontend WebSocket / real-time push (polling every 5s is sufficient)
- Multi-user / billing / onboarding (architecture is ready; not enabled)
- Backtest UI (raw SQL + scripts/backtest.py)
- Email/SMS alerts
- Distributed tracing / OpenTelemetry
- Hot-reload of model weights (restart scanner is fine)
- Multi-region failover
- A/B testing framework (run two model versions manually, compare)
- Sports beyond NBA
- Auto-arbitrage / hedging across venues

## 18. Risks acknowledged

| Risk | Mitigation in design |
|---|---|
| Projections might be inaccurate | Start projection weight at 20% (not 40%), ratchet up only as calibration proves it; closed-loop Brier scoring; skip categories model is weak at (rookies, injury returns); sanity guardrails on EV outliers |
| Scrapers break / get blocked | CloakBrowser stealth + Bright Data residential proxies; ≥2 sharp books needed (redundancy); Discord alerts on consecutive failures; The Odds API as drop-in replacement |
| Variance is brutal | Quarter-Kelly sizing; 5% bet cap regardless of Kelly output; volume over size (100 small bets > 10 big); CLV as leading indicator; performance dashboard prevents panic-quit |
| Kalshi liquidity is thin | `MIN_KALSHI_DEPTH` filter ($50 minimum); limit orders not market orders; diversify across many markets; future: provide liquidity (Safe Compounder pattern) |
| Twitter API quota exhaustion | Server-side keyword filter; time-gated polling; metric alert at 80% quota; snscrape fallback for tail reporters |
| Model drift over time | Backtest as CI test; per-book Brier scores recalculated rolling 60d; alert on result-vs-prediction divergence |

## 19. References

**Code we lift directly:**
- [ryanfrigo/kalshi-ai-trading-bot](https://github.com/ryanfrigo/kalshi-ai-trading-bot) — `src/clients/kalshi_client.py`, `kalshi_ws.py`, Kelly sizer, SQLite telemetry patterns. Lifts ~5 days of API plumbing.
- [swar/nba_api](https://github.com/swar/nba_api) — pip dependency for player stats (`pip install nba_api`).
- [CloakHQ/CloakBrowser](https://github.com/CloakHQ/CloakBrowser) — stealth Chromium for scraper resilience.

**Code we reference (steal ideas, not code):**
- [kyleskom/NBA-Machine-Learning-Sports-Betting](https://github.com/kyleskom/NBA-Machine-Learning-Sports-Betting) — feature engineering patterns for NBA features (rest days, pace adjustments).

**External APIs:**
- [Kalshi Trading API](https://trading-api.readme.io/) — markets + orders
- [Twitter API v2](https://developer.x.com/en/docs/x-api) — Basic tier
- [SportsDataIO](https://sportsdata.io/) — NBA injury feed
- [The Odds API](https://the-odds-api.com/) — fallback for sharp book odds
- [OpenAI API](https://platform.openai.com/) — GPT-4o-mini for news classification

## 20. Open questions for implementation phase

These don't block writing the spec but will surface during implementation:

1. Exact list of 30 paid + 30 fallback NBA beat reporters (`reporters.yml`) — to be curated before scanner launch.
2. Cold-start Brier weights — current values are hand-tuned; may need tweaking after first 30 days of data.
3. Exact opponent-defense formula — using `opponent_def_rating(opponent, stat) / league_avg(stat)` but the exact stat (DRtg, OppPPG, OppPPG-per-position) needs picking during projection build.
4. Kalshi market-discovery cadence — daily vs every-few-hours for new market activations.
5. Initial bankroll seed amount — confirmed <$1k starting; exact figure set via first `bankroll_events` row on launch.
6. Nightly reconciliation job design — fetches actual stat outcomes from `nba_api` and writes `market_outcomes` rows for every market that settled the previous day. Needs careful handling of pushed/voided/postponed games.
