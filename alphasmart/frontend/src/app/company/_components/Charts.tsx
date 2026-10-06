"use client";

import { useState } from "react";
import { isNum } from "@/lib/companyFormat";

export const PALETTE = ["#00ffb2", "#7aa2ff", "#ffcf66", "#ffb3ac", "#c792ea", "#5fd4e8"];

type V = number | null;

export function Sparkline({ values, width = 96, height = 28 }: { values: V[]; width?: number; height?: number }) {
  const pts = values.filter(isNum);
  if (pts.length < 2) return <span className="text-outline">—</span>;
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const d = pts
    .map((v, i) => `${i ? "L" : "M"}${((i / (pts.length - 1)) * width).toFixed(1)},${(height - ((v - min) / span) * height).toFixed(1)}`)
    .join("");
  const up = pts[pts.length - 1] >= pts[0];
  return (
    <svg width={width} height={height} className="block" aria-hidden>
      <path d={d} fill="none" stroke={up ? "#00ffb2" : "#ffb3ac"} strokeWidth={1.4} />
    </svg>
  );
}

interface Series {
  name: string;
  values: V[];
  color?: string;
}

interface ChartProps {
  labels: string[];
  series: Series[];
  format: (v: number) => string;
  height?: number;
  title?: string;
}

function niceBounds(all: number[], includeZero: boolean) {
  let min = Math.min(...all);
  let max = Math.max(...all);
  if (includeZero) {
    min = Math.min(0, min);
    max = Math.max(0, max);
  }
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.08;
  return { min: includeZero && min === 0 ? 0 : min - pad, max: max + pad };
}

function Frame({
  title,
  series,
  hover,
  labels,
  format,
  children,
}: {
  title?: string;
  series: Series[];
  hover: number | null;
  labels: string[];
  format: (v: number) => string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-surface-low border border-outline-dim/40 p-4">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        {title && <h4 className="font-headline text-xs uppercase tracking-widest text-on-surface-muted">{title}</h4>}
        <div className="flex flex-wrap gap-3 text-[11px] font-mono">
          {series.map((s, i) => {
            const v = hover != null ? s.values[hover] : s.values[s.values.length - 1];
            return (
              <span key={s.name} className="flex items-center gap-1">
                <span className="inline-block w-2 h-2" style={{ background: s.color ?? PALETTE[i] }} />
                <span className="text-on-surface-muted">{s.name}</span>
                <span>{isNum(v) ? format(v) : "—"}</span>
              </span>
            );
          })}
          <span className="text-outline">{hover != null ? labels[hover] : labels[labels.length - 1]}</span>
        </div>
      </div>
      {children}
    </div>
  );
}

const W = 600;
const PAD_L = 56;
const PAD_B = 22;
const PAD_T = 10;

export function BarChart({ labels, series, format, height = 200, title }: ChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const all = series.flatMap((s) => s.values.filter(isNum));
  if (!all.length) return <Frame {...{ title, series, hover, labels, format }}><Empty h={height} /></Frame>;
  const { min, max } = niceBounds(all, true);
  const plotH = height - PAD_B;
  const y = (v: number) => PAD_T + (plotH - PAD_T) - ((v - min) / (max - min)) * (plotH - PAD_T);
  const groupW = (W - PAD_L) / labels.length;
  const barW = Math.max(2, (groupW * 0.7) / series.length);
  const ticks = [min, (min + max) / 2, max];
  return (
    <Frame {...{ title, series, hover, labels, format }}>
      <svg viewBox={`0 0 ${W} ${height}`} className="w-full" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W} y1={y(t)} y2={y(t)} stroke="#3a4a41" strokeDasharray="2 4" />
            <text x={PAD_L - 6} y={y(t) + 4} textAnchor="end" className="fill-outline text-[10px] font-mono">{format(t)}</text>
          </g>
        ))}
        <line x1={PAD_L} x2={W} y1={y(0)} y2={y(0)} stroke="#83958a" />
        {labels.map((lab, i) => {
          const gx = PAD_L + i * groupW;
          return (
            <g key={lab + i} onMouseEnter={() => setHover(i)}>
              <rect x={gx} y={0} width={groupW} height={plotH} fill={hover === i ? "#ffffff08" : "transparent"} />
              {series.map((s, j) => {
                const v = s.values[i];
                if (!isNum(v)) return null;
                const top = Math.min(y(v), y(0));
                return (
                  <rect
                    key={s.name}
                    x={gx + groupW * 0.15 + j * barW}
                    y={top}
                    width={barW - 1}
                    height={Math.max(1, Math.abs(y(v) - y(0)))}
                    fill={v < 0 ? "#ffb3ac" : (s.color ?? PALETTE[j])}
                  />
                );
              })}
              <text x={gx + groupW / 2} y={height - 6} textAnchor="middle" className="fill-outline text-[10px] font-mono">{lab}</text>
            </g>
          );
        })}
      </svg>
    </Frame>
  );
}

