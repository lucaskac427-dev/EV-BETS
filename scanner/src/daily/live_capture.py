"""LIVE game capture — record NBA games AS THEY HAPPEN, not just post-game.

`src.daily.record_day` banks *completed* games once they're final. This module
is the live counterpart: it polls the NBA live CDN every N seconds while games
are in progress and snapshots the evolving state — score / period / clock, every
player's running box-score line, and the play-by-play feed — into the warehouse.

The result is a TIME SERIES per game: how the score, each player's stat line, and
the event stream looked at every poll. That's the raw material for live-EV work
(in-game win prob, prop pace-vs-pace, "will he hit the over" given current pace).

Three tables, all append/upsert so re-polling only adds the latest picture:
  - live_game_state    one row per (game_id, snapshot_at): score/period/clock/status
  - live_player_state  one row per (game_id, snapshot_at, person_id): pts/reb/ast/3pm/min
  - live_pbp_events    one row per (game_id, action_number): the play-by-play stream

INDEPENDENCE: these are NEW `live_*` tables. Nothing here touches the post-game
`pbp_events` / `player_game_logs` tables, the DFS consensus pipeline, or the
projection engine. It is purely additive capture.

The live CDN serves real-world data; outside of NBA game hours (or in a sandbox)
there are simply no live games and the calls return empty or raise — every fetch
is wrapped so the loop logs "no live games" and exits cleanly rather than crash.

Run:
    python -m src.daily.live_capture                 # one-shot: snapshot now, exit
    python -m src.daily.live_capture --loop          # poll every 60s until none live
    python -m src.daily.live_capture --loop --interval 30
    python -m src.daily.live_capture --once --no-pbp  # skip the play-by-play layer
"""

from __future__ import annotations

import argparse
import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import asyncpg

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

_CREATE = """
CREATE TABLE IF NOT EXISTS live_game_state (
    game_id        TEXT        NOT NULL,
    snapshot_at    TIMESTAMPTZ NOT NULL,
    status         INT,
    status_text    TEXT,
    period         INT,
    clock          TEXT,
    clock_seconds  NUMERIC,
    home_tricode   TEXT,
    away_tricode   TEXT,
    home_score     INT,
    away_score     INT,
    PRIMARY KEY (game_id, snapshot_at)
);
CREATE INDEX IF NOT EXISTS live_game_state_game_idx
    ON live_game_state (game_id, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS live_player_state (
    game_id        TEXT        NOT NULL,
    snapshot_at    TIMESTAMPTZ NOT NULL,
    person_id      BIGINT      NOT NULL,
    player_name    TEXT,
    team_tricode   TEXT,
    points         INT,
    rebounds       INT,
    assists        INT,
    threes         INT,
    minutes        NUMERIC,
    PRIMARY KEY (game_id, snapshot_at, person_id)
);
CREATE INDEX IF NOT EXISTS live_player_state_player_idx
    ON live_player_state (game_id, person_id, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS live_pbp_events (
    game_id        TEXT        NOT NULL,
    action_number  INT         NOT NULL,
    period         INT,
    clock          TEXT,
    team_tricode   TEXT,
    person_id      BIGINT,
    player_name    TEXT,
    action_type    TEXT,
    sub_type       TEXT,
    description    TEXT,
    score_home     INT,
    score_away     INT,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (game_id, action_number)
);
"""

_GAME_STATUS_LIVE = 2

# ISO-8601 duration the live feed uses for clocks/minutes, e.g. "PT11M58.00S".
_ISO_DURATION = re.compile(r"PT(?:(\d+)M)?(?:([\d.]+)S)?")


