"""football-data.co.uk full ingest.

Two file families:
  1. Main leagues: /mmz4281/{season}/{code}.csv — one file per league-season,
     back to 1993-94. Codes: E0-E3/EC (England), SC0-3 (Scotland), D1-2
     (Germany), SP1-2 (Spain), I1-2 (Italy), F1-2 (France), N1 (NL), B1 (BE),
     P1 (PT), T1 (TR), G1 (GR).
  2. Extra leagues: /new/{COUNTRY}.csv — one file covering all seasons, for
     Argentina, Austria, Brazil, China, Denmark, Finland, Ireland, Japan,
     Mexico, Norway, Poland, Romania, Russia, Sweden, Switzerland, USA (MLS).

Both give full-time/half-time results + 1X2 odds (Bet365, Pinnacle, William
Hill, market max/avg) + over/under 2.5 + Asian handicap. Older files have
fewer columns; we capture what's present and stash the whole row as JSONB.

Run:
    python -m src.historical.footballdata               # everything
    python -m src.historical.footballdata --main-only
    python -m src.historical.footballdata --from-year 2010
"""

import argparse
import asyncio
import csv
import io
from datetime import date, datetime

import httpx

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

BASE = "https://www.football-data.co.uk"

MAIN_CODES = {
    "E0": ("England", "Premier League"),
    "E1": ("England", "Championship"),
    "E2": ("England", "League One"),
    "E3": ("England", "League Two"),
    "EC": ("England", "Conference"),
    "SC0": ("Scotland", "Premiership"),
    "SC1": ("Scotland", "Championship"),
    "SC2": ("Scotland", "League One"),
    "SC3": ("Scotland", "League Two"),
    "D1": ("Germany", "Bundesliga"),
    "D2": ("Germany", "2. Bundesliga"),
    "SP1": ("Spain", "La Liga"),
    "SP2": ("Spain", "La Liga 2"),
    "I1": ("Italy", "Serie A"),
    "I2": ("Italy", "Serie B"),
    "F1": ("France", "Ligue 1"),
    "F2": ("France", "Ligue 2"),
    "N1": ("Netherlands", "Eredivisie"),
    "B1": ("Belgium", "Jupiler League"),
    "P1": ("Portugal", "Primeira Liga"),
    "T1": ("Turkey", "Super Lig"),
    "G1": ("Greece", "Super League"),
}

EXTRA_FILES = {
    "ARG": ("Argentina", "Primera Division"),
    "AUT": ("Austria", "Bundesliga"),
    "BRA": ("Brazil", "Serie A"),
    "CHN": ("China", "Super League"),
    "DNK": ("Denmark", "Superliga"),
    "FIN": ("Finland", "Veikkausliiga"),
    "IRL": ("Ireland", "Premier Division"),
    "JPN": ("Japan", "J1 League"),
    "MEX": ("Mexico", "Liga MX"),
    "NOR": ("Norway", "Eliteserien"),
    "POL": ("Poland", "Ekstraklasa"),
    "ROU": ("Romania", "Liga 1"),
    "RUS": ("Russia", "Premier League"),
    "SWE": ("Sweden", "Allsvenskan"),
    "SWZ": ("Switzerland", "Super League"),
    "USA": ("USA", "MLS"),
}


def _season_codes(from_year: int, to_year: int) -> list[str]:
    """1993 -> '9394', 2024 -> '2425'."""
    out = []
    for y in range(from_year, to_year + 1):
        a = y % 100
        b = (y + 1) % 100
        out.append(f"{a:02d}{b:02d}")
    return out


def _season_label(code: str) -> str:
    return f"20{code[:2]}-{code[2:]}" if code[0] in "012" else f"19{code[:2]}-{code[2:]}"


def _f(v) -> float | None:
    try:
        return float(v) if v not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None


def _i(v) -> int | None:
    try:
        return int(float(v)) if v not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None


