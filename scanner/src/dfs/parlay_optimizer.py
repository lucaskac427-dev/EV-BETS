"""Parlay portfolio optimizer + Monte Carlo simulator.

The problem: on DFS apps you can't bet a single prop — you must combine picks into
entries (parlays). So a pile of +edge picks isn't enough; HOW you combine them
decides whether variance wipes you out. This tool builds a *portfolio* of parlays
that covers the picks, then simulates tens of thousands of universes to measure
exactly how much luck is left — instead of picking a few and praying.

HONEST ASSUMPTIONS — read them, the answer depends on them:
  1. The PAYOUT tables below are ASSUMED PrizePicks numbers. They change with
     promos. VERIFY them in the app and edit — the math is exact GIVEN these.
  2. The sim treats legs as INDEPENDENT. Real props in the SAME game are
     correlated (one blowout and all the unders cash together), so a same-game
     slate's true variance is HIGHER than shown here. The fix is real games on the
     board, not math — diversify across games. A 1-game slate is the worst case.
  3. "Edge" came from the sharp consensus (fair_prob). Parlay payouts add their own
     tax on top, so a +EV single can become a -EV parlay. The sim shows when.

    python -m src.dfs.parlay_optimizer --min-edge 1.0 --pool 12
"""

import argparse
import asyncio
import itertools
import json
import random
import statistics
from math import comb

from src.db import close_pool, get_pool
from src.logger import configure_logging

# ===== Per-app payout tables. Each app pays DIFFERENTLY — never share one table.
# prizepicks: VERIFIED from prizepicks.com/help-center/payouts (May 2026).
# underdog:   from a search snippet — NOT fully verified; confirm in-app.
# sleeper/dk_pick6: NOT sourced yet — fall back to PrizePicks as a PLACEHOLDER
#   (dollars for those two are NOT real until their tables are entered).
PAYOUTS = {
    # PrizePicks — VERIFIED off Luke's app (May 2026). NOTE 3-flex 2/3 = 0.75x
    # (a partial LOSS, not a refund); 6-flex 6/6 = 28x.
    "prizepicks": {
        "power": {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5},
        "flex": {3: {3: 3.0, 2: 0.75}, 4: {4: 6.0, 3: 1.5},
                 5: {5: 10.0, 4: 2.0, 3: 0.4}, 6: {6: 28.0, 5: 2.0, 4: 0.4}},
    },
    # Sleeper — VERIFIED off Luke's app (flex only; power not provided). 2-leg
    # flex not offered. Note 3-flex 2/3 = 1.12x — Sleeper still PROFITS on 2/3.
    "sleeper": {
        "flex": {3: {3: 3.39, 2: 1.12}, 4: {4: 6.62, 3: 1.64},
                 5: {5: 10.86, 4: 2.11, 3: 0.42}, 6: {6: 24.22, 5: 1.93, 4: 0.38}},
    },
    # Underdog — VERIFIED off Luke's app. "up to" = ceiling; some picks pay less.
    # 2-leg is flat (no flex).
    "underdog": {
        "power": {2: 3.08},
        "flex": {3: {3: 2.866, 2: 1.09}, 4: {4: 5.43, 3: 1.54},
                 5: {5: 9.06, 4: 2.57}, 6: {6: 22.6, 5: 2.67, 4: 0.25}},
    },
    # DK Pick6 (DraftKings) — VERIFIED off Luke's app. No "flex" product; a tiered
    # "pricing summary" ("or more" = floor). Mostly all-or-nothing — only 5- & 6-leg
    # give any partial credit. Stored under "flex" since that's its only mode.
    "dk_pick6": {
        "flex": {2: {2: 3.0}, 3: {3: 6.0}, 4: {4: 9.9},
                 5: {5: 12.0, 4: 1.0}, 6: {6: 23.7, 5: 1.4}},
    },
}
VERIFIED = {"prizepicks", "sleeper", "underdog", "dk_pick6"}


