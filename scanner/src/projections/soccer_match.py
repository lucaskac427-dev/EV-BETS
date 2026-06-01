"""Soccer match projection — time-weighted Poisson goals model.

The canonical fundamentals model for match outcomes (Dixon-Coles family,
independent-Poisson core). Turns the derivable handicapping factors into a
full scoreline distribution, from which EVERY match-market probability falls
out: 1X2, double chance (win-or-draw), match totals, team totals, BTTS.

Factors captured directly from our 304K-match dataset:
  - Team attacking & defensive strength (goals for / against vs league)
  - Home / away split (separate home & away strength + home advantage)
  - Recent form (exponential time-decay weighting toward recent matches)
  - Opponent quality (strength × opponent-weakness in the rate)
  - Standings/season record (implicit in the strength ratings)
  - Head-to-head (optional pairwise nudge)

Factors that need external data / judgement (NOT modeled here; exposed as
manual multiplicative adjustments the caller can pass in):
  - Injuries, suspensions, confirmed lineups
  - Travel / rest, weather, elevation, attendance
  - Motivation (must-win, relegation, dead rubber)
These are real and often decisive — the model gives the statistical baseline;
the caller layers judgement on top via `home_adj` / `away_adj`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date


@dataclass
class TeamRating:
    home_attack: float = 1.0
    home_defense: float = 1.0
    away_attack: float = 1.0
    away_defense: float = 1.0
    matches: int = 0


@dataclass
class LeagueModel:
    avg_home_goals: float
    avg_away_goals: float
    ratings: dict[str, TeamRating] = field(default_factory=dict)


def _decay_weight(days_ago: float, half_life_days: float) -> float:
    return 0.5 ** (days_ago / half_life_days)


def build_league_model(
    matches: list[dict],
    *,
    as_of: date,
    half_life_days: float = 180.0,
) -> LeagueModel:
    """matches: list of {match_date, home_team, away_team, fthg, ftag} strictly
    BEFORE as_of (caller enforces — keeps the model walk-forward honest)."""
    # League baselines (time-weighted)
    wsum = whg = wag = 0.0
    for m in matches:
        if m["fthg"] is None or m["ftag"] is None:
            continue
        w = _decay_weight((as_of - m["match_date"]).days, half_life_days)
        wsum += w
        whg += w * m["fthg"]
        wag += w * m["ftag"]
    if wsum <= 0:
        return LeagueModel(1.4, 1.1)
    avg_home = whg / wsum
    avg_away = wag / wsum
    avg_home = max(avg_home, 0.2)
    avg_away = max(avg_away, 0.2)

    # Per-team weighted goals for/against in home & away contexts
    acc: dict[str, dict[str, float]] = {}
    for m in matches:
        if m["fthg"] is None or m["ftag"] is None:
            continue
        w = _decay_weight((as_of - m["match_date"]).days, half_life_days)
        h, a = m["home_team"], m["away_team"]
        for t in (h, a):
            acc.setdefault(t, {"hgf": 0, "hga": 0, "hw": 0, "agf": 0, "aga": 0, "aw": 0, "n": 0})
        acc[h]["hgf"] += w * m["fthg"]; acc[h]["hga"] += w * m["ftag"]; acc[h]["hw"] += w
        acc[a]["agf"] += w * m["ftag"]; acc[a]["aga"] += w * m["fthg"]; acc[a]["aw"] += w
        acc[h]["n"] += 1; acc[a]["n"] += 1

    ratings: dict[str, TeamRating] = {}
    for t, d in acc.items():
        # Shrink toward league average when sample is thin (Bayesian-ish)
        SHRINK = 2.0
        hgf = (d["hgf"] + SHRINK * avg_home) / (d["hw"] + SHRINK)
        hga = (d["hga"] + SHRINK * avg_away) / (d["hw"] + SHRINK)
        agf = (d["agf"] + SHRINK * avg_away) / (d["aw"] + SHRINK)
        aga = (d["aga"] + SHRINK * avg_home) / (d["aw"] + SHRINK)
        ratings[t] = TeamRating(
            home_attack=hgf / avg_home,
            home_defense=hga / avg_away,
            away_attack=agf / avg_away,
            away_defense=aga / avg_home,
            matches=d["n"],
        )
    return LeagueModel(avg_home, avg_away, ratings)


def expected_goals(
    model: LeagueModel, home: str, away: str,
    *, home_adj: float = 1.0, away_adj: float = 1.0,
) -> tuple[float, float] | None:
    rh = model.ratings.get(home)
    ra = model.ratings.get(away)
    if rh is None or ra is None:
        return None
    lam_home = model.avg_home_goals * rh.home_attack * ra.away_defense * home_adj
    lam_away = model.avg_away_goals * ra.away_attack * rh.home_defense * away_adj
    return max(lam_home, 0.05), max(lam_away, 0.05)


def _pois(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


# Dixon-Coles low-score dependency correction. Independent Poisson under-counts
# 0-0 / 1-1 and over-counts 1-0 / 0-1; tau re-weights the four low-score cells.
# rho ~ -0.13 is the canonical fitted value across European leagues.
DC_RHO = -0.13


def _dc_tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    if i == 0 and j == 0:
        return 1.0 - lam * mu * rho
    if i == 0 and j == 1:
        return 1.0 + lam * rho
    if i == 1 and j == 0:
        return 1.0 + mu * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def scoreline_matrix(lam_home: float, lam_away: float, max_goals: int = 10,
                     rho: float = DC_RHO):
    ph = [_pois(i, lam_home) for i in range(max_goals + 1)]
    pa = [_pois(j, lam_away) for j in range(max_goals + 1)]
    M = [[ph[i] * pa[j] * _dc_tau(i, j, lam_home, lam_away, rho)
          for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    # Re-normalize (tau perturbs the total mass slightly)
    s = sum(M[i][j] for i in range(max_goals + 1) for j in range(max_goals + 1))
    if s > 0:
        M = [[M[i][j] / s for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    return M


def market_probs(lam_home: float, lam_away: float) -> dict[str, float]:
    M = scoreline_matrix(lam_home, lam_away)
    n = len(M)
    home_win = sum(M[i][j] for i in range(n) for j in range(n) if i > j)
    draw = sum(M[i][i] for i in range(n))
    away_win = sum(M[i][j] for i in range(n) for j in range(n) if i < j)
    total_over = lambda x: sum(M[i][j] for i in range(n) for j in range(n) if i + j > x)
    home_goals = lambda x: sum(M[i][j] for i in range(n) for j in range(n) if i > x)
    away_goals = lambda x: sum(M[i][j] for i in range(n) for j in range(n) if j > x)
    btts = sum(M[i][j] for i in range(1, n) for j in range(1, n))
    return {
        "home_win": home_win, "draw": draw, "away_win": away_win,
        "home_or_draw": home_win + draw, "away_or_draw": away_win + draw,
        "home_or_away": home_win + away_win,
        "over_0.5": total_over(0), "over_1.5": total_over(1),
        "over_2.5": total_over(2), "over_3.5": total_over(3),
        "home_over_0.5": home_goals(0), "home_over_1.5": home_goals(1),
        "away_over_0.5": away_goals(0), "away_over_1.5": away_goals(1),
        "btts": btts,
        "exp_home_goals": lam_home, "exp_away_goals": lam_away,
    }
