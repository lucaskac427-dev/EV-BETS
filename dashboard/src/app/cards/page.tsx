"use client";

import { useEffect, useRef, useState } from "react";

type Pick = { n: number; player: string; pick: string; prob: number; edge: number; result: string | null };
type App = {
  app: string; verified: boolean; num_picks: number; legs_available: number[];
  picks: Pick[]; parlays: { id: number; legs: number[] }[]; num_parlays: number; cost: number; note: string;
};
type Cards = { legs: number; stake: number; source: string; sport?: string; apps: App[]; _fellBackToDemo?: boolean };

const NAMES: Record<string, string> = {
  prizepicks: "PrizePicks", sleeper: "Sleeper", underdog: "Underdog", dk_pick6: "DK Pick6",
};

type SportMode = "nba" | "mlb" | "both";
const SPORTS: { key: SportMode; label: string; color: string }[] = [
  { key: "nba", label: "NBA", color: "#ff7a45" },
  { key: "mlb", label: "MLB", color: "#46b1ff" },
  { key: "both", label: "Both", color: "#00e6a0" },
];

type BovEdge = { player: string; market: string; side: string; line: number; bovada_odds: number; fair_pct: number; ev_pct: number };
const decAmer = (d: number) => (d >= 2 ? `+${Math.round((d - 1) * 100)}` : `${Math.round(-100 / (d - 1))}`);

