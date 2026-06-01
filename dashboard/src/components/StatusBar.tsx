"use client";

import { useQuery } from "@tanstack/react-query";

type Stats = {
  opportunityCount: number;
  topEvPct: number | null;
  booksOnline: { book: string; quoteCount: number }[];
  lastTickAt: string | null;
  lastTickLatencyMs: number | null;
  generatedAt: string;
};

async function fetchStats(): Promise<Stats> {
  const r = await fetch("/api/stats");
  if (!r.ok) throw new Error("stats fetch failed");
  return r.json();
}

export function StatusBar() {
  const { data } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
    refetchInterval: 5000,
  });

  const ago = data?.lastTickAt
    ? Math.round((Date.now() - new Date(data.lastTickAt).getTime()) / 1000)
    : null;
  const live = ago !== null && ago < 90;

  return (
    <div className="glass sticky top-0 z-20">
      <div className="flex items-center justify-between gap-4 px-5 py-2.5">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-2 w-2 items-center justify-center">
              {live && (
                <span className="absolute inline-flex h-full w-full rounded-full bg-[color:var(--accent)] opacity-60 dot-pulse" />
              )}
              <span
                className={`relative inline-flex h-2 w-2 rounded-full ${
                  live ? "bg-[color:var(--accent)]" : "bg-[color:var(--text-muted)]"
                }`}
              />
            </span>
            <span className="text-[11px] font-medium text-[color:var(--text-dim)]">
              {live ? "Live" : "Idle"}
            </span>
          </div>
          <span className="h-4 w-px bg-[color:var(--border)]" />
          <div className="flex items-baseline gap-2">
            <span className="brand-grad text-[16px] font-bold tracking-tight">
              KALSHI·EV
            </span>
            <span className="hidden text-[11px] text-[color:var(--text-muted)] sm:inline">
              NBA player props
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <Metric label="Opps" value={data ? String(data.opportunityCount) : "—"} accent={!!data && data.opportunityCount > 0} />
          <Metric
            label="Top EV"
            value={data && data.topEvPct !== null ? `+${(data.topEvPct * 100).toFixed(2)}%` : "—"}
            accent={!!data && (data.topEvPct ?? 0) >= 0.03}
          />
          <Metric label="Books" value={data ? String(data.booksOnline.length) : "—"} hideSm />
          <Metric
            label="Tick"
            value={data?.lastTickLatencyMs != null ? `${(data.lastTickLatencyMs / 1000).toFixed(1)}s` : "—"}
            hideSm
          />
          <Metric label="Last" value={ago !== null ? `${ago}s` : "—"} warn={ago !== null && ago > 60} />
        </div>
      </div>

      {data && data.booksOnline.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-[color:var(--hairline)] px-5 py-2">
          <span className="mr-1 text-[10px] font-medium text-[color:var(--text-muted)]">
            Books online
          </span>
          {data.booksOnline.map((b) => (
            <span key={b.book} className="chip accent">
              {b.book.replace(/_/g, " ")}
              <span className="font-normal text-[color:var(--text-dim)]">{b.quoteCount}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  accent,
  warn,
  hideSm,
}: {
  label: string;
  value: string;
  accent?: boolean;
  warn?: boolean;
  hideSm?: boolean;
}) {
  const color = accent
    ? "text-[color:var(--accent)]"
    : warn
    ? "text-[color:var(--warn)]"
    : "text-[color:var(--text)]";
  return (
    <div
      className={`flex items-center gap-1.5 rounded-lg border border-[color:var(--border)] bg-[color:var(--bg-row)]/60 px-2.5 py-1 ${
        hideSm ? "hidden md:flex" : ""
      }`}
    >
      <span className="text-[9px] font-medium uppercase tracking-wider text-[color:var(--text-muted)]">
        {label}
      </span>
      <span className={`hero-num text-[12px] ${color}`}>{value}</span>
    </div>
  );
}
