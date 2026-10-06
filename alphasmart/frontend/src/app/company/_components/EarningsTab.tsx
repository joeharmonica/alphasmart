"use client";

import { useState } from "react";
import type { Earnings, Rec } from "@/lib/companyTypes";
import { fmtBig, fmtDate, fmtMoney, fmtPct, isNum, toneClass } from "@/lib/companyFormat";
import { BarChart } from "./Charts";
import { ErrorBox, Loading, Panel } from "./ui";
import { useJson } from "./useJson";

const PERIOD = { "0q": "Current qtr", "+1q": "Next qtr", "0y": "Current FY", "+1y": "Next FY" } as Record<string, string>;
const REC_KEYS = [
  ["strongBuy", "Strong buy", "#00ffb2"],
  ["buy", "Buy", "#00b37d"],
  ["hold", "Hold", "#ffcf66"],
  ["sell", "Sell", "#ff8a7f"],
  ["strongSell", "Strong sell", "#ff5449"],
] as const;

const num = (r: Rec, k: string) => (typeof r[k] === "number" ? (r[k] as number) : null);

export default function EarningsTab({ symbol }: { symbol: string }) {
  const { data, error, loading } = useJson<Earnings>(`/api/company/${symbol}/earnings`);
  const [now] = useState(() => Date.now());
  if (loading) return <Loading what="earnings" />;
  if (error) return <ErrorBox msg={error} />;
  if (!data) return null;

  const hist = data.history.slice(-12);
  const beats = hist.filter((h) => isNum(h.surprisePct) && h.surprisePct > 0).length;
  const avgSurprise = hist.length ? hist.reduce((a, h) => a + (h.surprisePct ?? 0), 0) / hist.length : null;
  const days = data.upcoming ? Math.ceil((new Date(data.upcoming.date).getTime() - now) / 86_400_000) : null;

  return (
    <div className="space-y-6">
      <div className="grid md:grid-cols-4 gap-px bg-outline-dim/30">
        {[
          ["Next report", data.upcoming ? fmtDate(data.upcoming.date) : "Not scheduled", days != null ? `in ${days} days` : ""],
          ["EPS consensus (next)", fmtMoney(data.upcoming?.epsEstimate), ""],
          ["Beat rate", hist.length ? `${beats} / ${hist.length}` : "—", "last 12 quarters"],
          ["Avg surprise", isNum(avgSurprise) ? `${avgSurprise > 0 ? "+" : ""}${avgSurprise.toFixed(1)}%` : "—", "vs consensus EPS"],
        ].map(([k, v, sub]) => (
          <div key={k} className="bg-surface-low px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-outline font-headline">{k}</div>
            <div className="font-mono text-xl">{v}</div>
            {sub && <div className="text-[11px] text-on-surface-muted">{sub}</div>}
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <BarChart
          title="EPS: estimate vs reported"
          labels={hist.map((h) => h.date.slice(0, 7))}
          format={(v) => fmtMoney(v)}
          series={[
            { name: "Estimate", values: hist.map((h) => h.epsEstimate), color: "#83958a" },
            { name: "Reported", values: hist.map((h) => h.epsActual), color: "#00ffb2" },
          ]}
        />
        <BarChart
          title="Surprise %"
          labels={hist.map((h) => h.date.slice(0, 7))}
          format={(v) => `${v.toFixed(1)}%`}
          series={[{ name: "Surprise", values: hist.map((h) => h.surprisePct), color: "#7aa2ff" }]}
        />
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <Panel title="Consensus estimates">
          <EstimateTable rows={data.epsEstimates} label="EPS" fmt={(v) => fmtMoney(v)} prior="yearAgoEps" />
          <div className="h-4" />
          <EstimateTable rows={data.revenueEstimates} label="Revenue" fmt={(v) => fmtBig(v)} prior="yearAgoRevenue" />
        </Panel>

        <Panel title="Analyst ratings (by month)">
          <div className="space-y-3">
            {data.recommendations.map((r) => {
              const total = REC_KEYS.reduce((a, [k]) => a + (num(r, k) ?? 0), 0) || 1;
              const period = String(r.period ?? "");
              return (
                <div key={period}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-on-surface-muted">{period === "0m" ? "This month" : `${period.replace("-", "")} ago`}</span>
                    <span className="font-mono text-outline">{total} analysts</span>
                  </div>
                  <div className="flex h-5">
                    {REC_KEYS.map(([k, label, color]) => {
                      const c = num(r, k) ?? 0;
                      return c ? (
                        <div key={k} title={`${label}: ${c}`} className="grid place-items-center text-[10px] font-mono text-surface" style={{ width: `${(c / total) * 100}%`, background: color }}>
                          {c / total > 0.06 ? c : ""}
                        </div>
                      ) : null;
                    })}
                  </div>
                </div>
              );
            })}
            <div className="flex flex-wrap gap-3 pt-1 text-[11px]">
              {REC_KEYS.map(([k, label, color]) => (
                <span key={k} className="flex items-center gap-1 text-on-surface-muted">
                  <span className="w-2 h-2 inline-block" style={{ background: color }} />
                  {label}
                </span>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="Earnings history">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-widest text-outline font-headline">
              {["Report date", "EPS estimate", "EPS reported", "Surprise"].map((h, i) => (
                <th key={h} className={`py-2 font-medium ${i ? "text-right" : "text-left"}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...data.history].reverse().map((h) => (
              <tr key={h.date} className="border-t border-outline-dim/25">
                <td className="py-1.5">{fmtDate(h.date)}</td>
                <td className="py-1.5 text-right font-mono">{fmtMoney(h.epsEstimate)}</td>
                <td className="py-1.5 text-right font-mono">{fmtMoney(h.epsActual)}</td>
                <td className={`py-1.5 text-right font-mono ${toneClass(h.surprisePct)}`}>
                  {isNum(h.surprisePct) ? `${h.surprisePct > 0 ? "+" : ""}${h.surprisePct.toFixed(2)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function EstimateTable({ rows, label, fmt, prior }: { rows: Rec[]; label: string; fmt: (v: number | null) => string; prior: string }) {
  if (!rows.length) return <div className="text-sm text-outline">No {label.toLowerCase()} estimates.</div>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-[10px] uppercase tracking-widest text-outline font-headline">
          {[label, "Avg", "Low", "High", "Year ago", "Growth", "#"].map((h, i) => (
            <th key={h} className={`py-1.5 font-medium ${i ? "text-right" : "text-left"}`}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={String(r.period)} className="border-t border-outline-dim/25">
            <td className="py-1.5 text-on-surface-muted">{PERIOD[String(r.period)] ?? r.period}</td>
            <td className="py-1.5 text-right font-mono">{fmt(num(r, "avg"))}</td>
            <td className="py-1.5 text-right font-mono text-on-surface-muted">{fmt(num(r, "low"))}</td>
            <td className="py-1.5 text-right font-mono text-on-surface-muted">{fmt(num(r, "high"))}</td>
            <td className="py-1.5 text-right font-mono text-on-surface-muted">{fmt(num(r, prior))}</td>
            <td className={`py-1.5 text-right font-mono ${toneClass(num(r, "growth"))}`}>{fmtPct(num(r, "growth"), 1, true)}</td>
            <td className="py-1.5 text-right font-mono text-outline">{num(r, "numberOfAnalysts") ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
