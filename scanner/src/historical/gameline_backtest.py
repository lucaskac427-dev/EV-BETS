"""Soccer game-line (1X2) backtest — the consensus model on match-result odds.

This is the same math as the prop backtest, applied to the deepest, sharpest
market we have: 296K football-data matches with Pinnacle (sharp) + market-max
(best available) odds + results.

Strategy under test = "line-shop against the sharp consensus":
  1. Devig Pinnacle's 3-way (home/draw/away) -> sharp fair probabilities.
  2. For each outcome, the price you'd actually get = market MAX (best book).
  3. EV = fair x max_decimal - 1. If EV >= threshold, bet at the max price.
  4. Score against the actual full-time result (FTR).

If even the best-available price can't beat Pinnacle's fair, game lines are
too efficient for this model — which is the expected, honest result.

Run: python -m src.historical.gameline_backtest --threshold 0.02
"""

import argparse
import asyncio
from collections import defaultdict

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log


def _f(v):
    try:
        return float(v) if v not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None


def _summary(bets: list[dict]) -> dict:
    if not bets:
        return {"n": 0, "wr": 0.0, "roi": 0.0, "edge": 0.0}
    wins = sum(1 for b in bets if b["won"])
    ret = sum(b["ret"] for b in bets)
    return {
        "n": len(bets),
        "wr": wins / len(bets),
        "roi": 100.0 * ret / len(bets),
        "edge": 100.0 * sum(b["edge"] for b in bets) / len(bets),
    }


async def run(threshold: float = 0.02) -> dict:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT ftr, pinnacle_home, pinnacle_draw, pinnacle_away,
                   raw->>'MaxH' AS maxh, raw->>'MaxD' AS maxd, raw->>'MaxA' AS maxa,
                   league_code
            FROM soccer_match_odds
            WHERE pinnacle_home IS NOT NULL AND pinnacle_draw IS NOT NULL
              AND pinnacle_away IS NOT NULL AND ftr IS NOT NULL
              AND raw ? 'MaxH'
            """
        )
        log.info("gameline_rows", count=len(rows))

        bets: list[dict] = []
        for r in rows:
            ph, pd, pa = float(r["pinnacle_home"]), float(r["pinnacle_draw"]), float(r["pinnacle_away"])
            if min(ph, pd, pa) <= 1.0:
                continue
            imp = [1/ph, 1/pd, 1/pa]
            tot = sum(imp)
            fair = [x/tot for x in imp]  # devigged sharp fair [H, D, A]
            best = [_f(r["maxh"]), _f(r["maxd"]), _f(r["maxa"])]
            ftr = r["ftr"]
            outcomes = ["H", "D", "A"]
            for i, oc in enumerate(outcomes):
                if best[i] is None or best[i] <= 1.0:
                    continue
                ev = fair[i] * best[i] - 1.0
                if ev < threshold:
                    continue
                won = (ftr == oc)
                ret = (best[i] - 1.0) if won else -1.0
                bets.append({"outcome": oc, "edge": ev, "won": won, "ret": ret})

        by = defaultdict(list)
        for b in bets:
            by[b["outcome"]].append(b)
        result = {"ALL": _summary(bets), **{k: _summary(v) for k, v in by.items()}}
        log.info("gameline_backtest_complete", **result["ALL"])
        return result
    finally:
        await close_pool()


def _fmt(label, s):
    if s["n"] == 0:
        return f"  {label:14s} n=     0"
    flag = "🟢" if s["roi"] > 0 else "🔴"
    return f"  {label:14s} n={s['n']:6d}  wr={s['wr']*100:5.1f}%  ROI={s['roi']:+6.2f}%  edge={s['edge']:+5.2f}%  {flag}"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=float, default=0.02)
    a = p.parse_args()
    res = asyncio.run(run(a.threshold))
    print(f"\nSOCCER GAME-LINE (1X2) BACKTEST · best-price vs Pinnacle fair · threshold {a.threshold*100:.0f}%")
    print(_fmt("ALL", res["ALL"]))
    for oc, lbl in (("H", "home win"), ("D", "draw"), ("A", "away win")):
        if oc in res:
            print(_fmt(lbl, res[oc]))
