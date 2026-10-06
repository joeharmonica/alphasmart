"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type Time,
} from "lightweight-charts";
import type { Prices } from "@/lib/companyTypes";
import { fmtPct, toneClass } from "@/lib/companyFormat";

const RANGES = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "10Y"] as const;
type Range = (typeof RANGES)[number];

function rangeStart(last: string, r: Range): string {
  const d = new Date(last + "T00:00:00Z");
  if (r === "YTD") return `${d.getUTCFullYear()}-01-01`;
  const months = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "3Y": 36, "5Y": 60, "10Y": 120 }[r];
  d.setUTCMonth(d.getUTCMonth() - months);
  return d.toISOString().slice(0, 10);
}

function sma(vals: number[], n: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  vals.forEach((v, i) => {
    sum += v;
    if (i >= n) sum -= vals[i - n];
    out.push(i >= n - 1 ? sum / n : null);
  });
  return out;
}

function rsi(vals: number[], n = 14): (number | null)[] {
  const out: (number | null)[] = [null];
  let gain = 0;
  let loss = 0;
  for (let i = 1; i < vals.length; i++) {
    const ch = vals[i] - vals[i - 1];
    const g = Math.max(ch, 0);
    const l = Math.max(-ch, 0);
    if (i <= n) {
      gain += g / n;
      loss += l / n;
      out.push(i === n ? 100 - 100 / (1 + gain / (loss || 1e-9)) : null);
    } else {
      gain = (gain * (n - 1) + g) / n;
      loss = (loss * (n - 1) + l) / n;
      out.push(100 - 100 / (1 + gain / (loss || 1e-9)));
    }
  }
  return out;
}

