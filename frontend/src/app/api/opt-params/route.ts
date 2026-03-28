import { runPython } from "@/lib/python";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

/** GET /api/opt-params — return full optimized_params.json store */
export async function GET() {
  try {
    const data = await runPython(["load_opt_params"]);
    return Response.json(data);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json({ error: msg }, { status: 500 });
  }
}

/** POST /api/opt-params — save one optimized result to the persistent store */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json() as {
      strategy: string;
      symbol: string;
      timeframe: string;
      objective: string;
      params: Record<string, number>;
      sharpe: number;
      cagr: number;
      max_drawdown: number;
      gate2_pass: boolean;
    };

    await runPython([
      "save_opt_params",
      body.strategy,
      body.symbol,
      body.timeframe,
      body.objective,
      JSON.stringify(body.params),
      String(body.sharpe),
      String(body.cagr),
      String(body.max_drawdown),
      String(body.gate2_pass),
    ]);

    return Response.json({ ok: true });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json({ error: msg }, { status: 500 });
  }
}
