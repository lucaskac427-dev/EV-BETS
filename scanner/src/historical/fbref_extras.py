"""Extend soccerdata's FBref league dictionary with leagues that aren't in
its default config but exist on fbref.com.

soccerdata reads ~/soccerdata/config/league_dict.json on import and merges
those entries into FBref's supported-leagues table. Call register_extras()
before instantiating any FBref class.

References:
  - FBref URL pattern: https://fbref.com/en/comps/<id>/<League-Name>-Stats
  - Each entry needs the league's FBref comp id and the season format key.

Leagues registered here (FBref comp id in comments):
  - 22  USA-Major League Soccer
  - 24  BRA-Série A
  - 21  ARG-Primera División
  - 23  NED-Eredivisie
  - 32  POR-Primeira Liga
  - 31  MEX-Liga MX
  - 17  ENG-Championship (second tier; many sharp prop markets)
   - 8   UEFA-Champions League (men's, the big one)
  - 19  UEFA-Europa League
  - 27  EUR-Euro Nations League
"""

import json
from pathlib import Path

EXTRAS: dict[str, dict] = {
    "USA-Major League Soccer": {
        "FBref": {"id": 22, "URL": "/en/comps/22/Major-League-Soccer-Stats"},
        "season_code": "single",
    },
    "BRA-Série A": {
        "FBref": {"id": 24, "URL": "/en/comps/24/Serie-A-Stats"},
        "season_code": "single",
    },
    "ARG-Primera División": {
        "FBref": {"id": 21, "URL": "/en/comps/21/Primera-Division-Stats"},
        "season_code": "single",
    },
    "NED-Eredivisie": {
        "FBref": {"id": 23, "URL": "/en/comps/23/Eredivisie-Stats"},
        "season_code": "dual",
    },
    "POR-Primeira Liga": {
        "FBref": {"id": 32, "URL": "/en/comps/32/Primeira-Liga-Stats"},
        "season_code": "dual",
    },
    "MEX-Liga MX": {
        "FBref": {"id": 31, "URL": "/en/comps/31/Liga-MX-Stats"},
        "season_code": "dual",
    },
    "ENG-Championship": {
        "FBref": {"id": 10, "URL": "/en/comps/10/Championship-Stats"},
        "season_code": "dual",
    },
    "UEFA-Champions League": {
        "FBref": {"id": 8, "URL": "/en/comps/8/Champions-League-Stats"},
        "season_code": "dual",
    },
    "UEFA-Europa League": {
        "FBref": {"id": 19, "URL": "/en/comps/19/Europa-League-Stats"},
        "season_code": "dual",
    },
}


def register_extras() -> int:
    """Write EXTRAS into soccerdata's user config. Returns count written.
    Safe to call multiple times; merges with anything already there."""
    config_dir = Path.home() / "soccerdata" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "league_dict.json"
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = {}
    existing.update(EXTRAS)
    path.write_text(json.dumps(existing, indent=2))
    return len(EXTRAS)
