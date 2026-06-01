import { spawn } from "node:child_process";
import path from "node:path";

const SCANNER_DIR = path.resolve(process.cwd(), "..", "scanner");

// Shared across /api/odds-refresh and /api/bovada (same Node process) so a
// freshness guard + in-flight coalescing protect Odds API credits.
let lastAt = 0;
let inFlight: Promise<number> | null = null;
const FRESH_MS = 180_000; // 3 min — these are paid Odds API pulls

function spawnRefresh(): Promise<number> {
  return new Promise((resolve) => {
    const proc = spawn(".venv/bin/python", ["-m", "src.dfs.live_odds"], { cwd: SCANNER_DIR });
    let out = "";
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.on("error", () => resolve(0));
    proc.on("close", () => {
      const m = out.match(/refreshed:\s*(\d+)/);
      resolve(m ? Number(m[1]) : 0);
    });
  });
}

export async function ensureFreshLiveOdds(
  force = false,
): Promise<{ refreshed: boolean; quotes?: number; ageMs: number }> {
  const age = Date.now() - lastAt;
  if (!force && age < FRESH_MS) return { refreshed: false, ageMs: age };
  if (!inFlight) {
    inFlight = spawnRefresh()
      .then((q) => {
        lastAt = Date.now();
        return q;
      })
      .finally(() => {
        inFlight = null;
      });
  }
  const quotes = await inFlight;
  return { refreshed: true, quotes, ageMs: 0 };
}
