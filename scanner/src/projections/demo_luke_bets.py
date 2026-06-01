"""Run Luke's six example bets through the Poisson match model."""

import asyncio

from src.db import close_pool, get_pool
from src.projections.soccer_match import build_league_model, expected_goals, market_probs

# (search_home, search_away, bet_team, market_label, his_american_odds, his_pct)
BETS = [
    ("Mainz", "Leipzig", "Leipzig", "win_or_draw", -550, 71.4),
    ("Hoffenheim", "Leverkusen", "Leverkusen", "win_or_draw", -575, 76.7),
    ("Sociedad", "Barcelona", "Barcelona", "team_over_0.5", -400, 82.9),
    ("Man City", "Bournemouth", "Man City", "team_over_1.5", -675, None),
    ("Salernitana", "Napoli", "Napoli", "win_or_draw", -850, 100.0),
    ("Milan", "Udinese", None, "match_over_1.5", -400, None),
]


def implied(american: int) -> float:
    return abs(american) / (abs(american) + 100) if american < 0 else 100 / (american + 100)


async def main():
    pool = await get_pool()
    try:
        for sh, sa, team, market, odds, his_pct in BETS:
            m = await pool.fetchrow(
                """SELECT match_date, home_team, away_team, league_code, fthg, ftag, ftr
                   FROM soccer_match_odds
                   WHERE (home_team ILIKE '%'||$1||'%' OR away_team ILIKE '%'||$1||'%')
                     AND (home_team ILIKE '%'||$2||'%' OR away_team ILIKE '%'||$2||'%')
                   ORDER BY match_date DESC LIMIT 1""", sh, sa)
            if not m:
                print(f"  {sh} vs {sa}: not found"); continue
            prior = await pool.fetch(
                """SELECT match_date, home_team, away_team, fthg, ftag
                   FROM soccer_match_odds
                   WHERE league_code=$1 AND match_date < $2 AND match_date > $2::date - 760
                     AND fthg IS NOT NULL""", m["league_code"], m["match_date"])
            model = build_league_model([dict(r) for r in prior], as_of=m["match_date"])
            eg = expected_goals(model, m["home_team"], m["away_team"])
            if not eg:
                print(f"  {m['home_team']} vs {m['away_team']}: no rating"); continue
            mp = market_probs(*eg)

            home = team and team.lower() in m["home_team"].lower()
            if market == "win_or_draw":
                p = mp["home_or_draw"] if home else mp["away_or_draw"]
            elif market == "team_over_0.5":
                p = mp["home_over_0.5"] if home else mp["away_over_0.5"]
            elif market == "team_over_1.5":
                p = mp["home_over_1.5"] if home else mp["away_over_1.5"]
            else:
                p = mp["over_1.5"]

            # Did the bet win?
            gh, ga = m["fthg"], m["ftag"]
            if market == "win_or_draw":
                won = (m["ftr"] in ("H", "D")) if home else (m["ftr"] in ("A", "D"))
            elif market == "team_over_0.5":
                won = (gh if home else ga) >= 1
            elif market == "team_over_1.5":
                won = (gh if home else ga) >= 2
            else:
                won = (gh + ga) >= 2

            line_imp = implied(odds)
            ev = p / line_imp - 1.0
            tag = "EDGE" if p > line_imp else "no edge"
            res = "WON" if won else "LOST"
            label = f"{team or 'Match'} {market}"
            print(f"  {m['home_team'][:12]:12s} v {m['away_team'][:12]:12s} | {label:22s}")
            print(f"      model P={p*100:4.1f}%  line={line_imp*100:4.1f}% ({odds})  "
                  f"your read={his_pct or '—'}  EV={ev*100:+5.1f}% [{tag}]  actual: {gh}-{ga} {res}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
