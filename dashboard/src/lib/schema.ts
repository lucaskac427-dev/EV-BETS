/**
 * Drizzle schema mirroring the Alembic-managed Postgres schema.
 *
 * The Python scanner owns migrations. This file is hand-maintained to match
 * what Alembic produced. If migrations change, update this file in lockstep.
 *
 * Reference: scanner/alembic/versions/001_initial_schema.py
 */

import {
  bigint,
  boolean,
  index,
  integer,
  numeric,
  pgTable,
  smallint,
  text,
  timestamp,
  uniqueIndex,
} from "drizzle-orm/pg-core";

export const markets = pgTable("markets", {
  id: bigint("id", { mode: "number" }).primaryKey(),
  userId: bigint("user_id", { mode: "number" }).notNull().default(1),
  sport: text("sport").notNull(),
  kalshiTicker: text("kalshi_ticker").notNull().unique(),
  marketType: text("market_type").notNull(),
  playerName: text("player_name"),
  statType: text("stat_type"),
  line: numeric("line", { precision: 6, scale: 2 }),
  gameId: text("game_id").notNull(),
  gameStartsAt: timestamp("game_starts_at", { withTimezone: true }).notNull(),
  isActive: boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const opportunities = pgTable("opportunities", {
  id: bigint("id", { mode: "number" }).primaryKey(),
  userId: bigint("user_id", { mode: "number" }).notNull().default(1),
  marketId: bigint("market_id", { mode: "number" }).notNull(),
  kalshiSide: text("kalshi_side").notNull(),
  kalshiDecimalOdds: numeric("kalshi_decimal_odds", { precision: 10, scale: 4 }).notNull(),
  consensusFairProb: numeric("consensus_fair_prob", { precision: 7, scale: 6 }).notNull(),
  projectionFairProb: numeric("projection_fair_prob", { precision: 7, scale: 6 }),
  blendedFairProb: numeric("blended_fair_prob", { precision: 7, scale: 6 }).notNull(),
  evPct: numeric("ev_pct", { precision: 6, scale: 4 }).notNull(),
  kellyFraction: numeric("kelly_fraction", { precision: 6, scale: 4 }),
  numSharpBooks: smallint("num_sharp_books").notNull(),
  suspicious: boolean("suspicious").notNull().default(false),
  scanTickAt: timestamp("scan_tick_at", { withTimezone: true }).notNull().defaultNow(),
});

export const scanTelemetry = pgTable("scan_telemetry", {
  id: bigint("id", { mode: "number" }).primaryKey(),
  tickId: text("tick_id").notNull(),
  source: text("source").notNull(),
  eventType: text("event_type").notNull(),
  latencyMs: integer("latency_ms"),
  statusDetail: text("status_detail"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});
