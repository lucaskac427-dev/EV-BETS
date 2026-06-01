import { sql } from "drizzle-orm";
import { db } from "./db";

export type OpportunityRow = {
  id: number;
  marketId: number;
  kalshiTicker: string;
  sport: string;
  playerName: string | null;
  statType: string | null;
  line: number | null;
  gameStartsAt: string;
  kalshiSide: string;
  kalshiDecimalOdds: number;
  consensusFairProb: number;
  projectionFairProb: number | null;
  blendedFairProb: number;
  evPct: number;
  kellyFraction: number | null;
  numSharpBooks: number;
  suspicious: boolean;
  scanTickAt: string;
};

export async function getLatestOpportunities(minEv = 0.01, limit = 100): Promise<OpportunityRow[]> {
  const rows = await db.execute(sql`
    SELECT DISTINCT ON (o.market_id)
      o.id, o.market_id, m.kalshi_ticker, m.sport, m.player_name, m.stat_type, m.line,
      m.game_starts_at, o.kalshi_side, o.kalshi_decimal_odds, o.consensus_fair_prob,
      o.projection_fair_prob, o.blended_fair_prob, o.ev_pct, o.kelly_fraction,
      o.num_sharp_books, o.suspicious, o.scan_tick_at
    FROM opportunities o
    JOIN markets m ON m.id = o.market_id
    WHERE o.ev_pct >= ${minEv} AND m.is_active = true
    ORDER BY o.market_id, o.scan_tick_at DESC
    LIMIT ${limit * 4}
  `);

  const opps: OpportunityRow[] = rows.map((r: any) => ({
    id: Number(r.id),
    marketId: Number(r.market_id),
    kalshiTicker: r.kalshi_ticker,
    sport: r.sport,
    playerName: r.player_name,
    statType: r.stat_type,
    line: r.line !== null ? Number(r.line) : null,
    gameStartsAt: r.game_starts_at,
    kalshiSide: r.kalshi_side,
    kalshiDecimalOdds: Number(r.kalshi_decimal_odds),
    consensusFairProb: Number(r.consensus_fair_prob),
    projectionFairProb: r.projection_fair_prob !== null ? Number(r.projection_fair_prob) : null,
    blendedFairProb: Number(r.blended_fair_prob),
    evPct: Number(r.ev_pct),
    kellyFraction: r.kelly_fraction !== null ? Number(r.kelly_fraction) : null,
    numSharpBooks: Number(r.num_sharp_books),
    suspicious: r.suspicious,
    scanTickAt: r.scan_tick_at,
  }));

  return opps.sort((a, b) => b.evPct - a.evPct).slice(0, limit);
}

export async function getOpportunityById(id: number): Promise<OpportunityRow | null> {
  const rows = await db.execute(sql`
    SELECT o.id, o.market_id, m.kalshi_ticker, m.sport, m.player_name, m.stat_type, m.line,
      m.game_starts_at, o.kalshi_side, o.kalshi_decimal_odds, o.consensus_fair_prob,
      o.projection_fair_prob, o.blended_fair_prob, o.ev_pct, o.kelly_fraction,
      o.num_sharp_books, o.suspicious, o.scan_tick_at
    FROM opportunities o
    JOIN markets m ON m.id = o.market_id
    WHERE o.id = ${id}
    LIMIT 1
  `);
  if (rows.length === 0) return null;
  const r: any = rows[0];
  return {
    id: Number(r.id),
    marketId: Number(r.market_id),
    kalshiTicker: r.kalshi_ticker,
    sport: r.sport,
    playerName: r.player_name,
    statType: r.stat_type,
    line: r.line !== null ? Number(r.line) : null,
    gameStartsAt: r.game_starts_at,
    kalshiSide: r.kalshi_side,
    kalshiDecimalOdds: Number(r.kalshi_decimal_odds),
    consensusFairProb: Number(r.consensus_fair_prob),
    projectionFairProb: r.projection_fair_prob !== null ? Number(r.projection_fair_prob) : null,
    blendedFairProb: Number(r.blended_fair_prob),
    evPct: Number(r.ev_pct),
    kellyFraction: r.kelly_fraction !== null ? Number(r.kelly_fraction) : null,
    numSharpBooks: Number(r.num_sharp_books),
    suspicious: r.suspicious,
    scanTickAt: r.scan_tick_at,
  };
}

export type HealthRow = { source: string; lastFetchAt: string | null };

