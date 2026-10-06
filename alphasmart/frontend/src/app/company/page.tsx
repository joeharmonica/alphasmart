"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Universe, UniverseRow } from "@/lib/companyTypes";
import { fmtBig, fmtMoney, fmtMult, fmtNum, fmtPct, median, toneClass } from "@/lib/companyFormat";
import Header from "./_components/Header";
import MarketMap from "./_components/MarketMap";
import { Sparkline } from "./_components/Charts";
import { useJson } from "./_components/useJson";

type Col = {
  key: keyof UniverseRow;
  label: string;
  fmt: (r: UniverseRow) => React.ReactNode;
  num?: boolean;
};

function signedPct(v: number | null) {
  return <span className={toneClass(v)}>{fmtPct(v, 1, true)}</span>;
}

const COLS: Col[] = [
  { key: "price", label: "Price", fmt: (r) => fmtMoney(r.price), num: true },
  { key: "chg1d", label: "1D", fmt: (r) => signedPct(r.chg1d), num: true },
  { key: "chg1m", label: "1M", fmt: (r) => signedPct(r.chg1m), num: true },
  { key: "chgYtd", label: "YTD", fmt: (r) => signedPct(r.chgYtd), num: true },
  { key: "chg1y", label: "1Y", fmt: (r) => signedPct(r.chg1y), num: true },
  { key: "marketCap", label: "Mkt Cap", fmt: (r) => fmtBig(r.marketCap), num: true },
  { key: "trailingPE", label: "P/E", fmt: (r) => fmtMult(r.trailingPE), num: true },
  { key: "forwardPE", label: "Fwd P/E", fmt: (r) => fmtMult(r.forwardPE), num: true },
  { key: "priceToSales", label: "P/S", fmt: (r) => fmtMult(r.priceToSales), num: true },
  { key: "evToEbitda", label: "EV/EBITDA", fmt: (r) => fmtMult(r.evToEbitda), num: true },
  { key: "profitMargin", label: "Net Mgn", fmt: (r) => fmtPct(r.profitMargin), num: true },
  { key: "roe", label: "ROE", fmt: (r) => fmtPct(r.roe), num: true },
  { key: "revenueGrowth", label: "Rev Gr.", fmt: (r) => signedPct(r.revenueGrowth), num: true },
  { key: "dividendYield", label: "Div Yld", fmt: (r) => fmtPct(r.dividendYield, 2), num: true },
];

