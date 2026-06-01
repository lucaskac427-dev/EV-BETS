import { NextResponse } from "next/server";
import { getScannerStats } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const stats = await getScannerStats();
  return NextResponse.json({ ...stats, generatedAt: new Date().toISOString() });
}
