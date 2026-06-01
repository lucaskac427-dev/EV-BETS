"""Soccer game-line (1X2) PROJECTION backtest — does OUR model beat the market?

Walk-forward and leak-free: for each match we build the calibrated Poisson league
model from ONLY prior matches, project home/draw/away fair probabilities, and bet
any outcome where `model_prob × best_market_decimal − 1 ≥ threshold`. Then grade
against the actual full-time result and report ROI.

This is System 2 (our own number) vs the soccer market — distinct from the
consensus-arb. The model is calibration-proven (beats climatology on big-5 1X2);
this measures whether that calibration converts to betting profit. Honest numbers,
no fudge. Run on the big-5 (the calibration-verified leagues).

Run: python -m src.projections.soccer_gameline_backtest --threshold 0.05
"""

import argparse
import asyncio
from collections import defaultdict

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.soccer_match import build_league_model, expected_goals, market_probs

LEAGUES = ["E0", "SP1", "I1", "D1", "F1"]  # big-5 main divisions (calibration-verified)


def _best(*vals) -> float | None:
    xs = [float(v) for v in vals if v is not None and float(v) > 1.0]
    return max(xs) if xs else None


async def run(threshold: float, from_year: int, to_year: int, window_days: int = 550) -> None:
    configure_logging(level="WARNING")
    pool = await get_pool()
    agg = defaultdict(lambda: {"n": 0, "wins": 0, "ret": 0.0, "edge": 0.0})
    try:
        for lg in LEAGUES:
            rows = await pool.fetch(
                """SELECT match_date, home_team, away_team, fthg, ftag,
                          odds_home, odds_draw, odds_away,
                          pinnacle_home, pinnacle_draw, pinnacle_away
                   FROM soccer_match_odds
                   WHERE league_code=$1 AND fthg IS NOT NULL AND odds_home IS NOT NULL
                     AND match_date >= make_date($2 - 2, 1, 1)
                     AND match_date <= make_date($3, 12, 31)
                   ORDER BY match_date""",
                lg, from_year, to_year,
            )
            ms = [dict(r) for r in rows]
            for i, m in enumerate(ms):
                if m["match_date"].year < from_year:
                    continue
                cutoff = m["match_date"]
                prior = [x for x in ms[:i] if (cutoff - x["match_date"]).days <= window_days]
                if len(prior) < 100:
                    continue
                model = build_league_model(prior, as_of=cutoff)
                eg = expected_goals(model, m["home_team"], m["away_team"])
                if not eg:
                    continue
                mp = market_probs(*eg)
                model_p = {"home": mp["home_win"], "draw": mp["draw"], "away": mp["away_win"]}
                price = {
                    "home": _best(m["odds_home"], m["pinnacle_home"]),
                    "draw": _best(m["odds_draw"], m["pinnacle_draw"]),
                    "away": _best(m["odds_away"], m["pinnacle_away"]),
                }
                gh, ga = m["fthg"], m["ftag"]
                actual = "home" if gh > ga else "away" if gh < ga else "draw"
                for side in ("home", "draw", "away"):
                    dec = price[side]
                    if dec is None:
                        continue
                    edge = model_p[side] * dec - 1.0
                    if edge < threshold:
                        continue
                    won = side == actual
                    ret = (dec - 1.0) if won else -1.0
                    for key in (side, "ALL"):
                        a = agg[key]
                        a["n"] += 1
                        a["edge"] += edge
                        a["wins"] += int(won)
                        a["ret"] += ret
            log.info("soccer_gl_league_done", league=lg, n=agg["ALL"]["n"])

        print(f"\n  SOCCER GAME-LINE PROJECTION BACKTEST · big-5 · {from_year}-{to_year} · edge≥{threshold*100:.0f}%")
        print(f"  (our Poisson model vs best market price, leak-free walk-forward)")
        print("  " + "─" * 64)
        print(f"  {'outcome':8s} {'bets':>6s} {'win%':>6s} {'ROI':>8s} {'avg edge':>9s}")
        for key in ("home", "draw", "away", "ALL"):
            a = agg[key]
            if not a["n"]:
                continue
            roi = 100 * a["ret"] / a["n"]
            wr = 100 * a["wins"] / a["n"]
            verdict = " 🟢" if roi > 0 else " 🔴"
            print(f"  {key:8s} {a['n']:6d} {wr:5.1f}% {roi:+7.2f}% {100*a['edge']/a['n']:+8.2f}%{verdict if key=='ALL' else ''}")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=float, default=0.05)
    p.add_argument("--from-year", type=int, default=2016)
    p.add_argument("--to-year", type=int, default=2025)
    a = p.parse_args()
    asyncio.run(run(a.threshold, a.from_year, a.to_year))
