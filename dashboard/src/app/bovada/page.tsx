"use client";

import { Fragment, useEffect, useState } from "react";

import { PlayerAvatar } from "@/components/PlayerAvatar";
import { StatusBar } from "@/components/StatusBar";
import { TopNav } from "@/components/TopNav";
import { probToAmerican } from "@/lib/odds";

type Backer = { book: string; over: number; under: number };
type Edge = {
  player: string; market: string; side: string; line: number;
  bovada_odds: number; fair_pct: number; ev_pct: number; event: string; books: number;
  backers?: Backer[];
};
type Data = { count: number; edges: Edge[]; min_ev: number; source?: string; error?: string };

const BOVADA = "#e0563a";
const STRONG_EV = 2; // EV at/above which a line is bright green
const EV_FLOORS: (number | null)[] = [null, 0.8, 1, 2]; // filter options; null = show all
const GRID = "grid-cols-[150px_minmax(150px,1fr)_96px_150px_84px_84px_84px_60px_28px]";

const MARKET_LABELS: Record<string, string> = {
  points: "Points", rebounds: "Rebounds", assists: "Assists", threes: "Threes",
  blocks: "Blocks", steals: "Steals", points_rebounds_assists: "PRA",
  points_rebounds: "PR", points_assists: "PA", rebounds_assists: "RA", blocks_steals: "Blk+Stl",
};
const marketLabel = (m: string) => MARKET_LABELS[m] ?? m.replace(/_/g, " ");
const decimalToAmerican = (d: number) =>
  d >= 2 ? `+${Math.round((d - 1) * 100)}` : `${Math.round(-100 / (d - 1))}`;