def _parse_date(v: str) -> date | None:
    if not v:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(v.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _row_to_record(row: dict, *, country: str, league_code: str,
                   league_name: str, season: str) -> dict | None:
    home = (row.get("HomeTeam") or row.get("Home") or "").strip()
    away = (row.get("AwayTeam") or row.get("Away") or "").strip()
    if not home or not away:
        return None
    md = _parse_date(row.get("Date") or "")
    # 1X2: prefer pre-match market avg, then closing (C-suffix, used by the
    # extra-league /new/ files), then Bet365, then Pinnacle (pre + closing).
    odds_home = (_f(row.get("AvgH")) or _f(row.get("AvgCH")) or _f(row.get("BbAvH"))
                 or _f(row.get("B365H")) or _f(row.get("B365CH"))
                 or _f(row.get("PH")) or _f(row.get("PSH")) or _f(row.get("PSCH")))
    odds_draw = (_f(row.get("AvgD")) or _f(row.get("AvgCD")) or _f(row.get("BbAvD"))
                 or _f(row.get("B365D")) or _f(row.get("B365CD"))
                 or _f(row.get("PD")) or _f(row.get("PSD")) or _f(row.get("PSCD")))
    odds_away = (_f(row.get("AvgA")) or _f(row.get("AvgCA")) or _f(row.get("BbAvA"))
                 or _f(row.get("B365A")) or _f(row.get("B365CA"))
                 or _f(row.get("PA")) or _f(row.get("PSA")) or _f(row.get("PSCA")))
    return {
        "country": country,
        "league_code": league_code,
        "league_name": league_name,
        "season": season,
        "match_date": md,
        "home_team": home,
        "away_team": away,
        "fthg": _i(row.get("FTHG") if row.get("FTHG") is not None else row.get("HG")),
        "ftag": _i(row.get("FTAG") if row.get("FTAG") is not None else row.get("AG")),
        "ftr": (row.get("FTR") or row.get("Res") or "").strip() or None,
        "hthg": _i(row.get("HTHG")),
        "htag": _i(row.get("HTAG")),
        "odds_home": odds_home,
        "odds_draw": odds_draw,
        "odds_away": odds_away,
        "pinnacle_home": _f(row.get("PSH")) or _f(row.get("PSCH")) or _f(row.get("PH")),
        "pinnacle_draw": _f(row.get("PSD")) or _f(row.get("PSCD")) or _f(row.get("PD")),
        "pinnacle_away": _f(row.get("PSA")) or _f(row.get("PSCA")) or _f(row.get("PA")),
        "over25": (_f(row.get("Avg>2.5")) or _f(row.get("AvgC>2.5"))
                   or _f(row.get("B365>2.5")) or _f(row.get("P>2.5"))),
        "under25": (_f(row.get("Avg<2.5")) or _f(row.get("AvgC<2.5"))
                    or _f(row.get("B365<2.5")) or _f(row.get("P<2.5"))),
        "ah_line": _f(row.get("AHh") or row.get("AHCh")),
        "ah_home": _f(row.get("AvgAHH") or row.get("B365AHH") or row.get("PAHH")),
        "ah_away": _f(row.get("AvgAHA") or row.get("B365AHA") or row.get("PAHA")),
        "raw": {k: v for k, v in row.items() if v not in (None, "")},
    }


async def _insert_records(pool, records: list[dict]) -> int:
    if not records:
        return 0
    import json
    cols = [
        "country", "league_code", "league_name", "season", "match_date",
        "home_team", "away_team", "fthg", "ftag", "ftr", "hthg", "htag",
        "odds_home", "odds_draw", "odds_away", "pinnacle_home", "pinnacle_draw",
        "pinnacle_away", "over25", "under25", "ah_line", "ah_home", "ah_away", "raw",
    ]
    placeholders = ",".join(f"${i+1}" for i in range(len(cols)))
    sql = f"""
        INSERT INTO soccer_match_odds ({",".join(cols)})
        VALUES ({placeholders})
        ON CONFLICT (league_code, season, match_date, home_team, away_team)
        DO NOTHING
    """
    n = 0
    async with pool.acquire() as conn:
        for rec in records:
            if rec["match_date"] is None:
                continue
            values = [rec[c] for c in cols]
            values[-1] = json.dumps(values[-1])  # raw -> json
            await conn.execute(sql, *values)
            n += 1
    return n


async def _ingest_csv(client, pool, url, *, country, league_code, league_name, season) -> int:
    try:
        r = await client.get(url)
        if r.status_code != 200 or not r.text.strip():
            return 0
    except Exception as e:
        log.warning("footballdata_fetch_failed", url=url, error=str(e))
        return 0

    text = r.text
    reader = csv.DictReader(io.StringIO(text))
    records = []
    for row in reader:
        rec = _row_to_record(
            row, country=country, league_code=league_code,
            league_name=league_name, season=season,
        )
        if rec:
            records.append(rec)
    n = await _insert_records(pool, records)
    if n:
        log.info("footballdata_file_done", code=league_code, season=season, rows=n)
    return n


async def ingest_main(pool, client, from_year: int, to_year: int) -> int:
    total = 0
    for season_code in _season_codes(from_year, to_year):
        season_label = _season_label(season_code)
        for code, (country, name) in MAIN_CODES.items():
            url = f"{BASE}/mmz4281/{season_code}/{code}.csv"
            total += await _ingest_csv(
                client, pool, url, country=country, league_code=code,
                league_name=name, season=season_label,
            )
    return total


async def ingest_extra(pool, client) -> int:
    """Extra-league files cover all seasons in one CSV — the row's own
    Season column is used per-record (we set season at file level to 'all'
    then the raw retains the real one)."""
    total = 0
    for short, (country, name) in EXTRA_FILES.items():
        url = f"{BASE}/new/{short}.csv"
        try:
            r = await client.get(url)
            if r.status_code != 200 or not r.text.strip():
                continue
        except Exception as e:
            log.warning("footballdata_extra_failed", short=short, error=str(e))
            continue
        reader = csv.DictReader(io.StringIO(r.text))
        records = []
        for row in reader:
            season = (row.get("Season") or "all").strip()
            rec = _row_to_record(
                row, country=country, league_code=f"X-{short}",
                league_name=name, season=season,
            )
            if rec:
                records.append(rec)
        n = await _insert_records(pool, records)
        total += n
        log.info("footballdata_extra_done", short=short, rows=n)
    return total


async def main(*, from_year: int = 1993, to_year: int = 2024,
               main_only: bool = False, extra_only: bool = False) -> None:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            total = 0
            if not extra_only:
                total += await ingest_main(pool, client, from_year, to_year)
            if not main_only:
                total += await ingest_extra(pool, client)
            log.info("footballdata_complete", total_rows=total)
            print(f"football-data ingest complete: {total:,} matches")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from-year", type=int, default=1993)
    p.add_argument("--to-year", type=int, default=2024)
    p.add_argument("--main-only", action="store_true")
    p.add_argument("--extra-only", action="store_true")
    a = p.parse_args()
    asyncio.run(main(from_year=a.from_year, to_year=a.to_year,
                     main_only=a.main_only, extra_only=a.extra_only))
