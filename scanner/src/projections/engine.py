"""Baseline projection engine.

Pure function: recent game samples + matchup context → projected (mean, std,
distribution, P(over line)). No I/O.

Adjustments (baseline v1):
  - Opponent defense: scoring stats only (points, pra, threes). factor =
    opp_def_rating / league_avg_def_rating. Higher opp def_rating = weaker
    defense (more points allowed) = boost.
  - Pace: all stats. factor = opp_pace / league_avg_pace. More possessions =
    more counting events.
  - Rest: 0.96 multiplier on a back-to-back.

News adjustments (injury_out etc.) are NOT handled here — Plan 3 adds them.
"""

import statistics
from dataclasses import dataclass

from src.math.distributions import STAT_DISTRIBUTIONS, fair_prob_over

MIN_SAMPLES = 5
B2B_MULTIPLIER = 0.96
SCORING_STATS = {"points", "pra", "threes"}


@dataclass(frozen=True, slots=True)
class StatSample:
    points: int
    rebounds: int
    assists: int
    threes: int
    blocks: int
    steals: int


@dataclass(frozen=True, slots=True)
class Projection:
    mean: float
    std: float
    distribution: str
    fair_prob_over: float


def extract_stat(sample: StatSample, stat: str) -> float:
    if stat == "pra":
        return sample.points + sample.rebounds + sample.assists
    if stat in ("points", "rebounds", "assists", "threes", "blocks", "steals"):
        return getattr(sample, stat)
    raise ValueError(f"unknown stat: {stat!r}")


def project(
    *,
    samples: list[StatSample],
    stat: str,
    line: float,
    opp_def_rating: float,
    league_avg_def_rating: float,
    opp_pace: float,
    league_avg_pace: float,
    is_b2b: bool,
) -> Projection | None:
    """Return a Projection, or None if not enough samples."""
    if stat not in STAT_DISTRIBUTIONS and stat != "pra":
        raise ValueError(f"unknown stat: {stat!r}")
    if len(samples) < MIN_SAMPLES:
        return None

    values = [extract_stat(s, stat) for s in samples]
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 1.0
    if std <= 0:
        std = 1.0

    # Pace adjustment (all stats)
    if league_avg_pace > 0:
        mean *= opp_pace / league_avg_pace

    # Opponent defense adjustment (scoring stats only)
    if stat in SCORING_STATS and league_avg_def_rating > 0:
        mean *= opp_def_rating / league_avg_def_rating

    # Rest
    if is_b2b:
        mean *= B2B_MULTIPLIER

    distribution = STAT_DISTRIBUTIONS["points"] if stat == "pra" else STAT_DISTRIBUTIONS[stat]
    prob = fair_prob_over(mean=mean, std=std, line=line, distribution=distribution)
    return Projection(mean=mean, std=std, distribution=distribution, fair_prob_over=prob)
