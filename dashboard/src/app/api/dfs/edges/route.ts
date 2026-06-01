import { NextResponse } from "next/server";
import { getLatestDfsEdges } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const edges = await getLatestDfsEdges();
  return NextResponse.json({ edges, generatedAt: new Date().toISOString() });
}
