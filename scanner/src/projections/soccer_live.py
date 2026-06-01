"""Live 1X2 — price today's soccer matches with the calibrated Poisson model.

This operationalizes the match model proven in `calibrate_soccer` (the one that
beats climatology and is well-calibrated on big-5 1X2). For a chosen league it:

  1. pulls live moneyline odds (h2h = home / draw / away) from The Odds API,
  2. builds the walk-forward league model from our ~300K-match history AS OF
     today (no leakage — only matches before now feed the ratings),
  3. prices each match (home/draw/away fair probabilities), devigs the book
     consensus, and ranks matches by model-vs-market edge at the BEST price.

The hard part is name resolution: the Odds API says "Atletico Mineiro", our
history says "Atletico-MG". A normalizer + alias map + fuzzy fallback bridges
them; anything still unmatched is reported, never silently mispriced.

Usage:
    python -m src.projections.soccer_live --list
    python -m src.projections.soccer_live --league brazil
    python -m src.projections.soccer_live --league epl --min-edge 0.03
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import re
import unicodedata
from datetime import date, datetime, timezone
from statistics import median

import httpx

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging
from src.projections.soccer_match import (
    build_league_model,
    expected_goals,
    market_probs,
)

# cli alias -> (odds_api_sport_key, our league_code in soccer_match_odds).
# Calibration-verified leagues (big-5) are flagged in CALIBRATED below.
LEAGUE_MAP: dict[str, tuple[str, str]] = {
    "epl": ("soccer_epl", "E0"),
    "championship": ("soccer_efl_champ", "E1"),
    "laliga": ("soccer_spain_la_liga", "SP1"),
    "laliga2": ("soccer_spain_segunda_division", "SP2"),
    "seriea": ("soccer_italy_serie_a", "I1"),
    "serieb": ("soccer_italy_serie_b", "I2"),
    "bundesliga": ("soccer_germany_bundesliga", "D1"),
    "bundesliga2": ("soccer_germany_bundesliga2", "D2"),
    "ligue1": ("soccer_france_ligue_one", "F1"),
    "ligue2": ("soccer_france_ligue_two", "F2"),
    "eredivisie": ("soccer_netherlands_eredivisie", "N1"),
    "primeira": ("soccer_portugal_primeira_liga", "P1"),
    "superlig": ("soccer_turkey_super_league", "T1"),
    "belgium": ("soccer_belgium_first_div", "B1"),
    "greece": ("soccer_greece_super_league", "G1"),
    "scotland": ("soccer_spl", "SC0"),
    "brazil": ("soccer_brazil_campeonato", "X-BRA"),
    "mls": ("soccer_usa_mls", "X-USA"),
    "argentina": ("soccer_argentina_primera_division", "X-ARG"),
    "mexico": ("soccer_mexico_ligamx", "X-MEX"),
    "jleague": ("soccer_japan_j_league", "X-JPN"),
    "china": ("soccer_china_superleague", "X-CHN"),
    "norway": ("soccer_norway_eliteserien", "X-NOR"),
    "sweden": ("soccer_sweden_allsvenskan", "X-SWE"),
    "denmark": ("soccer_denmark_superliga", "X-DNK"),
    "finland": ("soccer_finland_veikkausliiga", "X-FIN"),
    "poland": ("soccer_poland_ekstraklasa", "X-POL"),
    "romania": ("soccer_romania_liga_1", "X-ROU"),
    "russia": ("soccer_russia_premier_league", "X-RUS"),
    "austria": ("soccer_austria_bundesliga", "X-AUT"),
    "switzerland": ("soccer_switzerland_superleague", "X-SWZ"),
}

# Big-5 main divisions are the ones calibrate_soccer proved trustworthy.
CALIBRATED = {"E0", "SP1", "I1", "D1", "F1"}

# Residual name fixes fuzzy/normalize can't get — mostly clubs that share a
# city/name and are disambiguated only by a state or suffix code. Keyed by
# normalized Odds-API name -> exact DB team string.
HARD_ALIASES: dict[str, str] = {
    # Brazil — state codes disambiguate genuinely different clubs.
    "atletico mineiro": "Atletico-MG",
    "atletico paranaense": "Athletico-PR",
    "atletico goianiense": "Atletico GO",
    "athletico paranaense": "Athletico-PR",
    "botafogo": "Botafogo RJ",
    "bragantino": "Bragantino",
    "red bull bragantino": "Bragantino",
    "vasco da gama": "Vasco",
    "chapecoense": "Chapecoense-SC",
    # Japan
    "urawa red diamonds": "Urawa",
    "kyoto purple sanga": "Kyoto",
    "yokohama f marinos": "Yokohama FM",
    "shimizu s pulse": "Shimizu S-Pulse",
    "v varen nagasaki": "V-Varen Nagasaki",
    "machida zelvia": "Machida",
    "fc machida zelvia": "Machida",
    # Norway
    "viking fk": "Viking",
}

_SUFFIX = re.compile(
    r"\b(fc|cf|sc|afc|ac|fk|sk|if|bk|cd|ud|us|ss|club|de|the)\b"
)


def _norm(name: str) -> str:
    """Accent-fold, lowercase, strip punctuation + common club suffixes."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("-", " ").replace(".", " ").replace("/", " ")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def resolve_team(
    api_name: str, candidates: list[str], aliases: dict[str, str] = HARD_ALIASES
) -> str | None:
    """Map an Odds-API team name to one of the model's known teams.

    Order: hard alias -> exact normalized -> token-subset -> fuzzy ratio.
    Returns None when nothing clears the bar (caller reports it, never guesses)."""
    na = _norm(api_name)
    if na in aliases and aliases[na] in candidates:
        return aliases[na]

    norm_map: dict[str, str] = {}
    for c in candidates:
        norm_map.setdefault(_norm(c), c)

    if na in norm_map:
        return norm_map[na]

    # Token subset: every significant token of one name appears in the other.
    a_tok = set(na.split())
    best_tok: tuple[int, str] | None = None
    for nc, orig in norm_map.items():
        c_tok = set(nc.split())
        if not a_tok or not c_tok:
            continue
        if a_tok <= c_tok or c_tok <= a_tok:
            overlap = len(a_tok & c_tok)
            if best_tok is None or overlap > best_tok[0]:
                best_tok = (overlap, orig)
    if best_tok is not None:
        return best_tok[1]

    # Fuzzy fallback on the normalized strings.
    hit = difflib.get_close_matches(na, list(norm_map.keys()), n=1, cutoff=0.74)
    if hit:
        return norm_map[hit[0]]
    return None