def _table(app: str, mode: str):
    t = PAYOUTS.get(app)
    return t.get(mode) if t else None


async def load_picks(min_edge: float, source: str | None = None, sport: str = "nba"):
    """One row per (player, stat) — the higher-edge side — with the consensus
    probability and the real outcome we already graded. Optionally one app only
    (you can't combine apps in a single entry). sport: 'nba' | 'mlb' | 'both'."""
    pool = await get_pool()
    try:
        # ONE pick per (player, stat) — keep the higher-edge side so a player
        # can't have BOTH an over and an under on the same stat (Fox o-points and
        # Fox u-points can't coexist). Different stats for the same player are OK.
        conds = ["fair_prob IS NOT NULL", "edge_pct >= $1"]
        args: list = [min_edge / 100.0]
        if sport == "both":
            conds.append("sport IN ('nba','mlb')")
        else:
            args.append(sport)
            conds.append(f"sport = ${len(args)}")
        if source:
            args.append(source)
            conds.append(f"source = ${len(args)}")
        q = f"""SELECT DISTINCT ON (player_name, stat_type)
                   player_name, stat_type, pick_side, line, actual_value, source,
                   fair_prob, edge_pct,
                   CASE status WHEN 'win' THEN 1 WHEN 'miss' THEN 0 ELSE NULL END AS actual
               FROM tracked_picks
               WHERE {' AND '.join(conds)}
               ORDER BY player_name, stat_type, edge_pct DESC"""
        rows = await pool.fetch(q, *args)
        return [{"name": r["player_name"], "stat": r["stat_type"], "side": r["pick_side"],
                 "line": float(r["line"]), "actual_value": r["actual_value"], "source": r["source"],
                 "p": float(r["fair_prob"]), "edge": float(r["edge_pct"]) * 100,
                 "actual": r["actual"]} for r in rows]
    finally:
        await close_pool()


async def load_live_picks(source: str, min_edge: float, sport: str = "nba") -> list[dict]:
    """The CURRENT live slate for one app — latest scan, active lines only, one
    pick per (player, stat). No outcomes (these haven't been played yet).
    sport: 'nba' | 'mlb' | 'both'."""
    pool = await get_pool()
    try:
        conds = ["l.source=$1", "l.is_active", "x.edge_pct >= $2"]
        args: list = [source, min_edge / 100.0]
        if sport == "both":
            conds.append("l.sport IN ('nba','mlb')")
        else:
            args.append(sport)
            conds.append(f"l.sport = ${len(args)}")
        rows = await pool.fetch(
            f"""WITH latest AS (
                   SELECT DISTINCT ON (dfs_line_id) dfs_line_id, pick_side,
                          consensus_fair_prob, edge_pct
                   FROM dfs_opportunities ORDER BY dfs_line_id, scan_tick_at DESC)
               SELECT DISTINCT ON (l.player_name, l.stat_type)
                   l.player_name, l.stat_type, x.pick_side, l.line, l.team,
                   x.consensus_fair_prob AS fair_prob, x.edge_pct
               FROM latest x JOIN dfs_lines l ON l.id = x.dfs_line_id
               WHERE {' AND '.join(conds)}
               ORDER BY l.player_name, l.stat_type, x.edge_pct DESC""",
            *args)
        return [{"name": r["player_name"], "stat": r["stat_type"], "side": r["pick_side"],
                 "line": float(r["line"]), "team": r["team"], "p": float(r["fair_prob"]),
                 "edge": float(r["edge_pct"]) * 100, "actual": None} for r in rows]
    finally:
        await close_pool()


