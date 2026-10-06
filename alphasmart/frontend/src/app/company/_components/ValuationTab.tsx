"use client";

import type { Financials, Profile, UniverseRow } from "@/lib/companyTypes";
import { fmtMoney, fmtNum, fmtPct, isNum, median, toneClass } from "@/lib/companyFormat";
import { BarChart, LineChart } from "./Charts";
import { ErrorBox, Loading, Panel, StatGrid } from "./ui";
import { useJson } from "./useJson";

const num = (p: Profile, k: string) => (typeof p[k] === "number" ? (p[k] as number) : null);
// Negative / absurd multiples aren't meaningful for medians or comparisons.
const pos = (v: number | null) => (isNum(v) && v > 0 && v <= 500 ? v : null);

export default function ValuationTab({ p, all }: { p: Profile; all: UniverseRow[] }) {
  const fin = useJson<Financials>(`/api/company/${p.symbol}/financials`);
  const sector = all.filter((r) => r.sector === p.sector && r.symbol !== p.symbol);

  const metrics: { label: string; key: keyof UniverseRow; v: number | null }[] = [
    { label: "P/E (TTM)", key: "trailingPE", v: pos(num(p, "trailingPE")) },
    { label: "Forward P/E", key: "forwardPE", v: pos(num(p, "forwardPE")) },
    { label: "Price / sales", key: "priceToSales", v: pos(num(p, "priceToSalesTrailing12Months")) },
    { label: "EV / EBITDA", key: "evToEbitda", v: pos(num(p, "enterpriseToEbitda")) },
  ];
  const med = (rows: UniverseRow[], k: keyof UniverseRow) => median(rows.map((r) => pos(r[k] as number | null)));

  const price = num(p, "currentPrice");
  const fwdEps = num(p, "forwardEps");
  const shares = num(p, "sharesOutstanding");
  // Statement figures are in financialCurrency; convert to the trading
  // currency before dividing by market cap / share price.
  const fx = num(p, "fxToTrading") ?? 1;
  const revRaw = num(p, "totalRevenue");
  const rev = isNum(revRaw) ? revRaw * fx : null;
  const mcap = num(p, "marketCap");
  const fcfRaw = num(p, "freeCashflowTtm");
  const fcf = isNum(fcfRaw) ? fcfRaw * fx : num(p, "freeCashflow");
  const secFpe = med(sector, "forwardPE");
  const secPs = med(sector, "priceToSales");

  const refs: [string, number | null, string][] = [
    ["Current price", price, "#83958a"],
    ["Analyst mean target", num(p, "targetMeanPrice"), "#ffcf66"],
    [`Sector-median fwd P/E (${fmtNum(secFpe, 1)}×) × fwd EPS`, isNum(secFpe) && isNum(fwdEps) && fwdEps > 0 ? secFpe * fwdEps : null, "#7aa2ff"],
    [`Sector-median P/S (${fmtNum(secPs, 1)}×) × sales/share`, isNum(secPs) && isNum(rev) && isNum(shares) && shares > 0 ? (secPs * rev) / shares : null, "#c792ea"],
  ];
  const refMax = Math.max(...refs.map((r) => r[1] ?? 0));

  const hist = fin.data?.ratioHistory ?? [];
  const hLabels = hist.map((h) => `FY${h.period.slice(2, 4)}`);

  return (
    <div className="space-y-6">
      <div className="grid lg:grid-cols-2 gap-6">
        <Panel title={`Multiples vs ${p.sector ?? "sector"} peers (${sector.length}) & universe`}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] uppercase tracking-widest text-outline font-headline">
                <th className="text-left py-2 font-medium">Multiple</th>
                <th className="text-right py-2 font-medium">{p.symbol}</th>
                <th className="text-right py-2 font-medium">Sector med.</th>
                <th className="text-right py-2 font-medium">Universe med.</th>
                <th className="text-right py-2 font-medium w-40">vs sector</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => {
                const s = med(sector, m.key);
                const u = med(all, m.key);
                const prem = isNum(m.v) && isNum(s) ? m.v / s - 1 : null;
                const w = isNum(prem) ? Math.min(50, Math.abs(prem) * 50) : 0;
                return (
                  <tr key={m.label} className="border-t border-outline-dim/25">
                    <td className="py-2 text-on-surface-muted">{m.label}</td>
                    <td className="py-2 text-right font-mono">{fmtNum(m.v, 1)}</td>
                    <td className="py-2 text-right font-mono text-on-surface-muted">{fmtNum(s, 1)}</td>
                    <td className="py-2 text-right font-mono text-on-surface-muted">{fmtNum(u, 1)}</td>
                    <td className="py-2 pl-4">
                      <div className="relative h-3 bg-surface-high">
                        <div className="absolute left-1/2 top-0 h-3 w-px bg-outline" />
                        {isNum(prem) && (
                          <div
                            className={`absolute top-0 h-3 ${prem > 0 ? "bg-tertiary/70" : "bg-primary/70"}`}
                            style={prem > 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
                          />
                        )}
                      </div>
                      <div className={`text-[10px] font-mono text-right ${isNum(prem) ? (prem > 0 ? "text-tertiary" : "text-primary") : "text-outline"}`}>
                        {isNum(prem) ? `${fmtPct(prem, 0, true)} ${prem > 0 ? "premium" : "discount"}` : "n/a"}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-3 text-[11px] text-outline">Red = trades at a premium to sector median, mint = discount. Negative-earnings multiples are excluded.</p>
        </Panel>

        <Panel title="Yields & other multiples">
          <StatGrid
            items={[
              ["Earnings yield", fmtPct(pos(num(p, "trailingPE")) ? 1 / num(p, "trailingPE")! : null, 2)],
              ["FCF yield (TTM)", fmtPct(isNum(fcf) && isNum(mcap) && mcap > 0 ? fcf / mcap : null, 2)],
              ["Dividend yield", fmtPct(num(p, "dividendYield"), 2)],
              ["PEG (TTM)", fmtNum(num(p, "trailingPegRatio") ?? num(p, "pegRatio"), 2)],
              ["Price / book", fmtNum(num(p, "priceToBook"), 2)],
              ["EV / revenue", fmtNum(num(p, "enterpriseToRevenue"), 2)],
              ["Forward EPS", fmtMoney(fwdEps)],
              ["Book value / share", fmtMoney(num(p, "bookValue"))],
            ]}
          />
          <div className="mt-5">
            <h4 className="font-headline text-[10px] uppercase tracking-widest text-outline mb-2">Reference prices (not a fair-value estimate)</h4>
            <div className="space-y-2">
              {refs.map(([label, v, color]) => (
                <div key={label}>
                  <div className="flex justify-between text-xs">
                    <span className="text-on-surface-muted">{label}</span>
                    <span className="font-mono">
                      {fmtMoney(v)}
                      {isNum(v) && isNum(price) && label !== "Current price" && (
                        <span className={`ml-2 ${toneClass(v / price - 1)}`}>{fmtPct(v / price - 1, 0, true)}</span>
                      )}
                    </span>
                  </div>
                  <div className="h-1.5 bg-surface-high mt-1">
                    {isNum(v) && refMax > 0 && <div className="h-1.5" style={{ width: `${(v / refMax) * 100}%`, background: color }} />}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      {fin.loading && <Loading what="valuation history" />}
      {fin.error && <ErrorBox msg={fin.error} />}
      {fin.data && (
        <div className="grid lg:grid-cols-2 gap-6">
          <LineChart
            title="Historical multiples (at fiscal year end)"
            labels={hLabels}
            format={(v) => `${v.toFixed(1)}×`}
            series={[
              { name: "P/E", values: hist.map((h) => h.pe) },
              { name: "P/S", values: hist.map((h) => h.ps), color: "#7aa2ff" },
              { name: "P/FCF", values: hist.map((h) => h.pfcf), color: "#c792ea" },
            ]}
          />
          <LineChart
            title="Returns on capital"
            labels={hLabels}
            format={(v) => fmtPct(v, 0)}
            series={[
              { name: "ROE", values: hist.map((h) => h.roe) },
              { name: "ROA", values: hist.map((h) => h.roa), color: "#ffcf66" },
            ]}
          />
          <BarChart
            title="Growth (YoY)"
            labels={hLabels}
            format={(v) => fmtPct(v, 0)}
            series={[
              { name: "Revenue", values: hist.map((h) => h.revenueGrowth) },
              { name: "EPS", values: hist.map((h) => h.epsGrowth), color: "#ffcf66" },
            ]}
          />
          <BarChart
            title="Leverage (debt / equity)"
            labels={hLabels}
            format={(v) => `${v.toFixed(2)}×`}
            series={[{ name: "D/E", values: hist.map((h) => h.debtToEquity), color: "#83958a" }]}
          />
        </div>
      )}
    </div>
  );
}
