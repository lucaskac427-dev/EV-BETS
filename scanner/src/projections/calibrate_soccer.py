"""Walk-forward calibration of the soccer match Poisson model.

For every match in the test window, we build the model using ONLY prior
matches (no leakage), predict the market probabilities, and record
(prediction, actual_outcome). Then:

  - Reliability bins: does the "70%" bucket actually win ~70%?
  - Brier score: mean squared error of the probabilistic forecast (lower
    is better). Compared against the climatology baseline (always predict
    the base rate) — beating it means the model carries real information.
  - ECE: expected calibration error (avg gap between predicted & realized).

A model that's well-calibrated AND beats climatology is trustworthy to
blend. One that isn't makes EV worse and must not be trusted.

Run: python -m src.projections.calibrate_soccer
"""

import argparse
import asyncio
from collections import defaultdict

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.soccer_match import build_league_model, expected_goals, market_probs

LEAGUES = ["E0", "SP1", "I1", "D1", "F1"]  # big-5 main divisions


def _brier(pairs: list[tuple[float, int]]) -> float:
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs) if pairs else 0.0


def _reliability(pairs: list[tuple[float, int]], bins: int = 10):
    buckets = defaultdict(lambda: [0.0, 0, 0])  # sum_pred, count, wins
    for p, o in pairs:
        b = min(bins - 1, int(p * bins))
        buckets[b][0] += p
        buckets[b][1] += 1
        buckets[b][2] += o
    out = []
    ece = 0.0
    n = len(pairs)
    for b in range(bins):
        s, c, w = buckets[b]
        if c == 0:
            continue
        pred = s / c
        realized = w / c
        out.append((pred, realized, c))
        ece += (c / n) * abs(pred - realized)
    return out, ece


async def run(from_year: int = 2016, to_year: int = 2025, window_days: int = 550):
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        markets = {"home_win": [], "draw": [], "away_win": [], "over_2.5": []}
        climatology = {"home_win": [], "draw": [], "away_win": [], "over_2.5": []}

        for lg in LEAGUES:
            matches = await pool.fetch(
                """SELECT match_date, home_team, away_team, fthg, ftag
                   FROM soccer_match_odds
                   WHERE league_code=$1 AND fthg IS NOT NULL
                     AND match_date >= make_date($2 - 2, 1, 1)
                     AND match_date <= make_date($3, 12, 31)
                   ORDER BY match_date""",
                lg, from_year, to_year,
            )
            ms = [dict(r) for r in matches]
            for i, m in enumerate(ms):
                if m["match_date"].year < from_year:
                    continue
                cutoff = m["match_date"]
                prior = [x for x in ms[:i]
                         if (cutoff - x["match_date"]).days <= window_days]
                if len(prior) < 100:
                    continue
                model = build_league_model(prior, as_of=cutoff)
                eg = expected_goals(model, m["home_team"], m["away_team"])
                if not eg:
                    continue
                mp = market_probs(*eg)
                gh, ga = m["fthg"], m["ftag"]
                outcomes = {
                    "home_win": 1 if gh > ga else 0,
                    "draw": 1 if gh == ga else 0,
                    "away_win": 1 if gh < ga else 0,
                    "over_2.5": 1 if gh + ga > 2 else 0,
                }
                for k in markets:
                    markets[k].append((mp[k], outcomes[k]))
            log.info("calib_league_done", league=lg, n=len(markets["home_win"]))

        # Climatology baseline = overall base rate per market
        base = {k: (sum(o for _, o in v) / len(v) if v else 0) for k, v in markets.items()}

        print("\n" + "=" * 70)
        print(f"  SOCCER MATCH MODEL CALIBRATION · {from_year}-{to_year} · big-5")
        print(f"  Total predictions per market: {len(markets['home_win']):,}")
        print("=" * 70)
        for k in ["home_win", "draw", "away_win", "over_2.5"]:
            pairs = markets[k]
            brier = _brier(pairs)
            clim = [(base[k], o) for _, o in pairs]
            brier_clim = _brier(clim)
            rel, ece = _reliability(pairs)
            skill = 100 * (1 - brier / brier_clim) if brier_clim else 0
            verdict = "🟢 beats baseline" if brier < brier_clim else "🔴 worse than baseline"
            print(f"\n  {k.upper()}  (base rate {base[k]*100:.1f}%)")
            print(f"    Brier {brier:.4f} vs climatology {brier_clim:.4f}  →  skill {skill:+.1f}%  {verdict}")
            print(f"    ECE (calibration error): {ece*100:.2f}%  (lower=better; <3% is well-calibrated)")
            print(f"    reliability (predicted → realized):")
            for pred, realized, c in rel:
                bar = "█" * int(realized * 30)
                print(f"      {pred*100:5.1f}% → {realized*100:5.1f}%  (n={c:5d}) {bar}")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from-year", type=int, default=2016)
    p.add_argument("--to-year", type=int, default=2025)
    a = p.parse_args()
    asyncio.run(run(a.from_year, a.to_year))
