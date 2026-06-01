"""Forward-test tracker — bank every pick we surface, then grade it vs reality.

This is the feedback loop: every +EV DFS edge (and any game-line pick) gets
recorded as `pending` at the moment we'd bet it. After the game, `grade` looks
up what actually happened and marks hit/miss/push. Over time this builds a real,
out-of-sample track record — the thing that turns "the model says +EV" into
"this actually wins", and lets us see exactly where we're mis-calibrated so we
can keep improving.

Usage:
    python -m src.tracking.recorder record     # bank current +EV DFS edges
    python -m src.tracking.recorder grade       # grade finished pending picks
"""

from __future__ import annotations

import argparse
import asyncio

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

_CREATE = """
CREATE TABLE IF NOT EXISTS tracked_picks (
    id              SERIAL PRIMARY KEY,
    sport           TEXT NOT NULL,
    source          TEXT NOT NULL,          -- prizepicks/underdog/.../sportsbook/kalshi
    bet_kind        TEXT NOT NULL DEFAULT 'prop',  -- prop | game_line
    player_name     TEXT,
    team            TEXT,
    stat_type       TEXT NOT NULL,
    line            NUMERIC NOT NULL,
    pick_side       TEXT NOT NULL,          -- over/under | home/draw/away
    odds_type       TEXT DEFAULT 'standard',
    fair_prob       NUMERIC,                -- OUR probability for the pick side
    edge_pct        NUMERIC,
    num_books       INT,
    event_label     TEXT,
    game_starts_at  TIMESTAMPTZ,
    game_day        DATE,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|hit|miss|push|void
    actual_value    NUMERIC,
    graded_at       TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS tracked_picks_dedup
    ON tracked_picks (source, sport, COALESCE(player_name,''), stat_type, line, pick_side, game_day);
"""

# DFS stat_type -> how to compute the actual from player_game_logs columns.
_NBA_STAT_COLS = {
    "points": ["points"],
    "rebounds": ["rebounds"],
    "assists": ["assists"],
    "threes": ["threes"],
    "blocks": ["blocks"],
    "steals": ["steals"],
    "pra": ["points", "rebounds", "assists"],
}


async def ensure_schema(pool) -> None:
    await pool.execute(_CREATE)


async def record_dfs_edges(pool, *, min_edge: float = 0.0) -> int:
    """Bank every current +EV DFS edge as a pending pick (idempotent per game-day)."""
    await ensure_schema(pool)
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (o.dfs_line_id, o.pick_side)
            l.sport, l.source, l.player_name, l.team, l.stat_type, l.line,
            o.pick_side, l.odds_type,
            COALESCE(o.blended_fair_prob, o.consensus_fair_prob) AS fair_prob,
            o.edge_pct, o.num_sharp_books, l.game_starts_at
        FROM dfs_opportunities o
        JOIN dfs_lines l ON l.id = o.dfs_line_id
        WHERE l.is_active = true AND o.edge_pct >= $1
        ORDER BY o.dfs_line_id, o.pick_side, o.scan_tick_at DESC
        """,
        min_edge,
    )
    n = 0
    for r in rows:
        n += await _insert_pick(
            pool,
            sport=r["sport"], source=r["source"], bet_kind="prop",
            player_name=r["player_name"], team=r["team"],
            stat_type=r["stat_type"], line=float(r["line"]),
            pick_side=r["pick_side"], odds_type=r["odds_type"],
            fair_prob=float(r["fair_prob"]) if r["fair_prob"] is not None else None,
            edge_pct=float(r["edge_pct"]), num_books=r["num_sharp_books"],
            event_label=None, game_starts_at=r["game_starts_at"],
        )
    log.info("tracked_dfs_edges", banked=n, candidates=len(rows))
    return n


async def _insert_pick(pool, **f) -> int:
    """Insert one pick; returns 1 if new, 0 if it was already tracked today."""
    row = await pool.fetchrow(
        """
        INSERT INTO tracked_picks (
            sport, source, bet_kind, player_name, team, stat_type, line,
            pick_side, odds_type, fair_prob, edge_pct, num_books, event_label,
            game_starts_at, game_day)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::timestamptz,
                ($14::timestamptz)::date)
        ON CONFLICT (source, sport, COALESCE(player_name,''), stat_type, line, pick_side, game_day)
        DO NOTHING
        RETURNING id
        """,
        f["sport"], f["source"], f["bet_kind"], f["player_name"], f["team"],
        f["stat_type"], f["line"], f["pick_side"], f["odds_type"], f["fair_prob"],
        f["edge_pct"], f["num_books"], f["event_label"], f["game_starts_at"],
    )
    return 1 if row else 0


async def record_pick(pool, **f) -> int:
    """Public single-pick recorder (game lines, manual seeds)."""
    await ensure_schema(pool)
    f.setdefault("bet_kind", "game_line")
    for k in ("player_name", "team", "odds_type", "fair_prob", "edge_pct",
              "num_books", "event_label", "game_starts_at"):
        f.setdefault(k, None)
    f.setdefault("odds_type", "standard")
    return await _insert_pick(pool, **f)


async def grade_nba_props(pool) -> dict[str, int]:
    """Grade pending NBA prop picks whose game has passed, from player_game_logs."""
    await ensure_schema(pool)
    pending = await pool.fetch(
        """SELECT id, player_name, stat_type, line, pick_side, game_day
           FROM tracked_picks
           WHERE status='pending' AND sport='nba' AND bet_kind='prop'
             AND game_starts_at < NOW()"""
    )
    res = {"hit": 0, "miss": 0, "push": 0, "ungraded": 0}
    for p in pending:
        cols = _NBA_STAT_COLS.get(p["stat_type"])
        if not cols:
            res["ungraded"] += 1
            continue
        actual = await _nba_actual(pool, p["player_name"], cols, p["game_day"])
        if actual is None:
            res["ungraded"] += 1
            continue
        line = float(p["line"])
        if actual == line:
            status = "push"
        elif (p["pick_side"] == "over") == (actual > line):
            status = "hit"
        else:
            status = "miss"
        await pool.execute(
            "UPDATE tracked_picks SET status=$1, actual_value=$2, graded_at=NOW() WHERE id=$3",
            status, actual, p["id"],
        )
        res[status] += 1
    log.info("graded_nba_props", **res)
    return res


async def _nba_actual(pool, player_name, cols, game_day) -> float | None:
    sel = " + ".join(cols)
    for gd_off in (0, -1, 1):
        row = await pool.fetchrow(
            f"""SELECT ({sel})::numeric AS v FROM player_game_logs
                WHERE player_name=$1 AND game_date = $2::date + $3 LIMIT 1""",
            player_name, game_day, gd_off,
        )
        if row and row["v"] is not None:
            return float(row["v"])
    return None


async def _main() -> None:
    configure_logging(level=settings.log_level)
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["record", "grade"])
    p.add_argument("--min-edge", type=float, default=0.0)
    a = p.parse_args()
    pool = await get_pool()
    try:
        if a.cmd == "record":
            n = await record_dfs_edges(pool, min_edge=a.min_edge)
            print(f"  Banked {n} new picks.")
        else:
            r = await grade_nba_props(pool)
            print(f"  Graded: {r['hit']}W-{r['miss']}L-{r['push']}P  ({r['ungraded']} not yet gradeable)")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
