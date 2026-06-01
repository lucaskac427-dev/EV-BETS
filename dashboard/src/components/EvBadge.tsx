import { evColor, formatEvPct } from "@/lib/format";

export function EvBadge({ ev }: { ev: number }) {
  return (
    <span className={`font-mono tabular-nums ${evColor(ev)}`}>
      {formatEvPct(ev)}
    </span>
  );
}
