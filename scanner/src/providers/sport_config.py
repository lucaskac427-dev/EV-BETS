"""Per-sport mappings for The Odds API + PrizePicks.

Adding a new sport / league = add one entry to ODDS_API_SPORTS and
PRIZEPICKS_LEAGUES. The pipeline reads these to know which market keys to
fetch and how to normalize stat names into the canonical synth ticker.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OddsApiSportConfig:
    """How to query The Odds API for a given sport, plus market->stat mapping."""

    sport_key: str  # e.g. 'basketball_nba', 'soccer_uefa_champs_league'
    sport_tag: str  # internal namespace, e.g. 'NBA', 'SOCCER'
    # us + us2 unlocks Hard Rock (incl. hardrockbet_fl), ESPN Bet, Fliff,
    # BetPARX, Bally, ReBet on top of the standard us books — deeper consensus
    # and Hard Rock as a FL-legal target book.
    regions: str = "us,us2"
    # Odds API market key -> internal stat key (used in the synth ticker).
    market_to_stat: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PrizePicksLeagueConfig:
    league_id: int
    sport_tag: str
    # PrizePicks stat name -> internal stat key. Keys must match the values
    # produced by the matching OddsApiSportConfig.market_to_stat so quotes
    # join via the synth ticker.
    stat_to_internal: dict[str, str] = field(default_factory=dict)


# NBA — original config preserved.
NBA_ODDS = OddsApiSportConfig(
    sport_key="basketball_nba",
    sport_tag="NBA",
    regions="us,us2,eu,au",  # eu adds Pinnacle (sharp anchor); au adds 8 more books
    market_to_stat={
        "player_points": "points",
        "player_assists": "assists",
        "player_rebounds": "rebounds",
        "player_threes": "threes",
        "player_blocks": "blocks",
        "player_steals": "steals",
        "player_points_rebounds_assists": "pra",
    },
)

NBA_PRIZEPICKS = PrizePicksLeagueConfig(
    league_id=7,
    sport_tag="NBA",
    stat_to_internal={
        "Points": "points",
        "Assists": "assists",
        "Rebounds": "rebounds",
        "3-PT Made": "threes",
        "Blocked Shots": "blocks",
        "Steals": "steals",
        "Pts+Rebs+Asts": "pra",
    },
)

# MLB — internal keys are the OVERLAP of what the DFS apps post and what the
# sharp books price. DFS-only combos (Hits+Runs+RBIs, Hitter Fantasy Score) and
# batter strikeouts (no pitcher-side market) are left unmapped → filtered out,
# same rule as soccer. Book depth: strikeouts 9, total_bases 9, pitcher_outs 7,
# hits 6, home_runs 5, rbis 4 are the core; the rest are thin (1–3 books).
MLB_ODDS = OddsApiSportConfig(
    sport_key="baseball_mlb",
    sport_tag="MLB",
    market_to_stat={
        "pitcher_strikeouts": "strikeouts",
        "batter_total_bases": "total_bases",
        "pitcher_outs": "pitcher_outs",
        "batter_hits": "hits",
        "batter_home_runs": "home_runs",
        "batter_rbis": "rbis",
        "pitcher_hits_allowed": "hits_allowed",
        "batter_singles": "singles",
        "pitcher_earned_runs": "earned_runs",
        "batter_stolen_bases": "stolen_bases",
        "batter_doubles": "doubles",
        "batter_runs_scored": "runs",
        "batter_walks": "batter_walks",
        "pitcher_walks": "pitcher_walks",
    },
)

MLB_PRIZEPICKS = PrizePicksLeagueConfig(
    league_id=2,
    sport_tag="MLB",
    stat_to_internal={
        "Pitcher Strikeouts": "strikeouts",
        "Total Bases": "total_bases",
        "Pitching Outs": "pitcher_outs",
        "Hits": "hits",
        "Home Runs": "home_runs",
        "RBIs": "rbis",
        "Hits Allowed": "hits_allowed",
        "Singles": "singles",
        "Earned Runs Allowed": "earned_runs",
        "Stolen Bases": "stolen_bases",
        "Doubles": "doubles",
        "Runs": "runs",
        "Walks": "batter_walks",
        "Walks Allowed": "pitcher_walks",
        # "Hitter Strikeouts" (batter) has no pitcher-side sharp market — unmapped.
        # "Hits+Runs+RBIs" / "Hitter Fantasy Score" are DFS-only combos — unmapped.
    },
)

# WNBA — basketball, identical stat vocabulary to the NBA, so the providers'
# NBA stat-map fallback already handles it. Books offer points/rebounds/assists/
# threes/PRA (NOT blocks/steals — and those were the −EV noise markets in NBA
# anyway). 10 books incl. Pinnacle on The Odds API. In season May–Sept.
WNBA_ODDS = OddsApiSportConfig(
    sport_key="basketball_wnba",
    sport_tag="WNBA",
    regions="us,us2,eu,au",
    market_to_stat={
        "player_points": "points",
        "player_rebounds": "rebounds",
        "player_assists": "assists",
        "player_threes": "threes",
        "player_points_rebounds_assists": "pra",
    },
)

WNBA_PRIZEPICKS = PrizePicksLeagueConfig(
    league_id=3,  # confirmed live: PrizePicks "WNBA" = league_id 3 (4,296 lines)
    sport_tag="WNBA",
    stat_to_internal={
        "Points": "points",
        "Rebounds": "rebounds",
        "Assists": "assists",
        "3-PT Made": "threes",
        "Pts+Rebs+Asts": "pra",
    },
)

# Soccer — new. Maps PrizePicks names to the same internal keys the Odds API
# emits, so synth tickers join across the two.
#
# Only stats with overlap on both sides are listed — PrizePicks-only stats
# (Passes Attempted, Clearances, Crosses, Attempted Dribbles, Shots Assisted)
# get filtered out by the parser because no sharp consensus exists.
SOCCER_ODDS_UCL = OddsApiSportConfig(
    sport_key="soccer_uefa_champs_league",
    sport_tag="SOCCER",
    market_to_stat={
        "player_shots": "shots",
        "player_shots_on_target": "shots_on_target",
        "player_assists": "assists",
        "player_tackles": "tackles",
        "player_goalie_saves": "goalie_saves",
        # Note: player_goal_scorer_anytime + player_to_receive_card are BINARY
        # (Yes/No, no point) — different math, handled separately.
        # player_fouls_committed is rejected as INVALID_MARKET by the API.
    },
)

SOCCER_ODDS_WORLD_CUP = OddsApiSportConfig(
    sport_key="soccer_fifa_world_cup",
    sport_tag="SOCCER",
    market_to_stat=SOCCER_ODDS_UCL.market_to_stat,
)

# Additional active leagues to scan as they come into season — share UCL's
# market map since the market keys are global per-sport.
SOCCER_ODDS_BRAZIL_SERIE_A = OddsApiSportConfig(
    sport_key="soccer_brazil_campeonato",
    sport_tag="SOCCER",
    market_to_stat=SOCCER_ODDS_UCL.market_to_stat,
)

SOCCER_ODDS_J_LEAGUE = OddsApiSportConfig(
    sport_key="soccer_japan_j_league",
    sport_tag="SOCCER",
    market_to_stat=SOCCER_ODDS_UCL.market_to_stat,
)

SOCCER_ODDS_COPA_SUDAMERICANA = OddsApiSportConfig(
    sport_key="soccer_conmebol_copa_sudamericana",
    sport_tag="SOCCER",
    market_to_stat=SOCCER_ODDS_UCL.market_to_stat,
)

SOCCER_PRIZEPICKS = PrizePicksLeagueConfig(
    league_id=82,  # PrizePicks generic 'SOCCER'
    sport_tag="SOCCER",
    stat_to_internal={
        "Shots": "shots",
        "Shots On Target": "shots_on_target",
        "Assists": "assists",
        "Tackles": "tackles",
        "Fouls": "fouls",
        "Goals": "goals",  # binary on the sharp side; flagged separately
        "Goalie Saves": "goalie_saves",
    },
)


# Lookup tables
ODDS_API_SPORTS: dict[str, OddsApiSportConfig] = {
    "nba": NBA_ODDS,
    "mlb": MLB_ODDS,
    "wnba": WNBA_ODDS,
    "soccer_ucl": SOCCER_ODDS_UCL,
    "soccer_world_cup": SOCCER_ODDS_WORLD_CUP,
}

PRIZEPICKS_LEAGUES: dict[str, PrizePicksLeagueConfig] = {
    "nba": NBA_PRIZEPICKS,
    "mlb": MLB_PRIZEPICKS,
    "wnba": WNBA_PRIZEPICKS,
    "soccer": SOCCER_PRIZEPICKS,
}
