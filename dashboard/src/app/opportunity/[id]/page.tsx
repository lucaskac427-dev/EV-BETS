import Link from "next/link";
import { notFound } from "next/navigation";

import { BookBreakdown } from "@/components/BookBreakdown";
import { StatusBar } from "@/components/StatusBar";
import { getOpportunityById } from "@/lib/queries";
import { formatDecimalAsAmerican, formatStartsAt } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const opp = await getOpportunityById(Number(id));
  if (!opp) notFound();

  const stake = opp.kellyFraction
    ? `${(opp.kellyFraction * 100).toFixed(2)}%`
    : "—";
  const kalshiCents = ((1 / opp.kalshiDecimalOdds) * 100).toFixed(1);
  const evClass =
    opp.evPct >= 0.03
      ? "text-[color:var(--accent)]"
      : opp.evPct >= 0.015
      ? "text-[color:var(--warn)]"
      : "text-[color:var(--text-dim)]";

  return (
    <div className="relative min-h-screen">
      <StatusBar />

      <main className="relative z-10 mx-auto max-w-6xl px-5 py-6 space-y-5">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)] hover:text-[color:var(--accent)]"
        >
          ← Back to scanner
        </Link>

        <header className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-5">
          <div className="flex items-baseline justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
                {opp.sport} // {formatStartsAt(opp.gameStartsAt)}
              </div>
              <h1 className="mt-1 text-[24px] font-semibold tracking-tight">
                {opp.playerName}
              </h1>
              <div className="mt-1 text-[13px] uppercase tracking-wider text-[color:var(--text-dim)]">
                {opp.statType} · {opp.line}+ threshold
              </div>
            </div>
            <div className="flex flex-col items-end gap-1">
              <span
                className={`chip ${
                  opp.kalshiSide === "yes" ? "accent" : "negative"
                } text-[12px]`}
              >
                {opp.kalshiSide === "yes" ? "▲ BUY YES" : "▼ BUY NO"}
              </span>
              {opp.suspicious && (
                <span className="chip negative">⚠ verify quote</span>
              )}
            </div>
          </div>
        </header>

        <section className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <Metric label="EV" value={`${opp.evPct >= 0 ? "+" : ""}${(opp.evPct * 100).toFixed(2)}%`} highlight={evClass} />
          <Metric label="Fair (consensus)" value={`${(opp.consensusFairProb * 100).toFixed(2)}%`} />
          <Metric label="Kalshi price" value={`${kalshiCents}¢ · ${formatDecimalAsAmerican(opp.kalshiDecimalOdds)}`} />
          <Metric label="Recommended stake" value={stake} sub="of bankroll" />
        </section>

        <BookBreakdown opportunityId={opp.id} />

        <section className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-5">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)] mb-3">
            EV math
          </div>
          <pre className="text-[12px] text-[color:var(--text-dim)] leading-relaxed">
{`fair_prob × $1 payout    =  ${(opp.consensusFairProb).toFixed(4)} × $1.00     = $${opp.consensusFairProb.toFixed(4)}
kalshi share cost         =  ${kalshiCents}¢                              = $${(parseFloat(kalshiCents) / 100).toFixed(4)}
edge per share            =  $${(opp.consensusFairProb - parseFloat(kalshiCents) / 100).toFixed(4)}
edge % of stake           =  ${(opp.evPct * 100).toFixed(2)}%`}
          </pre>
          <div className="mt-3 text-[11px] text-[color:var(--text-muted)] leading-relaxed">
            Fair prob below 50% only means the event loses more than half the time —
            it&apos;s +EV because Kalshi&apos;s price is even lower than the loss rate would justify.
          </div>
        </section>

        <section className="flex gap-3">
          <a
            href={`https://kalshi.com/markets/${opp.kalshiTicker.split("-")[0]}/${opp.kalshiTicker.split("-").slice(0, 2).join("-")}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 border border-[color:var(--accent-dim)] bg-[rgba(0,255,157,0.07)] px-4 py-2 text-[11px] uppercase tracking-[0.2em] text-[color:var(--accent)] hover:bg-[rgba(0,255,157,0.15)] transition-colors"
          >
            Open on Kalshi →
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
