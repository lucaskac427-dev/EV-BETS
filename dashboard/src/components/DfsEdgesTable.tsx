"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import type { DfsEdgeRow } from "@/lib/queries";
import { probToAmerican, trueEvPct } from "@/lib/odds";
import { PlayerAvatar } from "@/components/PlayerAvatar";

type SortKey = "ev" | "fair" | "books";
type FilterMode = "all" | "edges" | "safe";
type SportFilter = string | "all";

// Highest-WINNING strategy: surface only +edge sides that ALSO clear a 55%
// consensus win-probability floor. On standard picks (breakeven 55%) every
// +edge side already clears it; this prunes the sub-55% "demon" longshots that
// are +EV only because of the 1.25× payout — successful, not lucky.
const WIN_FLOOR = 0.55;

async function fetchEdges(): Promise<{
  edges: DfsEdgeRow[];
  generatedAt: string;
}> {
  const r = await fetch("/api/dfs/edges");
  if (!r.ok) throw new Error("fetch failed");
  return r.json();
}

function formatStartsAt(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function statBadge(stat: string): string {
  // Friendly market labels for both NBA and soccer
  const map: Record<string, string> = {
    points: "Points",
    rebounds: "Rebounds",
    assists: "Assists",
    threes: "Threes",
    blocks: "Blocks",
    steals: "Steals",
    pra: "PRA",
    shots: "Shots",
    shots_on_target: "SOT",
    tackles: "Tackles",
    fouls: "Fouls",
    goals: "Goals",
    goalie_saves: "Saves",
  };
  return map[stat] ?? stat;
}

const SPORT_LABELS: Record<string, string> = {
  nba: "NBA",
  soccer: "Soccer",
};

function sportLabel(s: string): string {
  return SPORT_LABELS[s] ?? s.toUpperCase();
}

// The 5 DFS platforms, each with a signature color so every edge is clearly
// attributed to the book it came from.
const SOURCE_LABELS: Record<string, string> = {
  prizepicks: "PrizePicks",
  underdog: "Underdog",
  sleeper: "Sleeper",
  dk_pick6: "DK Pick 6",
};
const SOURCE_COLORS: Record<string, string> = {
  prizepicks: "#a07cff",
  underdog: "#ff9d4d",
  sleeper: "#33c4ff",
  dk_pick6: "#00e676",
};

function sourceLabel(s: string): string {
  return SOURCE_LABELS[s] ?? s;
}

export function DfsEdgesTable({ lockedSource }: { lockedSource?: string } = {}) {
  const [mode, setMode] = useState<FilterMode>("safe");
  const [sportFilter, setSportFilter] = useState<SportFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<string | "all">("all");
  const [statFilter, setStatFilter] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("fair");
  const activeSource = lockedSource ?? sourceFilter;

  const { data, isLoading, error } = useQuery({
    queryKey: ["dfs-edges"],
    queryFn: fetchEdges,
    refetchInterval: 10000,
  });

  const rows = useMemo(() => {
    if (!data) return [];
    const enriched = data.edges.map((e) => {
      // DFS EV is PURE sharp consensus — projections never touch player props.
      const fairForEv = e.consensusFairProb;
      return {
        ...e,
        trueEv: trueEvPct(fairForEv, e.breakevenPerLeg),
        hasProjection: e.projectionFairProb != null,
      };
    });
    const filtered = enriched
      .filter((e) =>
        mode === "edges"
          ? e.trueEv > 0
          : mode === "safe"
          ? e.trueEv > 0 && e.consensusFairProb >= WIN_FLOOR
          : true
      )
      .filter((e) => (sportFilter !== "all" ? e.sport === sportFilter : true))
      .filter((e) => (activeSource !== "all" ? e.source === activeSource : true))
      .filter((e) => (statFilter ? e.statType === statFilter : true));
    const sorted = filtered.sort((a, b) => {
      if (sortKey === "ev") return b.trueEv - a.trueEv;
      if (sortKey === "fair") return b.consensusFairProb - a.consensusFairProb;
      return b.numSharpBooks - a.numSharpBooks;
    });
    return sorted;
  }, [data, mode, sportFilter, activeSource, statFilter, sortKey]);

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
  if (!data || data.edges.length === 0) {
    return (
      <div className="p-12 text-center text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
        ─ No bets available right now ─
      </div>
    );
  }

  const allRows = data.edges;
  const positiveCount = allRows.filter(
    (e) => trueEvPct(e.consensusFairProb, e.breakevenPerLeg) > 0
  ).length;
  const safeCount = allRows.filter(
    (e) =>
      trueEvPct(e.consensusFairProb, e.breakevenPerLeg) > 0 &&
      e.consensusFairProb >= WIN_FLOOR
  ).length;
  const sportKeys = Array.from(new Set(allRows.map((e) => e.sport))).sort();
  const scopedForStats = allRows.filter(
    (e) => sportFilter === "all" || e.sport === sportFilter
  );
  const statKeys = Array.from(new Set(scopedForStats.map((e) => e.statType))).sort();
  const sportCounts = sportKeys.reduce<Record<string, number>>((acc, s) => {
    acc[s] = allRows.filter((e) => e.sport === s).length;
    return acc;
  }, {});
  const sourceKeys = Array.from(new Set(allRows.map((e) => e.source))).sort();
  const sourceCounts = sourceKeys.reduce<Record<string, number>>((acc, s) => {
    acc[s] = allRows.filter((e) => e.source === s).length;
    return acc;
  }, {});

  return (
    <div>
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2.5 border-b border-[color:var(--hairline)] bg-[color:var(--bg)]/50 px-5 py-3 text-[12px]">
        <div className="flex rounded-xl border border-[color:var(--border)] bg-[color:var(--bg-row)]/40 p-0.5">
          <button
            onClick={() => {
              setMode("safe");
              setSortKey("fair");
            }}
            title="Highest-winning: +edge sides that ALSO clear a 55% win-probability floor (skips sub-55% demon longshots)"
            className={`rounded-[9px] px-3 py-1.5 font-medium transition-all ${
              mode === "safe"
                ? "bg-[color:var(--accent)] text-[#04140f] shadow-[0_0_18px_-6px_var(--accent-glow)]"
                : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
            }`}
          >
            Safe · win ≥55% {safeCount}
          </button>
          <button
            onClick={() => setMode("edges")}
            title="Every +EV side, including sub-55% demon longshots (highest-paying)"
            className={`rounded-[9px] px-3 py-1.5 font-medium transition-all ${
              mode === "edges"
                ? "bg-[color:var(--bg-elevated)] text-[color:var(--text)]"
                : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
            }`}
          >
            +EV {positiveCount}
          </button>
          <button
            onClick={() => setMode("all")}
            className={`rounded-[9px] px-3 py-1.5 font-medium transition-all ${
              mode === "all"
                ? "bg-[color:var(--bg-elevated)] text-[color:var(--text)]"
                : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
            }`}
          >
            All {allRows.length}
          </button>
        </div>

        {sportKeys.length > 1 && (
          <div className="flex border border-[color:var(--border)]">
            <button
              onClick={() => {
                setSportFilter("all");
                setStatFilter(null);
              }}
              className={`px-3 py-1.5 transition-colors ${
                sportFilter === "all"
                  ? "bg-[color:var(--info-soft)] text-[color:var(--info)]"
                  : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
              }`}
            >
              All sports
            </button>
            {sportKeys.map((s) => (
              <button
                key={s}
                onClick={() => {
                  setSportFilter(s);
                  setStatFilter(null);
                }}
                className={`border-l border-[color:var(--border)] px-3 py-1.5 transition-colors ${
                  sportFilter === s
                    ? "bg-[color:var(--info-soft)] text-[color:var(--info)]"
                    : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
                }`}
              >
                {sportLabel(s)} {sportCounts[s]}
              </button>
            ))}
          </div>
        )}

        {/* Platform / book filter — hidden on a dedicated platform tab */}
        {!lockedSource && sourceKeys.length > 1 && (
          <div className="flex border border-[color:var(--border)]">
            <button
              onClick={() => setSourceFilter("all")}
              className={`px-3 py-1.5 transition-colors ${
                sourceFilter === "all"
                  ? "bg-[color:var(--bg-elevated)] text-[color:var(--text)]"
                  : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
              }`}
            >
              All books
            </button>
            {sourceKeys.map((s) => (
              <button
                key={s}
                onClick={() => setSourceFilter(s)}
                className="border-l border-[color:var(--border)] px-3 py-1.5 transition-colors hover:opacity-80"
                style={{
                  color:
                    sourceFilter === s
                      ? SOURCE_COLORS[s] ?? "var(--text)"
                      : "var(--text-muted)",
                  backgroundColor:
                    sourceFilter === s ? "var(--bg-elevated)" : "transparent",
                }}
              >
                {sourceLabel(s)} {sourceCounts[s]}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-1">
          <FilterChip
            active={statFilter === null}
            onClick={() => setStatFilter(null)}
            label="All stats"
          />
          {statKeys.map((k) => (
            <FilterChip
              key={k}
              active={statFilter === k}
              onClick={() => setStatFilter(k)}
              label={statBadge(k)}
            />
          ))}
        </div>

        <div className="ml-auto text-[11px] text-[color:var(--text-muted)]">
          <b className="num text-[color:var(--text-dim)]">{rows.length}</b> plays · break-even 55%
        </div>
      </div>

      {/* Header */}
      <div className="grid grid-cols-[160px_minmax(160px,1fr)_100px_160px_90px_90px_90px_70px] gap-0 border-b border-[color:var(--hairline)] bg-[color:var(--bg-2)]/40 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-[color:var(--text-muted)]">
        <div>Game</div>
        <div>Player</div>
        <div>Market</div>
        <div>Pick</div>
        <div className="text-right">Odds</div>
        <SortableHeader
          label="Fair"
          active={sortKey === "fair"}
          onClick={() => setSortKey("fair")}
        />
        <SortableHeader
          label="EV"
          active={sortKey === "ev"}
          onClick={() => setSortKey("ev")}
        />
        <SortableHeader
          label="Books"
          active={sortKey === "books"}
          onClick={() => setSortKey("books")}
        />
      </div>

      {/* Rows */}
      {rows.map((e) => {
        const isPositive = e.trueEv > 0;
        const evColor = isPositive
          ? e.trueEv >= 0.05
            ? "text-[color:var(--accent)]"
            : "text-[color:var(--accent)] opacity-80"
          : "text-[color:var(--negative)] opacity-80";

        const fairForDisplay = e.consensusFairProb;
        const fairAmerican = probToAmerican(fairForDisplay);
        const oddsAmerican = probToAmerican(e.breakevenPerLeg);
        const isDemon = e.oddsType === "demon";
        const isGoblin = e.oddsType === "goblin";

        return (
          <Link
            key={e.id}
            href={`/dfs/${e.id}`}
            className={`terminal-row ${
              isPositive ? "positive" : ""
            } grid grid-cols-[160px_minmax(160px,1fr)_100px_160px_90px_90px_90px_70px] gap-0 px-5 py-3.5 text-[13px]`}
          >
            {/* Game */}
            <div className="self-center">
              <div className="text-[11px] font-medium text-[color:var(--info)]">
                {sportLabel(e.sport)} · {e.team ?? ""}
              </div>
              <div className="mt-0.5 text-[10px] text-[color:var(--text-muted)]">
                {formatStartsAt(e.gameStartsAt)}
              </div>
            </div>

            {/* Player */}
            <div className="flex items-center gap-3 self-center min-w-0">
              <PlayerAvatar
                name={e.playerName}
                photoUrl={e.photoUrl}
                size={46}
                highlight={isPositive}
              />
              <div className="min-w-0">
                <div className="truncate text-[14px] font-semibold tracking-tight text-[color:var(--text)]">
                  {e.playerName}
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[color:var(--text-muted)]">
                  <span
                    className="font-semibold"
                    style={{ color: SOURCE_COLORS[e.source] ?? "var(--text-dim)" }}
                  >
                    {sourceLabel(e.source)}
                  </span>
                  {e.team && <span className="truncate">· {e.team}</span>}
                </div>
              </div>
            </div>

            {/* Market */}
            <div className="self-center">
              <span className="rounded-full border border-[color:var(--border)] bg-[color:var(--bg-row)]/50 px-2.5 py-0.5 text-[11px] font-medium text-[color:var(--text-dim)]">
                {statBadge(e.statType)}
              </span>
            </div>

            {/* Pick */}
            <div className="self-center flex items-center gap-2">
              <span
                className={`font-medium ${
                  e.pickSide === "over"
                    ? "text-[color:var(--accent)]"
                    : "text-[color:var(--warn)]"
                }`}
              >
                {e.pickSide === "over" ? "Over" : "Under"}
              </span>
              <span className="num text-[15px] font-semibold text-[color:var(--text)]">
                {e.line}
              </span>
              {isDemon && (
                <span className="chip highlight" title="Demon · 1.25× per-leg multiplier">
                  Demon
                </span>
              )}
              {isGoblin && (
                <span className="chip warn" title="Goblin · 0.5× per-leg multiplier">
                  Goblin
                </span>
              )}
            </div>

            {/* Odds */}
            <div className="num text-right self-center text-[color:var(--text)]">
              {oddsAmerican}
            </div>

            {/* Fair (blended when projection available — small icon flag) */}
            <div className="num text-right self-center text-[color:var(--text-dim)]">
              {fairAmerican}
              {e.hasProjection && (
                <span
                  className="ml-1 text-[10px] text-[color:var(--info)]"
                  title={`Blended w/ model (n=${e.projectionSampleSize} games): consensus ${(e.consensusFairProb * 100).toFixed(1)}% × projection ${((e.projectionFairProb ?? 0) * 100).toFixed(1)}%`}
                >
                  ⚛
                </span>
              )}
            </div>

            {/* EV — the hero metric, with a magnitude bar */}
            <div className="self-center text-right">
              <div className={`hero-num text-[15px] ${evColor}`}>
                {isPositive ? "+" : ""}
                {(e.trueEv * 100).toFixed(1)}%
              </div>
              <div className="edge-bar mt-1 ml-auto w-12">
                <span
                  style={{
                    width: `${Math.min(100, (Math.abs(e.trueEv) / 0.12) * 100)}%`,
                    background: isPositive
                      ? "linear-gradient(90deg, var(--accent-dim), var(--accent-2))"
                      : "var(--negative)",
                  }}
                />
              </div>
            </div>

            {/* Books */}
            <div className="text-right self-center">
              <span
                className={`chip ${
                  e.numSharpBooks >= 4
                    ? "accent"
                    : e.numSharpBooks >= 2
                    ? ""
                    : "warn"
                }`}
              >
                {e.numSharpBooks}
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function SortableHeader({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={(ev) => {
        ev.preventDefault();
        onClick();
      }}
      className={`flex items-center justify-end gap-1 text-right transition-colors ${
        active
          ? "text-[color:var(--accent)]"
          : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
      }`}
    >
      <span>{label}</span>
      <span className="text-[9px]">{active ? "▼" : "·"}</span>
    </button>
  );
}

function FilterChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-1 border border-[color:var(--border)] transition-colors ${
        active
          ? "bg-[color:var(--bg-elevated)] text-[color:var(--text)]"
          : "text-[color:var(--text-muted)] hover:text-[color:var(--text-dim)]"
      }`}
    >
      {label}
    </button>
  );
}
