"use client";

import { useState } from "react";
import type { Financials, Statement } from "@/lib/companyTypes";
import { fmtBig, fmtMoney, fmtPct, isNum, toneClass } from "@/lib/companyFormat";
import { BarChart, LineChart } from "./Charts";
import { ErrorBox, Loading, Panel, Toggle } from "./ui";
import { useJson } from "./useJson";

const FREQS = ["annual", "quarterly"] as const;
const STMTS = ["income", "balance", "cashflow"] as const;
const STMT_LABEL = { income: "Income statement", balance: "Balance sheet", cashflow: "Cash flow" };

// Rows where an increase is unfavourable — colour their change inversely.
const LOWER_IS_BETTER = new Set([
  "Cost of Revenue", "R&D", "SG&A", "Interest Expense", "Tax", "Diluted Shares",
  "Total Debt", "Total Liabilities", "Total Current Liabilities", "Net Debt",
  "Shares Outstanding", "Stock-Based Comp",
]);

const row = (s: Statement, label: string) => s.rows.find((r) => r.label === label)?.values ?? s.periods.map(() => null);
const ratio = (a: (number | null)[], b: (number | null)[]) => a.map((v, i) => (isNum(v) && isNum(b[i]) && b[i] !== 0 ? v / b[i]! : null));

function periodLabel(p: string, freq: (typeof FREQS)[number]) {
  const d = new Date(p + "T00:00:00Z");
  return freq === "annual" ? `FY${String(d.getUTCFullYear()).slice(2)}` : `${d.toLocaleString("en-US", { month: "short", timeZone: "UTC" })} ${String(d.getUTCFullYear()).slice(2)}`;
}

export default function FinancialsTab({ symbol }: { symbol: string }) {
  const { data, error, loading } = useJson<Financials>(`/api/company/${symbol}/financials`);
  const [freq, setFreq] = useState<(typeof FREQS)[number]>("annual");
  const [stmt, setStmt] = useState<(typeof STMTS)[number]>("income");

  if (loading) return <Loading what="financial statements" />;
  if (error) return <ErrorBox msg={error} />;
  if (!data) return null;

  const f = data[freq];
  const labels = f.income.periods.map((p) => periodLabel(p, freq));
  const rev = row(f.income, "Revenue");
  const ni = row(f.income, "Net Income");
  const gp = row(f.income, "Gross Profit");
  const op = row(f.income, "Operating Income");
  // cash-flow periods can differ from income periods; align by date
  const align = (s: Statement, label: string) => {
    const m = new Map(s.periods.map((p, i) => [p, row(s, label)[i]]));
    return f.income.periods.map((p) => m.get(p) ?? null);
  };
  const ocf = align(f.cashflow, "Operating Cash Flow");
  const fcf = align(f.cashflow, "Free Cash Flow");
  const eps = row(f.income, "Diluted EPS");
  const shares = row(f.income, "Diluted Shares");
  const cash = align(f.balance, "Cash & Short-Term Inv.");
  const debt = align(f.balance, "Total Debt");

  const big = (v: number) => fmtBig(v, 1);
  const pct = (v: number) => fmtPct(v, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Toggle value={freq} options={FREQS} onChange={setFreq} />
        <span className="text-[11px] text-outline">
          {freq === "annual" ? "Last 4 fiscal years" : "Last 5 quarters"} as reported by Yahoo Finance · {data.currency}
          {data.currency !== data.tradingCurrency && ` (shares trade in ${data.tradingCurrency})`}
        </span>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <BarChart title="Revenue & net income" labels={labels} format={big} series={[{ name: "Revenue", values: rev }, { name: "Net income", values: ni, color: "#7aa2ff" }]} />
        <BarChart title="Operating vs free cash flow" labels={labels} format={big} series={[{ name: "Op. cash flow", values: ocf, color: "#5fd4e8" }, { name: "Free cash flow", values: fcf, color: "#00ffb2" }]} />
        <LineChart
          title="Margins"
          labels={labels}
          format={pct}
          series={[
            { name: "Gross", values: ratio(gp, rev) },
            { name: "Operating", values: ratio(op, rev), color: "#ffcf66" },
            { name: "Net", values: ratio(ni, rev), color: "#7aa2ff" },
            { name: "FCF", values: ratio(fcf, rev), color: "#c792ea" },
          ]}
        />
        <BarChart title="Cash vs total debt" labels={labels} format={big} series={[{ name: "Cash & ST inv.", values: cash, color: "#00ffb2" }, { name: "Total debt", values: debt, color: "#ffb3ac" }]} />
        <BarChart title="Diluted EPS" labels={labels} format={(v) => fmtMoney(v)} series={[{ name: "EPS", values: eps, color: "#ffcf66" }]} />
        <BarChart title="Diluted shares (buybacks shrink this)" labels={labels} format={(v) => fmtBig(v, 2)} series={[{ name: "Shares", values: shares, color: "#83958a" }]} />
      </div>

      <Panel title={STMT_LABEL[stmt]} right={<Toggle value={stmt} options={STMTS} onChange={setStmt} />}>
        <StatementTable s={f[stmt]} freq={freq} />
      </Panel>
    </div>
  );
}

function StatementTable({ s, freq }: { s: Statement; freq: (typeof FREQS)[number] }) {
  if (!s.periods.length) return <div className="text-sm text-outline">Not reported.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-widest text-outline font-headline">
            <th className="text-left px-3 py-2 font-medium">Line item</th>
            {s.periods.map((p) => (
              <th key={p} className="text-right px-3 py-2 font-medium">{periodLabel(p, freq)}</th>
            ))}
            <th className="text-right px-3 py-2 font-medium">Δ last</th>
          </tr>
        </thead>
        <tbody>
          {s.rows.map((r) => {
            const vals = r.values;
            const last = vals[vals.length - 1];
            const prev = vals[vals.length - 2];
            const chg = isNum(last) && isNum(prev) && prev !== 0 ? (last - prev) / Math.abs(prev) : null;
            const perShare = r.label.includes("EPS");
            return (
              <tr key={r.label} className="border-t border-outline-dim/25 hover:bg-surface-container">
                <td className="px-3 py-1.5 text-on-surface-muted">{r.label}</td>
                {vals.map((v, i) => (
                  <td key={i} className={`px-3 py-1.5 text-right font-mono ${isNum(v) && v < 0 ? "text-tertiary" : ""}`}>
                    {perShare ? fmtMoney(v) : fmtBig(v)}
                  </td>
                ))}
                <td className={`px-3 py-1.5 text-right font-mono ${toneClass(isNum(chg) && LOWER_IS_BETTER.has(r.label) ? -chg : chg)}`}>{fmtPct(chg, 1, true)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