async def cards_json(legs: int, stake: float, min_edge: float, top_n: int, live: bool, sport: str = "nba") -> None:
    """Emit ready-to-place round-robin cards for ALL apps at a given leg count,
    as JSON (consumed by the dashboard). Live slate, or last-night demo.
    sport: 'nba' | 'mlb' | 'both' — 'both' mixes NBA+MLB legs (uncorrelated)."""
    configure_logging(level="CRITICAL")  # keep stdout clean for the JSON consumer
    apps = ["prizepicks", "sleeper", "underdog", "dk_pick6"]
    out = {"legs": legs, "stake": stake, "min_edge": min_edge, "sport": sport,
           "source": "live" if live else "demo (last night, graded)", "apps": []}
    for app in apps:
        picks = await load_live_picks(app, min_edge, sport) if live else await load_picks(min_edge, app, sport)
        picks.sort(key=lambda x: -x["p"])
        pool = picks[:top_n]
        tbl = _table(app, "flex")
        ao = {"app": app, "verified": app in VERIFIED, "num_picks": len(pool),
              "legs_available": sorted(tbl.keys()) if tbl else [], "picks": [],
              "parlays": [], "num_parlays": 0, "cost": 0, "note": ""}
        for i, pk in enumerate(pool, 1):
            ao["picks"].append({"n": i, "player": pk["name"],
                                "pick": f"{pk['side']} {pk['line']:g} {pk['stat']}",
                                "prob": round(pk["p"] * 100), "edge": round(pk["edge"], 1),
                                "result": None if pk["actual"] is None else ("WIN" if pk["actual"] else "MISS")})
        if tbl is None:
            ao["note"] = "payouts unconfirmed"
        elif legs not in tbl:
            ao["note"] = f"{app} has no {legs}-leg play"
        elif len(pool) < legs:
            ao["note"] = f"only {len(pool)} live picks (need {legs})"
        else:
            entries = list(itertools.combinations(range(len(pool)), legs))
            ao["parlays"] = [{"id": j + 1, "legs": [i + 1 for i in e]} for j, e in enumerate(entries)]
            ao["num_parlays"] = len(entries)
            ao["cost"] = round(len(entries) * stake, 2)
        out["apps"].append(ao)
    print(json.dumps(out))


async def card(min_edge: float, source: str, pool_size: int, k: int, mode: str, stake: float,
               show_entries: bool = False) -> None:
    """Print the ACTUAL card for one app and grade it in real dollars."""
    configure_logging(level="WARNING")
    picks = await load_picks(min_edge, source=source)
    picks.sort(key=lambda p: -p["p"])
    pool = picks[:pool_size]
    if len(pool) < k:
        print(f"  Only {len(pool)} {source} picks >= {min_edge}% edge — need >= {k}.")
        return
    if _table(source, mode) is None:
        print(f"\n  {source.upper()}: no confirmed {mode} payout table — refusing to invent dollars. "
              f"(Underdog & DraftKings still unconfirmed.)")
        return
    ptag = f"{source} {mode} payouts VERIFIED" if source in VERIFIED else f"⚠ {source} UNVERIFIED — confirm in-app"
    print(f"\n  YOUR {source.upper()} CARD · Game 7 SAS@OKC · {k}-pick {mode.upper()} round-robin")
    print(f"  {ptag}")
    print("  " + "─" * 60)
    print(f"  {'#':>2s} {'player':20s} {'the pick':24s} {'hit%':>4s} {'result':>7s}")
    outc = [p["actual"] for p in pool]
    for i, p in enumerate(pool, 1):
        res = "WIN ✓" if p["actual"] == 1 else "MISS ✗" if p["actual"] == 0 else "?"
        av = "" if p["actual_value"] is None else f" (got {p['actual_value']:g})"
        pk = f"{p['side']} {p['line']:g} {p['stat']}"
        print(f"  {i:>2d} {p['name'][:20]:20s} {pk[:24]:24s} {p['p']*100:>3.0f}% {res:>7s}{av}")
    if any(o is None for o in outc):
        print("  (some legs ungraded — can't compute the money)")
        return
    entries = list(itertools.combinations(range(len(pool)), k))
    if show_entries:
        print("  " + "─" * 60)
        print(f"  EVERY parlay — {len(entries)} of them ({k} legs each, legs by # above):")
        for ei, e in enumerate(entries, 1):
            hits = sum(outc[i] for i in e)
            ne = _entry_net(hits, k, mode, stake, source)
            tag = "WON " if ne > 1e-9 else ("push" if abs(ne) < 1e-9 else "lost")
            print(f"   #{ei:<2d}  legs {'+'.join(str(i + 1) for i in e):11s}  {hits}/{k} hit  "
                  f"${ne + stake:>6.2f} back  {tag}  (${ne:+.2f})")
    total_in = len(entries) * stake
    ret = sum(_entry_net(sum(outc[i] for i in e), k, mode, stake, source) + stake for e in entries)
    cashed = sum(1 for e in entries if _entry_net(sum(outc[i] for i in e), k, mode, stake, source) > 0)
    net = ret - total_in
    print("  " + "─" * 60)
    print(f"  legs hit: {sum(outc)}/{len(pool)}   ·   {len(entries)} flex parlays @ ${stake:g} = ${total_in:g} in")
    print(f"  returned ${ret:,.2f}  ({cashed}/{len(entries)} parlays cashed)")
    print(f"  NET: ${net:+,.2f}  ({100*net/total_in:+.0f}%)  ->  {'PROFIT 🟢' if net > 0 else 'LOSS 🔴'}")