def _i(v: Any) -> int | None:
    """Coerce to int, tolerating the feed's string-typed numbers and Nones."""
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _s(v: Any) -> str | None:
    """Coerce to a non-empty str, else None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _iso_duration_to_seconds(v: Any) -> float | None:
    """Parse "PT11M58.00S" -> 718.0 seconds. Used for both clock and minutes."""
    if not v or not isinstance(v, str):
        return None
    m = _ISO_DURATION.fullmatch(v.strip())
    if not m:
        return None
    mins = float(m.group(1)) if m.group(1) else 0.0
    secs = float(m.group(2)) if m.group(2) else 0.0
    return round(mins * 60.0 + secs, 2)


# --- blocking nba_api calls; each is run via asyncio.to_thread -------------


def _fetch_scoreboard() -> list[dict[str, Any]]:
    from nba_api.live.nba.endpoints import scoreboard

    data = scoreboard.ScoreBoard().get_dict()
    return data.get("scoreboard", {}).get("games", []) or []


def _fetch_boxscore(game_id: str) -> dict[str, Any]:
    from nba_api.live.nba.endpoints import boxscore

    return boxscore.BoxScore(game_id).get_dict().get("game", {}) or {}


def _fetch_pbp(game_id: str) -> list[dict[str, Any]]:
    from nba_api.live.nba.endpoints import playbyplay

    return playbyplay.PlayByPlay(game_id).get_dict().get("game", {}).get("actions", []) or []


# --- per-layer recording ---------------------------------------------------


def _player_rows(
    game: dict[str, Any], game_id: str, snapshot_at: datetime
) -> list[tuple[Any, ...]]:
    """Flatten both teams' live player statistics into row tuples."""
    rows: list[tuple[Any, ...]] = []
    for side in ("homeTeam", "awayTeam"):
        team = game.get(side) or {}
        tricode = _s(team.get("teamTricode"))
        for p in team.get("players", []) or []:
            person_id = _i(p.get("personId"))
            if person_id is None:
                continue
            st = p.get("statistics") or {}
            rows.append(
                (
                    game_id,
                    snapshot_at,
                    person_id,
                    _s(p.get("name")),
                    tricode,
                    _i(st.get("points")),
                    _i(st.get("reboundsTotal")),
                    _i(st.get("assists")),
                    _i(st.get("threePointersMade")),
                    _iso_duration_to_seconds(st.get("minutes")),
                )
            )
    return rows


async def _record_player_state(pool: asyncpg.Pool, game_id: str, snapshot_at: datetime) -> int:
    """Snapshot every player's live stat line from the boxscore feed."""
    try:
        game = await asyncio.to_thread(_fetch_boxscore, game_id)
    except Exception as e:  # noqa: BLE001 — feed can raise; never crash the loop
        log.warning("live_boxscore_failed", game_id=game_id, error=str(e)[:160])
        return 0

    rows = _player_rows(game, game_id, snapshot_at)
    if not rows:
        return 0
    await pool.executemany(
        """INSERT INTO live_player_state (game_id, snapshot_at, person_id,
             player_name, team_tricode, points, rebounds, assists, threes, minutes)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
           ON CONFLICT (game_id, snapshot_at, person_id) DO UPDATE SET
             player_name=EXCLUDED.player_name, team_tricode=EXCLUDED.team_tricode,
             points=EXCLUDED.points, rebounds=EXCLUDED.rebounds,
             assists=EXCLUDED.assists, threes=EXCLUDED.threes,
             minutes=EXCLUDED.minutes""",
        rows,
    )
    return len(rows)


async def _record_pbp(pool: asyncpg.Pool, game_id: str) -> int:
    """Append any new play-by-play actions (keyed by action_number, so resumable)."""
    try:
        actions = await asyncio.to_thread(_fetch_pbp, game_id)
    except Exception as e:  # noqa: BLE001
        log.warning("live_pbp_failed", game_id=game_id, error=str(e)[:160])
        return 0

    rows: list[tuple[Any, ...]] = []
    for a in actions:
        action_number = _i(a.get("actionNumber"))
        if action_number is None:
            continue
        rows.append(
            (
                game_id,
                action_number,
                _i(a.get("period")),
                _s(a.get("clock")),
                _s(a.get("teamTricode")),
                _i(a.get("personId")),
                _s(a.get("playerName")),
                _s(a.get("actionType")),
                _s(a.get("subType")),
                _s(a.get("description")),
                _i(a.get("scoreHome")),
                _i(a.get("scoreAway")),
            )
        )
    if not rows:
        return 0
    await pool.executemany(
        """INSERT INTO live_pbp_events (game_id, action_number, period, clock,
             team_tricode, person_id, player_name, action_type, sub_type,
             description, score_home, score_away)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
           ON CONFLICT (game_id, action_number) DO NOTHING""",
        rows,
    )
    return len(rows)


