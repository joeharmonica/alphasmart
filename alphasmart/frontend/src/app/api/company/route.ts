import { NextRequest, NextResponse } from "next/server";
import { runCompany } from "@/lib/company";

export async function GET(req: NextRequest) {
  const refresh = req.nextUrl.searchParams.get("refresh") === "1";
  try {
    const data = await runCompany(["universe", ...(refresh ? ["--refresh"] : [])], 180_000);
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
