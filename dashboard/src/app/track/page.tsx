import { StatusBar } from "@/components/StatusBar";
import { TopNav } from "@/components/TopNav";
import { getTrackRecord, type TrackPick } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const STAT: Record<string, string> = {
  points: "PTS", rebounds: "REB", assists: "AST", threes: "3PM", blocks: "BLK",
  steals: "STL", pra: "PRA", shots: "Shots", shots_on_target: "SOT", "1X2": "1X2",
};
const SOURCE: Record<string, string> = {
  prizepicks: "PrizePicks", underdog: "Underdog", sleeper: "Sleeper",
  dk_pick6: "DK Pick 6", model: "Model", sportsbook: "Sportsbook",
};

function StatusChip({ s }: { s: string }) {
  const map: Record<string, [string, string]> = {
    hit: ["WON", "var(--accent)"],
    miss: ["LOST", "var(--negative)"],
    push: ["PUSH", "var(--text-muted)"],
    pending: ["PENDING", "var(--warn)"],
  };
  const [label, color] = map[s] ?? [s, "var(--text-muted)"];
  return (
    <span
      className="rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider"
      style={{ color, border: `1px solid ${color}`, opacity: s === "pending" ? 0.7 : 1 }}
    >
      {label}
    </span>
  );
}

export default async function TrackPage() {
  const t = await getTrackRecord();
  const decided = t.hit + t.miss;

  return (
    <div className="relative min-h-screen">
      <StatusBar />
      <TopNav />
      <main className="relative z-10 mx-auto max-w-5xl px-5 py-6 space-y-5">
        <header>
          <h1 className="text-[18px] font-semibold tracking-tight">
            <span className="text-[color:var(--accent)]">▶</span> Track Record
          </h1>
          <p className="mt-1 text-[12px] leading-relaxed text-[color:var(--text-dim)]">
            Every edge we surface is banked here and graded against reality after the game.
            This is the out-of-sample proof — and where we see exactly where we&apos;re mis-calibrated,
            so we get sharper every day.
          </p>
        </header>

        {/* Headline record */}
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Record" value={`${t.hit}-${t.miss}${t.push ? `-${t.push}` : ""}`} />
          <Stat
            label="Hit rate"
            value={decided > 0 ? `${(t.hitRate * 100).toFixed(1)}%` : "—"}
            color={t.hitRate >= 0.55 ? "var(--accent)" : decided > 0 ? "var(--warn)" : undefined}
            sub={decided > 0 ? `${decided} graded` : "none graded yet"}
          />
          <Stat label="Pending" value={String(t.pending)} sub="awaiting results" />
          <Stat label="Total tracked" value={String(t.total)} />
        </section>

        {/* By source */}
        {t.bySource.length > 0 && (
          <section className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-4">
            <div className="mb-2 text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
              By platform
            </div>
            <div className="space-y-1.5">
              {t.bySource.map((s) => {
                const dec = s.hit + s.miss;
                return (
                  <div key={s.source} className="flex items-center gap-3 text-[12px]">
                    <div className="w-28 text-[color:var(--text)]">{SOURCE[s.source] ?? s.source}</div>
                    <div className="num w-20 text-[color:var(--text-dim)]">
                      {s.hit}-{s.miss}
                    </div>
                    <div className="num w-16 text-right" style={{ color: dec > 0 && s.hit / dec >= 0.55 ? "var(--accent)" : "var(--text-dim)" }}>
                      {dec > 0 ? `${((s.hit / dec) * 100).toFixed(0)}%` : "—"}
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">
                      {s.pending} pending
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Calibration */}
        {t.calibration.length > 0 && (
          <section className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-4">
            <div className="mb-2 text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
              Calibration — did our X% picks actually hit X%?
            </div>
            <div className="space-y-1">
              {t.calibration.map((c) => (
                <div key={c.bucket} className="flex items-center gap-3 text-[12px]">
                  <div className="num w-16 text-[color:var(--text-dim)]">{c.bucket}</div>
                  <div className="num w-20 text-right" style={{ color: c.actual >= c.predicted - 0.05 ? "var(--accent)" : "var(--warn)" }}>
                    hit {(c.actual * 100).toFixed(0)}%
                  </div>
                  <div className="text-[10px] text-[color:var(--text-muted)]">n={c.n}</div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Recent picks */}
        <section className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)]">
          <div className="border-b border-[color:var(--border)] px-4 py-2 text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
            Tracked picks ({t.recent.length} most recent)
          </div>
          {t.recent.length === 0 ? (
            <div className="p-6 text-center text-[12px] text-[color:var(--text-muted)]">
              Nothing tracked yet. Run <code className="text-[color:var(--accent)]">python -m src.tracking.recorder record</code> after a scan.
            </div>
          ) : (
            t.recent.map((p) => <PickRow key={p.id} p={p} />)
          )}
        </section>
      </main>
    </div>
  );
}

function PickRow({ p }: { p: TrackPick }) {
  const side = p.pickSide === "over" ? "MORE" : p.pickSide === "under" ? "LESS" : p.pickSide.toUpperCase();
  const label = p.betKind === "game_line" ? (p.eventLabel ?? p.team ?? "") : p.playerName;
  return (
    <div className="grid grid-cols-[1fr_120px_90px_70px_80px] items-center gap-2 border-b border-[color:var(--border)] px-4 py-2 text-[12px]">
      <div className="min-w-0">
        <div className="truncate text-[color:var(--text)]">{label}</div>
        <div className="text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">
          {SOURCE[p.source] ?? p.source} · {p.sport.toUpperCase()}
        </div>
      </div>
      <div className="text-[11px]">
        <span style={{ color: p.pickSide === "under" ? "var(--warn)" : "var(--accent)" }}>{side}</span>{" "}
        {p.betKind === "game_line" ? STAT[p.statType] ?? p.statType : `${p.line} ${STAT[p.statType] ?? p.statType}`}
      </div>
      <div className="num text-right text-[11px] text-[color:var(--text-dim)]">
        {p.fairProb != null ? `${(p.fairProb * 100).toFixed(0)}%` : "—"}
      </div>
      <div className="num text-right text-[11px] text-[color:var(--text-muted)]">
        {p.actualValue != null ? p.actualValue : ""}
      </div>
      <div className="text-right">
        <StatusChip s={p.status} />
      </div>
    </div>
  );
}

function Stat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] px-4 py-3">
      <div className="text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">{label}</div>
      <div className="num mt-1 text-[22px] font-semibold" style={{ color: color ?? "var(--text)" }}>{value}</div>
      {sub && <div className="text-[10px] uppercase tracking-[0.16em] text-[color:var(--text-muted)]">{sub}</div>}
    </div>
  );
}
