"use client";

import { useState } from "react";
import type { News } from "@/lib/companyTypes";
import { fmtDate, timeAgo } from "@/lib/companyFormat";
import { ErrorBox, Loading } from "./ui";
import { useJson } from "./useJson";

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export default function NewsTab({ symbol }: { symbol: string }) {
  const { data, error, loading } = useJson<News>(`/api/company/${symbol}/news`);
  const [onlyRelevant, setOnlyRelevant] = useState(true);
  if (loading) return <Loading what="news" />;
  if (error) return <ErrorBox msg={error} />;

  const all = data?.items ?? [];
  const relevant = all.filter((n) => n.relevant);
  // If the filter would leave almost nothing, show everything instead.
  const filterOn = onlyRelevant && relevant.length >= 3;
  const items = filterOn ? relevant : all;

  if (!all.length) return <div className="text-sm text-outline py-10 text-center">No recent headlines.</div>;

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-xs text-on-surface-muted w-fit cursor-pointer">
        <input type="checkbox" checked={onlyRelevant} onChange={(e) => setOnlyRelevant(e.target.checked)} className="accent-[#00ffb2]" />
        Only stories mentioning {symbol} ({relevant.length} of {all.length})
        {onlyRelevant && !filterOn && <span className="text-outline">— too few matches, showing all</span>}
      </label>
      <ul className="divide-y divide-outline-dim/25 bg-surface-low border border-outline-dim/40">
        {items.map((n) => (
          <li key={n.link} className="p-4 hover:bg-surface-container">
            <a href={n.link} target="_blank" rel="noopener noreferrer" className="group block">
              <div className="flex items-center gap-2 text-[11px] text-outline font-mono mb-1">
                <span>{hostOf(n.link)}</span>
                <span>·</span>
                <span title={fmtDate(n.published)}>{timeAgo(n.published)}</span>
                {!filterOn && !n.relevant && <span className="text-outline/70">· market</span>}
              </div>
              <h4 className="font-headline font-semibold group-hover:text-primary">{n.title}</h4>
              {n.summary && <p className="text-sm text-on-surface-muted mt-1 line-clamp-2">{n.summary}</p>}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
