import { runPython } from "@/lib/python";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const strategy = searchParams.get("strategy");
  const symbol = searchParams.get("symbol");
  const timeframe = searchParams.get("timeframe") ?? "1d";
  const objective = searchParams.get("objective") ?? "sharpe";

  if (!strategy || !symbol) {
    return Response.json(
      { error: "Missing required params: strategy, symbol" },
      { status: 400 }
    );
  }

  try {
    const data = await runPython(
      ["optimize", strategy, symbol, timeframe, objective],
      600_000 // 10 min — grid search + walk-forward can be slow
    );
    return Response.json(data);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json({ error: msg }, { status: 500 });
  }
}
