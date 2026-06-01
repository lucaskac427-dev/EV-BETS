import { StatusBar } from "@/components/StatusBar";
import { TopNav } from "@/components/TopNav";
import { getBookRoi } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function fmtBook(b: string): string {
  return b.replace(/_/g, " ").replace(/\bus\b/i, "US").toUpperCase();
}

export default async function BooksPage() {
  const rows = await getBookRoi();
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.roiPct)));

  return (
    <div className="relative min-h-screen">
      <StatusBar />
      <TopNav />
      <main className="relative z-10 mx-auto max-w-4xl px-5 py-6 space-y-5">
        <header>
          <h1 className="text-[18px] font-semibold tracking-tight">
            <span className="text-[color:var(--accent)]">▶</span> Book ROI — who to trust
          </h1>
          <p className="mt-1 text-[12px] leading-relaxed text-[color:var(--text-dim)]">
            Backtest result of betting our flagged edges <i>at each book</i> (NBA props, edge ≥ 3%).
            <span className="text-[color:var(--accent)]"> High ROI = SOFT</span> (its prices are
            often wrong in your favor — great to bet against, a noisier vote in consensus).
            <span className="text-[color:var(--negative)]"> Low / negative = SHARP</span> (you
            can&apos;t beat it — its line is a <i>better</i> vote for the fair number; an edge that
            survives a sharp book is the real deal).
          </p>
        </header>

        {rows.length === 0 ? (
          <div className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-8 text-center text-[12px] text-[color:var(--text-muted)]">
            No ROI computed yet — run <code className="text-[color:var(--accent)]">python -m src.historical.book_roi</code>
          </div>
        ) : (
          <div className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)]">
            <div className="grid grid-cols-[1fr_90px_70px_minmax(180px,1fr)_120px] gap-0 border-b border-[color:var(--border)] px-4 py-2 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
              <div>Book</div>
              <div className="text-right">Bets</div>
              <div className="text-right">Win%</div>
              <div className="text-center">ROI</div>
              <div className="text-right">Verdict</div>
            </div>
            {rows.map((r) => {
              const soft = r.roiPct > 3;
              const sharp = r.roiPct < 0;
              const noisy = r.nBets < 30;
              const color = soft
                ? "var(--accent)"
                : sharp
                ? "var(--negative)"
                : "var(--text-dim)";
              const pct = Math.min(100, (Math.abs(r.roiPct) / maxAbs) * 100);
              return (
                <div
                  key={r.book}
                  className="grid grid-cols-[1fr_90px_70px_minmax(180px,1fr)_120px] items-center gap-0 border-b border-[color:var(--border)] px-4 py-2.5 text-[12px]"
                >
                  <div className="font-medium text-[color:var(--text)]">
                    {fmtBook(r.book)}
                  </div>
                  <div className="num text-right text-[color:var(--text-dim)]">
                    {r.nBets}
                    {noisy && (
                      <span className="ml-1 text-[color:var(--warn)]" title="Small sample — noisy">
                        ⚠
                      </span>
                    )}
                  </div>
                  <div className="num text-right text-[color:var(--text-dim)]">
                    {(r.winRate * 100).toFixed(0)}%
                  </div>
                  {/* ROI bar centered at zero */}
                  <div className="flex items-center justify-center px-3">
                    <div className="relative h-2.5 w-full bg-[color:var(--bg)]">
                      <div className="absolute left-1/2 top-0 h-full w-px bg-[color:var(--border-bright)]" />
                      <div
                        className="absolute top-0 h-full"
                        style={{
                          backgroundColor: color,
                          width: `${pct / 2}%`,
                          left: r.roiPct >= 0 ? "50%" : `${50 - pct / 2}%`,
                          opacity: noisy ? 0.45 : 1,
                        }}
                      />
                    </div>
                  </div>
                  <div className="text-right">
                    <span className="num font-semibold" style={{ color }}>
                      {r.roiPct >= 0 ? "+" : ""}
                      {r.roiPct.toFixed(1)}%
                    </span>
                    <span className="ml-2 text-[9px] uppercase tracking-wider text-[color:var(--text-muted)]">
                      {soft ? "soft" : sharp ? "sharp" : "—"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <p className="text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
          ⚠ = under 30 bets (noisy, don&apos;t over-trust) · refresh with `book_roi` after new scans
        </p>
      </main>
    </div>
  );
}
