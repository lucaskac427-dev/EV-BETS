"""Segmented backtest report: market × (regular season vs playoffs),
with and without the projection blend, plus a per-book soft-vs-sharp pass.

Run: python -m src.historical.backtest_report
"""

import asyncio
from collections import defaultdict

from src.historical.backtest import BetResult, run_backtest, _summarize


def _seg(bets: list[BetResult], pred) -> dict:
    return _summarize([b for b in bets if pred(b)])


def _line(label: str, s: dict) -> str:
    if s["n"] == 0:
        return f"  {label:32s}  n=   0"
    flag = "🟢" if s["roi_pct"] > 0 else "🔴"
    return (
        f"  {label:32s}  n={s['n']:4d}  "
        f"wr={s['win_rate']*100:5.1f}%  "
        f"ROI={s['roi_pct']:+6.2f}%  "
        f"edge={s['avg_edge_pct']:+5.2f}%  {flag}"
    )


async def main() -> None:
    for use_proj in (False, True):
        tag = "WITH projection blend" if use_proj else "pure sharp consensus"
        print("\n" + "=" * 72)
        print(f"  NBA BACKTEST · {tag} · edge threshold 2%")
        print("=" * 72)
        result = await run_backtest(
            "basketball_nba", threshold=0.02, min_books=2, use_projection=use_proj
        )
        bets: list[BetResult] = result["bets"]
        print(_line("ALL", _summarize(bets)))
        print(_line("  regular season", _seg(bets, lambda b: b.segment == "regular")))
        print(_line("  playoffs", _seg(bets, lambda b: b.segment == "playoffs")))

        print("\n  By market (all games):")
        markets = sorted({b.market for b in bets})
        for m in markets:
            print(_line(m.replace("player_", ""), _seg(bets, lambda b, m=m: b.market == m)))

        print("\n  By market × segment:")
        for m in markets:
            for seg in ("regular", "playoffs"):
                print(
                    _line(
                        f"{m.replace('player_','')} · {seg}",
                        _seg(bets, lambda b, m=m, seg=seg: b.market == m and b.segment == seg),
                    )
                )


if __name__ == "__main__":
    asyncio.run(main())
