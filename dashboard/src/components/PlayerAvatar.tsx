"use client";

import { useState } from "react";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Deterministic hue from the name so every player gets a stable, distinct
// gradient (premium look, never a broken-image box).
function hueOf(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return h;
}

export function PlayerAvatar({
  name,
  photoUrl,
  size = 40,
  highlight = false,
}: {
  name: string;
  photoUrl?: string | null;
  size?: number;
  highlight?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const h = hueOf(name);
  const showPhoto = Boolean(photoUrl) && !failed;

  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-xl"
      style={{
        width: size,
        height: size,
        background: showPhoto
          ? `radial-gradient(circle at 50% 28%, hsl(${h} 48% 24%), hsl(${h} 42% 9%))`
          : `linear-gradient(145deg, hsl(${h} 55% 34%), hsl(${(h + 42) % 360} 52% 17%))`,
        boxShadow: highlight
          ? "0 0 0 1px var(--accent), 0 0 14px -2px var(--accent)"
          : "0 0 0 1px var(--border-bright)",
      }}
    >
      {showPhoto ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={photoUrl as string}
          alt={name}
          width={size}
          height={size}
          loading="lazy"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover object-top"
          style={{ filter: "saturate(1.06) contrast(1.03)" }}
        />
      ) : (
        <div
          className="flex h-full w-full items-center justify-center font-semibold tracking-wide text-white/90"
          style={{ fontSize: Math.round(size * 0.34) }}
        >
          {initials(name)}
        </div>
      )}
      {/* subtle inner vignette for depth on photos */}
      {showPhoto && (
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            boxShadow: "inset 0 -8px 14px -8px rgba(0,0,0,0.65)",
          }}
        />
      )}
    </div>
  );
}
