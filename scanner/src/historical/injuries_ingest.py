"""Ingest free historical injury data into the unified injuries table.

NBA  — ProSportsTransactions dumps (Kaggle): rows are movements where
       'Relinquished' = went OUT and 'Acquired' = returned. We pair each
       out-event with the player's next return-event into an injury spell.
Soccer — Transfermarkt injury archive (salimt/football-datasets CSV), already
       in (from_date, end_date, days_missed, games_missed) form; joined to the
       profiles CSV for player names.

Run:
    python -m src.historical.injuries_ingest --nba   _data/injuries/nba1/injuries_2010-2020.csv _data/injuries/nba2/injury_data.csv
    python -m src.historical.injuries_ingest --soccer _data/injuries/soccer_injuries.csv _data/injuries/soccer_profiles.csv
"""

import argparse
import asyncio
import csv
import re
import unicodedata
from datetime import date, datetime

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log


def _slug(name: str) -> str:
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z]+", "", ascii_only).upper()


def _clean_player(s: str) -> str:
    # PST names often have a leading "• " bullet and "(a. ...)" annotations
    s = s.replace("•", "").strip()
    s = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
    return s


def _d(s: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


async def ingest_nba(pool, paths: list[str]) -> int:
    # Collect per-player out/return events, then pair into spells.
    events: dict[str, list[tuple[date, str, str, str]]] = {}
    for path in paths:
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            for row in csv.DictReader(f):
                d = _d(row.get("Date", ""))
                if not d:
                    continue
                team = (row.get("Team") or "").strip()
                notes = (row.get("Notes") or "").strip()
                out_p = _clean_player(row.get("Relinquished") or "")
                back_p = _clean_player(row.get("Acquired") or "")
                if out_p:
                    events.setdefault(out_p, []).append((d, "out", team, notes))
                if back_p:
                    events.setdefault(back_p, []).append((d, "back", team, notes))

    n = 0
    async with pool.acquire() as conn:
        for player, evs in events.items():
            evs.sort(key=lambda e: e[0])
            open_out: tuple[date, str, str] | None = None
            for d, kind, team, notes in evs:
                if kind == "out" and open_out is None:
                    open_out = (d, team, notes)
                elif kind == "back" and open_out is not None:
                    fr, team0, notes0 = open_out
                    await conn.execute(
                        """INSERT INTO injuries (sport, source, player_name, player_slug,
                             team, from_date, end_date, status, reason, days_missed)
                           VALUES ('nba','prosportstransactions',$1,$2,$3,$4,$5,'out',$6,$7)""",
                        player, _slug(player), team0, fr, d, notes0, (d - fr).days,
                    )
                    n += 1
                    open_out = None
            if open_out is not None:  # still out at dataset end
                fr, team0, notes0 = open_out
                await conn.execute(
                    """INSERT INTO injuries (sport, source, player_name, player_slug,
                         team, from_date, end_date, status, reason)
                       VALUES ('nba','prosportstransactions',$1,$2,$3,$4,NULL,'out',$5)""",
                    player, _slug(player), team0, fr, notes0,
                )
                n += 1
    log.info("nba_injuries_ingested", rows=n)
    return n


async def ingest_soccer(pool, injuries_csv: str, profiles_csv: str) -> int:
    # player_id -> (name, slug)
    names: dict[str, tuple[str, str]] = {}
    with open(profiles_csv, newline="", encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            pid = (row.get("player_id") or "").strip()
            nm = (row.get("player_name") or "").strip()
            if pid and nm:
                names[pid] = (nm, _slug(nm))

    n = 0
    async with pool.acquire() as conn:
        with open(injuries_csv, newline="", encoding="utf-8", errors="ignore") as f:
            for row in csv.DictReader(f):
                pid = (row.get("player_id") or "").strip()
                nm, slug = names.get(pid, (None, None))
                fr = _d(row.get("from_date", ""))
                if fr is None:
                    continue
                end = _d(row.get("end_date", ""))
                try:
                    dm = int(float(row["days_missed"])) if row.get("days_missed") else None
                except (ValueError, TypeError):
                    dm = None
                try:
                    gm = int(float(row["games_missed"])) if row.get("games_missed") else None
                except (ValueError, TypeError):
                    gm = None
                await conn.execute(
                    """INSERT INTO injuries (sport, source, player_name, player_slug,
                         from_date, end_date, status, reason, days_missed, games_missed,
                         external_player_id)
                       VALUES ('soccer','transfermarkt',$1,$2,$3,$4,'injured',$5,$6,$7,$8)""",
                    nm, slug, fr, end, (row.get("injury_reason") or "").strip(), dm, gm, pid,
                )
                n += 1
    log.info("soccer_injuries_ingested", rows=n)
    return n


async def main(nba: list[str] | None, soccer: list[str] | None) -> None:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        if nba:
            n = await ingest_nba(pool, nba)
            print(f"NBA injuries: {n:,} spells")
        if soccer:
            n = await ingest_soccer(pool, soccer[0], soccer[1])
            print(f"Soccer injuries: {n:,} rows")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--nba", nargs="*", default=None)
    p.add_argument("--soccer", nargs=2, default=None)
    a = p.parse_args()
    asyncio.run(main(a.nba, a.soccer))