async def _record_game(
    pool: asyncpg.Pool, g: dict[str, Any], snapshot_at: datetime, *, with_pbp: bool
) -> dict[str, int]:
    """Record one live game: state snapshot + player snapshot + (optional) PBP."""
    game_id = _s(g.get("gameId"))
    out = {"player_rows": 0, "pbp_rows": 0}
    if game_id is None:
        return out

    home = g.get("homeTeam") or {}
    away = g.get("awayTeam") or {}
    await pool.execute(
        """INSERT INTO live_game_state (game_id, snapshot_at, status, status_text,
             period, clock, clock_seconds, home_tricode, away_tricode,
             home_score, away_score)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
           ON CONFLICT (game_id, snapshot_at) DO UPDATE SET
             status=EXCLUDED.status, status_text=EXCLUDED.status_text,
             period=EXCLUDED.period, clock=EXCLUDED.clock,
             clock_seconds=EXCLUDED.clock_seconds,
             home_score=EXCLUDED.home_score, away_score=EXCLUDED.away_score""",
        game_id,
        snapshot_at,
        _i(g.get("gameStatus")),
        _s(g.get("gameStatusText")),
        _i(g.get("period")),
        _s(g.get("gameClock")),
        _iso_duration_to_seconds(g.get("gameClock")),
        _s(home.get("teamTricode")),
        _s(away.get("teamTricode")),
        _i(home.get("score")),
        _i(away.get("score")),
    )

    out["player_rows"] = await _record_player_state(pool, game_id, snapshot_at)
    if with_pbp:
        out["pbp_rows"] = await _record_pbp(pool, game_id)

    log.info(
        "live_game_captured",
        game_id=game_id,
        matchup=f"{_s(away.get('teamTricode'))}@{_s(home.get('teamTricode'))}",
        score=f"{_i(away.get('score'))}-{_i(home.get('score'))}",
        period=_i(g.get("period")),
        clock=_s(g.get("gameClock")),
        players=out["player_rows"],
        pbp=out["pbp_rows"],
    )
    return out


async def capture_once(pool: asyncpg.Pool, *, with_pbp: bool = True) -> dict[str, int]:
    """One poll: snapshot every currently-live game. Returns aggregate counts.

    `live_games` in the result tells the loop whether to keep going.
    """
    snapshot_at = datetime.now(UTC)
    totals = {"live_games": 0, "player_rows": 0, "pbp_rows": 0}

    try:
        games = await asyncio.to_thread(_fetch_scoreboard)
    except Exception as e:  # noqa: BLE001 — empty/garbage CDN response off-hours
        log.info("live_scoreboard_unavailable", error=str(e)[:160])
        return totals

    live = [g for g in games if _i(g.get("gameStatus")) == _GAME_STATUS_LIVE]
    totals["live_games"] = len(live)
    if not live:
        log.info("no_live_games", games_on_slate=len(games))
        return totals

    for g in live:
        try:
            r = await _record_game(pool, g, snapshot_at, with_pbp=with_pbp)
        except Exception as e:  # noqa: BLE001 — one bad game must not kill the poll
            log.warning("live_game_record_failed", game_id=_s(g.get("gameId")), error=str(e)[:160])
            continue
        totals["player_rows"] += r["player_rows"]
        totals["pbp_rows"] += r["pbp_rows"]

    log.info("live_capture_poll_done", **totals)
    return totals


async def run(*, loop: bool = False, interval: int = 60, with_pbp: bool = True) -> dict[str, int]:
    """Entry point. One-shot by default; `loop=True` re-polls until none are live."""
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    grand = {"polls": 0, "live_games": 0, "player_rows": 0, "pbp_rows": 0}
    try:
        await pool.execute(_CREATE)
        while True:
            r = await capture_once(pool, with_pbp=with_pbp)
            grand["polls"] += 1
            grand["live_games"] = r["live_games"]  # last poll's live count
            grand["player_rows"] += r["player_rows"]
            grand["pbp_rows"] += r["pbp_rows"]

            if not loop:
                break
            if r["live_games"] == 0:
                log.info("live_capture_loop_exit", reason="no_games_live", polls=grand["polls"])
                break
            await asyncio.sleep(interval)
        return grand
    finally:
        await close_pool()


def _main() -> None:
    p = argparse.ArgumentParser(description="Capture in-progress NBA games live.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--loop",
        action="store_true",
        help="re-poll every --interval seconds until no games are live",
    )
    mode.add_argument("--once", action="store_true", help="single snapshot then exit (default)")
    p.add_argument(
        "--interval", type=int, default=60, help="seconds between polls in --loop mode (default 60)"
    )
    p.add_argument(
        "--no-pbp",
        action="store_true",
        help="skip the play-by-play layer (state + player stats only)",
    )
    a = p.parse_args()

    res = asyncio.run(run(loop=a.loop, interval=a.interval, with_pbp=not a.no_pbp))

    mode_str = f"loop@{a.interval}s" if a.loop else "one-shot"
    print(f"\n  LIVE NBA CAPTURE · {datetime.now(UTC).isoformat(timespec='seconds')} · {mode_str}")
    if res["polls"] and res["player_rows"] == 0 and res["pbp_rows"] == 0 and res["live_games"] == 0:
        print(f"    no live games (polled {res['polls']}x) — exited cleanly")
    else:
        print(
            f"    polls={res['polls']} · live_games(last)={res['live_games']} · "
            f"player_rows={res['player_rows']} · pbp_rows={res['pbp_rows']}"
        )


if __name__ == "__main__":
    _main()
