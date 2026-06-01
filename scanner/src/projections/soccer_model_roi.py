"""Soccer projection ROI — what would betting the model's picks ACTUALLY return.

Luke's bottom line: not just "how often was it right" but "what's the ROI." So we
bet the model's confident pick in each game AT THE REAL CLOSING PRICE and tally
the money. Priced markets we can settle honestly from the data:
  - Moneyline (1X2)            — best of consensus / Pinnacle
  - Over/Under 2.5 goals       — over25 / under25
  - Asian handicap (main line) — ah_home / ah_away, full quarter-line settlement

The model encodes the derivable half of Luke's 18-factor template (see
[[reference-betting-template]]): strength, home/away splits, form, rest, fixture
congestion, league standings (PPG), and head-to-head. Run --context to switch
those extras on over the goals baseline and compare. The factors we CAN'T feed
yet (injuries, lineups, suspensions, weather, travel distance, line movement) are
not faked — they need the SofaScore/geo layer and are flagged in memory.

Reports ROI + hit-rate, broken out by market, by confidence band, and for
selective betting (only when the model's prob beats the price).

Run: python -m src.projections.soccer_model_roi --context
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
PICK_LO, PICK_HI = 0.55, 0.92


def _best(*vals):
    xs = [float(v) for v in vals if v is not None and float(v) > 1.0]
    return max(xs) if xs else None


# ---- Asian-handicap settlement (handles half, integer-push, and quarter lines) ----
def _settle_half(r: float, dec: float) -> float:
    if r > 1e-9:
        return dec - 1.0
    if r < -1e-9:
        return -1.0
    return 0.0  # integer-line push: stake back


def _settle_ah(result: float, dec: float) -> float:
    frac = abs(result) % 1.0
    if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:  # quarter line -> split stake
        return 0.5 * _settle_half(result - 0.25, dec) + 0.5 * _settle_half(result + 0.25, dec)
    return _settle_half(result, dec)


def _ah_prob(M, line: float, home: bool) -> float:
    """Model probability the side covers (push counted as half)."""
    n = len(M)
    p = 0.0
    for i in range(n):
        for j in range(n):
            r = (i - j) + line if home else (j - i) - line
            frac = abs(r) % 1.0
            if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:
                wf = 0.5 * (1.0 if r - 0.25 > 0 else 0.5 if abs(r - 0.25) < 1e-9 else 0.0) \
                   + 0.5 * (1.0 if r + 0.25 > 0 else 0.5 if abs(r + 0.25) < 1e-9 else 0.0)
            else:
                wf = 1.0 if r > 1e-9 else 0.5 if abs(r) < 1e-9 else 0.0
            p += M[i][j] * wf
    return p


# ---- context factors (Luke's derivable template items) ----
def _rest_factor(r):
    if r is None: return 1.0
    if r >= 6: return 1.0
    if r <= 2: return 0.90
    return 0.90 + (r - 2) / 4.0 * 0.10

def _form_factor(g):
    return 1.0 if g is None else max(0.92, min(1.08, 1.0 + 0.05 * g))

def _ppg_factor(diff):
    return 1.0 if diff is None else max(0.94, min(1.06, 1.0 + 0.04 * diff))

def _h2h_factor(gd):
    return 1.0 if gd is None else max(0.96, min(1.04, 1.0 + 0.03 * gd))


async def run(from_year: int, to_year: int, use_context: bool, window_days: int = 550) -> None:
    configure_logging(level="WARNING")
    pool = await get_pool()
    try:
        allrows = await pool.fetch(
            """SELECT match_date, home_team, away_team, fthg, ftag
               FROM soccer_match_odds WHERE fthg IS NOT NULL ORDER BY match_date"""
        )
        tl: dict[str, dict[str, list]] = defaultdict(lambda: {"d": [], "gd": []})
        h2h: dict[tuple, list] = defaultdict(list)
        for r in allrows:
            h, a = r["home_team"], r["away_team"]
            gd = r["fthg"] - r["ftag"]
            tl[h]["d"].append(r["match_date"]); tl[h]["gd"].append(gd)
            tl[a]["d"].append(r["match_date"]); tl[a]["gd"].append(-gd)
            h2h[tuple(sorted((h, a)))].append((r["match_date"], h, gd))

        def ctx(team, d):
            t = tl.get(team)
            if not t: return None, None
            idx = bisect_left(t["d"], d)
            if idx == 0: return None, None
            rest = (d - t["d"][idx - 1]).days
            recent = t["gd"][max(0, idx - 5):idx]
            return rest, (sum(recent) / len(recent) if recent else None)

        def h2h_gd(home, away, d):
            ms = [(dt, hh, g) for dt, hh, g in h2h.get(tuple(sorted((home, away))), []) if dt < d]
            ms = ms[-5:]
            if len(ms) < 2: return None
            return sum(g if hh == home else -g for _, hh, g in ms) / len(ms)

        bets = defaultdict(lambda: {"n": 0, "win": 0, "ret": 0.0})       # by market
        bands = defaultdict(lambda: {"n": 0, "win": 0, "ret": 0.0})       # by confidence band
        overall = {"n": 0, "win": 0, "ret": 0.0}
        selective = {"n": 0, "win": 0, "ret": 0.0}                        # model prob > price

        for lg in LEAGUES:
            rows = await pool.fetch(
                """SELECT match_date, home_team, away_team, fthg, ftag, season,
                          odds_home, odds_draw, odds_away, pinnacle_home, pinnacle_draw, pinnacle_away,
                          over25, under25, ah_line, ah_home, ah_away
                   FROM soccer_match_odds
                   WHERE league_code=$1 AND fthg IS NOT NULL AND odds_home IS NOT NULL
                     AND match_date >= make_date($2 - 2, 1, 1) AND match_date <= make_date($3, 12, 31)
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
                    # league standings (PPG) from same-season prior matches
                    season = m["season"]
                    pts = defaultdict(lambda: [0, 0])  # team -> [points, games]
                    for x in prior:
                        if x["season"] != season:
                            continue
                        d = x["fthg"] - x["ftag"]
                        ph, pa = (3, 0) if d > 0 else (0, 3) if d < 0 else (1, 1)
                        pts[x["home_team"]][0] += ph; pts[x["home_team"]][1] += 1
                        pts[x["away_team"]][0] += pa; pts[x["away_team"]][1] += 1
                    def ppg(t):
                        v = pts.get(t)
                        return v[0] / v[1] if v and v[1] else None
                    pdiff = None
                    if ppg(m["home_team"]) is not None and ppg(m["away_team"]) is not None:
                        pdiff = ppg(m["home_team"]) - ppg(m["away_team"])
                    hg = h2h_gd(m["home_team"], m["away_team"], cutoff)
                    hadj = _rest_factor(rh) * _form_factor(fh) * _ppg_factor(pdiff) * _h2h_factor(hg)
                    aadj = _rest_factor(ra) * _form_factor(fa) * _ppg_factor(None if pdiff is None else -pdiff) * _h2h_factor(None if hg is None else -hg)
                eg = expected_goals(model, m["home_team"], m["away_team"], home_adj=hadj, away_adj=aadj)
                if not eg:
                    continue
                M = scoreline_matrix(*eg)
                gh, ga = m["fthg"], m["ftag"]
                n = len(M)
                p_home = sum(M[i2][j2] for i2 in range(n) for j2 in range(n) if i2 > j2)
                p_draw = sum(M[i2][i2] for i2 in range(n))
                p_away = sum(M[i2][j2] for i2 in range(n) for j2 in range(n) if i2 < j2)
                p_over = sum(M[i2][j2] for i2 in range(n) for j2 in range(n) if i2 + j2 >= 3)

                # candidate priced bets: (market, model_p, decimal, realised_return)
                cands = [
                    ("moneyline", p_home, _best(m["odds_home"], m["pinnacle_home"]), (_best(m["odds_home"], m["pinnacle_home"]) or 1) - 1 if gh > ga else -1.0),
                    ("moneyline", p_draw, _best(m["odds_draw"], m["pinnacle_draw"]), (_best(m["odds_draw"], m["pinnacle_draw"]) or 1) - 1 if gh == ga else -1.0),
                    ("moneyline", p_away, _best(m["odds_away"], m["pinnacle_away"]), (_best(m["odds_away"], m["pinnacle_away"]) or 1) - 1 if gh < ga else -1.0),
                ]
                if m["over25"] and m["under25"]:
                    cands.append(("total", p_over, float(m["over25"]), float(m["over25"]) - 1 if gh + ga >= 3 else -1.0))
                    cands.append(("total", 1 - p_over, float(m["under25"]), float(m["under25"]) - 1 if gh + ga <= 2 else -1.0))
                if m["ah_home"] and m["ah_away"] and m["ah_line"] is not None:
                    L = float(m["ah_line"])
                    cands.append(("spread", _ah_prob(M, L, True), float(m["ah_home"]), _settle_ah((gh - ga) + L, float(m["ah_home"]))))
                    cands.append(("spread", _ah_prob(M, L, False), float(m["ah_away"]), _settle_ah((ga - gh) - L, float(m["ah_away"]))))

                # the model's single most confident pick in the band, at a real price
                pick = None
                for mk, p, dec, ret in cands:
                    if dec is None or not (PICK_LO <= p <= PICK_HI):
                        continue
                    if pick is None or p > pick[1]:
                        pick = (mk, p, dec, ret)
                if pick is None:
                    continue
                mk, p, dec, ret = pick
                won = ret > 1e-9
                band = f"{int(p*20)*5}-{int(p*20)*5+5}%"
                for box in (overall, bets[mk], bands[band]):
                    box["n"] += 1; box["ret"] += ret; box["win"] += int(won)
                if p > 1.0 / dec:  # model thinks it's underpriced
                    selective["n"] += 1; selective["ret"] += ret; selective["win"] += int(won)

        # ---- report ----
        tag = "WITH context (rest/form/standings/H2H)" if use_context else "baseline (goals only)"
        roi = lambda b: 100 * b["ret"] / b["n"] if b["n"] else 0.0
        wr = lambda b: 100 * b["win"] / b["n"] if b["n"] else 0.0
        print(f"\n  SOCCER MODEL ROI · big-5 · {from_year}-{to_year} · {tag}")
        print(f"  Betting the model's confident pick at the real closing price.")
        print("  " + "═" * 60)
        print(f"  ► ALL PICKS   n={overall['n']:,}   hit={wr(overall):.1f}%   ROI={roi(overall):+.2f}%  {'🟢' if roi(overall)>0 else '🔴'}")
        print(f"\n  by market:")
        for mk in ("moneyline", "total", "spread"):
            b = bets[mk]
            if b["n"]:
                print(f"      {mk:10s} n={b['n']:>6,}  hit={wr(b):5.1f}%  ROI={roi(b):+7.2f}%")
        print(f"\n  by model confidence:")
        for band in sorted(bands):
            b = bands[band]
            if b["n"] >= 50:
                print(f"      {band:8s} n={b['n']:>6,}  hit={wr(b):5.1f}%  ROI={roi(b):+7.2f}%")
        print(f"\n  selective (only when model prob > price-implied):")
        print(f"      n={selective['n']:,}  hit={wr(selective):.1f}%  ROI={roi(selective):+.2f}%  {'🟢' if roi(selective)>0 else '🔴'}")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--context", action="store_true")
    p.add_argument("--from-year", type=int, default=2018)
    p.add_argument("--to-year", type=int, default=2025)
    a = p.parse_args()
    asyncio.run(run(a.from_year, a.to_year, a.context))