export function LineChart({ labels, series, format, height = 200, title }: ChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const all = series.flatMap((s) => s.values.filter(isNum));
  if (!all.length) return <Frame {...{ title, series, hover, labels, format }}><Empty h={height} /></Frame>;
  const { min, max } = niceBounds(all, false);
  const plotH = height - PAD_B;
  const n = labels.length;
  const x = (i: number) => PAD_L + (n === 1 ? (W - PAD_L) / 2 : (i / (n - 1)) * (W - PAD_L - 28));
  const y = (v: number) => PAD_T + (plotH - PAD_T) - ((v - min) / (max - min)) * (plotH - PAD_T);
  const ticks = [min, (min + max) / 2, max];
  return (
    <Frame {...{ title, series, hover, labels, format }}>
      <svg
        viewBox={`0 0 ${W} ${height}`}
        className="w-full"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          const i = n === 1 ? 0 : Math.round(((px - PAD_L) / (W - PAD_L - 28)) * (n - 1));
          setHover(Math.max(0, Math.min(n - 1, i)));
        }}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W} y1={y(t)} y2={y(t)} stroke="#3a4a41" strokeDasharray="2 4" />
            <text x={PAD_L - 6} y={y(t) + 4} textAnchor="end" className="fill-outline text-[10px] font-mono">{format(t)}</text>
          </g>
        ))}
        {series.map((s, j) => {
          const segs: string[] = [];
          s.values.forEach((v, i) => {
            if (isNum(v)) segs.push(`${segs.length && isNum(s.values[i - 1]) ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`);
          });
          const color = s.color ?? PALETTE[j];
          return (
            <g key={s.name}>
              <path d={segs.join("")} fill="none" stroke={color} strokeWidth={2} />
              {s.values.map((v, i) => (isNum(v) ? <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 4 : 2.5} fill={color} /> : null))}
            </g>
          );
        })}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={plotH} stroke="#83958a" strokeDasharray="3 3" />}
        {labels.map((lab, i) =>
          n <= 12 || i % Math.ceil(n / 12) === 0 ? (
            <text key={lab + i} x={x(i)} y={height - 6} textAnchor="middle" className="fill-outline text-[10px] font-mono">{lab}</text>
          ) : null,
        )}
      </svg>
    </Frame>
  );
}

function Empty({ h }: { h: number }) {
  return <div style={{ height: h }} className="grid place-items-center text-outline text-xs">No data reported</div>;
}

/** Horizontal low–high range with a marker (52-week range, analyst targets). */
export function RangeBar({
  label,
  low,
  high,
  value,
  mid,
  format,
}: {
  label: string;
  low: number | null;
  high: number | null;
  value: number | null;
  mid?: number | null;
  format: (v: number) => string;
}) {
  if (!isNum(low) || !isNum(high) || high <= low) return null;
  const lo = Math.min(low, isNum(value) ? value : low);
  const hi = Math.max(high, isNum(value) ? value : high);
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div>
      <div className="flex justify-between text-[11px] text-on-surface-muted mb-1">
        <span className="uppercase tracking-widest font-headline">{label}</span>
        {isNum(value) && <span className="font-mono text-on-surface">{format(value)}</span>}
      </div>
      <div className="relative h-2 bg-surface-high">
        <div className="absolute h-2 bg-primary/25" style={{ left: pos(low), width: `calc(${pos(high)} - ${pos(low)})` }} />
        {isNum(mid) && <div className="absolute top-[-3px] h-[14px] w-px bg-[#ffcf66]" style={{ left: pos(mid) }} title={`mean ${format(mid)}`} />}
        {isNum(value) && <div className="absolute top-[-4px] h-4 w-1 bg-primary" style={{ left: `calc(${pos(value)} - 2px)` }} />}
      </div>
      <div className="flex justify-between text-[10px] font-mono text-outline mt-1">
        <span>{format(low)}</span>
        {isNum(mid) && <span className="text-[#ffcf66]">mean {format(mid)}</span>}
        <span>{format(high)}</span>
      </div>
    </div>
  );
}
