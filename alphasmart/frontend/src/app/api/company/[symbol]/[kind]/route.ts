import { NextRequest, NextResponse } from "next/server";
import { COMPANY_KINDS, isValidSymbol, runCompany, type CompanyKind } from "@/lib/company";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ symbol: string; kind: string }> },
) {
  const { symbol: raw, kind } = await params;
  const symbol = raw.toUpperCase();
  if (!isValidSymbol(symbol)) {
    return NextResponse.json({ error: "invalid symbol" }, { status: 400 });
  }
  if (!COMPANY_KINDS.includes(kind as CompanyKind)) {
    return NextResponse.json({ error: "unknown data kind" }, { status: 404 });
  }
  const refresh = req.nextUrl.searchParams.get("refresh") === "1";
  try {
    const data = await runCompany([kind, symbol, ...(refresh ? ["--refresh"] : [])]);
    return NextResponse.json(data);
  } catch (err) {
    const msg = (err as Error).message;
    const status = msg.includes("not in the research universe") ? 404 : 502;
    return NextResponse.json({ error: msg }, { status });
  }
}
