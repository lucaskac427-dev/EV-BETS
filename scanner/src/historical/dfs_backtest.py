"""DFS pick'em backtest — the ACTUAL strategy: soft DFS line vs sharp consensus.

For every historical DFS pick'em line (PrizePicks / Underdog / DK Pick6 / Betr,
captured via The Odds API `us_dfs` region), estimate the sharp consensus
probability AT THE DFS LINE, bet the favored side at the flat DFS payout
(~1.82x per leg = 55% breakeven), and grade vs the box score. THIS is the edge
the live system actually bets — finally backtestable now that we have the
historical DFS lines (~late-2024 on).

Consensus at the DFS line:
  - if a sportsbook quoted that EXACT line -> use its de-vigged consensus;
  - else -> interpolate with a per-market normal model centered on the sharp
    main line (sigma = population std of the stat from box scores).

The soft-line edge: when PrizePicks posts a line BELOW the sharp number, the
over's true prob is >50% — and the flat 1.82x payout (breakeven 55%) prints if
that true prob clears 55%. We only bet sides where the consensus says >=55%.

    python -m src.historical.dfs_backtest --sport basketball_wnba
"""

import argparse
import asyncio
import math
from collections import defaultdict
from statistics import pstdev

from src.db import close_pool, get_pool
from src.logger import configure_logging
from src.historical.backtest import (
    _decimal_from_american,
    MARKET_TO_COLUMN_BY_SPORT,
    OUTCOME_SOURCE_BY_SPORT,
    _load_outcomes,
    _lookup_actual,
)

DFS_BOOKS = ("prizepicks", "underdog", "pick6", "draftkings_pick6", "betr_us_dfs", "betr")
PAYOUT = 1.817      # PrizePicks 3-pick Power per-leg (6x^(1/3)); breakeven 55.0%
BREAKEVEN = 0.55


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


