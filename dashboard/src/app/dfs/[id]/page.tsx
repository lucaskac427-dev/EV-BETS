import Link from "next/link";
import { notFound } from "next/navigation";

import { StatusBar } from "@/components/StatusBar";
import { TopNav } from "@/components/TopNav";
import { getDfsEdgeById } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const SOURCE_META: Record<string, { label: string; url: string }> = {
  prizepicks: { label: "PrizePicks", url: "https://app.prizepicks.com/" },
  underdog: { label: "Underdog", url: "https://underdogfantasy.com/pick-em" },
  sleeper: { label: "Sleeper", url: "https://sleeper.com/" },
  dk_pick6: { label: "DK Pick 6", url: "https://pick6.draftkings.com/" },
};

function formatStartsAt(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default async function DfsEdgeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const edge = await getDfsEdgeById(Number(id));
  if (!edge) notFound();

  const meta = SOURCE_META[edge.source] ?? { label: edge.source, url: "#" };

  const edgeClass =
    edge.edgePct >= 0.1
      ? "text-[color:var(--accent)]"
      : edge.edgePct >= 0.05
      ? "text-[color:var(--warn)]"
      : "text-[color:var(--text-dim)]";

  const oddsLabel =
    edge.oddsType === "demon"
      ? "🔥 DEMON"
      : edge.oddsType === "goblin"
      ? "👻 GOBLIN"
      : "STANDARD";

  return (
    <div className="relative min-h-screen">
      <StatusBar />
      <TopNav />

      <main className="relative z-10 mx-auto max-w-6xl px-5 py-6 space-y-5">
        <Link
          href="/dfs"
          className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)] hover:text-[color:var(--accent)]"
        >
          ← Back to edges
        </Link>

        <header className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-5">
          <div className="flex items-baseline justify-between">
            <div className="flex items-center gap-4">
              <div
                className="relative h-[88px] w-[88px] shrink-0 overflow-hidden rounded-xl"
                style={{
                  background:
                    "radial-gradient(circle at 50% 28%, #1b2440, #0a0f1f)",
                  boxShadow:
                    edge.edgePct >= 0.05
                      ? "0 0 0 1px var(--accent), 0 0 18px -3px var(--accent)"
                      : "0 0 0 1px var(--border-bright)",
                }}
              >
                {edge.photoUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={edge.photoUrl}
                    alt={edge.playerName}
                    className="h-full w-full object-cover object-top"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-[28px] font-semibold text-white/90">
                    {edge.playerName
                      .split(/\s+/)
                      .map((p) => p[0])
                      .slice(0, 2)
                      .join("")
                      .toUpperCase()}
                  </div>
                )}
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
                  {meta.label} // {edge.team ?? "NBA"} · {formatStartsAt(edge.gameStartsAt)}
                </div>
                <h1 className="mt-1 text-[24px] font-semibold tracking-tight">
                  {edge.playerName}
                </h1>
                <div className="mt-1 text-[13px] uppercase tracking-wider text-[color:var(--text-dim)]">
                  {edge.statType} · {edge.line}
                  <span className="ml-2 text-[10px] text-[color:var(--text-muted)]">
                    {oddsLabel}
                  </span>
                </div>
              </div>
            </div>
            <div className="flex flex-col items-end gap-1">
              <span
                className={`chip ${
                  edge.pickSide === "over" ? "accent" : "negative"
                } text-[12px]`}
              >
                {edge.pickSide === "over" ? "▲ PICK MORE" : "▼ PICK LESS"}
              </span>
            </div>
          </div>
        </header>

        <section className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <Metric label="Edge" value={`+${(edge.edgePct * 100).toFixed(2)}%`} highlight={edgeClass} />
          <Metric label="Sharp consensus" value={`${(edge.consensusFairProb * 100).toFixed(2)}%`} sub={`for ${edge.pickSide}`} />
          <Metric label="Breakeven / leg" value={`${(edge.breakevenPerLeg * 100).toFixed(1)}%`} sub="3-pick power play" />
          <Metric label="Sharp books" value={String(edge.numSharpBooks)} sub="agreeing on fair" />
        </section>

        <section className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-5">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)] mb-3">
            DFS edge math
          </div>
          <pre className="text-[12px] text-[color:var(--text-dim)] leading-relaxed whitespace-pre-wrap">
{`PrizePicks line:           ${edge.line} ${edge.statType}
Your pick:                 ${edge.pickSide === "over" ? "MORE" : "LESS"} (${edge.pickSide})
Pick type:                 ${oddsLabel}

Sharp books say:           P(${edge.pickSide}) = ${(edge.consensusFairProb * 100).toFixed(2)}%
Breakeven per leg:         ${(edge.breakevenPerLeg * 100).toFixed(2)}%   (3-pick @ 6x)
Edge:                      +${(edge.edgePct * 100).toFixed(2)}%

In a 3-pick Power Play with two other +EV legs of similar quality,
this pick contributes ~${(edge.edgePct * 100 * 3).toFixed(1)}% to parlay EV.`}
          </pre>

        </section>

        {edge.bookBreakdown && edge.bookBreakdown.length > 0 && (
          <section className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-5">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)] mb-3">
              Per-book breakdown — {edge.bookBreakdown.length} books · sorted by P(over)
            </div>
            <div className="grid grid-cols-[1fr_90px_90px_110px] gap-0 border-b border-[color:var(--border)] pb-2 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
              <div>Book</div>
              <div className="text-right">Over</div>
              <div className="text-right">Under</div>
              <div className="text-right">Fair P(over)</div>
            </div>
            {edge.bookBreakdown.map((b) => {
              const isSharp = b.book === "pinnacle";
              const isHardRock = b.book.includes("hardrock");
              return (
                <div
                  key={b.book}
                  className="grid grid-cols-[1fr_90px_90px_110px] gap-0 border-b border-[color:var(--border)] py-2 text-[12px]"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[color:var(--text)] uppercase tracking-wider">
                      {b.book.replace(/_/g, " ")}
                    </span>
                    {isSharp && (
                      <span className="chip accent text-[9px]">SHARP</span>
                    )}
                    {isHardRock && (
                      <span className="chip info text-[9px]">FL</span>
                    )}
                  </div>
                  <div className="num text-right text-[color:var(--text-dim)]">
                    {b.over ?? "—"}
                  </div>
                  <div className="num text-right text-[color:var(--text-dim)]">
                    {b.under ?? "—"}
                  </div>
                  <div className="num text-right text-[color:var(--text)]">
                    {b.fair_over != null ? `${(b.fair_over * 100).toFixed(1)}%` : "—"}
                  </div>
                </div>
              );
            })}
            <div className="mt-3 text-[10px] text-[color:var(--text-muted)]">
              Spread of P(over) across books shows where the platform line is stale.
              A wide gap between the sharpest book and the rest = a moving market.
            </div>
          </section>
        )}

        <section className="flex gap-3">
          <a
            href={meta.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 border border-[color:var(--accent-dim)] bg-[rgba(0,255,157,0.07)] px-4 py-2 text-[11px] uppercase tracking-[0.2em] text-[color:var(--accent)] hover:bg-[rgba(0,255,157,0.15)] transition-colors"
          >
            Open {meta.label} →
          </a>
        </section>
      </main>
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  highlight?: string;
}) {
  return (
    <div className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] px-4 py-3">
      <div className="text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
        {label}
      </div>
      <div
        className={`num mt-1 text-[20px] font-semibold ${
          highlight ?? "text-[color:var(--text)]"
        }`}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
          {sub}
        </div>
      )}
    </div>
  );
}
