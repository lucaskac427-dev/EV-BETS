"""Tests for the baseline projection engine."""

import math

import pytest

from src.projections.engine import StatSample, project

# Synthetic samples: 10 games of points for a ~25 PPG scorer.
POINTS_SAMPLES = [
    StatSample(points=24, rebounds=8, assists=7, threes=2, blocks=1, steals=1),
    StatSample(points=28, rebounds=7, assists=9, threes=3, blocks=0, steals=2),
    StatSample(points=22, rebounds=9, assists=6, threes=1, blocks=1, steals=0),
    StatSample(points=30, rebounds=6, assists=8, threes=4, blocks=2, steals=1),
    StatSample(points=26, rebounds=8, assists=7, threes=2, blocks=1, steals=1),
    StatSample(points=20, rebounds=10, assists=5, threes=1, blocks=0, steals=2),
    StatSample(points=27, rebounds=7, assists=9, threes=3, blocks=1, steals=1),
    StatSample(points=25, rebounds=8, assists=8, threes=2, blocks=1, steals=0),
    StatSample(points=23, rebounds=9, assists=6, threes=2, blocks=0, steals=1),
    StatSample(points=29, rebounds=6, assists=10, threes=4, blocks=2, steals=1),
]

# Neutral matchup: opponent exactly league-average, normal pace, not B2B.
NEUTRAL = dict(
    opp_def_rating=113.0, league_avg_def_rating=113.0,
    opp_pace=99.0, league_avg_pace=99.0, is_b2b=False,
)


def test_points_projection_mean_near_sample_mean():
    # sample mean = 25.4
    result = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **NEUTRAL)
    assert math.isclose(result.mean, 25.4, abs_tol=0.1)
    assert result.distribution == "normal"
    assert 0.5 < result.fair_prob_over < 0.65  # mean above line → over likelier


def test_rebounds_use_negative_binomial():
    result = project(samples=POINTS_SAMPLES, stat="rebounds", line=7.5, **NEUTRAL)
    assert result.distribution == "negative_binomial"
    # rebounds sample mean = 7.8 → slightly over 7.5
    assert result.fair_prob_over > 0.5


def test_pra_sums_three_stats():
    # PRA mean = points(25.4) + reb(7.8) + ast(7.5) = 40.7
    result = project(samples=POINTS_SAMPLES, stat="pra", line=39.5, **NEUTRAL)
    assert math.isclose(result.mean, 40.7, abs_tol=0.2)
    assert result.distribution == "normal"


def test_tough_defense_lowers_scoring_projection():
    # Opponent allows FEWER points (lower def_rating) → projection drops below neutral.
    tough = dict(NEUTRAL, opp_def_rating=105.0)  # better defense than 113 avg
    neutral = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **NEUTRAL)
    vs_tough = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **tough)
    assert vs_tough.mean < neutral.mean


def test_back_to_back_lowers_projection():
    b2b = dict(NEUTRAL, is_b2b=True)
    rested = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **NEUTRAL)
    tired = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **b2b)
    assert tired.mean < rested.mean
    assert math.isclose(tired.mean, rested.mean * 0.96, abs_tol=0.01)


def test_high_pace_raises_projection():
    fast = dict(NEUTRAL, opp_pace=104.0)  # faster than 99 avg
    neutral = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **NEUTRAL)
    vs_fast = project(samples=POINTS_SAMPLES, stat="points", line=24.5, **fast)
    assert vs_fast.mean > neutral.mean


def test_too_few_samples_returns_none():
    result = project(samples=POINTS_SAMPLES[:2], stat="points", line=24.5, **NEUTRAL)
    assert result is None  # need >= MIN_SAMPLES


def test_unknown_stat_raises():
    with pytest.raises(ValueError, match="unknown stat"):
        project(samples=POINTS_SAMPLES, stat="dunks", line=1.5, **NEUTRAL)
