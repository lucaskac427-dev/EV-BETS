"""NBA team identity — the one place that maps odds full names to game-log
abbreviations, and resolves franchise relocations.

`historical_odds_snapshots` carries full names ("Oklahoma City Thunder");
`player_game_logs` carries 3-letter abbreviations ("OKC"). The game model and
backtest must join the two, so this mapping lives in one shared module rather
than being duplicated.

Only the 30 current NBA franchises are modeled. The game logs also contain
non-NBA noise (FIBA / preseason exhibition teams like BAR, MEL, FCB); those
abbreviations are intentionally absent here and get filtered out upstream.
"""

from __future__ import annotations

# Canonical 3-letter abbreviation -> current full franchise name.
NBA_TEAMS: dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}

# Historical abbreviations that map onto a current franchise (relocations /
# renames). These appear in older game-log rows and must collapse to today's
# abbreviation so a team's history is continuous.
ABBR_ALIASES: dict[str, str] = {
    "NJN": "BKN",  # New Jersey Nets -> Brooklyn
    "NOH": "NOP",  # New Orleans Hornets -> Pelicans
    "NOK": "NOP",  # New Orleans/Oklahoma City Hornets -> Pelicans
    "SEA": "OKC",  # Seattle SuperSonics -> Oklahoma City Thunder
}

# Full name (lower-cased) -> abbreviation, including a few alternates the odds
# feed has used over the years.
_NAME_TO_ABBR: dict[str, str] = {name.lower(): abbr for abbr, name in NBA_TEAMS.items()}
_NAME_TO_ABBR.update(
    {
        "la clippers": "LAC",
        "los angeles clippers": "LAC",
        "la lakers": "LAL",
    }
)

# The set of abbreviations we consider "real NBA" for filtering game logs.
NBA_ABBRS: frozenset[str] = frozenset(NBA_TEAMS) | frozenset(ABBR_ALIASES)


def canonical_abbr(abbr: str | None) -> str | None:
    """Collapse a game-log abbreviation onto its current franchise, or None if
    it isn't one of the 30 NBA teams."""
    if not abbr:
        return None
    a = abbr.strip().upper()
    a = ABBR_ALIASES.get(a, a)
    return a if a in NBA_TEAMS else None


def abbr_from_full_name(name: str | None) -> str | None:
    """Map an odds-feed full team name to its abbreviation, or None."""
    if not name:
        return None
    return _NAME_TO_ABBR.get(name.strip().lower())