export default function CardsPage() {
  const [legs, setLegs] = useState(3);
  const [stake, setStake] = useState(5);
  const [minEv, setMinEv] = useState(1);
  const [sport, setSport] = useState<SportMode>("nba");
  const [data, setData] = useState<Cards | null>(null);
  const [loading, setLoading] = useState(true);
  const [changes, setChanges] = useState<string[] | null>(null);
  const [checking, setChecking] = useState(false);
  const [bovada, setBovada] = useState<{ edges: BovEdge[]; source?: string } | null>(null);
  const dataRef = useRef<Cards | null>(null);
  dataRef.current = data;

  useEffect(() => {
    fetch(`/api/bovada`)
      .then((r) => r.json())
      .then(setBovada)
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    setChanges(null);
    fetch(`/api/cards?legs=${legs}&top=6&stake=${stake}&minEv=${minEv}&sport=${sport}`)
      .then((r) => r.json())
      .then((d) => setData(d))
      .finally(() => setLoading(false));
  }, [legs, stake, minEv, sport]);

  // Lock & drop: re-pull the live board and flag anything that moved or dropped.
  async function recheck() {
    setChecking(true);
    try {
      const fresh: Cards = await (await fetch(`/api/cards?legs=${legs}&top=6&stake=${stake}&minEv=${minEv}&sport=${sport}`)).json();
      const old = dataRef.current;
      const ch: string[] = [];
      if (old) {
        for (const fa of fresh.apps) {
          const oa = old.apps.find((a) => a.app === fa.app);
          if (!oa) continue;
          for (const op of oa.picks) {
            const stat = op.pick.split(" ").slice(-1)[0];
            const np = fa.picks.find((p) => p.player === op.player && p.pick.split(" ").slice(-1)[0] === stat);
            if (!np) ch.push(`${NAMES[fa.app] ?? fa.app}: ${op.player} (${op.pick}) — DROPPED, don't bet it`);
            else if (np.pick !== op.pick) ch.push(`${NAMES[fa.app] ?? fa.app}: ${op.player} moved — ${op.pick} → ${np.pick}`);
          }
        }
      }
      setChanges(ch);
      setData(fresh);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-5 py-8 text-slate-100">
      <h1 className="text-3xl font-bold">Bet Builder</h1>
      <p className="mt-1 text-slate-400">
        Every bet to place tonight — 6 safest picks → round-robin for all 4 DFS apps
        {sport !== "mlb" && ", plus your Bovada legs"}. One page.
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-2.5">
        <span className="text-sm text-slate-400">Sport:</span>
        <div className="flex rounded-xl border border-[color:var(--border)] bg-[color:var(--bg-row)]/40 p-0.5">
          {SPORTS.map((s) => (
            <button
              key={s.key}
              onClick={() => setSport(s.key)}
              title={s.key === "both" ? "Mix NBA + MLB legs — maximally uncorrelated" : `${s.label} only`}
              className="rounded-[9px] px-4 py-1.5 text-sm font-bold transition-all"
              style={
                sport === s.key
                  ? { background: s.color, color: "#06121d", boxShadow: `0 0 18px -7px ${s.color}` }
                  : { color: "var(--text-muted)" }
              }
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className="text-sm text-slate-400">Legs per parlay:</span>
        {[3, 4, 5, 6].map((n) => (
          <button
            key={n}
            onClick={() => setLegs(n)}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
              legs === n ? "bg-emerald-500 text-black" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {n}-leg
          </button>
        ))}
        <span className="ml-4 text-sm text-slate-400">Stake/bet:</span>
        {[5, 10, 20].map((s) => (
          <button
            key={s}
            onClick={() => setStake(s)}
            className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
              stake === s ? "bg-sky-500 text-black" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            ${s}
          </button>
        ))}
        <span className="ml-4 text-sm text-slate-400" title="Lower this on thin/sharp slates to see more picks">
          Min edge:
        </span>
        {[1, 0.5, 0.3].map((m) => (
          <button
            key={m}
            onClick={() => setMinEv(m)}
            className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
              minEv === m ? "bg-violet-500 text-black" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {m}%
          </button>
        ))}
      </div>

      {data?._fellBackToDemo && (
        <div className="mt-4 rounded-lg border border-amber-700/50 bg-amber-950/40 px-4 py-2 text-sm text-amber-300">
          No live games right now — showing <b>last night&apos;s slate as an example</b>. Hit Scan during games for live cards.
        </div>
      )}

      <div className="mt-4 rounded-lg border border-rose-800/50 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
        ⚠ Place these <b>by hand</b> in each app. Never let a bot place them — automated bets are the #1 way to get
        limited or banned.
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          onClick={recheck}
          disabled={checking}
          className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
        >
          {checking ? "Checking…" : "🔄 Re-check lines before you place"}
        </button>
        {changes !== null && changes.length === 0 && (
          <span className="text-sm font-medium text-emerald-400">✓ All lines still good — place away.</span>
        )}
      </div>
      {changes !== null && changes.length > 0 && (
        <div className="mt-3 rounded-lg border border-rose-700/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
          <div className="mb-1 font-semibold">⚠ {changes.length} pick(s) changed since you opened this — re-verify:</div>
          <ul className="list-disc space-y-0.5 pl-5">
            {changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {loading && <p className="mt-8 text-slate-400">Building cards…</p>}

      {!loading && data?.apps && (
        <div className="mt-6 grid gap-5 md:grid-cols-2">
          {data.apps.map((a) => (
            <AppCard key={a.app} a={a} stake={data.stake} />
          ))}
        </div>
      )}

      {sport !== "mlb" && bovada?.edges && bovada.edges.length > 0 && <BovadaCard edges={bovada.edges} />}
    </div>
  );
}

const BOV_EV_OPTIONS = [0.8, 1, 2, 3];

function BovadaCard({ edges }: { edges: BovEdge[] }) {
  const [minEv, setMinEv] = useState(1);
  const eligible = edges.filter((e) => e.ev_pct >= minEv);
  const sorted = [...eligible].sort((a, b) => b.fair_pct - a.fair_pct).slice(0, 8);
  const topFair = sorted[0]?.fair_pct ?? 0;
  return (
    <div className="mt-6 rounded-2xl border border-[#e0563a]/40 bg-[#e0563a]/[0.06] p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">🎰 Bovada — one-click round robin</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">min EV</span>
          <div className="flex overflow-hidden rounded-lg border border-slate-700">
            {BOV_EV_OPTIONS.map((v) => (
              <button
                key={v}
                onClick={() => setMinEv(v)}
                className={`px-2.5 py-1 text-xs font-semibold transition ${
                  minEv === v ? "bg-[#e0563a] text-black" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {v}%
              </button>
            ))}
          </div>
        </div>
      </div>
      <p className="mt-1 text-sm text-slate-400">
        {sorted.length} leg{sorted.length === 1 ? "" : "s"} at <b>{minEv}%+ EV</b> · select in Bovada, hit{" "}
        <b>Round Robin</b>, submit once — every combo locks at the price you saw (no line movement).
      </p>
      {sorted.length === 0 ? (
        <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-2 text-xs text-slate-400">
          No Bovada legs at {minEv}%+ EV right now — drop the cutoff or wait for a fuller slate.
        </div>
      ) : (
        topFair < 50 && (
          <div className="mt-3 rounded-lg border border-amber-700/50 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
            ⚠ These are <b>longshots (under 50% to hit)</b> — fine as single +EV bets, riskier stacked in a round-robin.
            Stick to the highest Fair% legs.
          </div>
        )
      )}
      <ol className="mt-3 space-y-1 text-sm">
        {sorted.map((e, i) => (
          <li key={i} className="flex items-baseline gap-2">
            <span className="w-5 shrink-0 text-slate-500">{i + 1}.</span>
            <span className="font-medium">{e.player}</span>
            <span className="capitalize text-slate-400">
              {e.side} {e.line} {e.market.replace(/_/g, " ")}
            </span>
            <span className="ml-auto tabular-nums text-slate-500">{decAmer(e.bovada_odds)}</span>
            <span className={`w-12 text-right tabular-nums ${e.fair_pct >= 55 ? "text-emerald-400" : "text-amber-400"}`}>
              {e.fair_pct}%
            </span>
            <span className="w-14 text-right tabular-nums text-emerald-400">+{e.ev_pct.toFixed(1)}%</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function AppCard({ a, stake }: { a: App; stake: number }) {
  const [open, setOpen] = useState(false);
  const playable = a.num_parlays > 0;
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">{NAMES[a.app] ?? a.app}</h2>
        <span className={`rounded-full px-2 py-0.5 text-xs ${a.verified ? "bg-emerald-900 text-emerald-300" : "bg-slate-700 text-slate-300"}`}>
          {a.verified ? "payouts verified" : "unverified"}
        </span>
      </div>

      {!playable ? (
        <p className="mt-3 text-sm text-amber-400">{a.note || "no card"}</p>
      ) : (
        <>
          <ol className="mt-3 space-y-1 text-sm">
            {a.picks.map((p) => (
              <li key={p.n} className="flex items-baseline gap-2">
                <span className="w-5 shrink-0 text-slate-500">{p.n}.</span>
                <span className="font-medium">{p.player}</span>
                <span className="text-slate-400">{p.pick}</span>
                <span className="ml-auto text-emerald-400">{p.prob}%</span>
                {p.result && (
                  <span className={p.result === "WIN" ? "text-emerald-400" : "text-rose-400"}>
                    {p.result === "WIN" ? "✓" : "✗"}
                  </span>
                )}
              </li>
            ))}
          </ol>

          <div className="mt-4 flex items-center justify-between rounded-lg bg-slate-800/60 px-3 py-2 text-sm">
            <span>
              <b>{a.num_parlays}</b> parlays × ${stake}
            </span>
            <span className="font-bold text-sky-300">= ${a.cost} to place</span>
          </div>

          <button
            onClick={() => setOpen((o) => !o)}
            className="mt-3 text-sm font-semibold text-sky-400 hover:text-sky-300"
          >
            {open ? "Hide" : "Show"} all {a.num_parlays} bets to enter →
          </button>

          {open && (
            <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-300 sm:grid-cols-3">
              {a.parlays.map((pl) => (
                <div key={pl.id} className="tabular-nums">
                  <span className="text-slate-500">#{pl.id}</span>{" "}
                  {pl.legs.map((L) => a.picks.find((p) => p.n === L)?.player.split(" ").slice(-1)[0] ?? L).join(" + ")}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
