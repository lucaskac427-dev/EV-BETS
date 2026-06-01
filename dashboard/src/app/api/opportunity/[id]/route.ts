import { NextResponse } from "next/server";
import { getOpportunityById } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: Request,
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
  return NextResponse.json({ opportunity: opp });
}
