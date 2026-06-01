"use client";

import { useQuery } from "@tanstack/react-query";

type HealthData = {
  sources: { source: string; lastFetchAt: string | null }[];
  checkedAt: string;
};

async function fetchHealth(): Promise<HealthData> {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error("fetch failed");
  return res.json();
}

export function HealthCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  if (isLoading) return <div className="p-6 text-zinc-400">Loading…</div>;
  if (!data) return null;

  return (
    <div className="space-y-2">
      {data.sources.length === 0 && (
        <div className="text-sm text-amber-400">
          No fetch successes recorded yet — scanner may not be running.
        </div>
      )}
      {data.sources.map((s) => {
        const last = s.lastFetchAt ? new Date(s.lastFetchAt) : null;
        const ageSec = last ? (Date.now() - last.getTime()) / 1000 : null;
        const status =
          ageSec === null
            ? "unknown"
            : ageSec < 60
            ? "ok"
            : ageSec < 300
            ? "warn"
            : "fail";
        const color =
          status === "ok" ? "text-emerald-400"
          : status === "warn" ? "text-amber-400"
          : "text-red-400";
        return (
          <div
            key={s.source}
            className="flex justify-between border-b border-zinc-900 px-4 py-3"
          >
            <span className="text-zinc-300">{s.source}</span>
            <span className={`font-mono tabular-nums ${color}`}>
              {ageSec !== null ? `${Math.round(ageSec)}s ago` : "never"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