export async function getHealth(): Promise<HealthRow[]> {
  const rows = await db.execute(sql`
    SELECT DISTINCT ON (source) source, created_at
    FROM scan_telemetry
    WHERE event_type = 'fetch_success'
    ORDER BY source, created_at DESC
  `);
  return rows.map((r: any) => ({ source: r.source, lastFetchAt: r.created_at }));
}

export type BookQuote = {
  book: string;
  side: string;
  decimalOdds: number;
  impliedProb: number;
  fetchedAt: string;
};

export async function getBookBreakdown(marketId: number): Promise<BookQuote[]> {
  const rows = await db.execute(sql`
    SELECT DISTINCT ON (book, side)
      book, side, decimal_odds, implied_prob, fetched_at
    FROM odds_snapshots
    WHERE market_id = ${marketId}
    ORDER BY book, side, fetched_at DESC
  `);
  return rows.map((r: any) => ({
    book: r.book,
    side: r.side,
    decimalOdds: Number(r.decimal_odds),
    impliedProb: Number(r.implied_prob),
    fetchedAt: r.fetched_at,
  }));
}

export type DfsEdgeRow = {
  id: number;
  dfsLineId: number;
  source: string;
  sport: string;
  playerName: string;
  team: string | null;
  statType: string;
  line: number;
  oddsType: string;
  gameStartsAt: string;
  pickSide: string;
  consensusFairProb: number;
  projectionFairProb: number | null;
  blendedFairProb: number | null;
  projectionSampleSize: number | null;
  breakevenPerLeg: number;
  edgePct: number;
  numSharpBooks: number;
  scanTickAt: string;
  photoUrl: string | null;
};

/** Attach NBA headshot URLs (resolved via player_game_logs.player_id) to rows.
 * Mutates in place. Soccer players have no free ID-based source -> stay null
 * and the UI renders a monogram avatar. */
async function attachNbaPhotos(
  rows: { sport: string; playerName: string; photoUrl: string | null }[]
): Promise<void> {
  const names = Array.from(
    new Set(rows.filter((r) => r.sport === "nba").map((r) => r.playerName))
  );
  if (names.length === 0) return;
  const res = await db.execute(sql`
    SELECT DISTINCT ON (player_name) player_name, player_id
    FROM player_game_logs WHERE player_name IN ${names}
  `);
  const byName = new Map<string, number>();
  for (const r of res as any[]) byName.set(r.player_name, Number(r.player_id));
  for (const row of rows) {
    const id = byName.get(row.playerName);
    if (row.sport === "nba" && id != null) {
      row.photoUrl = `https://cdn.nba.com/headshots/nba/latest/260x190/${id}.png`;
    }
  }
}

export async function getLatestDfsEdges(limit = 600): Promise<DfsEdgeRow[]> {
  const rows = await db.execute(sql`
    SELECT DISTINCT ON (o.dfs_line_id, o.pick_side)
      o.id, o.dfs_line_id, l.source, l.sport, l.player_name, l.team, l.stat_type, l.line,
      l.odds_type, l.game_starts_at, o.pick_side, o.consensus_fair_prob,
      o.projection_fair_prob, o.blended_fair_prob, o.projection_sample_size,
      o.breakeven_per_leg, o.edge_pct, o.num_sharp_books, o.scan_tick_at
    FROM dfs_opportunities o
    JOIN dfs_lines l ON l.id = o.dfs_line_id
    WHERE l.is_active = true
    ORDER BY o.dfs_line_id, o.pick_side, o.scan_tick_at DESC
    LIMIT ${limit * 4}
  `);
  const edges: DfsEdgeRow[] = rows.map((r: any) => ({
    id: Number(r.id),
    dfsLineId: Number(r.dfs_line_id),
    source: r.source,
    sport: r.sport,
    playerName: r.player_name,
    team: r.team,
    statType: r.stat_type,
    line: Number(r.line),
    oddsType: r.odds_type,
    gameStartsAt: r.game_starts_at,
    pickSide: r.pick_side,
    consensusFairProb: Number(r.consensus_fair_prob),
    projectionFairProb: r.projection_fair_prob != null ? Number(r.projection_fair_prob) : null,
    blendedFairProb: r.blended_fair_prob != null ? Number(r.blended_fair_prob) : null,
    projectionSampleSize: r.projection_sample_size != null ? Number(r.projection_sample_size) : null,
    breakevenPerLeg: Number(r.breakeven_per_leg),
    edgePct: Number(r.edge_pct),
    numSharpBooks: Number(r.num_sharp_books),
    scanTickAt: r.scan_tick_at,
    photoUrl: null,
  }));
  const top = edges.sort((a, b) => b.edgePct - a.edgePct).slice(0, limit);
  await attachNbaPhotos(top);
  return top;
}

