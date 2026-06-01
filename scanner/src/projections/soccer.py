"""Soccer per-player projection model.

Crude first pass. For a given (player, stat, line):

  1. Pull the player's last N matches from soccer_player_match_stats
     (joined by normalized name slug — so 'Vinícius Júnior' matches
     'Vinicius Junior').
  2. Compute their per-90 rate for the stat across those matches.
  3. Scale to the expected minutes played (default 90).
  4. Apply Poisson distribution (counting stats are well-approximated by it)
     to get P(stat > line).

Returns None when there's not enough sample to project (< 3 matches).

Refinements deferred: opponent shots-allowed adjustment, position adjustment,
home/away factor. Those need the matchup join wired in and a richer historical
dataset (full season game logs, not just tournament samples).
"""

from __future__ import annotations

from math import exp

from src.providers._player_props import _normalize_name


# How many recent matches to average over.
DEFAULT_WINDOW = 10
# Minimum matches required to trust the rate.
MIN_MATCHES = 3
# Expected starting-XI minutes.
DEFAULT_MINUTES = 90.0

# Map our internal stat keys to the columns in soccer_player_match_stats.
STAT_COLUMN: dict[str, str] = {
    "shots": "shots",
    "shots_on_target": "shots_on_target",
    "assists": "assists",
    "goals": "goals",
    "tackles": "tackles",
    "fouls": "fouls_committed",
    "passes": "passes_attempted",
    "dribbles": "dribbles_attempted",
}


def _poisson_p_over(line: float, mean: float) -> float:
    """P(X > line) where X ~ Poisson(mean). Line is typically a half-point
    (e.g. 2.5); for an integer line N, we compute P(X > N) = 1 - P(X <= N)."""
    if mean <= 0:
        return 0.0
    # Floor the line, then P(X > floor(line)) = 1 - P(X <= floor(line)).
    # For half-point lines (2.5), this gives P(X >= 3) which is what we want.
    # For integer lines (2.0), this gives P(X >= 3) too — meaning a "push" at
    # exactly 2 counts as a loss for the over, matching most book conventions.
    k = int(line)
    # CDF: sum of pmf from 0..k
    pmf = exp(-mean)
    cdf = pmf
    for i in range(1, k + 1):
        pmf = pmf * mean / i
        cdf += pmf
    return max(0.0, min(1.0, 1.0 - cdf))


async def project_over(
    pool,
    *,
    player_name: str,
    stat: str,
    line: float,
    window: int = DEFAULT_WINDOW,
    expected_minutes: float = DEFAULT_MINUTES,
) -> float | None:
    """Return P(over line) for one player+stat+line, or None if not enough data."""
    column = STAT_COLUMN.get(stat)
    if not column:
        return None

    slug = _normalize_name(player_name)
    if not slug:
        return None

    # StatsBomb stores full legal names ("Lionel Andrés Messi Cuccittini")
    # while PrizePicks/sportsbooks use common names ("Lionel Messi"). Match
    # bidirectionally: either side's slug being a prefix of the other counts,
    # provided the shorter slug is at least 8 chars so we don't false-match
    # too-short queries like "JOSE".
    matched_slug = await _resolve_slug(pool, slug)
    if matched_slug is None:
        return None

    rows = await pool.fetch(
        f"""
        SELECT minutes_played, {column} AS value
        FROM soccer_player_match_stats
        WHERE player_name_slug = $1 AND minutes_played > 0
        ORDER BY match_date DESC
        LIMIT $2
        """,
        matched_slug,
        window,
    )
    if len(rows) < MIN_MATCHES:
        return None

    total_minutes = sum(int(r["minutes_played"]) for r in rows)
    total_value = sum(int(r["value"]) for r in rows)
    if total_minutes <= 0:
        return None

    per_90 = total_value * 90.0 / total_minutes
    mean = per_90 * (expected_minutes / 90.0)
    return _poisson_p_over(line, mean)


async def _resolve_slug(pool, slug: str) -> str | None:
    """Find the slug in soccer_player_match_stats that best matches `slug`,
    using exact-then-bidirectional-prefix. Returns None if no plausible match."""
    row = await pool.fetchrow(
        """
        SELECT player_name_slug
        FROM soccer_player_match_stats
        WHERE
            player_name_slug = $1
            OR (length($1) >= 8 AND player_name_slug LIKE $1 || '%')
            OR (length(player_name_slug) >= 8 AND $1 LIKE player_name_slug || '%')
        GROUP BY player_name_slug
        ORDER BY
            CASE WHEN player_name_slug = $1 THEN 0 ELSE 1 END,
            COUNT(*) DESC
        LIMIT 1
        """,
        slug,
    )
    return row["player_name_slug"] if row else None


async def projection_sample_size(pool, *, player_name: str) -> int:
    """How many matches we have for the player (for confidence display)."""
    slug = _normalize_name(player_name)
    if not slug:
        return 0
    matched_slug = await _resolve_slug(pool, slug)
    if matched_slug is None:
        return 0
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS n FROM soccer_player_match_stats WHERE player_name_slug = $1",
        matched_slug,
    )
    return int(row["n"]) if row else 0
