import { runPython } from "@/lib/python";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const strategy = searchParams.get("strategy");
  const symbol = searchParams.get("symbol");
  const timeframe = searchParams.get("timeframe") ?? "1d";
  const simType = searchParams.get("sim_type") ?? "block_bootstrap";
  const nSims = searchParams.get("n_sims") ?? "50";
  const capital = searchParams.get("capital") ?? "100000";

  if (!strategy || !symbol) {
    return Response.json(
      { error: "Missing required params: strategy, symbol" },
      { status: 400 }
    );
  }

  try {
    const data = await runPython(
      ["simulate", strategy, symbol, timeframe, simType, nSims, capital],
      300_000 // 5 min timeout for simulations
    );
    return Response.json(data);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json({ error: msg }, { status: 500 });
  }
}