export type DfsBookQuote = {
  book: string;
  over: string | null;
  under: string | null;
  fair_over: number | null;
};

export async function getDfsEdgeById(
  id: number
): Promise<(DfsEdgeRow & { bookBreakdown: DfsBookQuote[] }) | null> {
  const rows = await db.execute(sql`
    SELECT o.id, o.dfs_line_id, l.source, l.sport, l.player_name, l.team, l.stat_type, l.line,
      l.odds_type, l.game_starts_at, o.pick_side, o.consensus_fair_prob,
      o.breakeven_per_leg, o.edge_pct, o.num_sharp_books, o.scan_tick_at,
      o.book_breakdown
    FROM dfs_opportunities o JOIN dfs_lines l ON l.id = o.dfs_line_id
    WHERE o.id = ${id}
    LIMIT 1
  `);
  if (rows.length === 0) return null;
  const r: any = rows[0];
  let bookBreakdown: DfsBookQuote[] = [];
  if (r.book_breakdown) {
    try {
      bookBreakdown = typeof r.book_breakdown === "string"
        ? JSON.parse(r.book_breakdown)
        : r.book_breakdown;
    } catch {
      bookBreakdown = [];
    }
  }
  const result: any = {
    id: Number(r.id),
    dfsLineId: Number(r.dfs_line_id),
    source: r.source,
    sport: r.sport,
    playerName: r.player_name,
    team: r.team,
    statType: r.stat_type,
    line: Number(r.line),
    oddsType: r.odds_type,
    gameStartsAt: r.game_starts_at,
    pickSide: r.pick_side,
    consensusFairProb: Number(r.consensus_fair_prob),
    breakevenPerLeg: Number(r.breakeven_per_leg),
    edgePct: Number(r.edge_pct),
    numSharpBooks: Number(r.num_sharp_books),
    scanTickAt: r.scan_tick_at,
    photoUrl: null,
    bookBreakdown,
  };
  await attachNbaPhotos([result]);
  return result;
}

export type ScannerStats = {
  opportunityCount: number;
  topEvPct: number | null;
  booksOnline: { book: string; quoteCount: number }[];
  lastTickAt: string | null;
  lastTickLatencyMs: number | null;
};

export async function getScannerStats(): Promise<ScannerStats> {
  const oppsRow = (await db.execute(sql`
    SELECT COUNT(DISTINCT o.market_id) AS n, MAX(o.ev_pct) AS top
    FROM opportunities o
    JOIN markets m ON m.id = o.market_id
    WHERE m.is_active = true AND o.ev_pct >= 0.01
  `))[0] as any;

  const booksRows = await db.execute(sql`
    SELECT book, COUNT(*) AS n
    FROM odds_snapshots
    WHERE fetched_at > NOW() - INTERVAL '10 minutes'
    GROUP BY book
    ORDER BY n DESC
  `);

  const tickRow = (await db.execute(sql`
    SELECT created_at, latency_ms
    FROM scan_telemetry
    WHERE source = 'pipeline' AND event_type = 'tick_complete'
    ORDER BY created_at DESC
    LIMIT 1
  `))[0] as any;

  return {
    opportunityCount: Number(oppsRow?.n ?? 0),
    topEvPct: oppsRow?.top !== null && oppsRow?.top !== undefined ? Number(oppsRow.top) : null,
    booksOnline: booksRows.map((r: any) => ({
      book: r.book,
      quoteCount: Number(r.n),
    })),
    lastTickAt: tickRow?.created_at ?? null,
    lastTickLatencyMs: tickRow?.latency_ms !== undefined && tickRow?.latency_ms !== null
      ? Number(tickRow.latency_ms) : null,
  };
}

export type BookRoiRow = {
  book: string;
  nBets: number;
  winRate: number;
  roiPct: number;
  avgEdgePct: number;
};

/** Per-book ROI from the backtest (which books are soft vs sharp).
 * Populated by `python -m src.historical.book_roi`. */