export default function BovadaPage() {
  const [evFloor, setEvFloor] = useState<number | null>(null); // null = show all
  const [safeOnly, setSafeOnly] = useState(true); // highest-winning: win ≥55% + edge
  const [sortKey, setSortKey] = useState<"ev" | "fair">("fair");
  const [open, setOpen] = useState<number | null>(null);
  const [data, setData] = useState<Data | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/bovada`)
      .then((r) => r.json())
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  const all = data?.edges ?? [];
  const edges = [...all]
    .filter((e) => (evFloor === null ? true : e.ev_pct >= evFloor))
    .filter((e) => (safeOnly ? e.fair_pct >= 55 && e.ev_pct > 0 : true))
    .sort((a, b) => (sortKey === "ev" ? b.ev_pct - a.ev_pct : b.fair_pct - a.fair_pct));
  const safeCount = all.filter((e) => e.fair_pct >= 55 && e.ev_pct > 0).length;

  return (
    <div className="relative min-h-screen">
      <StatusBar />
      <TopNav />
      <main className="relative z-10">
        <div className="border-b border-[color:var(--border)] bg-[color:var(--bg)] px-5 py-3">
          <div className="flex items-baseline justify-between">
            <div>
              <h1 className="text-[15px] font-semibold tracking-tight">
                <span style={{ color: BOVADA }}>▶</span> Bovada Board
              </h1>
              <p className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
                Every Bovada line vs sharp consensus · {data?.source === "live" ? "live odds" : "stored odds"} · filter to your EV cutoff · click a row for the books
              </p>
            </div>
            <div className="flex items-center gap-3 text-[10px] uppercase tracking-[0.18em]">
              <button
                onClick={() => {
                  setSafeOnly((s) => !s);
                  setSortKey("fair");
                }}
                title="Highest-winning: only +EV lines that also clear a 55% win-probability floor (hides plus-money longshots)"
                className={`border px-3 py-1.5 transition-colors ${
                  safeOnly
                    ? "border-[color:var(--accent)] bg-[color:var(--accent-dim)] text-[color:var(--accent)]"
                    : "border-[color:var(--border)] text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
                }`}
              >
                Safe · win ≥55% {safeOnly ? `ON ${safeCount}` : "OFF"}
              </button>
              <div className="flex border border-[color:var(--border)]">
                {EV_FLOORS.map((v, idx) => {
                  const count = v === null ? all.length : all.filter((e) => e.ev_pct >= v).length;
                  const active = evFloor === v;
                  return (
                    <button
                      key={String(v)}
                      onClick={() => setEvFloor(v)}
                      className={`px-3 py-1.5 transition-colors ${idx > 0 ? "border-l border-[color:var(--border)]" : ""} ${
                        active
                          ? "bg-[color:var(--accent-dim)] text-[color:var(--accent)]"
                          : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
                      }`}
                    >
                      {v === null ? "All" : `${v}%+`} {count}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        <div className="border-b border-[color:var(--border)] bg-[color:var(--bg)] px-5 py-2 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
          {loading
            ? "Loading…"
            : `${edges.length} ${safeOnly ? "winning lines (win ≥55% + edge)" : evFloor === null ? "lines (full board)" : `lines at ${evFloor}%+ EV`} · sorting by ${sortKey === "ev" ? "EV (juiciest)" : "Fair % (safest)"}`}
        </div>

        <div className={`grid ${GRID} gap-0 border-b border-[color:var(--border)] bg-[color:var(--bg-elevated)] px-5 py-3 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]`}>
          <div>Game</div>
          <div>Player</div>
          <div>Market</div>
          <div>Pick</div>
          <div className="text-right">Odds</div>
          <button
            onClick={() => setSortKey("fair")}
            className={`text-right ${sortKey === "fair" ? "text-[color:var(--accent)]" : "hover:text-[color:var(--text-dim)]"}`}
          >
            Fair {sortKey === "fair" ? "▾" : "·"}
          </button>
          <button
            onClick={() => setSortKey("ev")}
            className={`text-right ${sortKey === "ev" ? "text-[color:var(--accent)]" : "hover:text-[color:var(--text-dim)]"}`}
          >
            EV {sortKey === "ev" ? "▾" : "·"}
          </button>
          <div className="text-right">Books</div>
          <div />
        </div>

        {loading && (
          <div className="p-12 text-center text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
            ▙ Loading Bovada board…
          </div>
        )}
        {!loading && edges.length === 0 && (
          <div className="p-12 text-center text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
            {safeOnly
              ? "─ No win ≥55% +edge Bovada lines right now — toggle Safe off to see longshots ─"
              : evFloor !== null
              ? `─ No Bovada lines at ${evFloor}%+ right now — drop the cutoff or switch to All ─`
              : "─ No Bovada lines with a sharp consensus right now ─"}
          </div>
        )}

        {edges.map((e, i) => {
          const safe = e.fair_pct >= 55;
          const strong = e.ev_pct >= STRONG_EV;
          const evColor = strong
            ? "text-[color:var(--accent)]"
            : e.ev_pct >= 0
              ? "text-[color:var(--accent)] opacity-60"
              : "text-[color:var(--negative)] opacity-80";
          return (
            <Fragment key={i}>
              <div
                onClick={() => setOpen(open === i ? null : i)}
                className={`terminal-row ${strong ? "positive" : ""} grid ${GRID} cursor-pointer gap-0 border-b border-[color:var(--border)] px-5 py-3 text-[13px] ${
                  e.ev_pct < 0 ? "opacity-75" : ""
                }`}
              >
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-[color:var(--info)]">NBA</div>
                  <div className="mt-0.5 text-[10px] text-[color:var(--text-muted)]">{e.event}</div>
                </div>
                <div className="flex min-w-0 items-center gap-2.5 self-center">
                  <PlayerAvatar name={e.player} highlight={strong && safe} />
                  <div className="min-w-0">
                    <div className="truncate font-medium text-[color:var(--text)]">{e.player}</div>
                    <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: BOVADA }}>
                      Bovada
                    </div>
                  </div>
                </div>
                <div className="self-center">
                  <span className="rounded border border-[color:var(--border-bright)] px-2 py-0.5 text-[11px] uppercase tracking-wider text-[color:var(--text-dim)]">
                    {marketLabel(e.market)}
                  </span>
                </div>
                <div className="flex items-center gap-2 self-center">
                  <span className={`font-medium ${e.side === "over" ? "text-[color:var(--accent)]" : "text-[color:var(--warn)]"}`}>
                    {e.side === "over" ? "Over" : "Under"}
                  </span>
                  <span className="num text-[15px] font-semibold text-[color:var(--text)]">{e.line}</span>
                </div>
                <div className="num self-center text-right text-[color:var(--text)]">{decimalToAmerican(e.bovada_odds)}</div>
                <div className={`num self-center text-right font-semibold ${safe ? "text-[color:var(--accent)]" : "text-[color:var(--warn)]"}`}>
                  {e.fair_pct}%
                </div>
                <div className={`num self-center text-right font-semibold ${evColor}`}>
                  {e.ev_pct >= 0 ? "+" : ""}{e.ev_pct.toFixed(1)}%
                </div>
                <div className="self-center text-right">
                  <span className={`chip ${e.books >= 4 ? "accent" : ""}`}>{e.books}</span>
                </div>
                <div className="self-center text-right text-[10px] text-[color:var(--text-muted)]">{open === i ? "▲" : "▼"}</div>
              </div>

              {open === i && (
                <div className="border-b border-[color:var(--border)] bg-[color:var(--bg)] px-5 py-3">
                  <div className="mb-2 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
                    Books backing this line · consensus fair {e.fair_pct}% · bovada {decimalToAmerican(e.bovada_odds)} ·{" "}
                    <span style={{ color: safe ? "var(--accent)" : "var(--warn)" }}>
                      {safe ? "safe-ish" : "longshot — high EV, low hit rate"}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] sm:grid-cols-3 md:grid-cols-4">
                    {(e.backers ?? []).map((b) => (
                      <div key={b.book} className="flex justify-between tabular-nums">
                        <span className="capitalize text-[color:var(--text-dim)]">{b.book.replace(/_/g, " ")}</span>
                        <span className="text-[color:var(--text-muted)]">
                          o{b.over} / u{b.under}
                        </span>
                      </div>
                    ))}
                    {(e.backers ?? []).length === 0 && (
                      <span className="text-[color:var(--text-muted)]">no two-sided books</span>
                    )}
                  </div>
                </div>
              )}
            </Fragment>
          );
        })}
      </main>

      <footer className="relative z-10 mt-6 border-t border-[color:var(--border)] px-5 py-3 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
        <span>KALSHI-EV · Bovada board</span>
        <span className="mx-3 text-[color:var(--border-bright)]">|</span>
        <span>fair × bovada price − 1 · de-vigged consensus</span>
        <span className="mx-3 text-[color:var(--border-bright)]">|</span>
        <span>All = every line · filter to your EV cutoff</span>
      </footer>
    </div>
  );
}
