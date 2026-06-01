"""Feature derivation for the NBA GAME-LINE projection engine (System 2).

Completely separate from the DFS player-prop system. This reads only
`player_game_logs` (+ `pbp_events` where present) and writes two derived,
point-in-time tables:

  * `player_features` — one row per (player_id, game_date): rolling means
    (last 5 / 10 / 20 games) and season-to-date averages for the box-score
    stats, home/away from the matchup string, days of rest, a minutes trend,
    and (when play-by-play exists for that game) shot-zone attempt rates.

  * `team_features` — one row per (team_abbr, game_date): the team's form
    going INTO that game — points scored / allowed (last 5/10 + season),
    a pace proxy (total possessions-ish = points for + against per game),
    win flag, and days rest. These feed nba_game_model.py.

Everything is strictly *prior* form: a row dated game G is computed only from
games BEFORE G (`ORDER BY game_date` + window frame `ROWS ... PRECEDING`), so
the features are usable as honest pre-game predictors with no leakage.

Resumable: each (entity, game_date) is upserted on its primary key, and a
`--since` watermark lets you process only new dates. PBP is optional — when a
game has no pbp_events rows the shot-zone columns are simply left NULL.

Run:
    python -m src.projections.features --since 2024-01-01
    python -m src.projections.features --full          # rebuild everything
    python -m src.projections.features --date 2026-05-28
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import date

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.nba_stats.tracking import Position, shot_zone
from src.projections.teams import NBA_ABBRS, canonical_abbr

# Box-score stats we roll up. Order matters only for readability.
STAT_COLUMNS: tuple[str, ...] = (
    "points",
    "rebounds",
    "assists",
    "threes",
    "blocks",
    "steals",
)

SHOT_ZONES: tuple[str, ...] = (
    "rim",
    "short_mid",
    "long_mid",
    "corner_three",
    "above_break_three",
)


_CREATE_PLAYER = """
CREATE TABLE IF NOT EXISTS player_features (
    player_id        BIGINT  NOT NULL,
    game_date        DATE    NOT NULL,
    player_name      TEXT,
    team_abbr        TEXT,
    game_id          TEXT,
    is_home          BOOLEAN,
    days_rest        INT,
    games_played     INT,
    minutes_l5       NUMERIC,
    minutes_l10      NUMERIC,
    minutes_trend    NUMERIC,
    points_l5        NUMERIC,
    points_l10       NUMERIC,
    points_l20       NUMERIC,
    points_season    NUMERIC,
    rebounds_l5      NUMERIC,
    rebounds_l10     NUMERIC,
    rebounds_season  NUMERIC,
    assists_l5       NUMERIC,
    assists_l10      NUMERIC,
    assists_season   NUMERIC,
    threes_l10       NUMERIC,
    blocks_l10       NUMERIC,
    steals_l10       NUMERIC,
    pbp_shots        INT,
    rim_rate         NUMERIC,
    short_mid_rate   NUMERIC,
    long_mid_rate    NUMERIC,
    corner_three_rate    NUMERIC,
    above_break_three_rate NUMERIC,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (player_id, game_date)
);
"""

_CREATE_TEAM = """
CREATE TABLE IF NOT EXISTS team_features (
    team_abbr        TEXT NOT NULL,
    game_date        DATE NOT NULL,
    game_id          TEXT,
    opponent_abbr    TEXT,
    is_home          BOOLEAN,
    days_rest        INT,
    games_played     INT,
    pts_for_l5       NUMERIC,
    pts_for_l10      NUMERIC,
    pts_for_season   NUMERIC,
    pts_against_l5   NUMERIC,
    pts_against_l10  NUMERIC,
    pts_against_season NUMERIC,
    net_rating_l10   NUMERIC,
    pace_proxy_l10   NUMERIC,
    win_pct_season   NUMERIC,
    -- actuals for this game (used by the backtest as ground truth)
    pts_scored       INT,
    pts_allowed      INT,
    won              BOOLEAN,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_abbr, game_date)
);
"""


def _parse_matchup(matchup: str | None) -> tuple[bool | None, str | None]:
    """('LAL @ BOS' | 'LAL vs. BOS') -> (is_home, opponent_abbr).

    'vs.' => home, '@' => away. Opponent is the team on the other side,
    canonicalised to a current franchise (or None if non-NBA)."""
    if not matchup:
        return None, None
    if " vs. " in matchup:
        is_home, _, opp = True, *matchup.split(" vs. ", 1)
    elif " @ " in matchup:
        is_home, _, opp = False, *matchup.split(" @ ", 1)
    else:
        return None, None
    return is_home, canonical_abbr(opp.strip())


async def _zone_rates_for_games(
    pool, game_ids: list[str]
) -> dict[tuple[str, int], dict[str, float]]:
    """Per (game_id, person_id) shot-zone attempt *rates* from pbp_events.

    Keyed on person_id because pbp_events.player_name is last-name-only
    ('Wembanyama') while player_game_logs is full-name ('Victor Wembanyama');
    pbp.person_id == player_game_logs.player_id, so that's the reliable join.

    Returns {} for any game with no pbp rows — the caller treats a missing
    entry as "no tracking data" and writes NULLs. Chunked to respect the 10s
    command timeout while the full backfill is still loading."""
    if not game_ids:
        return {}
    out: dict[tuple[str, int], dict[str, float]] = {}
    counts: dict[tuple[str, int], dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(SHOT_ZONES, 0)
    )
    totals: dict[tuple[str, int], int] = defaultdict(int)

    CHUNK = 200
    for i in range(0, len(game_ids), CHUNK):
        chunk = game_ids[i : i + CHUNK]
        rows = await pool.fetch(
            """
            SELECT game_id, person_id, x_legacy, y_legacy
            FROM pbp_events
            WHERE game_id = ANY($1::text[])
              AND shot_result IN ('Made', 'Missed')
              AND person_id IS NOT NULL
              AND x_legacy IS NOT NULL AND y_legacy IS NOT NULL
            """,
            chunk,
        )
        for r in rows:
            pos = Position.from_legacy(r["x_legacy"], r["y_legacy"])
            if pos is None:
                continue
            key = (r["game_id"], int(r["person_id"]))
            counts[key][shot_zone(pos)] += 1
            totals[key] += 1

    for key, total in totals.items():
        if total <= 0:
            continue
        rates = {z: counts[key][z] / total for z in SHOT_ZONES}
        rates["_total"] = float(total)
        out[key] = rates
    return out


async def build_player_features(
    pool, *, since: date | None, only_date: date | None, full: bool
) -> int:
    """Compute player_features for each (player, game). Window aggregates are
    done in SQL so a single pass covers the whole history efficiently; the
    point-in-time frame (`ROWS BETWEEN N PRECEDING AND 1 PRECEDING`) guarantees
    every feature uses only earlier games.

    The source ALWAYS reads a player's full history (date filters can't go in
    the source CTE or the PRECEDING frame would only see in-scope games and
    every form column would be NULL). Date scoping is applied to the OUTPUT
    rows only.

    The window query is chunked by player_id. Because every window PARTITIONs
    BY player_id, a chunk of whole players is mathematically identical to the
    monolithic query, and each chunk finishes well inside the 10s pool
    timeout (the all-history-all-windows query over 584K rows does not)."""
    # Which players need writing? Only those with a game in scope. For --full
    # that's everyone; otherwise restrict by the date scope so incremental runs
    # touch a handful of players.
    id_where = "team_abbr = ANY($1::text[])"
    id_params: list[object] = [list(NBA_ABBRS)]
    if only_date is not None:
        id_where += f" AND game_date = ${len(id_params) + 1}"
        id_params.append(only_date)
    elif not full and since is not None:
        id_where += f" AND game_date >= ${len(id_params) + 1}"
        id_params.append(since)
    id_rows = await pool.fetch(
        f"SELECT DISTINCT player_id FROM player_game_logs WHERE {id_where}",
        *id_params,
    )
    player_ids = [r["player_id"] for r in id_rows]
    log.info("player_features_players", count=len(player_ids))

    window_sql = f"""
        WITH src AS (
            SELECT player_id, player_name, team_abbr, game_id, game_date,
                   matchup, minutes, {", ".join(STAT_COLUMNS)}
            FROM player_game_logs
            WHERE minutes IS NOT NULL AND player_id = ANY($1::bigint[])
        )
        SELECT
            player_id, player_name, team_abbr, game_id, game_date, matchup,
            game_date - LAG(game_date) OVER w AS days_rest,
            COUNT(*)        OVER w_prior AS games_played,
            AVG(minutes)    OVER w5  AS minutes_l5,
            AVG(minutes)    OVER w10 AS minutes_l10,
            AVG(points)     OVER w5  AS points_l5,
            AVG(points)     OVER w10 AS points_l10,
            AVG(points)     OVER w20 AS points_l20,
            AVG(points)     OVER w_prior AS points_season,
            AVG(rebounds)   OVER w5  AS rebounds_l5,
            AVG(rebounds)   OVER w10 AS rebounds_l10,
            AVG(rebounds)   OVER w_prior AS rebounds_season,
            AVG(assists)    OVER w5  AS assists_l5,
            AVG(assists)    OVER w10 AS assists_l10,
            AVG(assists)    OVER w_prior AS assists_season,
            AVG(threes)     OVER w10 AS threes_l10,
            AVG(blocks)     OVER w10 AS blocks_l10,
            AVG(steals)     OVER w10 AS steals_l10,
            AVG(minutes)    OVER w3  AS minutes_l3
        FROM src
        WINDOW
            w        AS (PARTITION BY player_id ORDER BY game_date),
            w_prior  AS (PARTITION BY player_id ORDER BY game_date
                         ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
            w3  AS (PARTITION BY player_id ORDER BY game_date
                    ROWS BETWEEN 3  PRECEDING AND 1 PRECEDING),
            w5  AS (PARTITION BY player_id ORDER BY game_date
                    ROWS BETWEEN 5  PRECEDING AND 1 PRECEDING),
            w10 AS (PARTITION BY player_id ORDER BY game_date
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
            w20 AS (PARTITION BY player_id ORDER BY game_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
        ORDER BY game_date
    """

    rows: list = []
    ID_CHUNK = 60  # ~60 players' full histories per query stays under 10s
    for i in range(0, len(player_ids), ID_CHUNK):
        chunk_ids = player_ids[i : i + ID_CHUNK]
        chunk_rows = await pool.fetch(window_sql, chunk_ids)
        # Scope filter (output side only — the source kept full history so the
        # PRECEDING frames are correct).
        if only_date is not None:
            chunk_rows = [r for r in chunk_rows if r["game_date"] == only_date]
        elif not full and since is not None:
            chunk_rows = [r for r in chunk_rows if r["game_date"] >= since]
        rows.extend(chunk_rows)

    # PBP zone rates only for the games we're about to write.
    game_ids = sorted({r["game_id"] for r in rows if r["game_id"]})
    zone_rates = await _zone_rates_for_games(pool, game_ids)
    log.info(
        "player_features_pbp",
        games_in_scope=len(game_ids),
        games_with_pbp=len({gid for (gid, _pid) in zone_rates}),
        player_games_with_pbp=len(zone_rates),
    )

    written = 0
    BATCH = 1000
    batch: list[tuple] = []

    async def flush() -> None:
        nonlocal written, batch
        if not batch:
            return
        await pool.executemany(
            """
            INSERT INTO player_features (
                player_id, game_date, player_name, team_abbr, game_id,
                is_home, days_rest, games_played,
                minutes_l5, minutes_l10, minutes_trend,
                points_l5, points_l10, points_l20, points_season,
                rebounds_l5, rebounds_l10, rebounds_season,
                assists_l5, assists_l10, assists_season,
                threes_l10, blocks_l10, steals_l10,
                pbp_shots, rim_rate, short_mid_rate, long_mid_rate,
                corner_three_rate, above_break_three_rate, computed_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
                $18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30, NOW()
            )
            ON CONFLICT (player_id, game_date) DO UPDATE SET
                player_name=EXCLUDED.player_name, team_abbr=EXCLUDED.team_abbr,
                game_id=EXCLUDED.game_id, is_home=EXCLUDED.is_home,
                days_rest=EXCLUDED.days_rest, games_played=EXCLUDED.games_played,
                minutes_l5=EXCLUDED.minutes_l5, minutes_l10=EXCLUDED.minutes_l10,
                minutes_trend=EXCLUDED.minutes_trend,
                points_l5=EXCLUDED.points_l5, points_l10=EXCLUDED.points_l10,
                points_l20=EXCLUDED.points_l20, points_season=EXCLUDED.points_season,
                rebounds_l5=EXCLUDED.rebounds_l5, rebounds_l10=EXCLUDED.rebounds_l10,
                rebounds_season=EXCLUDED.rebounds_season,
                assists_l5=EXCLUDED.assists_l5, assists_l10=EXCLUDED.assists_l10,
                assists_season=EXCLUDED.assists_season,
                threes_l10=EXCLUDED.threes_l10, blocks_l10=EXCLUDED.blocks_l10,
                steals_l10=EXCLUDED.steals_l10, pbp_shots=EXCLUDED.pbp_shots,
                rim_rate=EXCLUDED.rim_rate, short_mid_rate=EXCLUDED.short_mid_rate,
                long_mid_rate=EXCLUDED.long_mid_rate,
                corner_three_rate=EXCLUDED.corner_three_rate,
                above_break_three_rate=EXCLUDED.above_break_three_rate,
                computed_at=NOW()
            """,
            batch,
        )
        written += len(batch)
        batch = []

    for r in rows:
        is_home, _opp = _parse_matchup(r["matchup"])
        days_rest = int(r["days_rest"]) if r["days_rest"] is not None else None
        # Minutes trend = last-3 avg minus last-10 avg (ramp up / wind down).
        m3, m10 = r["minutes_l3"], r["minutes_l10"]
        trend = round(float(m3) - float(m10), 2) if m3 is not None and m10 is not None else None
        zr = zone_rates.get((r["game_id"], r["player_id"]))
        pbp_shots = None
        rim = smid = lmid = c3 = ab3 = None
        if zr is not None:
            pbp_shots = int(zr["_total"])
            rim, smid, lmid = zr["rim"], zr["short_mid"], zr["long_mid"]
            c3, ab3 = zr["corner_three"], zr["above_break_three"]

        def num(v: object) -> float | None:
            return round(float(v), 3) if v is not None else None

        batch.append(
            (
                r["player_id"],
                r["game_date"],
                r["player_name"],
                r["team_abbr"],
                r["game_id"],
                is_home,
                days_rest,
                int(r["games_played"]) if r["games_played"] is not None else 0,
                num(r["minutes_l5"]),
                num(r["minutes_l10"]),
                trend,
                num(r["points_l5"]),
                num(r["points_l10"]),
                num(r["points_l20"]),
                num(r["points_season"]),
                num(r["rebounds_l5"]),
                num(r["rebounds_l10"]),
                num(r["rebounds_season"]),
                num(r["assists_l5"]),
                num(r["assists_l10"]),
                num(r["assists_season"]),
                num(r["threes_l10"]),
                num(r["blocks_l10"]),
                num(r["steals_l10"]),
                pbp_shots,
                num(rim),
                num(smid),
                num(lmid),
                num(c3),
                num(ab3),
            )
        )
        if len(batch) >= BATCH:
            await flush()
    await flush()
    return written


async def build_team_features(
    pool, *, since: date | None, only_date: date | None, full: bool
) -> int:
    """Aggregate game logs to one (team, game) row, then roll team form forward.

    Team-game scores come from summing player points per (game_id, team_abbr);
    opponent points come from the other team in the same game. Form columns use
    the same point-in-time PRECEDING frame as the player features."""
    # Step 1: collapse to team-game rows (both teams' scores) inside SQL.
    team_games = await pool.fetch(
        """
        WITH tg AS (
            SELECT game_id, game_date, team_abbr,
                   SUM(points) AS pts,
                   MAX(matchup) AS matchup
            FROM player_game_logs
            WHERE team_abbr = ANY($1::text[]) AND points IS NOT NULL
            GROUP BY game_id, game_date, team_abbr
        )
        SELECT a.game_id, a.game_date, a.team_abbr, a.matchup,
               a.pts AS pts_for, b.pts AS pts_against, b.team_abbr AS opp_abbr
        FROM tg a
        JOIN tg b ON a.game_id = b.game_id AND a.team_abbr <> b.team_abbr
        ORDER BY a.game_date
        """,
        list(NBA_ABBRS),
    )

    # Canonicalise abbreviations (collapse relocations) and keep one row per
    # (team, game). Build per-team ordered histories in Python so the rolling
    # frame is trivial and leak-free.
    by_team: dict[str, list[dict]] = defaultdict(list)
    for r in team_games:
        team = canonical_abbr(r["team_abbr"])
        opp = canonical_abbr(r["opp_abbr"])
        if team is None or opp is None:
            continue
        is_home, _ = _parse_matchup(r["matchup"])
        by_team[team].append(
            {
                "game_id": r["game_id"],
                "game_date": r["game_date"],
                "opp": opp,
                "is_home": is_home,
                "pts_for": int(r["pts_for"]),
                "pts_against": int(r["pts_against"]),
            }
        )

    def mean(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    rows_out: list[tuple] = []
    for team, games in by_team.items():
        games.sort(key=lambda g: g["game_date"])
        for i, g in enumerate(games):
            prior = games[:i]  # strictly earlier games => no leakage
            if only_date is not None and g["game_date"] != only_date:
                continue
            if only_date is None and not full and since is not None and g["game_date"] < since:
                continue
            pf = [p["pts_for"] for p in prior]
            pa = [p["pts_against"] for p in prior]
            wins = sum(1 for p in prior if p["pts_for"] > p["pts_against"])
            l10 = prior[-10:]
            pf10 = [p["pts_for"] for p in l10]
            pa10 = [p["pts_against"] for p in l10]
            net10 = (
                round(mean(pf10) - mean(pa10), 3)
                if pf10 and mean(pf10) is not None and mean(pa10) is not None
                else None
            )
            # Pace proxy: combined points per game over last 10 — higher means a
            # faster, higher-scoring environment (a stand-in for possessions).
            pace10 = round((sum(pf10) + sum(pa10)) / len(l10), 3) if l10 else None
            prev_date = prior[-1]["game_date"] if prior else None
            days_rest = (g["game_date"] - prev_date).days if prev_date else None

            rows_out.append(
                (
                    team,
                    g["game_date"],
                    g["game_id"],
                    g["opp"],
                    g["is_home"],
                    days_rest,
                    len(prior),
                    mean([p["pts_for"] for p in prior[-5:]]),
                    mean(pf10),
                    mean(pf),
                    mean([p["pts_against"] for p in prior[-5:]]),
                    mean(pa10),
                    mean(pa),
                    net10,
                    pace10,
                    round(wins / len(prior), 3) if prior else None,
                    g["pts_for"],
                    g["pts_against"],
                    g["pts_for"] > g["pts_against"],
                )
            )

    written = 0
    BATCH = 1000
    for i in range(0, len(rows_out), BATCH):
        chunk = rows_out[i : i + BATCH]
        await pool.executemany(
            """
            INSERT INTO team_features (
                team_abbr, game_date, game_id, opponent_abbr, is_home,
                days_rest, games_played,
                pts_for_l5, pts_for_l10, pts_for_season,
                pts_against_l5, pts_against_l10, pts_against_season,
                net_rating_l10, pace_proxy_l10, win_pct_season,
                pts_scored, pts_allowed, won, computed_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                $17,$18,$19, NOW()
            )
            ON CONFLICT (team_abbr, game_date) DO UPDATE SET
                game_id=EXCLUDED.game_id, opponent_abbr=EXCLUDED.opponent_abbr,
                is_home=EXCLUDED.is_home, days_rest=EXCLUDED.days_rest,
                games_played=EXCLUDED.games_played,
                pts_for_l5=EXCLUDED.pts_for_l5, pts_for_l10=EXCLUDED.pts_for_l10,
                pts_for_season=EXCLUDED.pts_for_season,
                pts_against_l5=EXCLUDED.pts_against_l5,
                pts_against_l10=EXCLUDED.pts_against_l10,
                pts_against_season=EXCLUDED.pts_against_season,
                net_rating_l10=EXCLUDED.net_rating_l10,
                pace_proxy_l10=EXCLUDED.pace_proxy_l10,
                win_pct_season=EXCLUDED.win_pct_season,
                pts_scored=EXCLUDED.pts_scored, pts_allowed=EXCLUDED.pts_allowed,
                won=EXCLUDED.won, computed_at=NOW()
            """,
            chunk,
        )
        written += len(chunk)
    return written


async def build_features(
    *,
    since: date | None = None,
    only_date: date | None = None,
    full: bool = False,
    tables: tuple[str, ...] = ("team", "player"),
) -> dict[str, int]:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        await pool.execute(_CREATE_PLAYER)
        await pool.execute(_CREATE_TEAM)
        result: dict[str, int] = {"team_features": 0, "player_features": 0}
        if "team" in tables:
            n_team = await build_team_features(pool, since=since, only_date=only_date, full=full)
            log.info("team_features_written", rows=n_team)
            result["team_features"] = n_team
        if "player" in tables:
            n_player = await build_player_features(
                pool, since=since, only_date=only_date, full=full
            )
            log.info("player_features_written", rows=n_player)
            result["player_features"] = n_player
        return result
    finally:
        await close_pool()


def _main() -> None:
    p = argparse.ArgumentParser(description="Build NBA game-model features.")
    p.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="Only (re)compute rows on/after this date (YYYY-MM-DD).",
    )
    p.add_argument(
        "--date",
        dest="only_date",
        type=date.fromisoformat,
        default=None,
        help="Only compute rows for this single date.",
    )
    p.add_argument(
        "--full", action="store_true", help="Rebuild the entire history (ignores --since)."
    )
    p.add_argument(
        "--tables",
        choices=["team", "player", "both"],
        default="both",
        help="Which feature table(s) to build.",
    )
    a = p.parse_args()
    tables = ("team", "player") if a.tables == "both" else (a.tables,)
    res = asyncio.run(
        build_features(since=a.since, only_date=a.only_date, full=a.full, tables=tables)
    )
    print("\nNBA FEATURES built")
    print(f"  team_features rows written:   {res['team_features']}")
    print(f"  player_features rows written: {res['player_features']}")


if __name__ == "__main__":
    _main()
