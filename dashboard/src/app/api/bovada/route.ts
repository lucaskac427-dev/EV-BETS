import { spawn } from "node:child_process";
import path from "node:path";

import { NextResponse } from "next/server";

import { ensureFreshLiveOdds } from "@/lib/liveOdds";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SCANNER_DIR = path.resolve(process.cwd(), "..", "scanner");

function run(minEv: number | null): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    // No threshold → full board (every consensus-matched line, for the Bovada page).
    // A threshold (the Bet Builder passes 2) → ONLY +EV legs, so it can never
    // surface juiced -EV favorites just because their hit rate is high.
    const args = ["-m", "src.dfs.bovada_edges", "--json", "--days", "3"];
    if (minEv === null) args.push("--all");
    else args.push("--min-ev", String(minEv));
    const proc = spawn(".venv/bin/python", args, { cwd: SCANNER_DIR });
    let out = "";
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.on("error", (e) => resolve({ error: String(e) }));
    proc.on("close", () => {
      for (const line of out.trim().split("\n").reverse()) {
        try {
          return resolve(JSON.parse(line));
        } catch {
          /* skip log lines */
        }
      }
      resolve({ error: "no JSON produced" });
    });
  });
}

export async function GET(req: Request) {
  const raw = new URL(req.url).searchParams.get("minEv");
  const minEv = raw === null ? null : Number(raw);
  await ensureFreshLiveOdds(false); // refresh live_book_odds (guarded) so edges are current
  return NextResponse.json(await run(minEv));
}
