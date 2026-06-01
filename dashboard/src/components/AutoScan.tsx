"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

// Fires on every page load / refresh: pulls fresh DFS lines AND live sportsbook
// odds (for the Bovada finder), then refetches the board. Both endpoints are
// freshness-guarded server-side, so a burst of refreshes can't burn API credits.
export function AutoScan() {
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "scanning" | "done">("idle");
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    setState("scanning");
    Promise.allSettled([
      fetch("/api/scan?sport=all", { method: "POST" }),
      fetch("/api/odds-refresh", { method: "POST" }),
    ])
      .then(() => qc.invalidateQueries())
      .finally(() => {
        setState("done");
        setTimeout(() => setState("idle"), 3500);
      });
  }, [qc]);

  if (state === "idle") return null;
  return (
    <div className="fixed bottom-4 right-4 z-50 flex items-center gap-2 rounded-lg border border-[color:var(--border)] bg-[color:var(--bg-elevated)] px-3 py-2 text-[11px] uppercase tracking-[0.16em] text-[color:var(--text-muted)] shadow-lg">
      {state === "scanning" ? (
        <>
          <span className="animate-spin text-[color:var(--accent)]">⟳</span> scanning fresh odds…
        </>
      ) : (
        <>
          <span className="text-[color:var(--accent)]">✓</span> odds updated
        </>
      )}
    </div>
  );
}
