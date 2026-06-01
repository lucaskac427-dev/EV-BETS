"""Ingest the FBref master.db archive into soccer_player_match_stats.

This is the rescued FBref detailed-stats SQLite (big-5 + Primeira Liga,
2017-08 → 2026-01), the data StatsPerform pulled from the live site in Jan
2026. 521K player-match rows with the full detail set — shots, shots on
target, tackles, fouls, passes, dribbles — that Understat lacks. It overlaps
the EPL prop-odds window (Aug 2024+), so it's what scores the soccer-prop
backtest.

Run: python -m src.historical.fbref_masterdb --db _data/fbref/master.db
"""

import argparse
import asyncio
import re
import sqlite3
import unicodedata
from datetime import date

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log


def _slug(name: str) -> str:
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z]+", "", ascii_only).upper()


import math


_INT64_MAX = 9223372036854775807


def _i(v):
    try:
        if v is None or str(v) == "":
            return None
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        iv = int(f)
        if abs(iv) > _INT64_MAX:  # corrupted/concatenated id in source data
            return None
        return iv
    except (TypeError, ValueError, OverflowError):
        return None


_JOIN_SQL = """
SELECT m.competition, m.season, m.match_id, m.date, m.home_team, m.away_team,
       pi.player_id, pi.name, pi.position, pi.minutes, pi.home_away,
       s.shots, s.shots_on_target, s.goals, s.assists, s.tackles,
       ms.fouls_committed, ms.fouls_drawn,
       pa.total_attempted AS passes_att, pa.total_completed AS passes_cmp,
       po.dribbles_attempted, po.successful_dribbles
FROM Player_Info pi
JOIN Match m              ON m.match_id = pi.match_id
LEFT JOIN Summary s       ON s.match_id = pi.match_id AND s.player_id = pi.player_id
LEFT JOIN Miscellaneous ms ON ms.match_id = pi.match_id AND ms.player_id = pi.player_id
LEFT JOIN Passing pa      ON pa.match_id = pi.match_id AND pa.player_id = pi.player_id
LEFT JOIN Possession po   ON po.match_id = pi.match_id AND po.player_id = pi.player_id
"""


async def main(db_path: str, batch: int = 5000) -> None:
    configure_logging(level=settings.log_level)
    sq = sqlite3.connect(db_path)
    sq.row_factory = sqlite3.Row
    pool = await get_pool()
    try:
        rows = sq.execute(_JOIN_SQL)
        n = 0
        pending = []
        async with pool.acquire() as conn:
            for r in rows:
                comp = (r["competition"] or "").replace("_", " ")
                date_str = r["date"]
                pname = r["name"]
                if not pname or not date_str:
                    continue
                try:
                    md = date.fromisoformat(date_str[:10])
                except (ValueError, TypeError):
                    continue
                mid = _i(r["match_id"])
                if mid is None:
                    # corrupted source id -> deterministic synthetic from the match
                    h = abs(hash((comp, date_str[:10], r["home_team"], r["away_team"])))
                    mid = h % 9_000_000_000_000_000
                pid = _i(r["player_id"])
                if pid is None:
                    pid = abs(hash(_slug(pname))) % 9_000_000_000_000_000
                team = r["home_team"] if (r["home_away"] or "").lower() == "home" else r["away_team"]
                team = team or r["home_team"] or "unknown"
                pending.append((
                    "fbref", comp, str(r["season"]), mid, md,
                    r["home_team"], r["away_team"], pid, pname, _slug(pname),
                    team, r["position"], _i(r["minutes"]) or 0,
                    _i(r["shots"]) or 0, _i(r["shots_on_target"]) or 0,
                    _i(r["goals"]) or 0, _i(r["assists"]) or 0,
                    _i(r["tackles"]) or 0, _i(r["fouls_committed"]) or 0,
                    _i(r["fouls_drawn"]) or 0, _i(r["passes_att"]) or 0,
                    _i(r["passes_cmp"]) or 0, _i(r["dribbles_attempted"]) or 0,
                    _i(r["successful_dribbles"]) or 0,
                ))
                if len(pending) >= batch:
                    await _flush(conn, pending)
                    n += len(pending)
                    pending = []
                    if n % 50000 == 0:
                        log.info("fbref_masterdb_progress", rows=n)
            if pending:
                await _flush(conn, pending)
                n += len(pending)
        log.info("fbref_masterdb_complete", rows=n)
        print(f"FBref master.db ingest complete: {n:,} player-match rows")
    finally:
        sq.close()
        await close_pool()


async def _flush(conn, rows: list[tuple]) -> None:
    await conn.executemany(
        """
        INSERT INTO soccer_player_match_stats
            (source, competition_name, season_name, match_id, match_date,
             home_team, away_team, player_id, player_name, player_name_slug,
             team_name, position, minutes_played, shots, shots_on_target,
             goals, assists, tackles, fouls_committed, fouls_won,
             passes_attempted, passes_completed, dribbles_attempted, dribbles_completed)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24)
        ON CONFLICT DO NOTHING
        """,
        rows,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="_data/fbref/master.db")
    a = p.parse_args()
    asyncio.run(main(a.db))
