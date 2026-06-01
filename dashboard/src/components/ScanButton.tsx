"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

export function ScanButton({ sport = "nba" }: { sport?: string }) {
  const qc = useQueryClient();
  const [scanning, setScanning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function scan() {
    setScanning(true);
    setMsg("pulling live odds…");
    try {
      const r = await fetch(`/api/scan?sport=${sport}&force=1`, { method: "POST" });
      const d = await r.json();
      const line = (d.results ?? [])
        .map((x: { tail: string }) =>
          (x.tail.match(/SCAN .*bets.*edge[^\n]*/) ?? [""])[0].trim(),
        )
        .filter(Boolean)
        .join(" · ");
      setMsg(line || "scan complete");
      // refetch everything that reads edges (table, parlays, track)
      await qc.invalidateQueries();
    } catch {
      setMsg("scan failed — is the scanner venv present?");
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={scan}
        disabled={scanning}
        className="inline-flex items-center gap-1.5 border border-[color:var(--accent-dim)] bg-[rgba(0,255,157,0.08)] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--accent)] transition-colors hover:bg-[rgba(0,255,157,0.16)] disabled:opacity-50"
      >
        <span className={scanning ? "animate-spin" : ""}>⟳</span>
        {scanning ? "Scanning…" : "Scan Now"}
      </button>
      {msg && (
        <span className="text-[10px] uppercase tracking-[0.14em] text-[color:var(--text-muted)]">
          {msg}
        </span>
      )}
    </div>
  );
}
