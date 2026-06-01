import { NextResponse } from "next/server";
import { getBookBreakdown, getOpportunityById } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const numericId = Number(id);
  if (!Number.isFinite(numericId)) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  const opp = await getOpportunityById(numericId);
  if (!opp) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const books = await getBookBreakdown(opp.marketId);
  return NextResponse.json({ books, generatedAt: new Date().toISOString() });
}
