"use client";

import Link from "next/link";
import type { Prices, Profile, UniverseRow } from "@/lib/companyTypes";
import { fmtBig, fmtDate, fmtMoney, fmtMult, fmtNum, fmtPct, toneClass } from "@/lib/companyFormat";
import PriceChart from "./PriceChart";
import { RangeBar } from "./Charts";
import { ErrorBox, Loading, Panel, StatGrid } from "./ui";
import { useJson } from "./useJson";

const n = (p: Profile, k: string) => (typeof p[k] === "number" ? (p[k] as number) : null);
const REC_LABEL: Record<string, string> = {
  strong_buy: "Strong Buy",
  buy: "Buy",
  hold: "Hold",
  underperform: "Underperform",
  sell: "Sell",
};

export default function OverviewTab({ p, peers }: { p: Profile; peers: UniverseRow[] }) {
  const prices = useJson<Prices>(`/api/company/${p.symbol}/prices`);
  const price = n(p, "currentPrice");
  const rec = typeof p.recommendationKey === "string" ? p.recommendationKey : null;
  const recTone = rec && ["strong_buy", "buy"].includes(rec) ? "text-primary border-primary" : rec && ["sell", "underperform"].includes(rec) ? "text-tertiary border-tertiary" : "text-[#ffcf66] border-[#ffcf66]";

  return (
    <div className="space-y-6">
      {prices.loading && <Loading what="price history" />}
      {prices.error && <ErrorBox msg={prices.error} />}
      {prices.data && <PriceChart prices={prices.data} />}

      <div className="grid lg:grid-cols-3 gap-6">
        <Panel title="Business">
          <p className="text-sm leading-relaxed text-on-surface/90 max-h-72 overflow-y-auto pr-2">{p.longBusinessSummary ?? "No description available."}</p>
          <div className="mt-4">
            <StatGrid
              items={[
                ["Sector", p.sector ?? "—"],
                ["Industry", p.industry ?? "—"],
                ["Employees", typeof p.fullTimeEmployees === "number" ? p.fullTimeEmployees.toLocaleString() : "—"],
                ["HQ", [p.city, p.state, p.country].filter(Boolean).join(", ") || "—"],
              ]}
            />
            {typeof p.website === "string" && p.website.startsWith("http") && (
              <a href={p.website} target="_blank" rel="noopener noreferrer" className="inline-block mt-3 text-xs text-primary hover:underline">
                {p.website.replace(/^https?:\/\//, "")} ↗
              </a>
            )}
          </div>
        </Panel>

        <Panel
          title="Key statistics"
          right={
            p.financialCurrency && p.financialCurrency !== p.currency ? (
              <span className="text-[10px] font-mono text-[#ffcf66]">statement figures in {p.financialCurrency}</span>
            ) : undefined
          }
        >
          <StatGrid
            items={[
              ["Market cap", fmtBig(n(p, "marketCap"))],
              ["Enterprise value", fmtBig(n(p, "enterpriseValue"))],
              ["Revenue (TTM)", fmtBig(n(p, "totalRevenue"))],
              ["Net income (TTM)", fmtBig(n(p, "netIncomeToCommon"))],
              ["Free cash flow (TTM)", fmtBig(n(p, "freeCashflowTtm") ?? n(p, "freeCashflow"))],
              ["EPS (TTM)", fmtMoney(n(p, "trailingEps"))],
              ["Gross margin", fmtPct(n(p, "grossMargins"))],
              ["Operating margin", fmtPct(n(p, "operatingMargins"))],
              ["Net margin", fmtPct(n(p, "profitMargins"))],
              ["ROE", fmtPct(n(p, "returnOnEquity"))],
              ["ROA", fmtPct(n(p, "returnOnAssets"))],
              ["Revenue growth (YoY)", <span key="rg" className={toneClass(n(p, "revenueGrowth"))}>{fmtPct(n(p, "revenueGrowth"), 1, true)}</span>],
              ["Cash", fmtBig(n(p, "totalCash"))],
              ["Debt", fmtBig(n(p, "totalDebt"))],
              ["Debt / equity", fmtNum(n(p, "debtToEquity") != null ? n(p, "debtToEquity")! / 100 : null, 2)],
              ["Current ratio", fmtNum(n(p, "currentRatio"), 2)],
            ]}
          />
        </Panel>

        <Panel title="Trading & analysts">
          <div className="space-y-5">
            <RangeBar label="52-week range" low={n(p, "fiftyTwoWeekLow")} high={n(p, "fiftyTwoWeekHigh")} value={price} format={(v) => fmtMoney(v)} />
            <RangeBar
              label={`Analyst targets (${p.numberOfAnalystOpinions ?? 0})`}
              low={n(p, "targetLowPrice")}
              high={n(p, "targetHighPrice")}
              value={price}
              mid={n(p, "targetMeanPrice")}
              format={(v) => fmtMoney(v)}
            />
            <div className="flex items-center gap-3">
              {rec && <span className={`border px-2 py-0.5 text-xs font-headline uppercase tracking-widest ${recTone}`}>{REC_LABEL[rec] ?? rec}</span>}
              {price && n(p, "targetMeanPrice") && (
                <span className="text-xs text-on-surface-muted">
                  Upside to mean target{" "}
                  <span className={`font-mono ${toneClass(n(p, "targetMeanPrice")! / price - 1)}`}>{fmtPct(n(p, "targetMeanPrice")! / price - 1, 1, true)}</span>
                </span>
              )}
            </div>
            <StatGrid
              items={[
                ["Beta", fmtNum(n(p, "beta"), 2)],
                ["50-day avg", fmtMoney(n(p, "fiftyDayAverage"))],
                ["200-day avg", fmtMoney(n(p, "twoHundredDayAverage"))],
                ["Avg volume", fmtBig(n(p, "averageVolume"), 1)],
                ["Dividend yield", fmtPct(n(p, "dividendYield"), 2)],
                ["Payout ratio", fmtPct(n(p, "payoutRatio"))],
                ["Ex-dividend", fmtDate(typeof p.exDividendDate === "string" ? p.exDividendDate : null)],
                ["Short % float", fmtPct(n(p, "shortPercentOfFloat"))],
                ["Insiders", fmtPct(n(p, "heldPercentInsiders"))],
                ["Institutions", fmtPct(n(p, "heldPercentInstitutions"))],
              ]}
            />
          </div>
        </Panel>
      </div>

      <Panel title={`Sector peers · ${p.sector ?? ""}`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] uppercase tracking-widest text-outline font-headline">
                {["Company", "Mkt cap", "YTD", "1Y", "P/E", "Fwd P/E", "P/S", "EV/EBITDA", "Net mgn", "ROE", "Rev gr."].map((h, i) => (
                  <th key={h} className={`px-3 py-2 font-medium ${i ? "text-right" : "text-left"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {peers.map((r) => (
                <tr key={r.symbol} className={`border-t border-outline-dim/25 ${r.symbol === p.symbol ? "bg-primary/5" : "hover:bg-surface-container"}`}>
                  <td className="px-3 py-1.5">
                    <Link href={`/company/${r.symbol}`} className="font-headline font-bold text-primary">{r.symbol}</Link>
                    <span className="ml-2 text-[11px] text-on-surface-muted">{r.name}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmtBig(r.marketCap)}</td>
                  <td className={`px-3 py-1.5 text-right font-mono ${toneClass(r.chgYtd)}`}>{fmtPct(r.chgYtd, 1, true)}</td>
                  <td className={`px-3 py-1.5 text-right font-mono ${toneClass(r.chg1y)}`}>{fmtPct(r.chg1y, 1, true)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmtMult(r.trailingPE)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmtMult(r.forwardPE)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmtMult(r.priceToSales)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmtMult(r.evToEbitda)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmtPct(r.profitMargin)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{fmtPct(r.roe)}</td>
                  <td className={`px-3 py-1.5 text-right font-mono ${toneClass(r.revenueGrowth)}`}>{fmtPct(r.revenueGrowth, 1, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