export async function getBookRoi(sport = "basketball_nba"): Promise<BookRoiRow[]> {
  try {
    const rows = await db.execute(sql`
      SELECT book, n_bets, win_rate, roi_pct, avg_edge_pct
      FROM book_roi WHERE sport = ${sport}
      ORDER BY roi_pct DESC
    `);
    return (rows as any[]).map((r) => ({
      book: r.book,
      nBets: Number(r.n_bets),
      winRate: Number(r.win_rate),
      roiPct: Number(r.roi_pct),
      avgEdgePct: Number(r.avg_edge_pct),
    }));
  } catch {
    return [];
  }
}

export type TrackPick = {
  id: number;
  sport: string;
  source: string;
  betKind: string;
  playerName: string | null;
  team: string | null;
  statType: string;
  line: number;
  pickSide: string;
  fairProb: number | null;
  edgePct: number | null;
  numBooks: number | null;
  eventLabel: string | null;
  gameStartsAt: string | null;
  status: string;
  actualValue: number | null;
};

export type TrackRecord = {
  total: number;
  pending: number;
  hit: number;
  miss: number;
  push: number;
  hitRate: number;
  bySource: { source: string; hit: number; miss: number; pending: number }[];
  calibration: { bucket: string; predicted: number; actual: number; n: number }[];
  recent: TrackPick[];
};

export async function getTrackRecord(): Promise<TrackRecord> {
  const empty: TrackRecord = {
    total: 0, pending: 0, hit: 0, miss: 0, push: 0, hitRate: 0,
    bySource: [], calibration: [], recent: [],
  };
  try {
    const tot = (await db.execute(sql`
      SELECT count(*) total,
        count(*) FILTER (WHERE status='pending') pending,
        count(*) FILTER (WHERE status='hit') hit,
        count(*) FILTER (WHERE status='miss') miss,
        count(*) FILTER (WHERE status='push') push
      FROM tracked_picks`))[0] as any;
    const bySrc = await db.execute(sql`
      SELECT source,
        count(*) FILTER (WHERE status='hit') hit,
        count(*) FILTER (WHERE status='miss') miss,
        count(*) FILTER (WHERE status='pending') pending
      FROM tracked_picks GROUP BY source ORDER BY source`);
    // calibration: did our X% picks hit X%? (graded only)
    const calib = await db.execute(sql`
      SELECT width_bucket(fair_prob, 0.5, 1.0, 5) b,
        avg(fair_prob) predicted,
        avg(CASE WHEN status='hit' THEN 1.0 ELSE 0.0 END) actual,
        count(*) n
      FROM tracked_picks
      WHERE status IN ('hit','miss') AND fair_prob IS NOT NULL
      GROUP BY 1 ORDER BY 1`);
    const recent = await db.execute(sql`
      SELECT id, sport, source, bet_kind, player_name, team, stat_type, line,
        pick_side, fair_prob, edge_pct, num_books, event_label, game_starts_at,
        status, actual_value
      FROM tracked_picks ORDER BY recorded_at DESC, id DESC LIMIT 80`);
    const hit = Number(tot.hit), miss = Number(tot.miss);
    return {
      total: Number(tot.total), pending: Number(tot.pending), hit, miss,
      push: Number(tot.push), hitRate: hit + miss > 0 ? hit / (hit + miss) : 0,
      bySource: (bySrc as any[]).map((r) => ({
        source: r.source, hit: Number(r.hit), miss: Number(r.miss), pending: Number(r.pending),
      })),
      calibration: (calib as any[]).map((r) => ({
        bucket: `${Math.round(Number(r.predicted) * 100)}%`,
        predicted: Number(r.predicted), actual: Number(r.actual), n: Number(r.n),
      })),
      recent: (recent as any[]).map((r) => ({
        id: Number(r.id), sport: r.sport, source: r.source, betKind: r.bet_kind,
        playerName: r.player_name, team: r.team, statType: r.stat_type,
        line: Number(r.line), pickSide: r.pick_side,
        fairProb: r.fair_prob != null ? Number(r.fair_prob) : null,
        edgePct: r.edge_pct != null ? Number(r.edge_pct) : null,
        numBooks: r.num_books != null ? Number(r.num_books) : null,
        eventLabel: r.event_label, gameStartsAt: r.game_starts_at,
        status: r.status, actualValue: r.actual_value != null ? Number(r.actual_value) : null,
      })),
    };
  } catch {
    return empty;
  }
}
