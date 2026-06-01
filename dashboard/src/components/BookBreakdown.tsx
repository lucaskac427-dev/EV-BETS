"use client";

import { useQuery } from "@tanstack/react-query";

type BookQuote = {
  book: string;
  side: string;
  decimalOdds: number;
  impliedProb: number;
  fetchedAt: string;
};

async function fetchBreakdown(id: number): Promise<{ books: BookQuote[] }> {
  const r = await fetch(`/api/opportunity/${id}/books`);
  if (!r.ok) throw new Error("breakdown fetch failed");
  return r.json();
}

function americanFromDecimal(d: number): string {
  if (d >= 2.0) return `+${Math.round((d - 1) * 100)}`;
  return `-${Math.round(100 / (d - 1))}`;
}

function devig(over: number, under: number): number {
  const total = over + under;
  return total > 0 ? over / total : 0;
}

export function BookBreakdown({ opportunityId }: { opportunityId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["breakdown", opportunityId],
    queryFn: () => fetchBreakdown(opportunityId),
    refetchInterval: 5000,
  });

  if (isLoading)
    return (
      <div className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)] p-6 text-[11px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
        ▙ loading book breakdown…
      </div>
    );

  const quotes = data?.books ?? [];

  // Group by book; collect over/under sides + kalshi yes/no
  const byBook = new Map<
    string,
    { over?: BookQuote; under?: BookQuote; yes?: BookQuote; no?: BookQuote }
  >();
  for (const q of quotes) {
    if (!byBook.has(q.book)) byBook.set(q.book, {});
    const entry = byBook.get(q.book)!;
    (entry as Record<string, BookQuote>)[q.side] = q;
  }

  const kalshi = byBook.get("kalshi");
  const sharpBooks = [...byBook.entries()]
    .filter(([b]) => b !== "kalshi")
    .sort((a, b) => a[0].localeCompare(b[0]));

  return (
    <div className="border border-[color:var(--border)] bg-[color:var(--bg-elevated)]">
      <div className="flex items-center justify-between border-b border-[color:var(--border)] px-5 py-2.5">
        <div className="flex items-baseline gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--accent)] dot-pulse" />
          <span className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--text)]">
            Live book breakdown
          </span>
        </div>
        <span className="text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
          {sharpBooks.length + (kalshi ? 1 : 0)} sources
        </span>
      </div>

      <div className="grid grid-cols-[1fr_120px_120px_120px_120px] gap-0 border-b border-[color:var(--border)] bg-[color:var(--bg-row)] px-5 py-2 text-[10px] uppercase tracking-[0.18em] text-[color:var(--text-muted)]">
        <div>Book</div>
        <div className="text-right">Over / Yes</div>
        <div className="text-right">Under / No</div>
        <div className="text-right">Devig Fair</div>
        <div className="text-right">Vig</div>
      </div>

      {/* Kalshi row first, highlighted */}
      {kalshi && (
        <BookRow
          name="kalshi"
          accent
          a={kalshi.yes}
          b={kalshi.no}
          aLabel="YES"
          bLabel="NO"
        />
      )}

      {sharpBooks.map(([book, entry]) => (
        <BookRow
          key={book}
          name={book}
          a={entry.over}
          b={entry.under}
          aLabel="OVER"
          bLabel="UNDER"
        />
      ))}

      {sharpBooks.length === 0 && !kalshi && (
        <div className="px-5 py-6 text-center text-[10px] uppercase tracking-[0.2em] text-[color:var(--text-muted)]">
          ─ no quotes yet ─
        </div>
      )}
    </div>
  );
}

function BookRow({
  name,
  a,
  b,
  aLabel,
  bLabel,
  accent,
}: {
  name: string;
  a?: BookQuote;
  b?: BookQuote;
  aLabel: string;
  bLabel: string;
  accent?: boolean;
}) {
  const aImplied = a ? Number(a.impliedProb) : 0;
  const bImplied = b ? Number(b.impliedProb) : 0;
  const total = aImplied + bImplied;
  const vig = total > 0 ? (total - 1) * 100 : 0;
  const fair = a && b ? devig(aImplied, bImplied) : null;

  return (
    <div
      className={`grid grid-cols-[1fr_120px_120px_120px_120px] gap-0 border-b border-[color:var(--border)] px-5 py-2.5 text-[12px] ${
        accent ? "bg-[rgba(0,255,157,0.04)]" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`chip ${accent ? "accent" : ""}`}
        >
          {name.replace(/_/g, " ")}
        </span>
        {accent && (
          <span className="text-[9px] uppercase tracking-[0.2em] text-[color:var(--accent)]">
            target
          </span>
        )}
      </div>

      <QuoteCell q={a} label={aLabel} />
      <QuoteCell q={b} label={bLabel} />

      <div className="num text-right text-[color:var(--text-dim)]">
        {fair !== null ? `${(fair * 100).toFixed(1)}%` : "—"}
      </div>

      <div
        className={`num text-right ${
          vig > 8
            ? "text-[color:var(--warn)]"
            : vig > 0
            ? "text-[color:var(--text-dim)]"
            : "text-[color:var(--text-muted)]"
        }`}
      >
        {vig > 0 ? `${vig.toFixed(1)}%` : "—"}
      </div>
    </div>
  );
}

function QuoteCell({ q, label }: { q?: BookQuote; label: string }) {
  if (!q)
    return (
      <div className="text-right text-[color:var(--text-muted)]">—</div>
    );
  const american = americanFromDecimal(Number(q.decimalOdds));
  const implied = (Number(q.impliedProb) * 100).toFixed(1);
  return (
    <div className="text-right">
      <div className="num text-[color:var(--text)]">{american}</div>
      <div className="num text-[10px] text-[color:var(--text-muted)]">
        {label} · {implied}%
      </div>
    </div>
  );
}
