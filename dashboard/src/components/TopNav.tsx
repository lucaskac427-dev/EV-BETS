"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const DFS_TABS: {
  href: string;
  label: string;
  color: string;
  match: (p: string) => boolean;
}[] = [
  {
    href: "/dfs",
    label: "All DFS",
    color: "var(--accent)",
    match: (p) => p === "/dfs" || /^\/dfs\/\d/.test(p),
  },
  { href: "/dfs/book/prizepicks", label: "PrizePicks", color: "#a07cff", match: (p) => p === "/dfs/book/prizepicks" },
  { href: "/dfs/book/underdog", label: "Underdog", color: "#ff9d4d", match: (p) => p === "/dfs/book/underdog" },
  { href: "/dfs/book/sleeper", label: "Sleeper", color: "#33c4ff", match: (p) => p === "/dfs/book/sleeper" },
  { href: "/dfs/book/dk_pick6", label: "DK Pick 6", color: "#00e676", match: (p) => p === "/dfs/book/dk_pick6" },
];

export function TopNav() {
  const pathname = usePathname();
  const onKalshi = pathname === "/" || pathname.startsWith("/opportunity");

  return (
    <nav className="relative z-10 flex items-center gap-0.5 overflow-x-auto border-b border-[color:var(--hairline)] bg-[color:var(--bg)]/70 px-4 py-2 backdrop-blur">
      <NavTab href="/" active={onKalshi} label="Kalshi EV" color="var(--accent)" />
      <NavTab href="/cards" active={pathname.startsWith("/cards")} label="Bet Builder" color="var(--accent)" />
      <NavTab href="/bovada" active={pathname.startsWith("/bovada")} label="Bovada RR" color="#e0563a" />
      <span className="mx-1.5 h-5 w-px shrink-0 bg-[color:var(--border)]" />
      {DFS_TABS.map((t) => (
        <NavTab key={t.href} href={t.href} active={t.match(pathname)} label={t.label} color={t.color} />
      ))}
      <span className="mx-1.5 h-5 w-px shrink-0 bg-[color:var(--border)]" />
      <NavTab href="/track" active={pathname.startsWith("/track")} label="Track Record" color="var(--accent)" />
      <NavTab href="/buckets" active={pathname.startsWith("/buckets")} label="Buckets" color="var(--info)" />
      <NavTab href="/books" active={pathname.startsWith("/books")} label="Books ROI" color="var(--info)" />
    </nav>
  );
}

function NavTab({
  href,
  active,
  label,
  color,
}: {
  href: string;
  active: boolean;
  label: string;
  color: string;
}) {
  return (
    <Link
      href={href}
      data-active={active}
      className="pill shrink-0 whitespace-nowrap px-3.5 py-1.5 text-[12.5px] font-medium"
      style={{ color: active ? "var(--text)" : "var(--text-muted)" }}
    >
      <span className="flex items-center gap-1.5">
        <span
          className="h-1.5 w-1.5 rounded-full transition-all"
          style={{
            background: color,
            opacity: active ? 1 : 0.4,
            boxShadow: active ? `0 0 8px ${color}` : "none",
          }}
        />
        {label}
      </span>
    </Link>
  );
}
