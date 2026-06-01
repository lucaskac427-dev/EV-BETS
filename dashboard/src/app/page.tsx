import { OpportunityTable } from "@/components/OpportunityTable";
import { StatusBar } from "@/components/StatusBar";
import { TopNav } from "@/components/TopNav";

export default function HomePage() {
  return (
    <div className="relative min-h-screen">
      <StatusBar />
      <TopNav />
      <main className="relative z-10">
        <div className="border-b border-[color:var(--border)] bg-[color:var(--bg)] px-5 py-3">
          <div className="flex items-baseline justify-between">
            <div>
              <h1 className="text-[15px] font-semibold tracking-tight">
                <span className="text-[color:var(--accent)]">▶</span> Opportunities
              </h1>
              <p className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
                Sorted by edge // Click any row for per-book detail
              </p>
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
              Auto-refresh · 5s
            </div>
          </div>
        </div>
        <OpportunityTable />
      </main>
      <footer className="relative z-10 mt-6 border-t border-[color:var(--border)] px-5 py-3 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
        <span>KALSHI-EV · v0.2 · NBA</span>
        <span className="mx-3 text-[color:var(--border-bright)]">|</span>
        <span>The Odds API + Pinnacle</span>
        <span className="mx-3 text-[color:var(--border-bright)]">|</span>
        <span>Min EV 1.00%</span>
        <span className="mx-3 text-[color:var(--border-bright)]">|</span>
        <span>Min sharp books 2</span>
      </footer>
    </div>
  );
}
