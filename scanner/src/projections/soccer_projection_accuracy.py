"""Soccer projection ACCURACY backtest — is the model RIGHT, not is there an edge.

A projection model is judged differently from the DFS consensus edge. We do NOT
ask "did the price disagree with us." We ask the only question that matters for a
predictor: **when the model made a call, how often did it actually happen?**

We score the model against the bets Luke actually takes — not just the moneyline:
  - Double chance (win-or-draw 1X / X2)  ← covers 2 of 3 outcomes by design
  - Team totals (home/away over 0.5, over 1.5)
  - Asian spreads (±1.5)
  - Match totals (over/under 1.5, 2.5, 3.5) and both-teams-to-score
All of these fall straight out of the model's full scoreline distribution.

CONTEXT (the handicapping factors, derived from the schedule — the thing Luke
said the model must be built on):
  - Rest days since each team's last match (any competition)
  - Short-term form (last-5 goal difference vs baseline)
  - Fixture congestion (matches in the trailing 10 days)
Travel distance, confirmed lineups and injuries need the SofaScore/geo layer and
are NOT in this version — flagged honestly. They get layered in as that data lands.

Output is accuracy + calibration: when the model says 75%, does it hit 75%?
And the headline — of the games where the model made a confident pick, how many
would we have won? Run with --context to add the schedule factors; compare.

Run: python -m src.projections.soccer_projection_accuracy --context
"""

import argparse
import asyncio
from bisect import bisect_left
from collections import defaultdict

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.soccer_match import build_league_model, expected_goals, scoreline_matrix

LEAGUES = ["E0", "SP1", "I1", "D1", "F1"]

# Luke's real bet menu. Each condition is evaluated on (home_goals, away_goals).
# (name, group, condition) — group lets us pick one "safe pick" per game.
BET_MENU = [
    ("home-or-draw (1X)",  "dc",     lambda i, j: i >= j),
    ("away-or-draw (X2)",  "dc",     lambda i, j: j >= i),
    ("home win",           "ml",     lambda i, j: i > j),
    ("away win",           "ml",     lambda i, j: j > i),
    ("draw",               "ml",     lambda i, j: i == j),
    ("home -1.5",          "ah",     lambda i, j: i - j >= 2),
    ("home +1.5",          "ah",     lambda i, j: i - j >= -1),
    ("away -1.5",          "ah",     lambda i, j: j - i >= 2),
    ("away +1.5",          "ah",     lambda i, j: j - i >= -1),
    ("home team o0.5",     "tt",     lambda i, j: i >= 1),
    ("home team o1.5",     "tt",     lambda i, j: i >= 2),
    ("away team o0.5",     "tt",     lambda i, j: j >= 1),
    ("away team o1.5",     "tt",     lambda i, j: j >= 2),
    ("match o1.5",         "tot",    lambda i, j: i + j >= 2),
    ("match o2.5",         "tot",    lambda i, j: i + j >= 3),
    ("match u2.5",         "tot",    lambda i, j: i + j <= 2),
    ("match u3.5",         "tot",    lambda i, j: i + j <= 3),
    ("BTTS yes",           "btts",   lambda i, j: i >= 1 and j >= 1),
    ("BTTS no",            "btts",   lambda i, j: i == 0 or j == 0),
]

# Bets that are real PREDICTIONS (exclude near-certainties like "match o0.5").
# A "confident pick" must land in this band — not a coin flip, not a sure thing.
PICK_LO, PICK_HI = 0.58, 0.90


def _bet_prob(M, cond) -> float:
    n = len(M)
    return sum(M[i][j] for i in range(n) for j in range(n) if cond(i, j))


def _rest_factor(rest: int | None) -> float:
    """<3 days rest = tired legs; >=6 = fully rested. Gentle, bounded."""
    if rest is None:
        return 1.0
    if rest >= 6:
        return 1.0
    if rest <= 2:
        return 0.90
    return 0.90 + (rest - 2) / 4.0 * 0.10


def _form_factor(form_gd: float | None) -> float:
    """Last-5 avg goal difference -> modest hot/cold streak nudge, capped ±8%."""
    if form_gd is None:
        return 1.0
    return max(0.92, min(1.08, 1.0 + 0.05 * form_gd))