export default function PriceChart({ prices }: { prices: Prices }) {
  const el = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState<Range>("1Y");
  const [kind, setKind] = useState<"candle" | "line">("candle");
  const [showSma, setShowSma] = useState(true);
  const [compare, setCompare] = useState(false);
  const [showRsi, setShowRsi] = useState(false);

  const bars = prices.bars;
  const last = bars[bars.length - 1]?.t;
  const from = last ? rangeStart(last, range) : "";

  const stats = useMemo(() => {
    const win = bars.filter((b) => b.t >= from);
    if (win.length < 2) return null;
    const closes = win.map((b) => b.c);
    const rets = closes.slice(1).map((c, i) => c / closes[i] - 1);
    const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
    const vol = Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length) * Math.sqrt(252);
    let peak = closes[0];
    let mdd = 0;
    for (const c of closes) {
      peak = Math.max(peak, c);
      mdd = Math.min(mdd, c / peak - 1);
    }
    const bench = prices.benchmark.bars.filter((b) => b.t >= from);
    const benchRet = bench.length > 1 ? bench[bench.length - 1].c / bench[0].c - 1 : null;
    return {
      ret: closes[closes.length - 1] / closes[0] - 1,
      high: Math.max(...win.map((b) => b.h)),
      low: Math.min(...win.map((b) => b.l)),
      vol,
      mdd,
      benchRet,
    };
  }, [bars, from, prices.benchmark.bars]);

  useEffect(() => {
    if (!el.current || !bars.length) return;
    const chart: IChartApi = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#181c21" },
        textColor: "#b9cbbe",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
        panes: { separatorColor: "#3a4a41" },
      },
      grid: { vertLines: { color: "#22272d" }, horzLines: { color: "#22272d" } },
      crosshair: { mode: CrosshairMode.Normal },
      // Embedded in a scrolling page: let the wheel scroll the page, not zoom the chart.
      handleScroll: { mouseWheel: false },
      handleScale: { mouseWheel: false },
      rightPriceScale: { borderColor: "#3a4a41" },
      timeScale: { borderColor: "#3a4a41" },
    });

    const t = (s: string) => s as Time;
    const closes = bars.map((b) => b.c);

    if (compare) {
      // Percent-return mode: both lines rebased to 0% at the range start.
      const base = bars.find((b) => b.t >= from)?.c ?? bars[0].c;
      const bBars = prices.benchmark.bars;
      const bBase = bBars.find((b) => b.t >= from)?.c ?? bBars[0].c;
      const pctFmt = { type: "custom" as const, formatter: (p: number) => `${p.toFixed(1)}%` };
      chart
        .addSeries(LineSeries, { color: "#00ffb2", lineWidth: 2, priceFormat: pctFmt, title: prices.symbol })
        .setData(bars.map((b) => ({ time: t(b.t), value: (b.c / base - 1) * 100 })));
      chart
        .addSeries(LineSeries, { color: "#7aa2ff", lineWidth: 2, priceFormat: pctFmt, title: prices.benchmark.symbol })
        .setData(bBars.map((b) => ({ time: t(b.t), value: (b.c / bBase - 1) * 100 })));
    } else if (kind === "candle") {
      chart
        .addSeries(CandlestickSeries, {
          upColor: "#00ffb2",
          downColor: "#ffb3ac",
          wickUpColor: "#00ffb2",
          wickDownColor: "#ffb3ac",
          borderVisible: false,
        })
        .setData(bars.map((b) => ({ time: t(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    } else {
      chart
        .addSeries(LineSeries, { color: "#00ffb2", lineWidth: 2 })
        .setData(bars.map((b) => ({ time: t(b.t), value: b.c })));
    }

    if (showSma && !compare) {
      for (const [n, color] of [
        [50, "#ffcf66"],
        [200, "#c792ea"],
      ] as const) {
        const s = sma(closes, n);
        chart
          .addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: `SMA${n}` })
          .setData(bars.flatMap((b, i) => (s[i] == null ? [] : [{ time: t(b.t), value: s[i]! }])));
      }
    }

    const vol = chart.addSeries(
      HistogramSeries,
      { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false },
      1,
    );
    vol.setData(
      bars.map((b, i) => ({
        time: t(b.t),
        value: b.v,
        color: i && b.c < bars[i - 1].c ? "#ffb3ac66" : "#00ffb266",
      })),
    );

    if (showRsi) {
      const r = rsi(closes);
      const rs = chart.addSeries(LineSeries, { color: "#5fd4e8", lineWidth: 1, title: "RSI14" }, 2);
      rs.setData(bars.flatMap((b, i) => (r[i] == null ? [] : [{ time: t(b.t), value: r[i]! }])));
      rs.createPriceLine({ price: 70, color: "#ffb3ac", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
      rs.createPriceLine({ price: 30, color: "#00ffb2", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
    }

    const panes = chart.panes();
    panes[1]?.setHeight(70);
    panes[2]?.setHeight(90);
    chart.timeScale().setVisibleRange({ from: t(from), to: t(last) });

    return () => chart.remove();
  }, [bars, prices.benchmark.bars, prices.benchmark.symbol, prices.symbol, kind, showSma, compare, showRsi, from, last]);

  const btn = (on: boolean) =>
    `px-2.5 py-1 text-[11px] font-mono border ${on ? "border-primary text-primary bg-primary/10" : "border-outline-dim/60 text-on-surface-muted hover:text-on-surface"}`;

  return (
    <div className="bg-surface-low border border-outline-dim/40">
      <div className="flex flex-wrap items-center gap-2 p-3 border-b border-outline-dim/40">
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button key={r} className={btn(r === range)} onClick={() => setRange(r)}>{r}</button>
          ))}
        </div>
        <div className="w-px h-5 bg-outline-dim/60 mx-1" />
        <button className={btn(kind === "candle" && !compare)} onClick={() => { setKind("candle"); setCompare(false); }}>Candles</button>
        <button className={btn(kind === "line" && !compare)} onClick={() => { setKind("line"); setCompare(false); }}>Line</button>
        <button className={btn(compare)} onClick={() => setCompare((c) => !c)}>vs SPY %</button>
        <button className={btn(showSma && !compare)} disabled={compare} onClick={() => setShowSma((s) => !s)}>SMA 50/200</button>
        <button className={btn(showRsi)} onClick={() => setShowRsi((s) => !s)}>RSI</button>
      </div>
      <div ref={el} className={showRsi ? "h-[560px]" : "h-[470px]"} />
      {stats && (
        <div className="grid grid-cols-3 md:grid-cols-6 gap-px bg-outline-dim/30 border-t border-outline-dim/40 text-xs">
          {[
            ["Return", fmtPct(stats.ret, 1, true), toneClass(stats.ret)],
            ["SPY", fmtPct(stats.benchRet, 1, true), toneClass(stats.benchRet)],
            ["High", stats.high.toFixed(2), ""],
            ["Low", stats.low.toFixed(2), ""],
            ["Volatility (ann.)", fmtPct(stats.vol), ""],
            ["Max drawdown", fmtPct(stats.mdd), "text-tertiary"],
          ].map(([k, v, c]) => (
            <div key={k} className="bg-surface-low px-3 py-2">
              <div className="text-[10px] uppercase tracking-widest text-outline font-headline">{k} · {range}</div>
              <div className={`font-mono text-sm ${c}`}>{v}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
