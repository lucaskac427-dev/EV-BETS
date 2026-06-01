import { spawn } from "node:child_process";
import path from "node:path";

import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SCANNER_DIR = path.resolve(process.cwd(), "..", "scanner");

function run(): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    const proc = spawn(".venv/bin/python", ["-m", "src.dfs.bucket_report", "--json"], { cwd: SCANNER_DIR });
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

export async function GET() {
  return NextResponse.json(await run());
}