async def fetch_live_h2h(sport_key: str) -> list[dict]:
    """Return [{home, away, commence, prices:{outcome:[decimals]}}] for a sport.
    `prices` keys are 'home'/'draw'/'away'; values are every book's decimal odds."""
    if not settings.odds_api_key:
        raise RuntimeError("ODDS_API_KEY missing")
    async with httpx.AsyncClient(base_url=settings.odds_api_base, timeout=20.0) as c:
        r = await c.get(
            f"/sports/{sport_key}/odds",
            params={
                "apiKey": settings.odds_api_key,
                "regions": "us,us2",
                "markets": "h2h",
                "oddsFormat": "decimal",
            },
        )
        r.raise_for_status()
        events = r.json()

    out: list[dict] = []
    for e in events:
        home, away = e.get("home_team"), e.get("away_team")
        if not home or not away:
            continue
        prices: dict[str, list[float]] = {"home": [], "draw": [], "away": []}
        for bm in e.get("bookmakers", []):
            for mk in bm.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                for o in mk.get("outcomes", []):
                    nm, price = o.get("name"), o.get("price")
                    if price is None:
                        continue
                    if nm == home:
                        prices["home"].append(float(price))
                    elif nm == away:
                        prices["away"].append(float(price))
                    elif nm == "Draw":
                        prices["draw"].append(float(price))
        if prices["home"] and prices["away"]:
            out.append(
                {"home": home, "away": away, "commence": e.get("commence_time"), "prices": prices}
            )
    return out


def _devig_consensus(prices: dict[str, list[float]]) -> dict[str, float] | None:
    """Median decimal per outcome -> implied -> normalize to a vig-free market."""
    med = {k: median(v) for k, v in prices.items() if v}
    if "home" not in med or "away" not in med:
        return None
    implied = {k: 1.0 / v for k, v in med.items()}
    s = sum(implied.values())
    if s <= 0:
        return None
    return {k: v / s for k, v in implied.items()}


