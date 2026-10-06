"use client";

import Link from "next/link";
import { use, useState } from "react";
import type { Profile, Universe } from "@/lib/companyTypes";
import { fmtBig, fmtMoney, fmtNum, fmtPct, toneClass } from "@/lib/companyFormat";
import Header from "../_components/Header";
import OverviewTab from "../_components/OverviewTab";
import FinancialsTab from "../_components/FinancialsTab";
import ValuationTab from "../_components/ValuationTab";
import EarningsTab from "../_components/EarningsTab";
import NewsTab from "../_components/NewsTab";
import { ErrorBox, Loading } from "../_components/ui";
import { useJson } from "../_components/useJson";

const TABS = ["Overview", "Financials", "Valuation", "Earnings", "News"] as const;
type Tab = (typeof TABS)[number];

export default function CompanyPage({ params }: { params: Promise<{ symbol: string }> }) {
  const symbol = decodeURIComponent(use(params).symbol).toUpperCase();
  const [tab, setTab] = useState<Tab>("Overview");
  const profile = useJson<Profile>(`/api/company/${encodeURIComponent(symbol)}/profile`);
  const uni = useJson<Universe>("/api/company");

  const p = profile.data;
  const rows = uni.data?.rows ?? [];
  const me = rows.find((r) => r.symbol === symbol);
  const peers = rows
    .filter((r) => p && r.sector === p.sector)
    .sort((a, b) => (b.marketCap ?? 0) - (a.marketCap ?? 0));

  const price = typeof p?.currentPrice === "number" ? p.currentPrice : me?.price ?? null;
  const chg = me?.chg1d ?? null;

  return (
    <div className="min-h-screen">
      <Header />
      <main className="max-w-[1500px] mx-auto px-6 py-6 space-y-6">
        <Link href="/company" className="text-xs text-on-surface-muted hover:text-primary">← Universe</Link>

        {profile.loading && <Loading what={symbol} />}
        {profile.error && <ErrorBox msg={`${symbol}: ${profile.error}`} />}

        {p && (
          <>
            <div className="flex flex-wrap items-end justify-between gap-6">
              <div>
                <div className="flex items-baseline gap-3">
                  <h1 className="font-headline text-4xl font-black">{symbol}</h1>
                  <span className="text-lg text-on-surface-muted">{p.longName ?? p.shortName}</span>
                </div>
                <div className="text-xs text-outline mt-1">
                  {[p.exchange, p.sector, p.industry].filter(Boolean).join(" · ")}
                </div>
              </div>
              <div className="flex items-end gap-8">
                <div className="text-right">
                  <div className="font-mono text-4xl">{fmtMoney(price)}</div>
                  <div className={`font-mono text-sm ${toneClass(chg)}`}>
                    {fmtPct(chg, 2, true)} today
                    {me && <span className="text-outline"> · YTD </span>}
                    {me && <span className={toneClass(me.chgYtd)}>{fmtPct(me.chgYtd, 1, true)}</span>}
                  </div>
                </div>
                <div className="hidden md:grid grid-cols-4 gap-px bg-outline-dim/30 text-xs">
                  {[
                    ["Mkt cap", fmtBig(p.marketCap as number)],
                    ["P/E", fmtNum(p.trailingPE as number, 1)],
                    ["Fwd P/E", fmtNum(p.forwardPE as number, 1)],
                    ["Div yld", fmtPct(p.dividendYield as number, 2)],
                  ].map(([k, v]) => (
                    <div key={k} className="bg-surface-low px-3 py-2">
                      <div className="text-[10px] uppercase tracking-widest text-outline font-headline">{k}</div>
                      <div className="font-mono">{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <nav className="flex gap-1 border-b border-outline-dim/40">
              {TABS.map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`px-4 py-2 text-sm font-headline uppercase tracking-widest border-b-2 -mb-px ${
                    tab === t ? "border-primary text-primary" : "border-transparent text-on-surface-muted hover:text-on-surface"
                  }`}
                >
                  {t}
                </button>
              ))}
            </nav>

            {tab === "Overview" && <OverviewTab p={p} peers={peers} />}
            {tab === "Financials" && <FinancialsTab symbol={symbol} />}
            {tab === "Valuation" && <ValuationTab p={p} all={rows} />}
            {tab === "Earnings" && <EarningsTab symbol={symbol} />}
            {tab === "News" && <NewsTab symbol={symbol} />}

            <p className="text-[11px] text-outline">Data: Yahoo Finance via yfinance, delayed and unofficial — for research only, not investment advice.</p>
          </>
        )}
      </main>
    </div>
  );
}
