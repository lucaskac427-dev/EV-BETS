"""MLB outcomes warehouse — per-player per-game box-score lines from MLB StatsAPI.

statsapi.mlb.com is free + keyless and serves box scores back to ~1901. We pull
schedule -> boxscore_data(gamePk) -> flatten each player's batting + pitching
line into mlb_game_logs. This is the OUTCOMES source that grades DFS picks and
backtests the consensus edge. (The consensus SIDE is odds-bounded to ~2023, but
outcomes go back a century — they also feed the future projection model.)

Backfill newest-first so the seasons with odds to backtest land first; deep
history fills in behind. Idempotent: re-running skips games already stored, so
it's resumable after an interrupt.

    python -m src.mlb_stats.ingest --date 2026-05-31           # one day (test)
    python -m src.mlb_stats.ingest --from 2026-06-01 --to 2023-01-01   # newest-first range
"""

import argparse
import asyncio
from datetime import date, timedelta

import statsapi

from src.db import close_pool, get_pool
from src.logger import configure_logging, log

_CREATE = """
CREATE TABLE IF NOT EXISTS mlb_game_logs (
    player_id           INTEGER NOT NULL,
    player_name         TEXT NOT NULL,
    game_id             INTEGER NOT NULL,
    game_date           DATE NOT NULL,
    team                TEXT,
    -- batting
    hits                INTEGER,
    doubles             INTEGER,
    triples             INTEGER,
    home_runs           INTEGER,
    singles             INTEGER,
    total_bases         INTEGER,
    rbi                 INTEGER,
    runs                INTEGER,
    batter_strikeouts   INTEGER,
    stolen_bases        INTEGER,
    batter_walks        INTEGER,
    -- pitching
    pitcher_strikeouts  INTEGER,
    pitcher_outs        INTEGER,
    hits_allowed        INTEGER,
    earned_runs         INTEGER,
    pitcher_walks       INTEGER,
    PRIMARY KEY (player_id, game_id)
);
CREATE INDEX IF NOT EXISTS mlb_game_logs_name_date ON mlb_game_logs (player_name, game_date);
"""

_COLS = [
    "player_id", "player_name", "game_id", "game_date", "team",
    "hits", "doubles", "triples", "home_runs", "singles", "total_bases",
    "rbi", "runs", "batter_strikeouts", "stolen_bases", "batter_walks",
    "pitcher_strikeouts", "pitcher_outs", "hits_allowed", "earned_runs", "pitcher_walks",
]


def _i(v):
    """Coerce a StatsAPI stat value to int, or None if blank/missing."""
    if v is None or v == "" or v == "-":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _ip_to_outs(ip) -> int | None:
    """inningsPitched '6.2' -> 20 outs (6 full innings + 2 outs)."""
    if ip in (None, ""):
        return None
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole or 0) * 3 + (int(frac) if frac else 0)
    except (TypeError, ValueError):
        return None


def flatten_game(bd: dict, game_id: int, game_date: date) -> list[dict]:
    """One row per player who batted or pitched, with both stat lines (nulls where N/A)."""
    info = bd.get("teamInfo", {}) or {}
    rows: list[dict] = []
    for side in ("home", "away"):
        s = bd.get(side, {}) or {}
        team = (info.get(side, {}) or {}).get("abbreviation")
        for pdata in (s.get("players", {}) or {}).values():
            person = pdata.get("person", {}) or {}
            name, pid = person.get("fullName"), person.get("id")
            if not name or pid is None:
                continue
            st = pdata.get("stats", {}) or {}
            bat = st.get("batting", {}) or {}
            pit = st.get("pitching", {}) or {}
            if not bat and not pit:
                continue  # didn't play

            hits, dbl, trp, hr = _i(bat.get("hits")), _i(bat.get("doubles")), _i(bat.get("triples")), _i(bat.get("homeRuns"))
            singles = total_bases = None
            if None not in (hits, dbl, trp, hr):
                singles = hits - dbl - trp - hr
                total_bases = hits + dbl + 2 * trp + 3 * hr  # TB = H + 2B + 2·3B + 3·HR

            rows.append({
                "player_id": pid, "player_name": name, "game_id": game_id,
                "game_date": game_date, "team": team,
                "hits": hits, "doubles": dbl, "triples": trp, "home_runs": hr,
                "singles": singles, "total_bases": total_bases,
                "rbi": _i(bat.get("rbi")), "runs": _i(bat.get("runs")),
                "batter_strikeouts": _i(bat.get("strikeOuts")),
                "stolen_bases": _i(bat.get("stolenBases")),
                "batter_walks": _i(bat.get("baseOnBalls")),
                "pitcher_strikeouts": _i(pit.get("strikeOuts")) if pit else None,
                "pitcher_outs": _ip_to_outs(pit.get("inningsPitched")) if pit else None,
                "hits_allowed": _i(pit.get("hits")) if pit else None,
                "earned_runs": _i(pit.get("earnedRuns")) if pit else None,
                "pitcher_walks": _i(pit.get("baseOnBalls")) if pit else None,
            })
    return rows