# Cross-league cups have no single domestic model spanning both teams, so we
# price them off ClubElo — one Elo scale across all of Europe (includes each
# club's cup form). cli alias -> Odds API sport key.
ELO_LEAGUES: dict[str, str] = {
    "ucl": "soccer_uefa_champs_league",
    "europa": "soccer_uefa_europa_league",
    "conference": "soccer_uefa_europa_conference_league",
}

# Elo -> goals heuristics. Tunable; calibrate against CL results later.
ELO_HOME_ADV = 65.0          # Elo points of home advantage (0 at neutral finals)
ELO_GOALS_PER_POINT = 0.004  # ~0.4 expected goal supremacy per 100 Elo
ELO_TOTAL_GOALS = 2.75       # CL-era average total goals

# Odds-API full names -> ClubElo's short names.
CLUBELO_ALIASES: dict[str, str] = {
    "bayern munich": "Bayern", "manchester city": "Man City",
    "manchester united": "Man United", "inter milan": "Inter",
    "internazionale": "Inter", "ac milan": "Milan",
    "paris saint germain": "Paris SG", "paris saint-germain": "Paris SG",
    "atletico madrid": "Atletico", "atletico de madrid": "Atletico",
    "borussia dortmund": "Dortmund", "borussia monchengladbach": "Gladbach",
    "real sociedad": "Sociedad", "rb leipzig": "RB Leipzig",
    "bayer leverkusen": "Leverkusen", "sporting cp": "Sporting",
    "tottenham hotspur": "Tottenham", "wolverhampton wanderers": "Wolves",
}


def _load_clubelo() -> dict[str, float]:
    """Current cross-league Elo for every European club (soccerdata.ClubElo)."""
    import soccerdata as sd

    df = sd.ClubElo().read_by_date().reset_index()
    return {str(r["team"]): float(r["elo"]) for _, r in df.iterrows()}


def _elo_expected_goals(
    elo_home: float, elo_away: float, *, neutral: bool = False
) -> tuple[float, float]:
    """Map an Elo gap to a (lam_home, lam_away) goal expectation, then the
    existing Dixon-Coles machinery turns it into 1X2/totals/BTTS."""
    dr = elo_home - elo_away + (0.0 if neutral else ELO_HOME_ADV)
    sup = dr * ELO_GOALS_PER_POINT
    lam_home = max((ELO_TOTAL_GOALS + sup) / 2.0, 0.05)
    lam_away = max((ELO_TOTAL_GOALS - sup) / 2.0, 0.05)
    return lam_home, lam_away


