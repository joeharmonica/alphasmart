import { runPython } from "@/lib/python";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const strategy = searchParams.get("strategy");
  const symbol = searchParams.get("symbol");
  const timeframe = searchParams.get("timeframe") ?? "1d";

  if (!strategy || !symbol) {
    return Response.json(
      { error: "Missing required params: strategy, symbol" },
      { status: 400 }
    );
  }

  try {
    const data = await runPython(
      ["insights", strategy, symbol, timeframe],
      60_000 // 1 min — backtest + LLM call
    );
    return Response.json(data);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json({ error: msg }, { status: 500 });
  }
}