_UPSERT = (
    f"INSERT INTO mlb_game_logs ({', '.join(_COLS)}) "
    f"VALUES ({', '.join('$' + str(i + 1) for i in range(len(_COLS)))}) "
    f"ON CONFLICT (player_id, game_id) DO UPDATE SET "
    + ", ".join(f"{c}=EXCLUDED.{c}" for c in _COLS if c not in ("player_id", "game_id"))
)


async def _upsert(pool, rows: list[dict]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as con:
        await con.executemany(_UPSERT, [[r[c] for c in _COLS] for r in rows])
    return len(rows)


async def ingest_day(pool, day: date, done: set[int], throttle: float) -> int:
    try:
        sched = statsapi.schedule(start_date=day.strftime("%m/%d/%Y"), end_date=day.strftime("%m/%d/%Y"))
    except Exception as e:
        log.warning("mlb_schedule_failed", date=str(day), error=str(e)[:100])
        return 0
    wrote = 0
    for g in sched:
        if g.get("status") != "Final":
            continue
        gid = g.get("game_id")
        if gid is None or gid in done:
            continue
        try:
            bd = statsapi.boxscore_data(gid)
            wrote += await _upsert(pool, flatten_game(bd, gid, day))
            done.add(gid)
        except Exception as e:
            log.warning("mlb_boxscore_failed", game=gid, error=str(e)[:100])
        await asyncio.sleep(throttle)
    return wrote


async def backfill(start: date, end: date, *, throttle: float = 0.4) -> int:
    """Ingest every Final game's box scores from `start` to `end` inclusive.
    If start >= end, walks NEWEST-FIRST (recent seasons land before deep history)."""
    configure_logging(level="WARNING")
    pool = await get_pool()
    try:
        for stmt in _CREATE.strip().split(";"):
            if stmt.strip():
                await pool.execute(stmt)
        done = {r["game_id"] for r in await pool.fetch("SELECT DISTINCT game_id FROM mlb_game_logs")}
        step = timedelta(days=-1) if start >= end else timedelta(days=1)
        d, total = start, 0
        while (d >= end) if step.days < 0 else (d <= end):
            n = await ingest_day(pool, d, done, throttle)
            total += n
            if n:
                log.warning("mlb_day_ingested", date=str(d), rows=n, cumulative=total)
            d += step
        print(f"mlb backfill {start}..{end}: {total} player-game rows ingested")
        return total
    finally:
        await close_pool()


def _parse(s: str) -> date:
    return date.fromisoformat(s)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="ingest a single day (YYYY-MM-DD)")
    p.add_argument("--from", dest="frm", help="start date (YYYY-MM-DD)")
    p.add_argument("--to", dest="to", help="end date (YYYY-MM-DD); newest-first if before --from")
    p.add_argument("--throttle", type=float, default=0.4, help="seconds between box-score calls")
    a = p.parse_args()
    if a.date:
        asyncio.run(backfill(_parse(a.date), _parse(a.date), throttle=a.throttle))
    elif a.frm and a.to:
        asyncio.run(backfill(_parse(a.frm), _parse(a.to), throttle=a.throttle))
    else:
        p.error("pass --date, or --from and --to")
