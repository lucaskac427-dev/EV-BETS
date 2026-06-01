"use client";

import { useEffect, useState } from "react";

import { StatusBar } from "@/components/StatusBar";
import { TopNav } from "@/components/TopNav";

type Bucket = { label: string; n: number; wins: number; win_pct: number; trusted: boolean };
type Dim = { name: string; buckets: Bucket[] };
type Data = {
  total: number; wins: number; overall_win_pct: number; min_sample: number;
  dimensions: Dim[]; error?: string;
};

function color(p: number): string {
  if (p >= 55) return "var(--accent)";
  if (p >= 50) return "var(--warn)";
  return "var(--negative)";
}

export default function BucketsPage() {
  const [data, setData] = useState<Data | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/buckets")
      .then((r) => r.json())
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="relative min-h-screen">
      <StatusBar />
      <TopNav />
      <main className="relative z-10">
        <div className="border-b border-[color:var(--border)] bg-[color:var(--bg)] px-5 py-3">
          <h1 className="text-[15px] font-semibold tracking-tight">
            <span className="text-[color:var(--accent)]">▶</span> Which Buckets Are Winning
          </h1>
          <p className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
            forward tracker · learns which TYPES of bet win as it banks every night · judge by sample size
          </p>
        </div>

        {data && !data.error && (
          <div className="border-b border-[color:var(--border)] bg-[color:var(--bg)] px-5 py-2 text-[11px] text-[color:var(--text-dim)]">
            <b>{data.total}</b> graded bets · overall <b style={{ color: color(data.overall_win_pct) }}>{data.overall_win_pct}%</b> win ·
            faded buckets are under {data.min_sample} bets — too small to trust yet (they sharpen every night)
          </div>
        )}

        {loading && (
          <div className="p-12 text-center text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
            ▙ Crunching the tracker…
          </div>
        )}
        {!loading && data?.error && (
          <div className="p-12 text-center text-[11px] uppercase tracking-[0.2em] text-[color:var(--negative)]">
            ✕ {data.error}
          </div>
        )}
        {!loading && data?.total === 0 && (
          <div className="p-12 text-center text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
            ─ No graded bets yet — the tracker fills as games finish ─
          </div>
        )}

        {!loading && data?.dimensions && data.total > 0 && (
          <div className="grid gap-4 p-5 md:grid-cols-2 lg:grid-cols-3">
            {data.dimensions.map((dim) => (
              <div
                key={dim.name}
                className="rounded-xl border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-4"
              >
                <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
                  {dim.name}
                </div>
                <div className="space-y-2">
                  {dim.buckets.map((b) => (
                    <div
                      key={b.label}
                      className={`flex items-center gap-2 text-[13px] ${b.trusted ? "" : "opacity-45"}`}
                      title={`${b.wins}/${b.n} won${b.trusted ? "" : " · small sample"}`}
                    >
                      <span className="w-24 shrink-0 truncate capitalize text-[color:var(--text-dim)]">{b.label}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded bg-[color:var(--bg)]">
                        <div
                          className="h-full rounded"
                          style={{ width: `${b.win_pct}%`, background: color(b.win_pct) }}
                        />
                      </div>
                      <span className="num w-12 text-right font-semibold" style={{ color: color(b.win_pct) }}>
                        {b.win_pct}%
                      </span>
                      <span className="num w-8 text-right text-[10px] text-[color:var(--text-muted)]">{b.n}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      <footer className="relative z-10 mt-2 border-t border-[color:var(--border)] px-5 py-3 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
        <span>KALSHI-EV · bucket learning</span>
        <span className="mx-3 text-[color:var(--border-bright)]">|</span>
        <span>one game = noise · ~500+ bets per bucket = signal</span>
        <span className="mx-3 text-[color:var(--border-bright)]">|</span>
        <span>green ≥55% · amber 50–55% · red &lt;50%</span>
      </footer>
    </div>
  );
}
