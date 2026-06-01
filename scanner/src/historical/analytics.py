"""No-bullshit validation of the consensus edge.

Runs the real backtest once, then computes every metric that separates a REAL
edge from variance — nothing hardcoded, all from the data:

  • ROI + bootstrap 95% CI            -> is the edge significantly > 0?
  • ROI by predicted-edge bucket      -> monotonic? (the model actually predicts)
  • ROI by season                     -> does it hold out-of-sample, year over year?
  • Calibration (Brier + reliability) -> are the fair probabilities accurate?
  • Drawdown / Sharpe / losing streak -> how bad does it get?
  • DFS forward-test (tracked_picks)  -> real picks, win rate + Wilson CI + significance

    python -m src.historical.analytics
"""

import asyncio
import math
import random
from collections import defaultdict

from src.db import close_pool, get_pool
from src.historical.backtest import run_backtest

random.seed(7)
DFS_BREAKEVEN = 0.55  # 3-pick power-play breakeven, the bar the DFS edge must clear


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def _bootstrap_roi_ci(returns: list[float], iters: int = 5000) -> tuple[float, float]:
    n = len(returns)
    means = sorted(100 * (sum(random.choices(returns, k=n)) / n) for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def _season(d) -> str:
    if d is None:
        return "?"
    y = d.year
    return f"{y}-{str(y + 1)[2:]}" if d.month >= 10 else f"{y - 1}-{str(y)[2:]}"


def _roi(bets) -> tuple[int, float, float]:
    if not bets:
        return 0, 0.0, 0.0
    n = len(bets)
    wins = sum(1 for b in bets if b.won and not b.pushed)
    dec = sum(1 for b in bets if not b.pushed)
    roi = 100 * sum(b.return_per_unit for b in bets) / n
    return n, (wins / dec * 100 if dec else 0.0), roi


def _bar(label, n, wr, roi, extra=""):
    print(f"   {label:14s} n={n:5d}  win={wr:5.1f}%  ROI={roi:+6.2f}%  {extra}")


async def main(min_fair: float = 0.0) -> None:
    res = await run_backtest("basketball_nba", threshold=0.02, min_books=2, use_projection=False, min_fair=min_fair)
    bets = [b for b in res["bets"] if not b.pushed]
    returns = [b.return_per_unit for b in bets]
    n = len(bets)
    wins = sum(1 for b in bets if b.won)
    roi = 100 * sum(returns) / n
    lo, hi = _bootstrap_roi_ci(returns)

    print("\n" + "=" * 74)
    print(f"  NBA CONSENSUS-EDGE BACKTEST — FULL VALIDATION  (2% edge, no projection, win-prob floor {min_fair:.0%})")
    print("=" * 74)
    print(f"\n  HEADLINE: {n} bets · win rate {100*wins/n:.2f}% · ROI {roi:+.2f}%")
    print(f"  Bootstrap 95% CI on ROI: [{lo:+.2f}% , {hi:+.2f}%]")
    print(f"  -> {'SIGNIFICANT: the whole CI is above 0 (edge is real, not variance).' if lo > 0 else 'NOT significant: CI includes 0 — could be luck.'}")

    # 1) Monotonicity: do bigger predicted edges produce bigger realized ROI?
    print("\n  [1] ROI BY PREDICTED-EDGE BUCKET  (monotonic ⇒ the model genuinely predicts):")
    buckets = [(0.02, 0.03), (0.03, 0.05), (0.05, 0.08), (0.08, 0.12), (0.12, 9.0)]
    labels = ["2–3%", "3–5%", "5–8%", "8–12%", "12%+"]
    prev = None
    mono = True
    for (a, b), lab in zip(buckets, labels):
        bk = [x for x in bets if a <= x.edge < b]
        nn, wr, rr = _roi(bk)
        _bar(lab, nn, wr, rr)
        if nn >= 30:
            if prev is not None and rr < prev - 3:
                mono = False
            prev = rr
    print(f"   -> {'MONOTONIC-ish: realized ROI rises with predicted edge — real signal.' if mono else 'NON-monotonic — predicted edge is a weak signal; be cautious.'}")

    # 2) Out-of-sample stability by season
    print("\n  [2] ROI BY SEASON  (out-of-sample stability — does it hold every year?):")
    by_season = defaultdict(list)
    for x in bets:
        by_season[_season(x.event_date)].append(x)
    pos = 0
    for s in sorted(by_season):
        nn, wr, rr = _roi(by_season[s])
        _bar(s, nn, wr, rr)
        if rr > 0 and nn >= 30:
            pos += 1
    print(f"   -> {pos}/{sum(1 for s in by_season if len(by_season[s])>=30)} seasons (n≥30) profitable.")

    # 3) By market
    print("\n  [3] ROI BY MARKET:")
    by_mkt = defaultdict(list)
    for x in bets:
        by_mkt[x.market].append(x)
    for m in sorted(by_mkt, key=lambda k: -_roi(by_mkt[k])[2]):
        nn, wr, rr = _roi(by_mkt[m])
        _bar(m.replace("player_", ""), nn, wr, rr)

    # 4) Calibration — are the fair probabilities accurate?
    print("\n  [4] CALIBRATION  (predicted P(win) vs actual — diagonal = perfect):")
    edges = [(0.30, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 1.01)]
    brier = sum((b.fair_prob - (1.0 if b.won else 0.0)) ** 2 for b in bets) / n
    ece = 0.0
    for a, c in edges:
        bk = [x for x in bets if a <= x.fair_prob < c]
        if not bk:
            continue
        pred = sum(x.fair_prob for x in bk) / len(bk)
        act = sum(1 for x in bk if x.won) / len(bk)
        ece += len(bk) / n * abs(pred - act)
        print(f"   predicted {pred*100:4.1f}%  ->  actual {act*100:4.1f}%   (n={len(bk)})")
    print(f"   Brier score: {brier:.4f}  ·  Expected Calibration Error: {ece*100:.2f}%   (lower = better)")

    # 5) Risk
    print("\n  [5] RISK:")
    seq = [b.return_per_unit for b in sorted(bets, key=lambda x: (x.event_date or __import__('datetime').date.min))]
    cum, peak, maxdd, streak, worst_streak = 0.0, 0.0, 0, 0, 0
    for r in seq:
        cum += r
        peak = max(peak, cum)
        maxdd = max(maxdd, peak - cum)
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    mean = sum(returns) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / n)
    print(f"   max drawdown: {maxdd:.1f} units  ·  longest losing streak: {worst_streak} bets")
    print(f"   per-bet return {mean:+.3f} ± {sd:.3f}  ·  Sharpe (per bet) {mean/sd:.3f}")

    await close_pool()

    # 6) DFS forward-test — the real picks
    pool = await get_pool()
    try:
        rows = await pool.fetch("""
            SELECT source, count(*) FILTER (WHERE status='win') w,
                   count(*) FILTER (WHERE status IN ('win','miss')) g
            FROM tracked_picks WHERE sport='nba' GROUP BY source""")
        tot_w = sum(r["w"] for r in rows)
        tot_g = sum(r["g"] for r in rows)
        print("\n  [6] DFS FORWARD-TEST (real graded picks · breakeven 55%):")
        for r in sorted(rows, key=lambda r: -r["g"]):
            if r["g"]:
                lo2, hi2 = _wilson(r["w"], r["g"])
                print(f"   {r['source']:12s} {r['w']:3d}/{r['g']:3d} = {100*r['w']/r['g']:4.1f}%  95%CI[{lo2*100:.0f}–{hi2*100:.0f}%]")
        if tot_g:
            p = tot_w / tot_g
            lo2, hi2 = _wilson(tot_w, tot_g)
            z = (p - DFS_BREAKEVEN) / math.sqrt(DFS_BREAKEVEN * (1 - DFS_BREAKEVEN) / tot_g)
            pval = 1 - _ncdf(z)
            print(f"   OVERALL {tot_w}/{tot_g} = {p*100:.1f}%  95%CI[{lo2*100:.0f}–{hi2*100:.0f}%]")
            print(f"   vs 55% breakeven: z={z:+.2f}, p={pval:.3f}  -> "
                  f"{'beats breakeven, but ' if z>0 else 'below breakeven; '}"
                  f"{'NOT yet significant (need more picks).' if pval>0.05 else 'significant.'}")
    finally:
        await close_pool()
    print("\n" + "=" * 74)


if __name__ == "__main__":
    import sys
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 0.0))
