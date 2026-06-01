import { NextResponse } from "next/server";

import { ensureFreshLiveOdds } from "@/lib/liveOdds";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const force = new URL(req.url).searchParams.get("force") === "1";
  return NextResponse.json(await ensureFreshLiveOdds(force));
}
