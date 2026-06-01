"""Which buckets are winning — the forward-tracker learning report.

Groups every GRADED tracked pick (win/miss) by edge / fair% / #books / stat / app
/ side and shows the win rate per bucket. As the tracker banks every night, the
buckets get trustworthy — judge them by SAMPLE SIZE, not one slate. One game is
noise; a few hundred bets per bucket is signal. This is the "keep learning every
day" engine: over time it tells you which TYPES of bet to keep and which to drop.

    python -m src.dfs.bucket_report          # readable
    python -m src.dfs.bucket_report --json
"""

import argparse
import asyncio
import json

from src.db import close_pool, get_pool
from src.logger import configure_logging

MIN_SAMPLE = 30  # below this, a bucket is "too small to trust"


def _bucket(rows, key_fn, order):
    agg: dict = {}
    for r in rows:
        k = key_fn(r)
        if k is None:
            continue
        a = agg.setdefault(k, [0, 0])
        a[0] += 1
        a[1] += 1 if r["status"] == "win" else 0
    keys = order or sorted(agg)
    return [
        {"label": str(k), "n": agg[k][0], "wins": agg[k][1],
         "win_pct": round(100 * agg[k][1] / agg[k][0], 1), "trusted": agg[k][0] >= MIN_SAMPLE}
        for k in keys if k in agg
    ]


async def compute(sport: str = "nba") -> dict:
    configure_logging(level="CRITICAL")
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """SELECT edge_pct, fair_prob, num_books, stat_type, source, pick_side, status
               FROM tracked_picks WHERE sport=$1 AND status IN ('win','miss')""", sport)
    finally:
        await close_pool()
    rows = [dict(r) for r in rows]
    total = len(rows)
    wins = sum(1 for r in rows if r["status"] == "win")

    def edge_b(r):
        e = float(r["edge_pct"]) * 100 if r["edge_pct"] is not None else None
        return None if e is None else ("1.5%+" if e >= 1.5 else "0.8–1.5%" if e >= 0.8 else "under 0.8%")

    def fair_b(r):
        f = float(r["fair_prob"]) * 100 if r["fair_prob"] is not None else None
        if f is None:
            return None
        return "60%+" if f >= 60 else "55–60%" if f >= 55 else "50–55%" if f >= 50 else "under 50%"

    def books_b(r):
        b = r["num_books"]
        return None if b is None else ("6+" if b >= 6 else "4–5" if b >= 4 else "2–3" if b >= 2 else "1")

    dims = [
        {"name": "Edge size", "buckets": _bucket(rows, edge_b, ["1.5%+", "0.8–1.5%", "under 0.8%"])},
        {"name": "Consensus fair %", "buckets": _bucket(rows, fair_b, ["60%+", "55–60%", "50–55%", "under 50%"])},
        {"name": "# books backing", "buckets": _bucket(rows, books_b, ["6+", "4–5", "2–3", "1"])},
        {"name": "Stat type", "buckets": sorted(_bucket(rows, lambda r: r["stat_type"], None), key=lambda x: -x["n"])},
        {"name": "DFS app", "buckets": sorted(_bucket(rows, lambda r: r["source"], None), key=lambda x: -x["n"])},
        {"name": "Over / Under", "buckets": _bucket(rows, lambda r: r["pick_side"], ["over", "under"])},
    ]
    return {"total": total, "wins": wins,
            "overall_win_pct": round(100 * wins / total, 1) if total else 0,
            "min_sample": MIN_SAMPLE, "dimensions": dims}


async def _main(as_json: bool) -> None:
    d = await compute()
    if as_json:
        print(json.dumps(d))
        return
    print(f"\n  WHICH BUCKETS ARE WINNING · {d['total']} graded bets · overall {d['overall_win_pct']}% win")
    print(f"  (buckets under {MIN_SAMPLE} bets are too small to trust — they grow every night)")
    for dim in d["dimensions"]:
        print(f"\n  {dim['name']}")
        for b in dim["buckets"]:
            flag = "" if b["trusted"] else "  · small sample"
            print(f"    {b['label']:14s} {b['n']:>4d} bets   {b['win_pct']:>5.1f}% win{flag}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    asyncio.run(_main(p.parse_args().json))