async def _market_sigma(pool, sport: str) -> dict[str, float]:
    """Population std per market (combos = sqrt of summed column variances)."""
    table, _ = OUTCOME_SOURCE_BY_SPORT[sport]
    m2c = MARKET_TO_COLUMN_BY_SPORT[sport]
    cols = sorted({c for cc in m2c.values() for c in cc})
    colsig: dict[str, float] = {}
    for col in cols:
        vals = [r[col] for r in await pool.fetch(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL")]
        colsig[col] = pstdev(vals) if len(vals) > 1 else 1.0
    return {mk: (math.sqrt(sum(colsig.get(c, 1.0) ** 2 for c in cc)) or 1.0) for mk, cc in m2c.items()}


async def run(sport: str, *, breakeven: float = BREAKEVEN, payout: float = PAYOUT,
              exclude: tuple[str, ...] = ()) -> dict:
    configure_logging(level="WARNING")
    pool = await get_pool()
    try:
        m2c = MARKET_TO_COLUMN_BY_SPORT[sport]
        # Only load rows for (event, player) combos that actually have a DFS line —
        # sharp rows for players with no DFS line are never bettable. This keeps the
        # NBA pull at ~hundreds of K rows instead of ~15M (no OOM, fast).
        rows = await pool.fetch(
            """WITH dfs_keys AS (
                   SELECT DISTINCT event_id, regexp_replace(market_key,'_alternate$','') mk,
                          player_name, line
                   FROM historical_odds_snapshots
                   WHERE sport_key=$1 AND book = ANY($3::text[]) AND market_key = ANY($2::text[])
                     AND player_name IS NOT NULL AND line IS NOT NULL)
               SELECT s.event_id, s.event_start, regexp_replace(s.market_key,'_alternate$','') mk,
                      s.player_name, s.line, s.book, s.side, s.american_odds
               FROM historical_odds_snapshots s
               JOIN dfs_keys k ON k.event_id = s.event_id
                    AND k.mk = regexp_replace(s.market_key,'_alternate$','')
                    AND k.player_name = s.player_name AND k.line = s.line
               WHERE s.sport_key=$1 AND s.market_key = ANY($2::text[])
                 AND s.player_name IS NOT NULL AND s.line IS NOT NULL""",
            sport, list(m2c.keys()), list(DFS_BOOKS), timeout=600)

        estart: dict = {}
        sharp: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))  # key->line->book->side->odds
        dfs: dict = defaultdict(lambda: defaultdict(dict))                          # key->(book,line)->side->odds
        for r in rows:
            key = (r["event_id"], r["mk"], r["player_name"])
            estart[r["event_id"]] = r["event_start"]
            if r["book"] in DFS_BOOKS:
                dfs[key][(r["book"], float(r["line"]))][r["side"]] = r["american_odds"]
            else:
                sharp[key][float(r["line"])][r["book"]][r["side"]] = r["american_odds"]

        sigma = await _market_sigma(pool, sport)
        outcomes = await _load_outcomes(pool, sport)

        agg = lambda: {"n": 0, "w": 0, "ret": 0.0}
        overall, by_app, by_mkt, by_band = agg(), defaultdict(agg), defaultdict(agg), defaultdict(agg)
        by_src = {"exact-line (true consensus)": agg(), "interpolated": agg()}

        for key, dfslines in dfs.items():
            ev_id, mk, player = key
            if mk in exclude:
                continue
            cons: dict[float, float] = {}
            for ln, books in sharp.get(key, {}).items():
                fos = []
                for b, ss in books.items():
                    if "over" in ss and "under" in ss:
                        oi = 1 / _decimal_from_american(ss["over"]); ui = 1 / _decimal_from_american(ss["under"])
                        if oi + ui > 0:
                            fos.append(oi / (oi + ui))
                if len(fos) >= 2:
                    cons[ln] = sum(fos) / len(fos)
            if not cons:
                continue
            L0 = min(cons, key=lambda l: abs(cons[l] - 0.5))   # sharp main line ≈ projected mean
            sig = sigma.get(mk, 1.0) or 1.0
            gd = estart[ev_id].date()

            # one DFS line per app per player-market = the standard line (closest to L0)
            best: dict[str, float] = {}
            for (book, ln) in dfslines:
                if book not in best or abs(ln - L0) < abs(best[book] - L0):
                    best[book] = ln
            for book, ln in best.items():
                is_exact = ln in cons
                fair_over = cons[ln] if is_exact else _phi((L0 - ln) / sig)
                favored = "over" if fair_over >= 0.5 else "under"
                fair = max(fair_over, 1 - fair_over)
                if fair < breakeven:
                    continue
                actual = _lookup_actual(outcomes, player=player, market=mk, game_date=gd, m2c=m2c)
                if actual is None or actual == ln:
                    continue
                won = actual > ln if favored == "over" else actual < ln
                r = (payout - 1) if won else -1
                band = "55-60%" if fair < 0.60 else ("60-70%" if fair < 0.70 else "70%+")
                src = by_src["exact-line (true consensus)"] if is_exact else by_src["interpolated"]
                for d in (overall, by_app[book], by_mkt[mk], by_band[band], src):
                    d["n"] += 1; d["w"] += int(won); d["ret"] += r
        return {"overall": overall, "by_app": dict(by_app), "by_mkt": dict(by_mkt),
                "by_band": dict(by_band), "by_src": by_src}
    finally:
        await close_pool()


def _show(label: str, d: dict) -> None:
    n = d["n"]
    if not n:
        print(f"  {label:22s} no bets"); return
    print(f"  {label:22s} {n:6d} bets · {100*d['w']/n:5.1f}% win · ROI {100*d['ret']/n:+6.2f}%")


async def main(sport: str, exclude: tuple[str, ...] = ()) -> None:
    res = await run(sport, exclude=exclude)
    ex = f" · excl {','.join(e.replace('player_','').replace('batter_','') for e in exclude)}" if exclude else ""
    print(f"\n=== DFS PICK'EM BACKTEST · {sport} · favored ≥55% at flat {PAYOUT}x payout{ex} ===")
    _show("OVERALL", res["overall"])
    print("  by consensus source (engine sanity check):")
    [_show("  " + k, v) for k, v in res["by_src"].items()]
    print("  by app:");   [_show("  " + k, v) for k, v in sorted(res["by_app"].items(), key=lambda kv: -kv[1]["n"])]
    print("  by market:");[_show("  " + k.replace("player_", ""), v) for k, v in sorted(res["by_mkt"].items(), key=lambda kv: -kv[1]["n"])]
    print("  by consensus band:");[_show("  " + k, res["by_band"][k]) for k in ("55-60%","60-70%","70%+") if k in res["by_band"]]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sport", default="basketball_wnba")
    p.add_argument("--exclude", default="", help="comma-separated market keys to drop")
    a = p.parse_args()
    asyncio.run(main(a.sport, tuple(x for x in a.exclude.split(",") if x)))
