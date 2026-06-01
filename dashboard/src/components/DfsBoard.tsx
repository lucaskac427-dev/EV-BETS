import { DfsEdgesTable } from "@/components/DfsEdgesTable";
import { ScanButton } from "@/components/ScanButton";
import { StatusBar } from "@/components/StatusBar";
import { TopNav } from "@/components/TopNav";

export const DFS_PLATFORMS: Record<
  string,
  { label: string; color: string; url: string }
> = {
  prizepicks: { label: "PrizePicks", color: "#a07cff", url: "https://app.prizepicks.com/" },
  underdog: { label: "Underdog", color: "#ff9d4d", url: "https://underdogfantasy.com/pick-em" },
  sleeper: { label: "Sleeper", color: "#33c4ff", url: "https://sleeper.com/" },
  dk_pick6: { label: "DK Pick 6", color: "#00e676", url: "https://pick6.draftkings.com/" },
};

export function DfsBoard({ source }: { source?: string }) {
  const meta = source ? DFS_PLATFORMS[source] : null;
  const accent = meta?.color ?? "var(--accent)";
  return (
    <div className="relative min-h-screen">
      <StatusBar />
      <TopNav />
      <main className="relative z-10">
        <header className="flex items-end justify-between gap-4 px-5 pb-4 pt-6">
          <div className="flex items-center gap-3.5">
            <span
              className="h-9 w-1.5 rounded-full"
              style={{ background: accent, boxShadow: `0 0 18px ${accent}` }}
            />
            <div>
              <h1 className="text-[26px] font-bold leading-none tracking-tight text-[color:var(--text)]">
                {meta ? `${meta.label} Edges` : "DFS Edges"}
              </h1>
              <p className="mt-1.5 text-[12.5px] text-[color:var(--text-dim)]">
                {meta
                  ? `${meta.label} lines vs the sharp consensus`
                  : "PrizePicks · Underdog · Sleeper · DK Pick 6 — soft lines vs the sharp consensus"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1.5 text-[11px] text-[color:var(--text-muted)] sm:flex">
              <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--accent)] dot-pulse" />
              auto · 10s
            </span>
            <ScanButton sport="all" />
          </div>
        </header>
        <DfsEdgesTable lockedSource={source} />
      </main>
      <footer className="relative z-10 mt-8 flex flex-wrap gap-x-6 gap-y-1 border-t border-[color:var(--hairline)] px-5 py-4 text-[11px] text-[color:var(--text-muted)]">
        <span className="font-medium text-[color:var(--text-dim)]">KALSHI·EV</span>
        <span>{meta ? meta.label : "5 platforms"} vs Odds API consensus</span>
        <span>win&gt;55% Safe mode default</span>
      </footer>
    </div>
  );
}
