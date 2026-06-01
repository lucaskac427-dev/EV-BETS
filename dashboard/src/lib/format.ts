export function formatEvPct(ev: number): string {
  const sign = ev >= 0 ? "+" : "";
  return `${sign}${(ev * 100).toFixed(2)}%`;
}

export function formatDecimalAsAmerican(decimal: number): string {
  if (decimal >= 2.0) {
    return `+${Math.round((decimal - 1) * 100)}`;
  }
  return `-${Math.round(100 / (decimal - 1))}`;
}

export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function formatStartsAt(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function evColor(ev: number): string {
  if (ev >= 0.03) return "text-emerald-400";
  if (ev >= 0.01) return "text-amber-400";
  return "text-zinc-400";
}