def _entry_net(hits: int, k: int, mode: str, stake: float, app: str = "prizepicks") -> float:
    tbl = _table(app, mode)
    if tbl is None:
        return 0.0  # callers must check _table() first; no table = no payout
    if mode == "power":
        mult = tbl.get(k, 0.0) if hits == k else 0.0
    else:
        mult = tbl.get(k, {}).get(hits, 0.0)
    return stake * mult - stake


def simulate(probs, entries, k, mode, *, stake=1.0, n_sims=20000, seed=7) -> dict:
    rng = random.Random(seed)
    n = len(probs)
    staked = len(entries) * stake
    pnls = []
    for _ in range(n_sims):
        out = [1 if rng.random() < probs[i] else 0 for i in range(n)]
        pnl = 0.0
        for e in entries:
            pnl += _entry_net(sum(out[i] for i in e), k, mode, stake)
        pnls.append(pnl)
    pnls.sort()
    m = statistics.mean(pnls)
    return {
        "entries": len(entries), "staked": staked, "ev_pct": 100 * m / staked if staked else 0,
        "p_profit": 100 * sum(1 for x in pnls if x > 1e-9) / len(pnls),
        "p5": pnls[int(0.05 * len(pnls))], "p50": pnls[len(pnls) // 2],
        "p95": pnls[int(0.95 * len(pnls))], "worst": pnls[0],
    }


def actual_net(picks, entries, k, mode, *, stake=1.0):
    out = [p["actual"] for p in picks]
    if any(o is None for o in out):
        return None
    staked = len(entries) * stake
    pnl = sum(_entry_net(sum(out[i] for i in e), k, mode, stake) for e in entries)
    return pnl, staked


def _rr_return(n: int, h: int, k: int, mode: str, stake: float, app: str = "prizepicks") -> float:
    """Exact return of a full k-pick round-robin over n picks when exactly h of
    them hit. Depends only on the COUNT h (not which legs)."""
    tbl = _table(app, mode)
    if tbl is None:
        return 0.0
    total = 0.0
    for j in range(k + 1):  # j = hits inside a given parlay
        nc = comb(h, j) * comb(n - h, k - j)
        mult = (tbl.get(k, 0.0) if j == k else 0.0) if mode == "power" else tbl.get(k, {}).get(j, 0.0)
        total += nc * mult * stake
    return total


def scenarios(n: int, k: int, stake: float, app: str = "prizepicks") -> None:
    entries = comb(n, k)
    staked = entries * stake
    vtag = "VERIFIED" if app in VERIFIED else "UNVERIFIED — confirm in-app"
    print(f"\n  NEXT-GAME SCENARIOS · {app} · {n} picks · {k}-pick round-robin · {entries} parlays @ ${stake:g} = ${staked:g} in")
    print(f"  payouts: {vtag} · per single ${staked:g} app card")
    has_power = _table(app, "power") is not None
    print("  " + "─" * 60)
    hdr = f"  {'legs hit':>9s}   {'FLEX (partial pays)':>22s}"
    if has_power:
        hdr += f"   {'POWER (all-or-nothing)':>22s}"
    print(hdr)
    for h in range(n, -1, -1):
        rf = _rr_return(n, h, k, "flex", stake, app) - staked
        mark = "  ← break-even-ish" if -0.15 < rf / staked < 0.15 else ""
        row = f"  {h}/{n} hit   ${rf:>+8.2f} ({100*rf/staked:>+4.0f}%)"
        if has_power:
            rp = _rr_return(n, h, k, "power", stake, app) - staked
            row += f"      ${rp:>+8.2f} ({100*rp/staked:>+4.0f}%)"
        print(row + mark)


def _play_ev(p: float, k: int, mode: str, app: str = "prizepicks") -> float | None:
    """EV per $1 of a single k-leg play at per-leg hit-rate p (legs independent)."""
    tbl = _table(app, mode)
    if tbl is None or k not in tbl:
        return None
    ev = 0.0
    for h in range(k + 1):
        ph = comb(k, h) * p**h * (1 - p) ** (k - h)
        mult = (tbl.get(k, 0.0) if h == k else 0.0) if mode == "power" else tbl.get(k, {}).get(h, 0.0)
        ev += ph * mult
    return ev - 1.0


def sweep(app: str, probs: tuple) -> None:
    vtag = "VERIFIED" if app in VERIFIED else "UNVERIFIED — confirm in-app"
    print(f"\n  STRUCTURE SWEEP · {app} ({vtag}) · EV per $1, single play, legs independent")
    print("  Answers 'how many legs?' — it depends on your per-leg hit rate:")
    print("  " + "─" * 60)
    print("  structure         " + "".join(f"@{round(p*100)}%".rjust(9) for p in probs))
    for mode in ("power", "flex"):
        for k in range(2, 7):
            evs = [_play_ev(p, k, mode, app) for p in probs]
            if all(e is None for e in evs):
                continue
            cells = "".join("—".rjust(9) if e is None else f"{e*100:+.0f}%".rjust(9) for e in evs)
            print(f"  {k}-pick {mode:5s}    {cells}")
    print("\n  Note: more legs shows MORE EV here (the multipliers outrun the odds) — but")
    print("  variance explodes (a 6-pick rarely goes 6/6). Flex gives up a little EV for a")
    print("  cushion. 'Best' = EV vs survival, and it's brutally sensitive to your hit rate.")


async def run(min_edge: float, pool_size: int, n_sims: int) -> None:
    configure_logging(level="WARNING")
    picks = await load_picks(min_edge)
    picks.sort(key=lambda p: -p["p"])  # strongest-probability first (parlays need high p)
    pool = picks[:pool_size]
    if len(pool) < 4:
        print(f"  Only {len(pool)} picks at >= {min_edge}% edge — not enough to build a portfolio.")
        return
    probs = [p["p"] for p in pool]
    avg = 100 * sum(probs) / len(probs)

    print(f"\n  PARLAY PORTFOLIO SIMULATOR · {len(pool)} strongest picks at >= {min_edge}% edge")
    print(f"  avg hit probability {avg:.1f}%  ·  {n_sims:,} simulated universes each")
    print(f"  ⚠ payouts are ASSUMED PrizePicks values — verify in the app · legs treated as independent")
    print("  " + "═" * 78)
    print(f"  {'strategy':34s} {'plays':>5s} {'EV%':>6s} {'chance$+':>8s} {'typical':>8s} {'bad day(5%)':>11s}")

    def line(name, entries, k, mode):
        s = simulate(probs, entries, k, mode, n_sims=n_sims)
        st = s["staked"]
        print(f"  {name:34s} {s['entries']:>5d} {s['ev_pct']:>+5.1f}% {s['p_profit']:>7.0f}% "
              f"{100*s['p50']/st:>+7.0f}% {100*s['p5']/st:>+10.0f}%")
        return s

    idx = list(range(len(pool)))
    # 1) "pick a few and pray" — one parlay
    line("ONE 4-pick power (pray)", [tuple(idx[:4])], 4, "power")
    # 2) cover everything — round robins, power vs flex
    rr2 = list(itertools.combinations(idx, 2))
    rr3 = list(itertools.combinations(idx, 3))
    line("Round-robin 2-pick power", rr2, 2, "power")
    line("Round-robin 3-pick power", rr3, 3, "power")
    line("Round-robin 3-pick FLEX", rr3, 3, "flex")
    if pool_size >= 8:
        rr4 = list(itertools.combinations(idx, 4))
        line("Round-robin 4-pick FLEX", rr4, 4, "flex")

    print("\n  Columns: EV% = long-run edge · chance$+ = how often the night profits ·")
    print("  typical = median night · bad day(5%) = your worst 1-in-20 night (the downside).")

    # Reality check: what these structures ACTUALLY returned last night.
    real3f = actual_net(pool, rr3, 3, "flex")
    real2p = actual_net(pool, rr2, 2, "power")
    if real3f:
        print(f"\n  REALITY CHECK (last night's actual graded outcomes, these {len(pool)} picks):")
        print(f"    Round-robin 2-pick power: {100*real2p[0]/real2p[1]:+.0f}% on the night")
        print(f"    Round-robin 3-pick FLEX:  {100*real3f[0]/real3f[1]:+.0f}% on the night")
        print(f"    (one night = one dot in the simulated cloud above — not proof, just a check)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--min-edge", type=float, default=1.0, help="minimum edge %% to include")
    p.add_argument("--pool", type=int, default=12, help="how many of the strongest picks to combine")
    p.add_argument("--sims", type=int, default=20000)
    p.add_argument("--card", metavar="APP", help="grade the ACTUAL card for one app (e.g. prizepicks)")
    p.add_argument("--legs", type=int, default=3, help="legs per parlay for --card")
    p.add_argument("--mode", default="flex", choices=["flex", "power"])
    p.add_argument("--stake", type=float, default=5.0)
    p.add_argument("--scenarios", action="store_true", help="P/L by how many legs hit next game")
    p.add_argument("--sweep", action="store_true", help="EV by leg-count + play type (answers 'how many legs?')")
    p.add_argument("--show-entries", action="store_true", help="print every single parlay in the round-robin")
    p.add_argument("--live-cards", action="store_true", help="JSON: ready-to-place cards from the LIVE slate")
    p.add_argument("--demo-cards", action="store_true", help="JSON: same, from last night's graded slate")
    p.add_argument("--top", type=int, default=6, help="how many of the best picks per app")
    p.add_argument("--sport", default="nba", choices=["nba", "mlb", "both"],
                   help="cards for nba only, mlb only, or both (mixed uncorrelated legs)")
    a = p.parse_args()
    if a.live_cards or a.demo_cards:
        asyncio.run(cards_json(a.legs, a.stake, a.min_edge, a.top, live=a.live_cards, sport=a.sport))
    elif a.sweep:
        sweep(a.card or "prizepicks", (0.55, 0.58, 0.60, 0.62, 0.65))
    elif a.scenarios:
        scenarios(a.pool, a.legs, a.stake, a.card or "prizepicks")
    elif a.card:
        asyncio.run(card(a.min_edge, a.card, a.pool, a.legs, a.mode, a.stake, a.show_entries))
    else:
        asyncio.run(run(a.min_edge, a.pool, a.sims))
