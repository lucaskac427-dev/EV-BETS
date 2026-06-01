import { spawn } from "node:child_process";
import path from "node:path";

import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// The scanner Python package sits next to the dashboard in the repo.
const SCANNER_DIR = path.resolve(process.cwd(), "..", "scanner");

function runScan(sport: string): Promise<{ sport: string; ok: boolean; tail: string }> {
  return new Promise((resolve) => {
    const proc = spawn(
      ".venv/bin/python",
      ["-m", "src.scan", "--sport", sport, "--min-edge", "0"],
      { cwd: SCANNER_DIR },
    );
    let out = "";
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.stderr.on("data", (d) => (out += d.toString()));
    proc.on("error", (e) => resolve({ sport, ok: false, tail: String(e) }));
    proc.on("close", (code) =>
      resolve({ sport, ok: code === 0, tail: out.trim().split("\n").slice(-12).join("\n") }),
    );
  });
}

// Module-level freshness guard: auto-scan fires on every page load/refresh, so
// skip if we just scanned (protects Odds API credits + rate limits), and coalesce
// concurrent triggers into one run. The manual button passes force=1.
let lastScanAt = 0;
let inFlight: Promise<{ results: unknown[]; at: string }> | null = null;
const FRESH_MS = 45_000;

async function doScan(sports: string[]) {
  const results = [];
  for (const s of sports) results.push(await runScan(s)); // sequential to avoid API contention
  lastScanAt = Date.now();
  return { results, at: new Date().toISOString() };
}

export async function POST(req: Request) {
  const u = new URL(req.url).searchParams;
  const force = u.get("force") === "1";
  const sport = u.get("sport") ?? "nba";
  const sports = sport === "all" ? ["nba", "soccer"] : [sport];

  const age = Date.now() - lastScanAt;
  if (!force && age < FRESH_MS) {
    return NextResponse.json({ skipped: true, ageMs: age, results: [] });
  }
  if (!inFlight) {
    inFlight = doScan(sports).finally(() => {
      inFlight = null;
    });
  }
  return NextResponse.json(await inFlight);
}