export default function UniversePage() {
  const { data, error, loading } = useJson<Universe>("/api/company");
  const [q, setQ] = useState("");
  const [sector, setSector] = useState("All");
  const [sort, setSort] = useState<{ key: keyof UniverseRow; dir: 1 | -1 }>({ key: "marketCap", dir: -1 });

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const sectors = useMemo(() => ["All", ...[...new Set(rows.map((r) => r.sector ?? "Other"))].sort()], [rows]);

  const view = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = rows.filter(
      (r) =>
        (sector === "All" || (r.sector ?? "Other") === sector) &&
        (!needle || r.symbol.toLowerCase().includes(needle) || r.name.toLowerCase().includes(needle) || (r.industry ?? "").toLowerCase().includes(needle)),
    );
    return [...filtered].sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
    });
  }, [rows, q, sector, sort]);

  const breadth = useMemo(() => {
    const up = rows.filter((r) => (r.chg1d ?? 0) > 0).length;
    return {
      up,
      down: rows.filter((r) => (r.chg1d ?? 0) < 0).length,
      medPe: median(rows.map((r) => r.trailingPE)),
      medYtd: median(rows.map((r) => r.chgYtd)),
      cap: rows.reduce((a, r) => a + (r.marketCap ?? 0), 0),
    };
  }, [rows]);

  return (
    <div className="min-h-screen">
      <Header />
      <main className="max-w-[1500px] mx-auto px-6 py-6 space-y-6">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="font-headline text-3xl font-bold">Research Universe</h1>
            <p className="text-on-surface-muted text-sm">
              {rows.length || 57} large caps from the Trader universe
              {data && <> · data as of {new Date(data.asOf).toLocaleString()}</>}
            </p>
          </div>
          {data && (
            <div className="grid grid-cols-4 gap-px bg-outline-dim/30 text-xs">
              {[
                ["Advancers / decliners", `${breadth.up} / ${breadth.down}`],
                ["Median YTD", fmtPct(breadth.medYtd, 1, true)],
                ["Median P/E", fmtNum(breadth.medPe, 1)],
                ["Total mkt cap", `$${fmtBig(breadth.cap)}`],
              ].map(([k, v]) => (
                <div key={k} className="bg-surface-low px-4 py-2">
                  <div className="text-[10px] uppercase tracking-widest text-outline font-headline">{k}</div>
                  <div className="font-mono text-base">{v}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {loading && <div className="text-on-surface-muted text-sm py-16 text-center">Loading universe (first load fetches 57 companies, ~10–60s)…</div>}
        {error && <div className="text-error text-sm border border-error-container p-4">Failed to load universe: {error}</div>}

        {data && (
          <>
            <MarketMap rows={rows} />

            <div className="bg-surface-low border border-outline-dim/40">
              <div className="flex flex-wrap items-center gap-3 p-3 border-b border-outline-dim/40">
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Filter by ticker, name, industry…"
                  className="w-72 bg-surface-container border border-outline-dim/60 px-3 py-1.5 text-sm placeholder:text-outline focus:outline-none focus:border-primary"
                />
                <div className="flex flex-wrap gap-1">
                  {sectors.map((s) => (
                    <button
                      key={s}
                      onClick={() => setSector(s)}
                      className={`px-2.5 py-1 text-[11px] border ${sector === s ? "border-primary text-primary bg-primary/10" : "border-outline-dim/60 text-on-surface-muted hover:text-on-surface"}`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
                <span className="ml-auto text-xs text-outline font-mono">{view.length} shown</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-widest text-outline font-headline">
                      <Th label="Company" k="symbol" sort={sort} setSort={setSort} left />
                      <th className="px-3 py-2 text-left font-medium">3M</th>
                      {COLS.map((c) => (
                        <Th key={c.key} label={c.label} k={c.key} sort={sort} setSort={setSort} />
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {view.map((r) => (
                      <tr key={r.symbol} className="border-t border-outline-dim/25 hover:bg-surface-container">
                        <td className="px-3 py-2">
                          <Link href={`/company/${r.symbol}`} className="block">
                            <span className="font-headline font-bold text-primary">{r.symbol}</span>
                            <span className="block text-[11px] text-on-surface-muted truncate max-w-[220px]">{r.name}</span>
                          </Link>
                        </td>
                        <td className="px-3 py-2"><Sparkline values={r.spark} /></td>
                        {COLS.map((c) => (
                          <td key={c.key} className="px-3 py-2 text-right font-mono text-[13px] whitespace-nowrap">{c.fmt(r)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
        <p className="text-[11px] text-outline">Data: Yahoo Finance via yfinance, delayed and unofficial — for research only, not investment advice.</p>
      </main>
    </div>
  );
}

function Th({
  label,
  k,
  sort,
  setSort,
  left,
}: {
  label: string;
  k: keyof UniverseRow;
  sort: { key: keyof UniverseRow; dir: 1 | -1 };
  setSort: (s: { key: keyof UniverseRow; dir: 1 | -1 }) => void;
  left?: boolean;
}) {
  const active = sort.key === k;
  return (
    <th className={`px-3 py-2 font-medium ${left ? "text-left" : "text-right"}`}>
      <button
        className={`uppercase tracking-widest ${active ? "text-primary" : "hover:text-on-surface"}`}
        onClick={() => setSort({ key: k, dir: active ? (sort.dir === 1 ? -1 : 1) : -1 })}
      >
        {label}
        {active ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );
}