async def run(league: str, min_edge: float, *, neutral: bool = False) -> None:
    configure_logging(level="WARNING")
    as_of = date.today()
    pool = await get_pool()
    try:
        # Set up the pricing function + team universe for either a domestic
        # Poisson model or the ClubElo cross-league path.
        if league in ELO_LEAGUES:
            sport_key = ELO_LEAGUES[league]
            try:
                elo = await asyncio.to_thread(_load_clubelo)
            except Exception as e:
                print(f"  ClubElo load failed: {e}")
                return
            teams = list(elo.keys())
            aliases = CLUBELO_ALIASES
            header = f"{league.upper()} · ClubElo cross-league ({len(teams)} clubs)"
            calibrated = False

            def price(h: str, a: str) -> tuple[float, float] | None:
                return _elo_expected_goals(elo[h], elo[a], neutral=neutral)
        elif league in LEAGUE_MAP:
            sport_key, league_code = LEAGUE_MAP[league]
            rows = await pool.fetch(
                """SELECT match_date, home_team, away_team, fthg, ftag
                   FROM soccer_match_odds
                   WHERE league_code=$1 AND fthg IS NOT NULL
                     AND match_date >= $2::date - 900
                     AND match_date < $2::date
                   ORDER BY match_date""",
                league_code, as_of,
            )
            history = [dict(r) for r in rows]
            if len(history) < 200:
                print(f"  Not enough history for {league_code} ({len(history)} matches) — can't model.")
                return
            model = build_league_model(history, as_of=as_of)
            teams = list(model.ratings.keys())
            aliases = HARD_ALIASES
            header = f"{league.upper()} ({league_code}) · {len(history):,} match history"
            calibrated = league_code in CALIBRATED

            def price(h: str, a: str) -> tuple[float, float] | None:
                return expected_goals(model, h, a)
        else:
            opts = ", ".join(sorted([*LEAGUE_MAP, *ELO_LEAGUES]))
            print(f"Unknown league '{league}'. Options: {opts}")
            return

        try:
            events = await fetch_live_h2h(sport_key)
        except Exception as e:
            print(f"  Odds API fetch failed: {e}")
            return

        graded: list[dict] = []
        unmatched: list[str] = []
        for ev in events:
            h = resolve_team(ev["home"], teams, aliases)
            a = resolve_team(ev["away"], teams, aliases)
            if h is None:
                unmatched.append(ev["home"])
            if a is None:
                unmatched.append(ev["away"])
            if h is None or a is None:
                continue
            eg = price(h, a)
            if not eg:
                continue
            mp = market_probs(*eg)
            market = _devig_consensus(ev["prices"])
            if not market:
                continue
            model_p = {"home": mp["home_win"], "draw": mp["draw"], "away": mp["away_win"]}
            best = {k: max(v) for k, v in ev["prices"].items() if v}
            legs = []
            for side in ("home", "draw", "away"):
                if side not in best or side not in market:
                    continue
                ev_pct = model_p[side] * best[side] - 1.0
                legs.append(
                    {
                        "side": side,
                        "model": model_p[side],
                        "market": market[side],
                        "price": best[side],
                        "edge": ev_pct,
                    }
                )
            if not legs:
                continue
            top = max(legs, key=lambda x: x["edge"])
            graded.append(
                {
                    "home": ev["home"], "away": ev["away"],
                    "mh": h, "ma": a, "commence": ev["commence"],
                    "eg": eg, "legs": legs, "top": top,
                }
            )

        graded.sort(key=lambda x: x["top"]["edge"], reverse=True)
        flag = "🟢 calibration-verified" if calibrated else "⚠️  model applied (not calibration-verified)"
        venue = " · NEUTRAL venue" if (neutral and league in ELO_LEAGUES) else ""
        print(f"\n  LIVE 1X2 · {header}{venue} · {len(graded)} matches priced · {flag}")
        print(f"  as of {as_of}")
        print("  " + "─" * 86)
        shown = 0
        for g in graded:
            if g["top"]["edge"] < min_edge:
                continue
            shown += 1
            t = g["top"]
            sidelbl = {"home": g["home"], "draw": "Draw", "away": g["away"]}[t["side"]]
            ko = _fmt_ko(g["commence"])
            print(f"  {g['home']} vs {g['away']}  ({ko})")
            print(f"      xG {g['eg'][0]:.2f}–{g['eg'][1]:.2f}  →  best bet: {sidelbl}  @ {t['price']:.2f}")
            print(f"      model {t['model']*100:5.1f}%  vs  market {t['market']*100:5.1f}%   EDGE +{t['edge']*100:5.2f}%")
            others = [l for l in g["legs"] if l["side"] != t["side"]]
            detail = "   ".join(
                f"{s['side']}: m{ s['model']*100:.0f}%/k{s['market']*100:.0f}% @{s['price']:.2f} ({s['edge']*100:+.1f}%)"
                for s in others
            )
            print(f"      {detail}")
        if shown == 0:
            print(f"  No matches clear +{min_edge*100:.0f}% edge. Lower --min-edge to see the full board.")
        if unmatched:
            uniq = sorted(set(unmatched))
            print(f"\n  ⚠️  unmatched teams (skipped): {', '.join(uniq)}")
    finally:
        await close_pool()


def _fmt_ko(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%b %d %H:%MZ")
    except Exception:
        return iso


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--league", default="brazil")
    p.add_argument("--min-edge", type=float, default=0.0)
    p.add_argument("--neutral", action="store_true",
                   help="Neutral venue (no home advantage) — for ClubElo finals")
    p.add_argument("--list", action="store_true", help="list mappable leagues + exit")
    a = p.parse_args()
    if a.list:
        print("Domestic leagues (Poisson model):")
        for name, (sk, lc) in sorted(LEAGUE_MAP.items()):
            tag = "  [calibration-verified]" if lc in CALIBRATED else ""
            print(f"  {name:14s} -> {lc:6s} {sk}{tag}")
        print("\nCross-league cups (ClubElo pricing; add --neutral for finals):")
        for name, sk in sorted(ELO_LEAGUES.items()):
            print(f"  {name:14s} -> {sk}")
    else:
        asyncio.run(run(a.league, a.min_edge, neutral=a.neutral))
