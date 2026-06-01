import { NextResponse } from "next/server";
import { getHealth } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const sources = await getHealth();
  return NextResponse.json({ sources, checkedAt: new Date().toISOString() });
}
