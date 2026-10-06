"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { UniverseRow } from "@/lib/companyTypes";
import { fmtPct, isNum } from "@/lib/companyFormat";

type Rect = { x: number; y: number; w: number; h: number };
type Item<T> = { value: number; data: T };

/** Squarified treemap layout (Bruls et al.) into a w×h box. */
function squarify<T>(items: Item<T>[], box: Rect): (Rect & { data: T })[] {
  const total = items.reduce((a, b) => a + b.value, 0);
  if (!total) return [];
  const scale = (box.w * box.h) / total;
  const nodes = items.map((it) => ({ area: it.value * scale, data: it.data })).sort((a, b) => b.area - a.area);
  const out: (Rect & { data: T })[] = [];
  let { x, y, w, h } = box;

  const worst = (row: number[], side: number) => {
    const s = row.reduce((a, b) => a + b, 0);
    const mx = Math.max(...row);
    const mn = Math.min(...row);
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };

  let row: typeof nodes = [];
  const layoutRow = () => {
    const s = row.reduce((a, b) => a + b.area, 0);
    if (w >= h) {
      const cw = s / h;
      let cy = y;
      for (const n of row) {
        const ch = n.area / cw;
        out.push({ x, y: cy, w: cw, h: ch, data: n.data });
        cy += ch;
      }
      x += cw;
      w -= cw;
    } else {
      const ch = s / w;
      let cx = x;
      for (const n of row) {
        const cw = n.area / ch;
        out.push({ x: cx, y, w: cw, h: ch, data: n.data });
        cx += cw;
      }
      y += ch;
      h -= ch;
    }
    row = [];
  };

  for (const n of nodes) {
    const side = Math.min(w, h);
    const areas = row.map((r) => r.area);
    if (!row.length || worst([...areas, n.area], side) <= worst(areas, side)) {
      row.push(n);
    } else {
      layoutRow();
      row.push(n);
    }
  }
  if (row.length) layoutRow();
  return out;
}

const METRICS = [
  ["chg1d", "1D", 0.03],
  ["chg1m", "1M", 0.12],
  ["chgYtd", "YTD", 0.4],
  ["chg1y", "1Y", 0.6],
] as const;
type MetricKey = (typeof METRICS)[number][0];

function heat(v: number | null, cap: number): string {
  if (!isNum(v)) return "#262a30";
  const t = Math.max(-1, Math.min(1, v / cap));
  // red (loss) <- neutral -> mint (gain)
  const [r, g, b] = t >= 0 ? [16 + (0 - 16) * t, 40 + (170 - 40) * t, 36 + (110 - 36) * t] : [40 + (150 - 40) * -t, 36 + (40 - 36) * -t, 40 + (45 - 40) * -t];
  return `rgb(${r | 0},${g | 0},${b | 0})`;
}

export default function MarketMap({ rows }: { rows: UniverseRow[] }) {
  const [metric, setMetric] = useState<MetricKey>("chg1d");
  const cap = METRICS.find((m) => m[0] === metric)![2];
  const W = 1200;
  const H = 520;

  const tiles = useMemo(() => {
    const bySector = new Map<string, UniverseRow[]>();
    for (const r of rows) {
      if (!isNum(r.marketCap)) continue;
      const k = r.sector ?? "Other";
      bySector.set(k, [...(bySector.get(k) ?? []), r]);
    }
    const sectors = squarify(
      [...bySector.entries()].map(([name, rs]) => ({ value: rs.reduce((a, r) => a + (r.marketCap ?? 0), 0), data: { name, rs } })),
      { x: 0, y: 0, w: W, h: H },
    );
    return sectors.map((s) => ({
      ...s,
      children: squarify(
        s.data.rs.map((r) => ({ value: r.marketCap!, data: r })),
        { x: s.x + 1, y: s.y + 16, w: Math.max(0, s.w - 2), h: Math.max(0, s.h - 17) },
      ),
    }));
  }, [rows]);

  return (
    <div className="bg-surface-low border border-outline-dim/40">
      <div className="flex items-center justify-between p-3 border-b border-outline-dim/40">
        <h3 className="font-headline text-xs uppercase tracking-widest text-on-surface-muted">Market map · size = market cap</h3>
        <div className="flex gap-1">
          {METRICS.map(([k, label]) => (
            <button
              key={k}
              onClick={() => setMetric(k)}
              className={`px-2.5 py-1 text-[11px] font-mono border ${metric === k ? "border-primary text-primary bg-primary/10" : "border-outline-dim/60 text-on-surface-muted hover:text-on-surface"}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="relative w-full" style={{ aspectRatio: `${W} / ${H}` }}>
        {tiles.map((s) => (
          <div key={s.data.name}>
            <div
              className="absolute text-[10px] uppercase tracking-widest font-headline text-on-surface-muted truncate px-1"
              style={{ left: `${(s.x / W) * 100}%`, top: `${(s.y / H) * 100}%`, width: `${(s.w / W) * 100}%`, height: 16 }}
            >
              {s.data.name}
            </div>
            {s.children.map((c) => {
              const v = c.data[metric];
              const big = c.w > 70 && c.h > 40;
              return (
                <Link
                  key={c.data.symbol}
                  href={`/company/${c.data.symbol}`}
                  title={`${c.data.name} · ${fmtPct(v, 2, true)}`}
                  className="absolute border border-surface-low grid place-items-center text-center overflow-hidden hover:brightness-125 transition"
                  style={{
                    left: `${(c.x / W) * 100}%`,
                    top: `${(c.y / H) * 100}%`,
                    width: `${(c.w / W) * 100}%`,
                    height: `${(c.h / H) * 100}%`,
                    background: heat(v, cap),
                  }}
                >
                  {c.w > 34 && c.h > 22 && (
                    <div className="leading-tight">
                      <div className={`font-headline font-bold ${big ? "text-sm" : "text-[10px]"}`}>{c.data.symbol}</div>
                      {big && <div className="font-mono text-[11px]">{fmtPct(v, 2, true)}</div>}
                    </div>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
