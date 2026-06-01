"""NBA per-player projection model.

Same shape as src/projections/soccer.py:

  1. Pull the player's last N games from player_game_logs.
  2. Per-36-minute (instead of per-90 for soccer) rate for the stat.
  3. Scale to expected minutes played.
  4. Poisson distribution → P(stat > line).

Returns None when there's not enough sample (< MIN_GAMES games).
"""

from __future__ import annotations

import re
import unicodedata
from math import exp


# Window of recent games to average over.
DEFAULT_WINDOW = 20
MIN_GAMES = 5
DEFAULT_MINUTES = 32.0  # typical starter minutes

# Map our internal stat keys to columns in player_game_logs.
STAT_COLUMN: dict[str, str] = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes": "threes",
    "blocks": "blocks",
    "steals": "steals",
}


def _poisson_p_over(line: float, mean: float) -> float:
    if mean <= 0:
        return 0.0
    k = int(line)
    pmf = exp(-mean)
    cdf = pmf
    for i in range(1, k + 1):
        pmf = pmf * mean / i
        cdf += pmf
    return max(0.0, min(1.0, 1.0 - cdf))


def _normalize_nba_name(name: str) -> str:
    """For player_game_logs.player_name. NBA names are typically clean but
    we still strip accents and suffix variants ('Jr.' / 'II' / 'III')."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_only.strip()


_SUFFIX = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", re.IGNORECASE)


def _strip_suffix(name: str) -> str:
    return _SUFFIX.sub("", name).strip()


async def _resolve_name(pool, player_name: str) -> str | None:
    """Find the canonical player_game_logs.player_name that best matches.
    Tries: exact, accent-insensitive exact via unaccent(), suffix-stripped,
    then accent-insensitive substring as last resort.

    Picks the row with the most games to prefer the real player when names
    collide (Bogdan Bogdanović vs Bojan Bogdanovic)."""
    a = _normalize_nba_name(player_name)
    b = _strip_suffix(a)
    candidates = [a, b] if b != a else [a]

    for name in candidates:
        # Exact + accent-insensitive in one shot, prefer the most-played
        # variant (handles "Luka Doncic" 2-game ghost row vs main "Luka
        # Dončić" with thousands of games).
        row = await pool.fetchrow(
            """
            SELECT player_name, COUNT(*) AS n
            FROM player_game_logs
            WHERE player_name = $1
               OR unaccent(player_name) = unaccent($1)
            GROUP BY player_name ORDER BY n DESC LIMIT 1
            """,
            name,
        )
        if row:
            return row["player_name"]

    # Accent-insensitive substring as last resort.
    for name in candidates:
        parts = name.split()
        if len(parts) >= 2:
            first, last = parts[0], parts[-1]
            row = await pool.fetchrow(
                """
                SELECT player_name, COUNT(*) AS n
                FROM player_game_logs
                WHERE unaccent(player_name) ILIKE $1 || '%' || $2 || '%'
                GROUP BY player_name ORDER BY n DESC LIMIT 1
                """,
                first,
                last,
            )
            if row:
                return row["player_name"]
    return None


async def project_over(
    pool,
    *,
    player_name: str,
    stat: str,
    line: float,
    window: int = DEFAULT_WINDOW,
    expected_minutes: float = DEFAULT_MINUTES,
) -> float | None:
    column = STAT_COLUMN.get(stat)
    if not column:
        return None

    canonical = await _resolve_name(pool, player_name)
    if not canonical:
        return None

    rows = await pool.fetch(
        f"""
        SELECT minutes, {column} AS value
        FROM player_game_logs
        WHERE player_name = $1
          AND minutes IS NOT NULL AND minutes > 0
          AND {column} IS NOT NULL
        ORDER BY game_date DESC
        LIMIT $2
        """,
        canonical,
        window,
    )
    if len(rows) < MIN_GAMES:
        return None

    total_minutes = sum(float(r["minutes"]) for r in rows)
    total_value = sum(int(r["value"]) for r in rows)
    if total_minutes <= 0:
        return None

    per_36 = total_value * 36.0 / total_minutes
    mean = per_36 * (expected_minutes / 36.0)
    return _poisson_p_over(line, mean)


async def projection_sample_size(pool, *, player_name: str) -> int:
    canonical = await _resolve_name(pool, player_name)
    if not canonical:
        return 0
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS n FROM player_game_logs WHERE player_name = $1",
        canonical,
    )
    return int(row["n"]) if row else 0
