"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import type { OpportunityRow } from "@/lib/queries";
import { formatDecimalAsAmerican, formatStartsAt } from "@/lib/format";

async function fetchOpportunities(): Promise<{
  opportunities: OpportunityRow[];
  generatedAt: string;
}> {
  const res = await fetch("/api/opportunities");
  if (!res.ok) throw new Error("fetch failed");
  return res.json();
}

export function OpportunityTable() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["opportunities"],
    queryFn: fetchOpportunities,
    refetchInterval: 5000,
  });

  if (isLoading)
    return (
      <div className="p-12 text-center text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
        ▙ Connecting to scanner…
      </div>
    );
  if (error)
    return (
      <div className="p-12 text-center text-[11px] uppercase tracking-[0.2em] text-[color:var(--negative)]">
        ✕ {String(error)}
      </div>
    );
  if (!data || data.opportunities.length === 0) {
    return (
      <div className="p-12 text-center">
        <div className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
          ─ No edges right now ─
        </div>
        <div className="mt-2 text-[10px] text-[color:var(--text-muted)]">
          Scanner is ticking, waiting for mispriced lines.
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-[140px_minmax(200px,1fr)_120px_140px_110px_90px_90px_60px] gap-0 border-b border-[color:var(--border)] bg-[color:var(--bg-elevated)] px-5 py-2.5 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
        <div>Game</div>
        <div>Market</div>
        <div className="text-right">Side</div>
        <div className="text-right">Kalshi</div>
        <div className="text-right">Fair</div>
        <div className="text-right">EV</div>
        <div className="text-right">Kelly</div>
        <div className="text-right">Books</div>
      </div>

      {data.opportunities.map((o) => {
        const evClass =
          o.evPct >= 0.03
            ? "text-[color:var(--accent)]"
            : o.evPct >= 0.015
            ? "text-[color:var(--warn)]"
            : "text-[color:var(--text-dim)]";
        const kalshiCents = ((1 / o.kalshiDecimalOdds) * 100).toFixed(0);

        return (
          <Link
            key={o.id}
            href={`/opportunity/${o.id}`}
            className="terminal-row grid grid-cols-[140px_minmax(200px,1fr)_120px_140px_110px_90px_90px_60px] gap-0 border-b border-[color:var(--border)] px-5 py-3 text-[13px] transition-colors"
          >
            <div>
              <div className="text-[11px] uppercase tracking-wider text-[color:var(--text)]">
                {o.sport}
              </div>
              <div className="mt-0.5 text-[10px] text-[color:var(--text-muted)]">
                {formatStartsAt(o.gameStartsAt)}
              </div>
            </div>

            <div>
              <div className="text-[color:var(--text)]">
                {o.playerName ?? "—"}
              </div>
              <div className="mt-0.5 text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">
                {o.statType} {o.line ?? ""}
                {o.suspicious && (
                  <span className="ml-2 chip negative">⚠ sus</span>
                )}
              </div>
            </div>

            <div className="flex items-center justify-end">
              <span
                className={`chip ${
                  o.kalshiSide === "yes" ? "accent" : "negative"
                }`}
              >
                {o.kalshiSide === "yes" ? "▲ YES" : "▼ NO"}
              </span>
            </div>

            <div className="flex items-baseline justify-end gap-1.5 num">
              <span className="text-[color:var(--text)]">
                {formatDecimalAsAmerican(o.kalshiDecimalOdds)}
              </span>
              <span className="text-[10px] text-[color:var(--text-muted)]">
                {kalshiCents}¢
              </span>
            </div>

            <div className="num text-right text-[color:var(--text-dim)]">
              {(o.blendedFairProb * 100).toFixed(1)}%
            </div>

            <div className={`num text-right font-semibold ${evClass}`}>
              {o.evPct >= 0 ? "+" : ""}
              {(o.evPct * 100).toFixed(2)}%
            </div>

            <div className="num text-right text-[color:var(--text-dim)]">
              {o.kellyFraction
                ? `${(o.kellyFraction * 100).toFixed(2)}%`
                : "—"}
            </div>

            <div className="text-right">
              <span
                className={`chip ${
                  o.numSharpBooks >= 4
                    ? "accent"
                    : o.numSharpBooks >= 2
                    ? ""
                    : "warn"
                }`}
              >
                {o.numSharpBooks}
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
