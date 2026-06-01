import { spawn } from "node:child_process";
import path from "node:path";

import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SCANNER_DIR = path.resolve(process.cwd(), "..", "scanner");

function buildCards(legs: number, top: number, stake: number, live: boolean, minEv: number, sport: string): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    const proc = spawn(
      ".venv/bin/python",
      ["-m", "src.dfs.parlay_optimizer", live ? "--live-cards" : "--demo-cards",
        "--legs", String(legs), "--top", String(top), "--stake", String(stake),
        "--min-edge", String(minEv), "--sport", sport],
      { cwd: SCANNER_DIR },
    );
    let out = "";
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.on("error", (e) => resolve({ error: String(e) }));
    proc.on("close", () => {
      for (const line of out.trim().split("\n").reverse()) {
        try {
          return resolve(JSON.parse(line));
        } catch {
          /* skip non-JSON log lines */
        }
      }
      resolve({ error: "no JSON produced", raw: out.slice(-300) });
    });
  });
}

export async function GET(req: Request) {
  const q = new URL(req.url).searchParams;
  const legs = Math.max(3, Math.min(6, Number(q.get("legs") ?? 3)));
  const top = Math.max(legs, Math.min(8, Number(q.get("top") ?? 6)));
  const stake = Number(q.get("stake") ?? 5);
  const minEv = Number(q.get("minEv") ?? 1);
  const sportRaw = q.get("sport") ?? "nba";
  const sport = ["nba", "mlb", "both"].includes(sportRaw) ? sportRaw : "nba";

  let data = await buildCards(legs, top, stake, true, minEv, sport);
  const apps = (data?.apps as Array<{ num_picks: number }> | undefined) ?? [];
  // No live games right now? Show last night's graded slate so the page isn't blank.
  if (apps.length && apps.every((a) => a.num_picks === 0)) {
    data = await buildCards(legs, top, stake, false, minEv, sport);
    data._fellBackToDemo = true;
  }
  return NextResponse.json(data);
}
