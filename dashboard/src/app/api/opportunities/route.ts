import { NextResponse } from "next/server";
import { getLatestOpportunities } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const minEv = Number(url.searchParams.get("minEv") ?? "0.01");
  const limit = Number(url.searchParams.get("limit") ?? "100");
  const opps = await getLatestOpportunities(minEv, limit);
  return NextResponse.json({ opportunities: opps, generatedAt: new Date().toISOString() });
}