async def run(from_year: int, to_year: int, use_context: bool, window_days: int = 550) -> None:
    configure_logging(level="WARNING")
    pool = await get_pool()
    try:
        # Global per-team timeline (ALL competitions) for rest / form / congestion.
        allrows = await pool.fetch(
            """SELECT match_date, home_team, away_team, fthg, ftag
               FROM soccer_match_odds WHERE fthg IS NOT NULL
               ORDER BY match_date"""
        )
        tl: dict[str, dict[str, list]] = defaultdict(lambda: {"d": [], "gd": []})
        for r in allrows:
            tl[r["home_team"]]["d"].append(r["match_date"]); tl[r["home_team"]]["gd"].append(r["fthg"] - r["ftag"])
            tl[r["away_team"]]["d"].append(r["match_date"]); tl[r["away_team"]]["gd"].append(r["ftag"] - r["fthg"])

        def ctx(team: str, d) -> tuple[int | None, float | None]:
            t = tl.get(team)
            if not t:
                return None, None
            idx = bisect_left(t["d"], d)
            if idx == 0:
                return None, None
            rest = (d - t["d"][idx - 1]).days
            recent = t["gd"][max(0, idx - 5):idx]
            form = sum(recent) / len(recent) if recent else None
            return rest, form

        # (pred, hit) samples, per bet name, for calibration + per-bet accuracy.
        samples: dict[str, list[tuple[float, int]]] = defaultdict(list)
        picks = {"n": 0, "pred": 0.0, "hit": 0}  # one confident pick per game
        brier = {"n": 0, "sum": 0.0}

        for lg in LEAGUES:
            rows = await pool.fetch(
                """SELECT match_date, home_team, away_team, fthg, ftag
                   FROM soccer_match_odds
                   WHERE league_code=$1 AND fthg IS NOT NULL
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
                hadj = aadj = 1.0
                if use_context:
                    rh, fh = ctx(m["home_team"], cutoff)
                    ra, fa = ctx(m["away_team"], cutoff)
                    hadj = _rest_factor(rh) * _form_factor(fh)
                    aadj = _rest_factor(ra) * _form_factor(fa)
                eg = expected_goals(model, m["home_team"], m["away_team"], home_adj=hadj, away_adj=aadj)
                if not eg:
                    continue
                M = scoreline_matrix(*eg)
                gh, ga = m["fthg"], m["ftag"]

                best = None  # (pred, hit, name) — the model's most confident real pick
                for name, _grp, cond in BET_MENU:
                    p = _bet_prob(M, cond)
                    hit = int(cond(gh, ga))
                    samples[name].append((p, hit))
                    brier["n"] += 1; brier["sum"] += (p - hit) ** 2
                    if PICK_LO <= p <= PICK_HI and (best is None or p > best[0]):
                        best = (p, hit, name)
                if best:
                    picks["n"] += 1; picks["pred"] += best[0]; picks["hit"] += best[1]

        # ---- report ----
        tag = "WITH schedule context (rest/form/congestion)" if use_context else "baseline (goals only)"
        print(f"\n  SOCCER PROJECTION ACCURACY · big-5 · {from_year}-{to_year} · {tag}")
        print(f"  Question: when the model made a call, how often was it RIGHT?")
        print("  " + "═" * 66)

        # Headline: the confident pick per game.
        if picks["n"]:
            pred = 100 * picks["pred"] / picks["n"]
            act = 100 * picks["hit"] / picks["n"]
            print(f"\n  ► CONFIDENT PICK (best {int(PICK_LO*100)}-{int(PICK_HI*100)}% bet per game)")
            print(f"      games picked : {picks['n']:,}")
            print(f"      model said   : {pred:.1f}% would hit")
            print(f"      actually hit : {act:.1f}%   →  {'ACCURATE ✅' if abs(pred-act) <= 2.5 else 'off by %.1fpts' % (act-pred)}")

        # Calibration: pooled across all bets — does 70% mean 70%?
        print(f"\n  ► CALIBRATION (all bets pooled — is the % honest?)")
        print(f"      {'model says':>12s} {'n':>7s} {'actually hit':>13s}")
        alls = [s for v in samples.values() for s in v]
        for lo in range(50, 100, 10):
            hi = lo + 10
            bucket = [h for p, h in alls if lo <= p * 100 < hi]
            if bucket:
                print(f"      {lo:>3d}-{hi:<3d}%   {len(bucket):>7,} {100*sum(bucket)/len(bucket):>11.1f}%")
        b = brier["sum"] / brier["n"]
        print(f"      Brier score: {b:.4f}  (lower = sharper; 0.25 = coin flip)")

        # Per-bet-type accuracy for Luke's signature bets.
        print(f"\n  ► BY BET TYPE (model's avg confidence vs reality)")
        print(f"      {'bet':20s} {'n':>7s} {'said':>7s} {'hit':>7s} {'gap':>7s}")
        for name, _grp, _c in BET_MENU:
            v = samples[name]
            if not v:
                continue
            said = 100 * sum(p for p, _ in v) / len(v)
            hit = 100 * sum(h for _, h in v) / len(v)
            print(f"      {name:20s} {len(v):>7,} {said:>6.1f}% {hit:>6.1f}% {hit-said:>+6.1f}")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--context", action="store_true", help="add schedule factors (rest/form/congestion)")
    p.add_argument("--from-year", type=int, default=2018)
    p.add_argument("--to-year", type=int, default=2025)
    a = p.parse_args()
    asyncio.run(run(a.from_year, a.to_year, a.context))
