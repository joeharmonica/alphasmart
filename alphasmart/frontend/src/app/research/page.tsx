"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface SymbolInfo {
  symbol: string;
  timeframe: string;
  record_count: number;
  last_fetched_at: string | null;
}

interface StrategyInfo {
  key: string;
  label: string;
}

interface Metrics {
  sharpe: number;
  sortino: number;
  cagr: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number;
  total_return: number;
  trade_count: number;
  exposure: number;
  avg_trade_return: number;
  best_trade: number;
  worst_trade: number;
  n_bars: number;
  gate1_pass: boolean;
}

interface CurvePoint {
  date: string;
  equity: number;
}

interface Fill {
  date: string;
  side: "buy" | "sell";
  price: number;
  quantity: number;
  commission: number;
}

interface BacktestResult {
  strategy: string;
  strategy_label: string;
  symbol: string;
  timeframe: string;
  initial_capital: number;
  date_range: string;
  halted: boolean;
  halt_reason: string;
  metrics: Metrics;
  equity_curve: CurvePoint[];
  benchmark: CurvePoint[];
  fills: Fill[];
}

interface SummaryRow {
  rank: number;
  strategy: string;
  strategy_label: string;
  symbol: string;
  timeframe: string;
  sharpe: number;
  cagr: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number;
  total_return: number;
  trade_count: number;
  score: number;
  gate1_pass: boolean;
  halted: boolean;
  is_optimized?: boolean;
}

interface QueueItem {
  id: string;
  strategy: string;
  strategyLabel: string;
  symbol: string;
  timeframe: string;
  objective: OptObjective;
  status: "pending" | "running" | "done" | "error";
  result?: OptimizeResult;
  errorMsg?: string;
}

interface RoundTrip {
  entryDate: string;
  exitDate: string;
  entryPrice: number;
  exitPrice: number;
  quantity: number;
  pnlPct: number;
}

interface GridRow {
  params: Record<string, number>;
  sharpe: number;
  cagr: number;
  max_drawdown: number;
  win_rate: number;
  trade_count: number;
  total_return: number;
}

interface WFRow {
  fold: number;
  is_bars: number;
  oos_bars: number;
  is_sharpe: number;
  oos_sharpe: number | null;
  is_cagr: number;
  oos_cagr: number | null;
  best_is_params: Record<string, number>;
  is_period: string;
  oos_period: string;
}

interface StabilityMap1D {
  type: "1d";
  x_label: string;
  points: Array<{ x: number; sharpe: number }>;
}
interface StabilityMap2D {
  type: "2d";
  x_label: string;
  y_label: string;
  x_vals: number[];
  y_vals: number[];
  rows: Array<{ y_val: number; cells: Array<{ x: number; y: number; sharpe: number | null }> }>;
}
type StabilityMap = StabilityMap1D | StabilityMap2D | { type: "none" };

interface OptimizeResult {
  strategy: string;
  symbol: string;
  timeframe: string;
  objective?: string;
  total_combos: number;
  valid_combos: number;
  best_params: Record<string, number>;
  best_sharpe: number;
  best_cagr: number;
  best_max_drawdown: number;
  best_trade_count: number;
  grid_results: GridRow[];
  walk_forward: WFRow[];
  overfitting_score: number | null;
  gate2_pass: boolean;
  stability_map: StabilityMap;
}

interface SimPercentiles {
  p5: number; p25: number; p50: number; p75: number; p95: number;
  mean: number; std: number;
}
interface SimulationResult {
  strategy_key: string;
  symbol: string;
  timeframe: string;
  simulation_type: string;
  n_simulations: number;
  original_metrics: {
    sharpe: number; cagr: number; max_drawdown: number; win_rate: number; trade_count: number;
  };
  percentiles: {
    sharpe?: SimPercentiles;
    cagr?: SimPercentiles;
    max_drawdown?: SimPercentiles;
    win_rate?: SimPercentiles;
  };
  sim_sharpes: number[];
  sim_cagrs: number[];
  sim_max_drawdowns: number[];
  sim_win_rates: number[];
  sim_trade_counts: number[];
}

interface RiskFlag {
  severity: "high" | "medium" | "low";
  flag: string;
  detail: string;
}

interface InsightsResult {
  regime: string;
  regime_confidence: number;
  regime_label: string;
  regime_explanation: string;
  risk_flags: RiskFlag[];
  strategy_assessment: string;
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  gate2_readiness: "ready" | "conditional" | "not_ready";
  gate2_rationale: string;
}

// ---------------------------------------------------------------------------
// Tutorial step definitions
// ---------------------------------------------------------------------------
interface TutorialStep {
  title: string;
  body: string;
  /** CSS selector for the element to spotlight. Empty = centered modal. */
  target: string;
  /** Where the tooltip card appears relative to the spotlight box. */
  position: "right" | "left" | "bottom" | "top" | "center";
  icon: string;
  /** If set, the tutorial will switch to this view before spotlighting. */
  requiresView?: "explorer" | "summary" | "optimizer" | "insights" | "simulation";
}

const TUTORIAL_STEPS: TutorialStep[] = [
  {
    title: "Welcome to AlphaSMART",
    body: "Your institutional-grade backtest platform. 15 strategies, 4 timeframes, walk-forward optimization, bootstrapping simulation, and an LLM copilot — all running on real historical data stored locally. Let's walk through each view.",
    target: "",
    position: "center",
    icon: "🎯",
  },
  {
    title: "Configure a Backtest",
    body: "Use the sidebar to pick a Strategy (11 available across trend, reversion, and proprietary families), a Symbol, and a Timeframe (15m / 1h / 1d / 1wk). The backtest runs automatically on selection change.",
    target: "[data-tour='sidebar']",
    position: "right",
    icon: "⚙️",
  },
  {
    title: "Gate 1 — Qualification Check",
    body: "Every run is scored against Gate 1: Sharpe > 1.2, Max Drawdown < 25%, and ≥ 100 completed trades. Gate 1 pass is required before a strategy is worth optimizing. With 5 years of daily data you'll see real differentiation.",
    target: "[data-tour='gate1']",
    position: "bottom",
    requiresView: "explorer",
    icon: "🔒",
  },
  {
    title: "Key Performance Metrics",
    body: "Sharpe = risk-adjusted return. Max Drawdown = worst peak-to-trough loss. CAGR = compound annual growth. Win Rate = fraction of profitable round-trips. Profit Factor = gross profit ÷ gross loss. All annualised correctly for the selected timeframe.",
    target: "[data-tour='metrics-bar']",
    position: "bottom",
    requiresView: "explorer",
    icon: "📈",
  },
  {
    title: "Equity Curve vs Buy & Hold",
    body: "Green line = strategy equity growth. Dashed grey = buy-and-hold benchmark. Consistent outperformance above the dashed line indicates real alpha. The shaded area visualises drawdown depth over time.",
    target: "[data-tour='equity-chart']",
    position: "top",
    requiresView: "explorer",
    icon: "📉",
  },
  {
    title: "Trade Log & P&L Distribution",
    body: "The histogram shows how trade P&L is distributed across wins (green) and losses (red). The table lists every round-trip: entry/exit dates, prices, and net P&L %. A right-skewed histogram with a fat right tail is what you want.",
    target: "[data-tour='trade-section']",
    position: "top",
    requiresView: "explorer",
    icon: "📋",
  },
  {
    title: "All Results — Strategy Rankings",
    body: "Runs all 15 strategies × every symbol in your database and ranks them by composite score: Sharpe × 40% + CAGR × 30% + Drawdown resilience × 20% + Win rate × 10%. Click any row to drill into that run in the Explorer.",
    target: "[data-tour='all-results-btn']",
    position: "right",
    icon: "📊",
    requiresView: "summary",
  },
  {
    title: "Optimizer — Walk-Forward Validation",
    body: "Runs a grid search across all parameter combinations, then validates each using 3-year in-sample / 1-year out-of-sample walk-forward folds. Choose your objective: Max Sharpe, Max CAGR, Min Drawdown, or Max Profit Factor. Gate 2 passes when OOS Sharpe ≥ 70% of in-sample.",
    target: "[data-tour='optimizer-btn']",
    position: "right",
    icon: "⚡",
    requiresView: "optimizer",
  },
  {
    title: "AI Insights — Claude Copilot",
    body: "Sends your backtest metrics and equity curve to Claude for analysis: market regime classification, risk flag detection, strategy strengths/weaknesses, and Gate 2 readiness. Requires ANTHROPIC_API_KEY in .env. Analytical only — zero write access to orders or parameters.",
    target: "[data-tour='insights-btn']",
    position: "right",
    icon: "🤖",
    requiresView: "insights",
  },
  {
    title: "Simulation — Stress Testing",
    body: "Generates hundreds of synthetic price paths via Block Bootstrap (preserves volatility clustering), Jackknife (leave-one-period-out), or Monte Carlo GBM. Shows metric distributions (p5 → p95) across paths. ROBUST = median Sharpe ≥ 65% of original. Fragile = strategy is likely overfit.",
    target: "[data-tour='simulation-btn']",
    position: "right",
    icon: "🎲",
    requiresView: "simulation",
  },
];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const pctSigned = (v: number) =>
  `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const num2 = (v: number) => v.toFixed(2);
const dollars = (v: number) =>
  v >= 1_000_000
    ? `$${(v / 1_000_000).toFixed(2)}M`
    : `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

// ---------------------------------------------------------------------------
// Compute round-trips from fill list
// ---------------------------------------------------------------------------
function computeRoundTrips(fills: Fill[]): RoundTrip[] {
  const sorted = [...fills].sort((a, b) => a.date.localeCompare(b.date));
  const openBuys: Fill[] = [];
  const trips: RoundTrip[] = [];
  for (const fill of sorted) {
    if (fill.side === "buy") {
      openBuys.push(fill);
    } else if (fill.side === "sell" && openBuys.length > 0) {
      const buy = openBuys.shift()!;
      trips.push({
        entryDate: buy.date,
        exitDate: fill.date,
        entryPrice: buy.price,
        exitPrice: fill.price,
        quantity: Math.min(buy.quantity, fill.quantity),
        pnlPct: (fill.price - buy.price) / buy.price,
      });
    }
  }
  return trips;
}

// ---------------------------------------------------------------------------
// Histogram
// ---------------------------------------------------------------------------
interface Bin {
  min: number;
  max: number;
  count: number;
  isProfit: boolean;
}

function buildHistogram(trips: RoundTrip[], numBins = 12): Bin[] {
  if (!trips.length) return [];
  const returns = trips.map((t) => t.pnlPct);
  const minVal = Math.min(...returns);
  const maxVal = Math.max(...returns);
  const range = maxVal - minVal || 0.02;
  const step = range / numBins;
  const bins: Bin[] = Array.from({ length: numBins }, (_, i) => ({
    min: minVal + i * step,
    max: minVal + (i + 1) * step,
    count: 0,
    isProfit: minVal + (i + 0.5) * step >= 0,
  }));
  for (const r of returns) {
    const idx = Math.min(Math.floor(((r - minVal) / range) * numBins), numBins - 1);
    bins[idx].count++;
  }
  return bins;
}

// ---------------------------------------------------------------------------
// SVG equity curve math
// ---------------------------------------------------------------------------
function buildSVGPaths(
  points: CurvePoint[],
  benchPoints: CurvePoint[],
  W: number,
  H: number
) {
  const PAD = { top: 15, bottom: 35, left: 62, right: 12 };
  const iW = W - PAD.left - PAD.right;
  const iH = H - PAD.top - PAD.bottom;

  if (!points.length) return null;

  const allEq = [
    ...points.map((p) => p.equity),
    ...benchPoints.map((p) => p.equity),
  ];
  const rawMin = Math.min(...allEq);
  const rawMax = Math.max(...allEq);
  const spread = rawMax - rawMin || 1;
  const minEq = rawMin - spread * 0.03;
  const maxEq = rawMax + spread * 0.03;
  const n = points.length;

  const toX = (i: number) =>
    PAD.left + (n <= 1 ? 0 : (i / (n - 1)) * iW);
  const toY = (eq: number) =>
    PAD.top + iH - ((eq - minEq) / (maxEq - minEq)) * iH;

  const stratCoords = points.map((p, i) => ({ x: toX(i), y: toY(p.equity) }));
  const linePath = stratCoords
    .map((c, i) => `${i === 0 ? "M" : "L"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`)
    .join(" ");
  const areaPath =
    `${linePath} L ${stratCoords[stratCoords.length - 1].x.toFixed(1)} ${(PAD.top + iH).toFixed(1)} L ${PAD.left.toFixed(1)} ${(PAD.top + iH).toFixed(1)} Z`;

  const benchPath = benchPoints.length
    ? benchPoints
        .map((p, i) => `${i === 0 ? "M" : "L"} ${toX(i).toFixed(1)} ${toY(p.equity).toFixed(1)}`)
        .join(" ")
    : "";

  const yLabels = Array.from({ length: 5 }, (_, i) => {
    const eq = minEq + ((4 - i) / 4) * (maxEq - minEq);
    const label =
      eq >= 1_000_000 ? `$${(eq / 1_000_000).toFixed(1)}M` : `$${Math.round(eq / 1000)}K`;
    return { y: toY(eq), label };
  });

  const xSteps = 5;
  const xLabels = Array.from({ length: xSteps }, (_, i) => {
    const idx = Math.round((i / (xSteps - 1)) * (n - 1));
    return { x: toX(idx), label: points[idx]?.date?.slice(0, 7) ?? "" };
  });

  return { linePath, areaPath, benchPath, yLabels, xLabels, PAD, iH };
}

// ---------------------------------------------------------------------------
// Tutorial spotlight overlay — clean 4-rect approach
// ---------------------------------------------------------------------------
const OVERLAY_BG = "rgba(0,0,0,0.75)";
const TOOLTIP_W = 360;
const MARGIN = 14;

function TutorialOverlay({
  step,
  stepIndex,
  total,
  onNext,
  onPrev,
  onClose,
}: {
  step: TutorialStep;
  stepIndex: number;
  total: number;
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
}) {
  const [box, setBox] = useState<DOMRect | null>(null);

  // Find and measure the target element, retrying once after 120 ms to allow
  // the view to finish rendering after a programmatic view switch.
  useEffect(() => {
    setBox(null); // reset while switching steps

    if (!step.target) return;

    function measure() {
      const el = document.querySelector<HTMLElement>(step.target);
      if (!el) return false;
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      setBox(el.getBoundingClientRect());
      return true;
    }

    if (!measure()) {
      const id = setTimeout(() => { measure(); }, 150);
      return () => clearTimeout(id);
    }
  }, [step.target, step]);

  // Keyboard: Escape = close, ArrowRight/Enter = next, ArrowLeft = prev
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "Enter") onNext();
      else if (e.key === "ArrowLeft") onPrev();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onNext, onPrev, onClose]);

  const [vw, setVw] = useState(1440);
  const [vh, setVh] = useState(900);
  useEffect(() => {
    setVw(window.innerWidth);
    setVh(window.innerHeight);
  }, []);

  // ---- 4-rect spotlight coords ----
  const sp = box
    ? { top: box.top - 6, left: box.left - 6, w: box.width + 12, h: box.height + 12 }
    : null;

  // ---- tooltip position ----
  let tooltipStyle: CSSProperties = { position: "fixed", width: TOOLTIP_W, zIndex: 1002 };

  if (!sp || step.position === "center") {
    tooltipStyle = { ...tooltipStyle, top: "50%", left: "50%", transform: "translate(-50%,-50%)" };
  } else {
    let top = 0, left = 0;

    if (step.position === "right") {
      top  = sp.top + sp.h / 2 - 130;
      left = sp.left + sp.w + MARGIN;
    } else if (step.position === "left") {
      top  = sp.top + sp.h / 2 - 130;
      left = sp.left - TOOLTIP_W - MARGIN;
    } else if (step.position === "bottom") {
      top  = sp.top + sp.h + MARGIN;
      left = sp.left + sp.w / 2 - TOOLTIP_W / 2;
    } else { // top
      top  = sp.top - MARGIN; // will be pushed up dynamically
      left = sp.left + sp.w / 2 - TOOLTIP_W / 2;
      // We'll let the clamping handle the actual top
    }

    // Clamp to viewport
    left = Math.max(MARGIN, Math.min(left, vw - TOOLTIP_W - MARGIN));
    if (step.position === "top") {
      // position above, dynamically sized
      top = sp.top - 260 - MARGIN;
    }
    top  = Math.max(MARGIN, Math.min(top, vh - 280));

    tooltipStyle = { ...tooltipStyle, top, left };
  }

  const isFirst = stepIndex === 0;
  const isLast  = stepIndex === total - 1;

  return (
    <div className="fixed inset-0 z-[1000]" style={{ pointerEvents: "auto" }}>
      {/* ---- 4-rect dark overlay (leaves spotlight transparent) ---- */}
      {sp ? (
        <>
          {/* top */}
          <div style={{ position:"fixed", top:0, left:0, right:0, height:sp.top, background:OVERLAY_BG }} />
          {/* bottom */}
          <div style={{ position:"fixed", top:sp.top+sp.h, left:0, right:0, bottom:0, background:OVERLAY_BG }} />
          {/* left */}
          <div style={{ position:"fixed", top:sp.top, left:0, width:sp.left, height:sp.h, background:OVERLAY_BG }} />
          {/* right */}
          <div style={{ position:"fixed", top:sp.top, left:sp.left+sp.w, right:0, height:sp.h, background:OVERLAY_BG }} />
          {/* spotlight ring */}
          <div style={{
            position:"fixed", top:sp.top, left:sp.left,
            width:sp.w, height:sp.h,
            outline:"2px solid #00ffb2",
            boxShadow:"0 0 0 1px rgba(0,255,178,0.15), 0 0 20px rgba(0,255,178,0.12)",
            pointerEvents:"none",
          }} />
        </>
      ) : (
        /* full dark overlay when no spotlight target */
        <div style={{ position:"fixed", inset:0, background:OVERLAY_BG }} />
      )}

      {/* ---- Tooltip card ---- */}
      <div
        style={tooltipStyle}
        className="bg-[#181c21] border border-[#00ffb2]/25 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Progress dots + close */}
        <div className="flex items-center justify-between px-5 pt-4 pb-0">
          <div className="flex gap-1.5 items-center">
            {Array.from({ length: total }).map((_, i) => (
              <div
                key={i}
                style={{
                  width: i === stepIndex ? 20 : 8,
                  height: 3,
                  borderRadius: 2,
                  background: i === stepIndex ? "#00ffb2" : "#3a4a41",
                  transition: "width 0.2s, background 0.2s",
                }}
              />
            ))}
            <span className="text-[9px] font-mono text-[#3a4a41] ml-2">
              {stepIndex + 1}/{total}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-[#3a4a41] hover:text-[#83958a] text-base leading-none transition-colors"
            aria-label="Close tutorial"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="px-5 pt-3 pb-5">
          <div className="text-xl mb-2">{step.icon}</div>
          <h3 className="font-headline font-bold text-[#e0e2ea] text-sm uppercase tracking-wide mb-2">
            {step.title}
          </h3>
          <p className="text-xs text-[#b9cbbe] leading-relaxed mb-5">
            {step.body}
          </p>

          {/* Nav row */}
          <div className="flex items-center justify-between">
            <button
              onClick={onPrev}
              disabled={isFirst}
              className="text-[10px] font-mono text-[#83958a] hover:text-[#e0e2ea] uppercase tracking-widest transition-colors disabled:opacity-25 disabled:cursor-default"
            >
              ← Back
            </button>
            <div className="flex items-center gap-3">
              <button
                onClick={onClose}
                className="text-[10px] font-mono text-[#3a4a41] hover:text-[#83958a] uppercase tracking-widest transition-colors"
              >
                Skip
              </button>
              <button
                onClick={onNext}
                className="bg-[#00ffb2] text-[#003824] px-5 py-1.5 text-[10px] font-mono font-bold uppercase tracking-widest active:scale-95 transition-transform"
              >
                {isLast ? "Done ✓" : "Next →"}
              </button>
            </div>
          </div>

          {/* Keyboard hint */}
          {stepIndex === 0 && (
            <p className="text-[9px] font-mono text-[#3a4a41] mt-3 text-center">
              Tip: use ← → arrow keys or Escape to navigate
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="p-5 border-r border-[#3a4a41]/20 last:border-r-0 flex flex-col gap-1">
      <p className="text-[10px] text-[#83958a] uppercase font-mono tracking-widest">
        {label}
      </p>
      <p className={`text-2xl font-mono font-bold ${color ?? "text-[#e0e2ea]"}`}>
        {value}
      </p>
    </div>
  );
}

function Gate1Badge({ pass }: { pass: boolean }) {
  return (
    <div
      data-tour="gate1"
      className={`flex items-center gap-3 p-4 border-l-4 ${
        pass
          ? "border-[#00ffb2] bg-[#00ffb2]/5"
          : "border-[#ffb3ac] bg-[#ffb3ac]/5"
      }`}
    >
      <div className="flex-1">
        <div className="flex items-center gap-2 mb-1">
          <span
            className={`w-2 h-2 rounded-full ${pass ? "bg-[#00ffb2]" : "bg-[#ffb3ac]"}`}
          />
          <span className="text-[10px] font-mono text-[#83958a] uppercase tracking-widest">
            Gate 1 Status
          </span>
        </div>
        <p className="text-xs font-headline font-bold text-[#e0e2ea]">
          {pass
            ? "CRITERIA PASSED — SHARPE > 1.2, MaxDD < 25%, TRADES ≥ 100"
            : "NOT MET — SHARPE > 1.2 AND MaxDD < 25% AND TRADES ≥ 100 REQUIRED"}
        </p>
      </div>
      <span
        className={`shrink-0 px-4 py-2 text-[10px] font-headline font-black uppercase tracking-widest border ${
          pass
            ? "border-[#00ffb2]/40 text-[#00ffb2] bg-[#00ffb2]/10"
            : "border-[#ffb3ac]/40 text-[#ffb3ac] bg-[#ffb3ac]/10"
        }`}
      >
        {pass ? "READY FOR OPTIMIZATION" : "REVIEW REQUIRED"}
      </span>
    </div>
  );
}

function EquityCurveChart({
  equityCurve,
  benchmark,
}: {
  equityCurve: CurvePoint[];
  benchmark: CurvePoint[];
}) {
  const W = 900;
  const H = 260;
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const result = buildSVGPaths(equityCurve, benchmark, W, H);

  if (!result) {
    return (
      <div className="flex-1 flex items-center justify-center text-[#83958a] text-sm font-mono">
        No equity curve data
      </div>
    );
  }

  const { linePath, areaPath, benchPath, yLabels, xLabels, PAD, iH } = result;
  const GRAD_ID = "strat-gradient";
  const n = equityCurve.length;

  // Convert SVG mouse position → nearest data index
  function handleMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    // Map client x to SVG coordinate space
    const svgX = ((e.clientX - rect.left) / rect.width) * W;
    // Map svgX → index into equityCurve
    const iW = W - PAD.left - PAD.right;
    const frac = Math.max(0, Math.min(1, (svgX - PAD.left) / iW));
    const idx = Math.round(frac * (n - 1));
    setHoverIdx(idx);
  }

  function handleMouseLeave() {
    setHoverIdx(null);
  }

  // Hover point coordinates
  const hp = hoverIdx !== null ? equityCurve[hoverIdx] : null;
  const hpBench = hoverIdx !== null ? benchmark[hoverIdx] : null;
  const iW = W - PAD.left - PAD.right;
  const allEq = [...equityCurve.map((p) => p.equity), ...benchmark.map((p) => p.equity)];
  const rawMin = allEq.length ? Math.min(...allEq) : 0;
  const rawMax = allEq.length ? Math.max(...allEq) : 1;
  const spread = rawMax - rawMin || 1;
  const minEq = rawMin - spread * 0.03;
  const maxEq = rawMax + spread * 0.03;
  const toX = (i: number) => PAD.left + (n <= 1 ? 0 : (i / (n - 1)) * iW);
  const toY = (eq: number) => PAD.top + iH - ((eq - minEq) / (maxEq - minEq)) * iH;

  const hx = hoverIdx !== null ? toX(hoverIdx) : null;
  const hy = hp ? toY(hp.equity) : null;

  // Tooltip: keep inside SVG bounds
  const ttW = 170;
  const ttH = hpBench ? 64 : 44;
  const ttX = hx !== null ? Math.min(hx + 10, W - ttW - 4) : 0;
  const ttY = hy !== null ? Math.max(PAD.top, Math.min(hy - ttH / 2, PAD.top + iH - ttH)) : 0;

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      width="100%"
      height="100%"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{ cursor: "crosshair" }}
    >
      <defs>
        <linearGradient id={GRAD_ID} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#00ffb2" stopOpacity="0.20" />
          <stop offset="100%" stopColor="#00ffb2" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Grid */}
      {yLabels.map((l) => (
        <line key={l.label} x1={PAD.left} y1={l.y} x2={W - PAD.right} y2={l.y}
          stroke="#3a4a41" strokeWidth="0.5" strokeDasharray="4" opacity="0.5" />
      ))}

      {/* Y labels */}
      {yLabels.map((l) => (
        <text key={l.label} x={PAD.left - 6} y={l.y + 4} textAnchor="end"
          fontSize="9" fill="#83958a" fontFamily="JetBrains Mono">{l.label}</text>
      ))}

      {/* X labels */}
      {xLabels.map((l) => (
        <text key={l.label} x={l.x} y={H - 8} textAnchor="middle"
          fontSize="9" fill="#83958a" fontFamily="JetBrains Mono">{l.label}</text>
      ))}

      {/* Benchmark */}
      {benchPath && (
        <path d={benchPath} fill="none" stroke="#83958a" strokeWidth="1.2"
          strokeDasharray="5 3" opacity="0.65" />
      )}

      {/* Baseline */}
      <line x1={PAD.left} y1={PAD.top + iH} x2={W - PAD.right} y2={PAD.top + iH}
        stroke="#3a4a41" strokeWidth="1" opacity="0.5" />

      {/* Area fill */}
      <path d={areaPath} fill={`url(#${GRAD_ID})`} />

      {/* Strategy line */}
      <path d={linePath} fill="none" stroke="#00ffb2" strokeWidth="2" />

      {/* Glow */}
      <path d={linePath} fill="none" stroke="#00ffb2" strokeWidth="10" opacity="0.06" />

      {/* Hover crosshair + tooltip */}
      {hx !== null && hp && hy !== null && (
        <>
          {/* Vertical line */}
          <line x1={hx} y1={PAD.top} x2={hx} y2={PAD.top + iH}
            stroke="#00ffb2" strokeWidth="0.8" strokeDasharray="3 2" opacity="0.5" />

          {/* Strategy dot */}
          <circle cx={hx} cy={hy} r={3.5} fill="#00ffb2" stroke="#101419" strokeWidth="1.5" />

          {/* Benchmark dot */}
          {hpBench && (
            <circle cx={hx} cy={toY(hpBench.equity)} r={3} fill="#83958a"
              stroke="#101419" strokeWidth="1.5" />
          )}

          {/* Tooltip box */}
          <rect x={ttX} y={ttY} width={ttW} height={ttH}
            fill="#181c21" stroke="#3a4a41" strokeWidth="0.8" rx="0" />
          <text x={ttX + 8} y={ttY + 14} fontSize="9" fill="#83958a" fontFamily="JetBrains Mono">
            {hp.date}
          </text>
          <circle cx={ttX + 10} cy={ttY + 27} r="3" fill="#00ffb2" />
          <text x={ttX + 18} y={ttY + 31} fontSize="9.5" fill="#00ffb2" fontFamily="JetBrains Mono" fontWeight="bold">
            {hp.equity >= 1_000_000
              ? `$${(hp.equity / 1_000_000).toFixed(3)}M`
              : `$${hp.equity.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
          </text>
          {hpBench && (
            <>
              <circle cx={ttX + 10} cy={ttY + 47} r="2.5" fill="#83958a" />
              <text x={ttX + 18} y={ttY + 51} fontSize="9" fill="#83958a" fontFamily="JetBrains Mono">
                {hpBench.equity >= 1_000_000
                  ? `$${(hpBench.equity / 1_000_000).toFixed(3)}M`
                  : `$${hpBench.equity.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
              </text>
            </>
          )}
        </>
      )}
    </svg>
  );
}

function TradeDistribution({ trips }: { trips: RoundTrip[] }) {
  const bins = buildHistogram(trips, 12);
  if (!bins.length) {
    return (
      <div className="flex-1 flex items-center justify-center text-[#83958a] text-xs font-mono">
        No trades yet
      </div>
    );
  }
  const maxCount = Math.max(...bins.map((b) => b.count));
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 flex items-end gap-[2px]">
        {bins.map((bin, i) => {
          const h = maxCount > 0 ? (bin.count / maxCount) * 100 : 0;
          return (
            <div
              key={i}
              className="flex-1 flex flex-col items-center justify-end group relative"
              style={{ height: "100%" }}
              title={`${pct(bin.min)} → ${pct(bin.max)}: ${bin.count} trades`}
            >
              {bin.count > 0 && (
                <span className="absolute -top-5 text-[8px] font-mono text-[#83958a] opacity-0 group-hover:opacity-100 transition-opacity">
                  {bin.count}
                </span>
              )}
              <div
                style={{ height: `${h}%` }}
                className={`w-full transition-all ${
                  bin.isProfit
                    ? "bg-[#00ffb2]/50 hover:bg-[#00ffb2]/80"
                    : "bg-[#ffb3ac]/50 hover:bg-[#ffb3ac]/80"
                }`}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mt-2 text-[9px] font-mono text-[#83958a]">
        <span>{pct(bins[0].min)}</span>
        <span>0.0%</span>
        <span>{pct(bins[bins.length - 1].max)}</span>
      </div>
    </div>
  );
}

function TradeLog({ trips }: { trips: RoundTrip[] }) {
  if (!trips.length) {
    return (
      <div className="flex items-center justify-center h-28 text-[#83958a] text-xs font-mono">
        No completed round-trips
      </div>
    );
  }
  const sorted = [...trips].sort((a, b) => b.exitDate.localeCompare(a.exitDate));
  return (
    <div className="overflow-x-auto overflow-y-auto max-h-[200px] hide-scrollbar">
      <table className="w-full text-left border-collapse">
        <thead className="sticky top-0 bg-[#262a30]">
          <tr>
            {["Entry", "Exit", "Entry $", "Exit $", "P/L %"].map((h) => (
              <th
                key={h}
                className="px-4 py-2 text-[10px] font-mono text-[#83958a] uppercase tracking-wider"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#3a4a41]/20">
          {sorted.slice(0, 80).map((t, i) => (
            <tr key={i} className="hover:bg-[#1c2025] transition-colors">
              <td className="px-4 py-2 text-xs font-mono text-[#b9cbbe]">{t.entryDate}</td>
              <td className="px-4 py-2 text-xs font-mono text-[#b9cbbe]">{t.exitDate}</td>
              <td className="px-4 py-2 text-xs font-mono">{t.entryPrice.toFixed(2)}</td>
              <td className="px-4 py-2 text-xs font-mono">{t.exitPrice.toFixed(2)}</td>
              <td
                className={`px-4 py-2 text-xs font-mono font-bold text-right ${
                  t.pnlPct >= 0 ? "text-[#00ffb2]" : "text-[#ffb3ac]"
                }`}
              >
                {pctSigned(t.pnlPct)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SummaryTable({
  rows,
  onSelectRow,
}: {
  rows: SummaryRow[];
  onSelectRow: (row: SummaryRow) => void;
}) {
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto hide-scrollbar">
      <table className="w-full text-left border-collapse">
        <thead className="sticky top-0 bg-[#262a30]">
          <tr>
            {[
              "#",
              "Strategy",
              "Symbol",
              "TF",
              "Sharpe",
              "CAGR",
              "Max DD",
              "Win Rate",
              "Trades",
              "Score",
              "Gate 1",
            ].map((h) => (
              <th
                key={h}
                className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#3a4a41]/10">
          {rows.map((row) => (
            <tr
              key={`${row.strategy}-${row.symbol}-${row.timeframe}`}
              onClick={() => onSelectRow(row)}
              className="hover:bg-[#1c2025] cursor-pointer transition-colors group"
            >
              <td className="px-4 py-3 text-xs font-mono text-[#83958a]">#{row.rank}</td>
              <td className="px-4 py-3 text-xs font-mono font-bold text-[#e0e2ea] group-hover:text-[#00ffb2] transition-colors">
                <span>{row.strategy_label ?? row.strategy}</span>
                {row.is_optimized && (
                  <span className="ml-2 text-[8px] font-mono font-bold text-[#00ffb2] border border-[#00ffb2]/40 px-1 py-0.5 leading-none align-middle">
                    ✦ OPT
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-xs font-mono text-[#00e29d]">{row.symbol}</td>
              <td className="px-4 py-3 text-xs font-mono text-[#83958a]">{row.timeframe}</td>
              <td
                className={`px-4 py-3 text-xs font-mono font-bold ${
                  row.sharpe >= 1.2 ? "text-[#00ffb2]" : "text-[#e0e2ea]"
                }`}
              >
                {num2(row.sharpe)}
              </td>
              <td
                className={`px-4 py-3 text-xs font-mono ${
                  row.cagr >= 0 ? "text-[#00ffb2]" : "text-[#ffb3ac]"
                }`}
              >
                {pct(row.cagr)}
              </td>
              <td className="px-4 py-3 text-xs font-mono text-[#ffb3ac]">
                {pct(row.max_drawdown)}
              </td>
              <td className="px-4 py-3 text-xs font-mono">{pct(row.win_rate)}</td>
              <td className="px-4 py-3 text-xs font-mono">{row.trade_count}</td>
              <td className="px-4 py-3 text-xs font-mono text-[#83958a]">{num2(row.score)}</td>
              <td className="px-4 py-3 text-center">
                {row.gate1_pass ? (
                  <span className="text-[#00ffb2] text-xs font-bold">✓</span>
                ) : (
                  <span className="text-[#ffb3ac] text-xs">✗</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------
function Skeleton({ className }: { className?: string }) {
  return (
    <div className={`bg-[#262a30] animate-pulse ${className ?? ""}`} />
  );
}

// ---------------------------------------------------------------------------
// Simulation histogram component
// ---------------------------------------------------------------------------
function SimHistogram({
  values,
  original,
  label,
  goodThreshold,
}: {
  values: number[];
  original: number;
  label: string;
  goodThreshold: number;
}) {
  if (!values.length) return null;
  const numBins = 15;
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 0.01;
  const step = range / numBins;
  const bins = Array.from({ length: numBins }, (_, i) => ({
    min: minV + i * step,
    max: minV + (i + 1) * step,
    count: 0,
  }));
  for (const v of values) {
    const idx = Math.min(Math.floor(((v - minV) / range) * numBins), numBins - 1);
    bins[idx].count++;
  }
  const maxCount = Math.max(...bins.map((b) => b.count), 1);

  return (
    <div>
      <div className="flex items-end gap-0.5" style={{ height: 80 }}>
        {bins.map((bin, i) => {
          const h = Math.max(2, (bin.count / maxCount) * 80);
          const mid = (bin.min + bin.max) / 2;
          const isOrigBin = original >= bin.min && original < bin.max;
          const color = isOrigBin
            ? "#00ffb2"
            : mid >= goodThreshold
            ? "#3a8a6a"
            : "#2a3a5a";
          return (
            <div
              key={i}
              title={`${label} ${bin.min.toFixed(2)}–${bin.max.toFixed(2)}: ${bin.count} paths`}
              style={{ height: h, background: color, flex: 1 }}
            />
          );
        })}
      </div>
      <div className="flex justify-between mt-1">
        <span className="text-[9px] font-mono text-[#3a4a41]">{minV.toFixed(2)}</span>
        <span className="text-[9px] font-mono text-[#3a4a41]">{maxV.toFixed(2)}</span>
      </div>
    </div>
  );
}

function SimRobustnessCard({
  origSharpe,
  p25Sharpe,
  p50Sharpe,
  simType,
}: {
  origSharpe: number;
  p25Sharpe: number;
  p50Sharpe: number;
  simType: string;
}) {
  const degradation = origSharpe > 0 ? p50Sharpe / origSharpe : 0;
  const isRobust = degradation >= 0.65 && p25Sharpe > 0.5;
  return (
    <div className={`flex items-center gap-3 p-4 border-l-4 ${
      isRobust ? "border-[#00ffb2] bg-[#00ffb2]/5" : "border-[#ffd580] bg-[#ffd580]/5"
    }`}>
      <div className="flex-1">
        <div className="flex items-center gap-2 mb-1">
          <span className={`w-2 h-2 rounded-full ${isRobust ? "bg-[#00ffb2]" : "bg-[#ffd580]"}`} />
          <span className="text-[10px] font-mono text-[#83958a] uppercase tracking-widest">
            Simulation Robustness — {simType === "block_bootstrap" ? "Block Bootstrap" : simType === "monte_carlo" ? "Monte Carlo" : "Jackknife"}
          </span>
        </div>
        <p className="text-xs font-headline font-bold text-[#e0e2ea]">
          {isRobust
            ? `ROBUST — Median sim Sharpe is ${(degradation * 100).toFixed(0)}% of original across synthetic paths`
            : `FRAGILE — Median sim Sharpe drops to ${(degradation * 100).toFixed(0)}% of original — strategy may be overfit`}
        </p>
        <p className="text-[10px] font-mono text-[#83958a] mt-1">
          Original: {origSharpe.toFixed(3)} · Sim median: {p50Sharpe.toFixed(3)} · Sim p25: {p25Sharpe.toFixed(3)}
        </p>
      </div>
      <span className={`shrink-0 px-4 py-2 text-[10px] font-headline font-black uppercase tracking-widest border ${
        isRobust
          ? "border-[#00ffb2]/40 text-[#00ffb2] bg-[#00ffb2]/10"
          : "border-[#ffd580]/40 text-[#ffd580] bg-[#ffd580]/10"
      }`}>
        {isRobust ? "ROBUST" : "FRAGILE"}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stability Heatmap component
// ---------------------------------------------------------------------------
function StabilityHeatmap({ map }: { map: StabilityMap }) {
  if (map.type === "none") return null;

  if (map.type === "1d") {
    const maxSharpe = Math.max(...map.points.map((p) => p.sharpe), 0.01);
    const minSharpe = Math.min(...map.points.map((p) => p.sharpe));
    return (
      <div className="w-full">
        <p className="text-[10px] font-mono text-[#83958a] uppercase tracking-wider mb-3">
          Sharpe by {map.x_label}
        </p>
        <div className="flex items-end gap-1" style={{ height: 100 }}>
          {map.points.map((pt) => {
            const norm = (pt.sharpe - minSharpe) / (maxSharpe - minSharpe || 1);
            const h = Math.max(4, norm * 100);
            const color = pt.sharpe >= 1.2 ? "#00ffb2" : pt.sharpe >= 0.6 ? "#ffd580" : "#ffb3ac";
            return (
              <div key={pt.x} className="flex-1 flex flex-col items-center gap-1" title={`${map.x_label}=${pt.x}, Sharpe=${pt.sharpe.toFixed(3)}`}>
                <div style={{ height: h, background: color, width: "100%", minWidth: 12 }} />
                <span className="text-[8px] font-mono text-[#83958a]">{pt.x}</span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  if (map.type === "2d") {
    const allSharpes = map.rows.flatMap((r) => r.cells.map((c) => c.sharpe)).filter((s): s is number => s !== null);
    const maxS = Math.max(...allSharpes, 0.01);
    const minS = Math.min(...allSharpes);

    function sharpeToColor(s: number | null): string {
      if (s === null) return "#262a30";
      const t = (s - minS) / (maxS - minS || 1);
      if (t >= 0.67) return `rgba(0,255,178,${0.3 + t * 0.6})`;
      if (t >= 0.33) return `rgba(255,213,128,${0.3 + t * 0.4})`;
      return `rgba(255,179,172,${0.3 + (1 - t) * 0.4})`;
    }

    return (
      <div className="overflow-x-auto hide-scrollbar">
        <table className="border-collapse text-[10px] font-mono">
          <thead>
            <tr>
              <th className="px-2 py-1 text-[#83958a] text-right pr-3">{map.y_label} ↓ / {map.x_label} →</th>
              {map.x_vals.map((x) => (
                <th key={x} className="px-3 py-1 text-[#83958a] text-center">{x}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {map.rows.map((row) => (
              <tr key={row.y_val}>
                <td className="px-2 py-1 text-[#83958a] text-right pr-3 whitespace-nowrap">{row.y_val}</td>
                {row.cells.map((cell, ci) => (
                  <td
                    key={ci}
                    className="px-3 py-2 text-center"
                    style={{ background: sharpeToColor(cell.sharpe), minWidth: 60 }}
                    title={`${map.y_label}=${cell.y}, ${map.x_label}=${cell.x}, Sharpe=${cell.sharpe?.toFixed(3) ?? "N/A"}`}
                  >
                    {cell.sharpe !== null ? cell.sharpe.toFixed(2) : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center gap-3 mt-3">
          <div className="w-4 h-3" style={{ background: "rgba(255,179,172,0.7)" }} />
          <span className="text-[9px] font-mono text-[#83958a]">Low</span>
          <div className="w-4 h-3" style={{ background: "rgba(255,213,128,0.7)" }} />
          <span className="text-[9px] font-mono text-[#83958a]">Mid</span>
          <div className="w-4 h-3" style={{ background: "rgba(0,255,178,0.9)" }} />
          <span className="text-[9px] font-mono text-[#83958a]">High Sharpe</span>
        </div>
      </div>
    );
  }

  return null;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
type View = "explorer" | "summary" | "optimizer" | "insights" | "simulation";
type OptObjective = "sharpe" | "cagr" | "max_drawdown" | "profit_factor";

export default function Home() {
  // ---- catalog ----
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  // ---- selectors ----
  const [selStrategy, setSelStrategy] = useState<string>("");
  const [selSymbol, setSelSymbol] = useState<string>("");
  const [selTimeframe, setSelTimeframe] = useState<string>("1d");

  // ---- explorer ----
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [explorerLoading, setExplorerLoading] = useState(false);
  const [explorerError, setExplorerError] = useState<string | null>(null);

  // ---- summary ----
  const [summaryRows, setSummaryRows] = useState<SummaryRow[]>([]);
  const [summaryMeta, setSummaryMeta] = useState<{
    total_runs?: number;
    gate1_passes?: number;
    opt_params_used?: number;
  }>({});
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  // ---- optimizer ----
  const [optResult, setOptResult] = useState<OptimizeResult | null>(null);
  const [optLoading, setOptLoading] = useState(false);
  const [optError, setOptError] = useState<string | null>(null);
  const [optFor, setOptFor] = useState<{ strategy: string; symbol: string } | null>(null);

  // ---- insights ----
  const [insights, setInsights] = useState<InsightsResult | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [insightsNeedsKey, setInsightsNeedsKey] = useState(false);
  const [insightsFor, setInsightsFor] = useState<{ strategy: string; symbol: string } | null>(null);

  // ---- simulation ----
  const [simResult, setSimResult] = useState<SimulationResult | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);
  const [simType, setSimType] = useState<"block_bootstrap" | "jackknife" | "monte_carlo">("block_bootstrap");
  const [simNSims, setSimNSims] = useState<number>(50);

  // ---- optimizer objective (for all strategies) ----
  const [optObjective, setOptObjective] = useState<OptObjective>("sharpe");

  // ---- optimization queue ----
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [queueRunning, setQueueRunning] = useState(false);
  const [savedOptParams, setSavedOptParams] = useState<Record<string, unknown>>({});

  // ---- nav ----
  const [view, setView] = useState<View>("summary"); // default to summary so results show on load

  // ---- tutorial ----
  const [tutorialStep, setTutorialStep] = useState<number | null>(null); // null = hidden

  // ---- derived ----
  const uniqueSymbols = [...new Set(symbols.map((s) => s.symbol))];
  const availableTFs = selSymbol
    ? [...new Set(symbols.filter((s) => s.symbol === selSymbol).map((s) => s.timeframe))]
    : [];
  const roundTrips = result ? computeRoundTrips(result.fills) : [];

  // ---- load catalog + saved opt params ----
  useEffect(() => {
    async function load() {
      try {
        const [symRes, stratRes] = await Promise.all([
          fetch("/api/symbols"),
          fetch("/api/strategies"),
        ]);
        if (!symRes.ok || !stratRes.ok) throw new Error("API error");
        const [symData, stratData] = await Promise.all([
          symRes.json(),
          stratRes.json(),
        ]);
        if (symData.error) throw new Error(symData.error);
        if (stratData.error) throw new Error(stratData.error);
        const syms: SymbolInfo[] = symData.symbols ?? [];
        const strats: StrategyInfo[] = stratData.strategies ?? [];
        setSymbols(syms);
        setStrategies(strats);
        if (strats.length) setSelStrategy(strats[0].key);
        if (syms.length) {
          setSelSymbol(syms[0].symbol);
          setSelTimeframe(syms[0].timeframe);
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setCatalogError(`Could not load data catalog: ${msg}`);
      }
    }
    load();
    // Load any previously saved optimized params (best-effort, ignore errors)
    fetch("/api/opt-params").then(r => r.json()).then(d => {
      if (d && typeof d === "object" && !d.error) setSavedOptParams(d);
    }).catch(() => {});
  }, []);

  // ---- auto-run summary on first load ----
  useEffect(() => {
    runSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- show tutorial on first ever visit ----
  useEffect(() => {
    try {
      if (!localStorage.getItem("alphasmart_tutorial_seen")) {
        // Small delay so the page has rendered before we spotlight elements
        setTimeout(() => goToStep(0), 400);
      }
    } catch {
      // SSR / private browsing — skip tutorial
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally only on mount

  // ---- run single backtest ----
  const runBacktest = useCallback(async () => {
    if (!selStrategy || !selSymbol) return;
    setExplorerLoading(true);
    setExplorerError(null);
    setResult(null);
    try {
      const url = `/api/backtest?strategy=${encodeURIComponent(selStrategy)}&symbol=${encodeURIComponent(selSymbol)}&timeframe=${selTimeframe}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error ?? `HTTP ${res.status}`);
      setResult(data as BacktestResult);
    } catch (e: unknown) {
      setExplorerError(e instanceof Error ? e.message : String(e));
    } finally {
      setExplorerLoading(false);
    }
  }, [selStrategy, selSymbol, selTimeframe]);

  // ---- run all strategies ----
  const runSummary = useCallback(async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const res = await fetch("/api/summary");
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error ?? `HTTP ${res.status}`);
      setSummaryRows(data.results ?? []);
      setSummaryMeta({ total_runs: data.total_runs, gate1_passes: data.gate1_passes, opt_params_used: data.opt_params_used });
    } catch (e: unknown) {
      setSummaryError(e instanceof Error ? e.message : String(e));
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  // ---- run optimization ----
  const runOptimization = useCallback(async () => {
    if (!selStrategy || !selSymbol) return;
    setOptLoading(true);
    setOptError(null);
    setOptResult(null);
    setOptFor({ strategy: selStrategy, symbol: selSymbol });
    setView("optimizer");
    try {
      const url = `/api/optimize?strategy=${encodeURIComponent(selStrategy)}&symbol=${encodeURIComponent(selSymbol)}&timeframe=${selTimeframe}&objective=${optObjective}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error ?? `HTTP ${res.status}`);
      setOptResult(data as OptimizeResult);
    } catch (e: unknown) {
      setOptError(e instanceof Error ? e.message : String(e));
    } finally {
      setOptLoading(false);
    }
  }, [selStrategy, selSymbol, selTimeframe, optObjective]);

  // ---- add current selection to optimization queue ----
  const addToQueue = useCallback(() => {
    if (!selStrategy || !selSymbol) return;
    const stratLabel = strategies.find(s => s.key === selStrategy)?.label ?? selStrategy;
    const id = Math.random().toString(36).slice(2);
    setQueue(prev => [...prev, {
      id,
      strategy: selStrategy,
      strategyLabel: stratLabel,
      symbol: selSymbol,
      timeframe: selTimeframe,
      objective: optObjective,
      status: "pending",
    }]);
  }, [selStrategy, selSymbol, selTimeframe, optObjective, strategies]);

  // ---- save the current opt result to persistent store ----
  const saveCurrentOpt = useCallback(async () => {
    if (!optResult || !optFor) return;
    try {
      await fetch("/api/opt-params", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy: optFor.strategy,
          symbol: optFor.symbol,
          timeframe: selTimeframe,
          objective: optObjective,
          params: optResult.best_params,
          sharpe: optResult.best_sharpe,
          cagr: optResult.best_cagr,
          max_drawdown: optResult.best_max_drawdown,
          gate2_pass: optResult.gate2_pass,
        }),
      });
      const key = `${optFor.strategy}::${optFor.symbol}::${selTimeframe}`;
      setSavedOptParams(prev => ({ ...prev, [key]: optResult.best_params }));
    } catch (e) {
      console.error("Failed to save opt params:", e);
    }
  }, [optResult, optFor, selTimeframe, optObjective]);

  // ---- run all pending queue items sequentially ----
  const runQueue = useCallback(async () => {
    setQueueRunning(true);
    const pending = queue.filter(q => q.status === "pending");
    for (const item of pending) {
      setQueue(prev => prev.map(q => q.id === item.id ? { ...q, status: "running" } : q));
      try {
        const url = `/api/optimize?strategy=${encodeURIComponent(item.strategy)}&symbol=${encodeURIComponent(item.symbol)}&timeframe=${item.timeframe}&objective=${item.objective}`;
        const res = await fetch(url);
        const data = await res.json() as OptimizeResult & { error?: string };
        if (data.error) throw new Error(data.error);
        await fetch("/api/opt-params", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            strategy: item.strategy,
            symbol: item.symbol,
            timeframe: item.timeframe,
            objective: item.objective,
            params: data.best_params,
            sharpe: data.best_sharpe,
            cagr: data.best_cagr,
            max_drawdown: data.best_max_drawdown,
            gate2_pass: data.gate2_pass,
          }),
        });
        const key = `${item.strategy}::${item.symbol}::${item.timeframe}`;
        setSavedOptParams(prev => ({ ...prev, [key]: data.best_params }));
        setQueue(prev => prev.map(q => q.id === item.id ? { ...q, status: "done", result: data } : q));
      } catch (e) {
        setQueue(prev => prev.map(q => q.id === item.id ? { ...q, status: "error", errorMsg: String(e) } : q));
      }
    }
    setQueueRunning(false);
  }, [queue]);

  // ---- run insights ----
  const runInsights = useCallback(async () => {
    if (!selStrategy || !selSymbol) return;
    setInsightsLoading(true);
    setInsightsError(null);
    setInsights(null);
    setInsightsNeedsKey(false);
    setInsightsFor({ strategy: selStrategy, symbol: selSymbol });
    setView("insights");
    try {
      const url = `/api/insights?strategy=${encodeURIComponent(selStrategy)}&symbol=${encodeURIComponent(selSymbol)}&timeframe=${selTimeframe}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.needs_api_key) { setInsightsNeedsKey(true); return; }
      if (!res.ok || data.error) throw new Error(data.error ?? `HTTP ${res.status}`);
      setInsights(data.insights as InsightsResult);
    } catch (e: unknown) {
      setInsightsError(e instanceof Error ? e.message : String(e));
    } finally {
      setInsightsLoading(false);
    }
  }, [selStrategy, selSymbol, selTimeframe]);

  // ---- run simulation ----
  const runSimulation = useCallback(async () => {
    if (!selStrategy || !selSymbol) return;
    setSimLoading(true);
    setSimError(null);
    setSimResult(null);
    setView("simulation");
    try {
      const url = `/api/simulate?strategy=${encodeURIComponent(selStrategy)}&symbol=${encodeURIComponent(selSymbol)}&timeframe=${selTimeframe}&sim_type=${simType}&n_sims=${simNSims}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error ?? `HTTP ${res.status}`);
      setSimResult(data as SimulationResult);
    } catch (e: unknown) {
      setSimError(e instanceof Error ? e.message : String(e));
    } finally {
      setSimLoading(false);
    }
  }, [selStrategy, selSymbol, selTimeframe, simType, simNSims]);

  // ---- auto-run backtest when selector changes ----
  useEffect(() => {
    if (selStrategy && selSymbol && selTimeframe) {
      runBacktest();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selStrategy, selSymbol, selTimeframe]);

  // ---- click summary row → switch to explorer with that run ----
  const handleSummaryRowClick = useCallback((row: SummaryRow) => {
    setSelStrategy(row.strategy);
    setSelSymbol(row.symbol);
    setSelTimeframe(row.timeframe);
    setView("explorer");
  }, []);

  // ---- tutorial controls ----
  const closeTutorial = useCallback(() => {
    setTutorialStep(null);
    try { localStorage.setItem("alphasmart_tutorial_seen", "1"); } catch { /* ignore */ }
  }, []);

  // Switch view if the next step requires it, then advance
  const goToStep = useCallback((idx: number) => {
    if (idx < 0 || idx >= TUTORIAL_STEPS.length) { closeTutorial(); return; }
    const next = TUTORIAL_STEPS[idx];
    if (next.requiresView) setView(next.requiresView);
    setTutorialStep(idx);
  }, [closeTutorial]);

  const nextStep = useCallback(() => {
    if (tutorialStep === null) return;
    if (tutorialStep >= TUTORIAL_STEPS.length - 1) { closeTutorial(); return; }
    goToStep(tutorialStep + 1);
  }, [tutorialStep, goToStep, closeTutorial]);

  const prevStep = useCallback(() => {
    if (tutorialStep === null || tutorialStep === 0) return;
    goToStep(tutorialStep - 1);
  }, [tutorialStep, goToStep]);

  // ============================================================
  return (
    <div className="flex min-h-screen">
      {/* Ambient glows */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
        <div className="absolute top-[20%] right-[10%] w-[500px] h-[500px] bg-[#00ffb2]/4 blur-[120px] rounded-full" />
        <div className="absolute bottom-[10%] left-[15%] w-[400px] h-[400px] bg-[#ffb3ac]/3 blur-[100px] rounded-full" />
      </div>

      {/* ============================================================
          TUTORIAL
          ============================================================ */}
      {tutorialStep !== null && (
        <TutorialOverlay
          step={TUTORIAL_STEPS[tutorialStep]}
          stepIndex={tutorialStep}
          total={TUTORIAL_STEPS.length}
          onNext={nextStep}
          onPrev={prevStep}
          onClose={closeTutorial}
        />
      )}

      {/* ============================================================
          SIDEBAR
          ============================================================ */}
      <aside
        data-tour="sidebar"
        className="fixed left-0 top-0 h-screen flex flex-col z-40 w-64 bg-[#0a0e13]"
      >
        {/* Logo */}
        <div className="p-6 border-b border-[#3a4a41]/20">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-[#00ffb2] flex items-center justify-center shrink-0">
              <span className="text-[#003824] font-mono font-bold text-sm">α</span>
            </div>
            <div>
              <h2 className="font-mono text-xs uppercase text-[#00ffb2] font-bold tracking-widest">
                AlphaSMART
              </h2>
              <p className="font-mono text-[10px] uppercase text-[#83958a] opacity-70">
                Phase 3 — Optimization + AI
              </p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="py-3 border-b border-[#3a4a41]/20">
          <button
            onClick={() => setView("explorer")}
            className={`w-full flex items-center gap-3 px-6 py-3 font-mono text-xs uppercase transition-all ${
              view === "explorer"
                ? "bg-[#262a30] text-[#00ffb2] border-r-4 border-[#00ffb2]"
                : "text-[#83958a] hover:bg-[#181c21]"
            }`}
          >
            <span>📈</span>
            <span>Explorer</span>
          </button>
          <button
            data-tour="all-results-btn"
            onClick={() => setView("summary")}
            className={`w-full flex items-center gap-3 px-6 py-3 font-mono text-xs uppercase transition-all ${
              view === "summary"
                ? "bg-[#262a30] text-[#00ffb2] border-r-4 border-[#00ffb2]"
                : "text-[#83958a] hover:bg-[#181c21]"
            }`}
          >
            <span>📊</span>
            <span>All Results</span>
            {summaryRows.length > 0 && (
              <span className="ml-auto bg-[#262a30] text-[#83958a] text-[9px] font-mono px-1.5 py-0.5">
                {summaryRows.length}
              </span>
            )}
          </button>
          <button
            data-tour="optimizer-btn"
            onClick={() => setView("optimizer")}
            className={`w-full flex items-center gap-3 px-6 py-3 font-mono text-xs uppercase transition-all ${
              view === "optimizer"
                ? "bg-[#262a30] text-[#00ffb2] border-r-4 border-[#00ffb2]"
                : "text-[#83958a] hover:bg-[#181c21]"
            }`}
          >
            <span>⚡</span>
            <span>Optimizer</span>
            {optResult && (
              <span className={`ml-auto text-[9px] font-mono px-1.5 py-0.5 ${optResult.gate2_pass ? "text-[#00ffb2] bg-[#00ffb2]/10" : "text-[#ffb3ac] bg-[#ffb3ac]/10"}`}>
                {optResult.gate2_pass ? "G2✓" : "G2✗"}
              </span>
            )}
          </button>
          <button
            data-tour="insights-btn"
            onClick={() => setView("insights")}
            className={`w-full flex items-center gap-3 px-6 py-3 font-mono text-xs uppercase transition-all ${
              view === "insights"
                ? "bg-[#262a30] text-[#00ffb2] border-r-4 border-[#00ffb2]"
                : "text-[#83958a] hover:bg-[#181c21]"
            }`}
          >
            <span>🤖</span>
            <span>AI Insights</span>
          </button>
          <button
            data-tour="simulation-btn"
            onClick={() => setView("simulation")}
            className={`w-full flex items-center gap-3 px-6 py-3 font-mono text-xs uppercase transition-all ${
              view === "simulation"
                ? "bg-[#262a30] text-[#00ffb2] border-r-4 border-[#00ffb2]"
                : "text-[#83958a] hover:bg-[#181c21]"
            }`}
          >
            <span>🎲</span>
            <span>Simulation</span>
            {simResult && (
              <span className="ml-auto text-[9px] font-mono px-1.5 py-0.5 text-[#83958a] bg-[#262a30]">
                {simResult.n_simulations}
              </span>
            )}
          </button>
        </nav>

        {/* Selectors (explorer only) */}
        <div className="flex-1 overflow-y-auto hide-scrollbar px-4 pt-4 pb-4 space-y-3">
          {catalogError ? (
            <div className="p-3 bg-[#93000a]/20 border border-[#ffb4ab]/20">
              <p className="text-[10px] font-mono text-[#ffb4ab] leading-relaxed">
                {catalogError}
              </p>
            </div>
          ) : (
            <>
              <p className="text-[9px] font-mono text-[#3a4a41] uppercase tracking-widest pt-1">
                Configure Backtest
              </p>

              <div>
                <label className="text-[9px] font-mono text-[#83958a] uppercase tracking-wider block mb-1">
                  Strategy
                </label>
                {strategies.length === 0 ? (
                  <Skeleton className="h-8 w-full" />
                ) : (
                  <select
                    value={selStrategy}
                    onChange={(e) => setSelStrategy(e.target.value)}
                    className="w-full bg-[#1c2025] text-[#00ffb2] text-xs font-mono px-2 py-2 border border-[#3a4a41]/40 focus:outline-none focus:border-[#00ffb2]/50 appearance-none cursor-pointer"
                  >
                    {strategies.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div>
                <label className="text-[9px] font-mono text-[#83958a] uppercase tracking-wider block mb-1">
                  Symbol
                </label>
                {uniqueSymbols.length === 0 ? (
                  <Skeleton className="h-8 w-full" />
                ) : (
                  <select
                    value={selSymbol}
                    onChange={(e) => {
                      setSelSymbol(e.target.value);
                      const tfs = [
                        ...new Set(
                          symbols
                            .filter((s) => s.symbol === e.target.value)
                            .map((s) => s.timeframe)
                        ),
                      ];
                      setSelTimeframe(tfs[0] ?? "1d");
                    }}
                    className="w-full bg-[#1c2025] text-[#e0e2ea] text-xs font-mono px-2 py-2 border border-[#3a4a41]/40 focus:outline-none focus:border-[#00ffb2]/50 appearance-none cursor-pointer"
                  >
                    {uniqueSymbols.map((sym) => (
                      <option key={sym} value={sym}>
                        {sym}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div>
                <label className="text-[9px] font-mono text-[#83958a] uppercase tracking-wider block mb-1">
                  Timeframe
                </label>
                <select
                  value={selTimeframe}
                  onChange={(e) => setSelTimeframe(e.target.value)}
                  className="w-full bg-[#1c2025] text-[#e0e2ea] text-xs font-mono px-2 py-2 border border-[#3a4a41]/40 focus:outline-none focus:border-[#00ffb2]/50 appearance-none cursor-pointer"
                >
                  {(availableTFs.length ? availableTFs : ["1d"]).map((tf) => (
                    <option key={tf} value={tf}>
                      {tf}
                    </option>
                  ))}
                </select>
              </div>

              <button
                onClick={() => { setView("explorer"); runBacktest(); }}
                disabled={explorerLoading || !selStrategy || !selSymbol}
                className="w-full bg-[#00ffb2] text-[#003824] py-2.5 font-headline font-bold text-xs uppercase tracking-widest active:scale-95 transition-transform disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {explorerLoading ? "Running…" : "Run Backtest"}
              </button>

              {/* Optimization objective selector */}
              <div>
                <label className="text-[9px] font-mono text-[#3a4a41] uppercase tracking-widest block mb-1">
                  Optimize For
                </label>
                <select
                  value={optObjective}
                  onChange={(e) => setOptObjective(e.target.value as OptObjective)}
                  className="w-full bg-[#1c2025] text-[#83958a] text-[10px] font-mono px-2 py-1.5 border border-[#3a4a41]/40 focus:outline-none focus:border-[#00ffb2]/50 appearance-none cursor-pointer"
                >
                  <option value="sharpe">Max Sharpe Ratio</option>
                  <option value="cagr">Max CAGR</option>
                  <option value="max_drawdown">Min Max Drawdown</option>
                  <option value="profit_factor">Max Profit Factor</option>
                </select>
              </div>

              <button
                onClick={runOptimization}
                disabled={optLoading || !selStrategy || !selSymbol}
                className="w-full bg-[#1c2025] border border-[#3a4a41]/40 text-[#00ffb2] py-2 font-headline font-bold text-xs uppercase tracking-widest active:scale-95 transition-all hover:bg-[#262a30] disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {optLoading ? "Optimizing…" : "⚡ Run Optimization"}
              </button>

              <button
                onClick={addToQueue}
                disabled={!selStrategy || !selSymbol}
                className="w-full bg-[#1c2025] border border-[#00ffb2]/30 text-[#83958a] hover:text-[#00ffb2] hover:border-[#00ffb2]/60 py-2 font-headline font-bold text-xs uppercase tracking-widest active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                title="Add to optimization queue"
              >
                + Add to Queue {queue.length > 0 && `(${queue.length})`}
              </button>

              <button
                onClick={runInsights}
                disabled={insightsLoading || !selStrategy || !selSymbol}
                className="w-full bg-[#1c2025] border border-[#3a4a41]/40 text-[#83958a] py-2 font-headline font-bold text-xs uppercase tracking-widest active:scale-95 transition-all hover:bg-[#262a30] hover:text-[#e0e2ea] disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {insightsLoading ? "Analyzing…" : "🤖 AI Insights"}
              </button>

              {/* Simulation controls */}
              <div className="pt-2 border-t border-[#3a4a41]/20 space-y-2">
                <p className="text-[9px] font-mono text-[#3a4a41] uppercase tracking-widest">
                  Simulation
                </p>
                <div>
                  <label className="text-[9px] font-mono text-[#83958a] uppercase tracking-wider block mb-1">
                    Method
                  </label>
                  <select
                    value={simType}
                    onChange={(e) => setSimType(e.target.value as typeof simType)}
                    className="w-full bg-[#1c2025] text-[#83958a] text-[10px] font-mono px-2 py-1.5 border border-[#3a4a41]/40 focus:outline-none focus:border-[#00ffb2]/50 appearance-none cursor-pointer"
                  >
                    <option value="block_bootstrap">Block Bootstrap</option>
                    <option value="monte_carlo">Monte Carlo (GBM)</option>
                    <option value="jackknife">Jackknife</option>
                  </select>
                </div>
                {simType !== "jackknife" && (
                  <div>
                    <label className="text-[9px] font-mono text-[#83958a] uppercase tracking-wider block mb-1">
                      # Simulations
                    </label>
                    <select
                      value={simNSims}
                      onChange={(e) => setSimNSims(Number(e.target.value))}
                      className="w-full bg-[#1c2025] text-[#83958a] text-[10px] font-mono px-2 py-1.5 border border-[#3a4a41]/40 focus:outline-none focus:border-[#00ffb2]/50 appearance-none cursor-pointer"
                    >
                      <option value={25}>25 (fast)</option>
                      <option value={50}>50 (default)</option>
                      <option value={100}>100 (thorough)</option>
                    </select>
                  </div>
                )}
                <button
                  onClick={runSimulation}
                  disabled={simLoading || !selStrategy || !selSymbol}
                  className="w-full bg-[#1c2025] border border-[#3a4a41]/40 text-[#83958a] py-2 font-headline font-bold text-xs uppercase tracking-widest active:scale-95 transition-all hover:bg-[#262a30] hover:text-[#e0e2ea] disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {simLoading ? "Simulating…" : "🎲 Run Simulation"}
                </button>
              </div>

              {symbols.length > 0 && (
                <p className="text-[9px] font-mono text-[#3a4a41] pt-1">
                  {symbols.length} series in DB ·{" "}
                  {symbols.reduce((s, r) => s + (r.record_count ?? 0), 0)} bars total
                </p>
              )}
            </>
          )}
        </div>

        {/* Fetch hint */}
        {symbols.length === 0 && !catalogError && (
          <div className="px-4 pb-4">
            <div className="bg-[#1c2025] p-3 border border-[#3a4a41]/20">
              <p className="text-[9px] font-mono text-[#83958a] leading-relaxed">
                No data yet. From alphasmart/:
              </p>
              <code className="text-[9px] text-[#00ffb2] block mt-1">
                python main.py fetch AAPL
              </code>
            </div>
          </div>
        )}

        {/* Bottom controls */}
        <div className="px-4 pb-5 pt-3 border-t border-[#3a4a41]/20 space-y-2">
          <button
            onClick={() => goToStep(0)}
            className="w-full flex items-center gap-2 text-[10px] font-mono text-[#83958a] hover:text-[#e0e2ea] uppercase tracking-widest transition-colors py-1"
          >
            <span>?</span>
            <span>How to use this dashboard</span>
          </button>
        </div>
      </aside>

      {/* ============================================================
          MAIN
          ============================================================ */}
      <main className="flex-1 ml-64 min-h-screen flex flex-col relative z-10">
        {/* Top bar */}
        <header className="flex justify-between items-center px-6 py-3 bg-[#101419] border-b border-[#262a30] sticky top-0 z-20">
          <div className="flex items-center gap-6">
            <h1 className="text-xl font-black text-[#e0e2ea] tracking-tighter uppercase font-headline">
              AlphaSMART
            </h1>
            <nav className="hidden md:flex gap-5">
              {(["explorer", "summary", "optimizer", "insights"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`font-headline uppercase tracking-wider text-sm font-bold transition-colors pb-0.5 ${
                    view === v
                      ? "text-[#00ffb2] border-b-2 border-[#00ffb2]"
                      : "text-[#83958a] hover:text-[#e0e2ea]"
                  }`}
                >
                  {v === "explorer" ? "Explorer" : v === "summary" ? "All Results" : v === "optimizer" ? "Optimizer" : "AI Insights"}
                </button>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-4">
            {result && view === "explorer" && (
              <span className="hidden md:block text-xs font-mono text-[#83958a]">
                {result.date_range} · {result.metrics.n_bars} bars
              </span>
            )}
            <button
              onClick={() => goToStep(0)}
              className="w-7 h-7 border border-[#3a4a41] text-[#83958a] hover:text-[#00ffb2] hover:border-[#00ffb2]/40 text-xs font-mono transition-colors flex items-center justify-center"
              title="Open tutorial"
            >
              ?
            </button>
          </div>
        </header>

        {/* ============================================================
            SUMMARY VIEW
            ============================================================ */}
        {view === "summary" && (
          <div className="p-6 space-y-5 flex-1">
            {/* Header */}
            <div className="flex justify-between items-end">
              <div>
                <h2 className="text-2xl font-black font-headline tracking-tighter uppercase">
                  All Backtest Results
                </h2>
                <p className="text-xs font-mono text-[#83958a] mt-1">
                  All 15 strategies × every symbol in your database, ranked by composite score
                </p>
              </div>
              <button
                onClick={runSummary}
                disabled={summaryLoading}
                className="bg-[#1c2025] border border-[#3a4a41]/40 text-[#00ffb2] px-4 py-2 text-[10px] font-mono font-bold uppercase tracking-widest hover:bg-[#262a30] transition-colors disabled:opacity-40"
              >
                {summaryLoading ? "Computing…" : "↺  Refresh All"}
              </button>
            </div>

            {/* Error */}
            {summaryError && (
              <div className="bg-[#93000a]/20 border-l-4 border-[#ffb4ab] p-4">
                <p className="text-sm font-mono text-[#ffb4ab]">{summaryError}</p>
              </div>
            )}

            {/* Loading skeletons */}
            {summaryLoading && (
              <div className="space-y-4">
                <div className="bg-[#1c2025] p-6 flex items-center gap-5">
                  <div className="w-5 h-5 border-2 border-[#00ffb2] border-t-transparent rounded-full animate-spin shrink-0" />
                  <div>
                    <p className="text-sm font-mono text-[#e0e2ea]">
                      Running all strategy combinations…
                    </p>
                    <p className="text-xs font-mono text-[#83958a] mt-1">
                      15 strategies × {uniqueSymbols.length || "?"} symbols. This takes 30–120 seconds depending on data volume.
                    </p>
                  </div>
                </div>
                {/* Strategy progress indicators */}
                <div className="grid grid-cols-5 gap-3">
                  {["EMA Crossover", "RSI Reversion", "ATR Breakout", "MACD Momentum", "Alpha Composite ✦"].map((s) => (
                    <div key={s} className="bg-[#1c2025] p-4 border border-[#3a4a41]/10">
                      <p className="text-[9px] font-mono text-[#83958a] uppercase tracking-wider mb-2">{s}</p>
                      <Skeleton className="h-4 w-3/4 mb-1" />
                      <Skeleton className="h-3 w-1/2" />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Results */}
            {!summaryLoading && summaryRows.length > 0 && (
              <>
                {/* Stats bar */}
                <div className="grid grid-cols-5 bg-[#1c2025] border border-[#3a4a41]/20">
                  <MetricCard label="Total Runs" value={String(summaryMeta.total_runs ?? summaryRows.length)} />
                  <MetricCard
                    label="Gate 1 Passes"
                    value={String(summaryMeta.gate1_passes ?? summaryRows.filter((r) => r.gate1_pass).length)}
                    color="text-[#00ffb2]"
                  />
                  <MetricCard
                    label="Best Sharpe"
                    value={num2(Math.max(...summaryRows.map((r) => r.sharpe)))}
                    color="text-[#00ffb2]"
                  />
                  <MetricCard
                    label="Best CAGR"
                    value={pct(Math.max(...summaryRows.map((r) => r.cagr)))}
                    color="text-[#00ffb2]"
                  />
                  <MetricCard
                    label="✦ Optimized"
                    value={String(summaryMeta.opt_params_used ?? summaryRows.filter((r) => r.is_optimized).length)}
                    color={(summaryMeta.opt_params_used ?? 0) > 0 ? "text-[#00ffb2]" : "text-[#83958a]"}
                  />
                </div>

                {/* Scoring explanation */}
                <div className="bg-[#1c2025] px-5 py-3 border-l-4 border-[#00ffb2]/30 flex items-start gap-3">
                  <span className="text-[#00ffb2] text-xs mt-0.5">ℹ</span>
                  <div>
                    <p className="text-[10px] font-mono text-[#83958a]">
                      <span className="text-[#e0e2ea] font-bold">Composite Score</span> =
                      Sharpe × 40% + CAGR × 30% + DrawdownResistance × 20% + WinRate × 10%.
                      Losing strategies (negative total return) score 0 and rank last.
                    </p>
                    <p className="text-[10px] font-mono text-[#83958a] mt-1">
                      Click any row to open it in the Explorer →
                    </p>
                  </div>
                </div>

                {/* Table */}
                <div className="bg-[#181c21] overflow-hidden">
                  <SummaryTable rows={summaryRows} onSelectRow={handleSummaryRowClick} />
                </div>
              </>
            )}

            {/* No data state */}
            {!summaryLoading && !summaryError && summaryRows.length === 0 && (
              <div className="bg-[#1c2025] p-10 text-center space-y-4">
                <p className="text-lg font-mono text-[#e0e2ea]">No results yet</p>
                <p className="text-sm font-mono text-[#83958a]">
                  The summary runs automatically on page load. If it failed, check that
                  you have data in the database:
                </p>
                <code className="text-sm text-[#00ffb2] block">
                  python main.py fetch AAPL --period 5y
                </code>
                <button
                  onClick={runSummary}
                  className="bg-[#00ffb2] text-[#003824] px-6 py-2.5 font-headline font-bold text-xs uppercase tracking-widest"
                >
                  Retry
                </button>
              </div>
            )}
          </div>
        )}

        {/* ============================================================
            EXPLORER VIEW
            ============================================================ */}
        {view === "explorer" && (
          <div className="p-6 space-y-5 flex-1">
            {/* Header */}
            <div>
              <h2 className="text-2xl font-black font-headline tracking-tighter uppercase">
                Backtest Explorer
              </h2>
              {result && (
                <p className="text-xs font-mono text-[#83958a] mt-1">
                  {result.strategy_label} · {result.symbol} · {result.timeframe.toUpperCase()} · {result.metrics.n_bars} bars
                </p>
              )}
            </div>

            {/* Error */}
            {explorerError && !explorerLoading && (
              <div className="bg-[#93000a]/20 border-l-4 border-[#ffb4ab] p-4">
                <p className="text-sm font-mono text-[#ffb4ab]">{explorerError}</p>
                <p className="text-xs font-mono text-[#83958a] mt-2">
                  Make sure you have data: <code className="text-[#00ffb2]">python main.py fetch AAPL --period 5y</code>
                </p>
              </div>
            )}

            {/* Loading skeletons */}
            {explorerLoading && (
              <div className="space-y-4">
                <div className="bg-[#1c2025] p-5 flex items-center gap-4">
                  <div className="w-4 h-4 border-2 border-[#00ffb2] border-t-transparent rounded-full animate-spin shrink-0" />
                  <span className="text-sm font-mono text-[#83958a]">
                    Running {strategies.find((s) => s.key === selStrategy)?.label} on {selSymbol}…
                  </span>
                </div>
                <div className="grid grid-cols-5 bg-[#1c2025] border border-[#3a4a41]/20">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="p-5 border-r border-[#3a4a41]/20 last:border-r-0">
                      <Skeleton className="h-3 w-16 mb-3" />
                      <Skeleton className="h-7 w-20" />
                    </div>
                  ))}
                </div>
                <div className="bg-[#181c21] p-5 h-[320px] flex flex-col">
                  <Skeleton className="h-4 w-48 mb-4" />
                  <Skeleton className="flex-1 w-full" />
                </div>
              </div>
            )}

            {/* No selection prompt */}
            {!explorerLoading && !explorerError && !result && !catalogError && (
              <div className="bg-[#1c2025] p-10 text-center">
                <p className="text-sm font-mono text-[#83958a]">
                  Select a strategy and symbol in the sidebar to run a backtest
                </p>
              </div>
            )}

            {/* Results */}
            {result && !explorerLoading && (
              <>
                {/* Gate 1 */}
                <Gate1Badge pass={result.metrics.gate1_pass} />

                {/* Primary metrics */}
                <div
                  data-tour="metrics-bar"
                  className="grid grid-cols-5 bg-[#1c2025] border border-[#3a4a41]/20"
                >
                  <MetricCard
                    label="Sharpe Ratio"
                    value={num2(result.metrics.sharpe)}
                    color={result.metrics.sharpe >= 1.2 ? "text-[#00ffb2]" : "text-[#ffb3ac]"}
                  />
                  <MetricCard
                    label="Max Drawdown"
                    value={`-${pct(result.metrics.max_drawdown)}`}
                    color="text-[#ffb3ac]"
                  />
                  <MetricCard
                    label="CAGR"
                    value={pct(result.metrics.cagr)}
                    color={result.metrics.cagr >= 0 ? "text-[#e0e2ea]" : "text-[#ffb3ac]"}
                  />
                  <MetricCard label="Win Rate" value={pct(result.metrics.win_rate)} />
                  <MetricCard
                    label="Profit Factor"
                    value={isFinite(result.metrics.profit_factor) ? num2(result.metrics.profit_factor) : "∞"}
                  />
                </div>

                {/* Secondary metrics */}
                <div className="grid grid-cols-4 gap-3">
                  {[
                    {
                      label: "Total Return",
                      value: pctSigned(result.metrics.total_return),
                      color: result.metrics.total_return >= 0 ? "text-[#00ffb2]" : "text-[#ffb3ac]",
                    },
                    { label: "Sortino", value: num2(result.metrics.sortino) },
                    { label: "Trades", value: String(result.metrics.trade_count) },
                    { label: "Exposure", value: pct(result.metrics.exposure) },
                    {
                      label: "Avg Trade",
                      value: pctSigned(result.metrics.avg_trade_return),
                      color: result.metrics.avg_trade_return >= 0 ? "text-[#00ffb2]" : "text-[#ffb3ac]",
                    },
                    { label: "Best Trade", value: pctSigned(result.metrics.best_trade), color: "text-[#00ffb2]" },
                    { label: "Worst Trade", value: pctSigned(result.metrics.worst_trade), color: "text-[#ffb3ac]" },
                    {
                      label: "Final Value",
                      value: dollars(result.initial_capital * (1 + result.metrics.total_return)),
                    },
                  ].map((m) => (
                    <div key={m.label} className="bg-[#1c2025] px-4 py-3 border border-[#3a4a41]/10">
                      <p className="text-[10px] font-mono text-[#83958a] uppercase tracking-wider mb-1">
                        {m.label}
                      </p>
                      <p className={`text-sm font-mono font-bold ${m.color ?? "text-[#e0e2ea]"}`}>
                        {m.value}
                      </p>
                    </div>
                  ))}
                </div>

                {/* Halt warning */}
                {result.halted && (
                  <div className="bg-[#93000a]/20 border-l-4 border-[#ffb4ab] p-3 flex items-center gap-3">
                    <span className="text-[#ffb4ab]">⚠</span>
                    <p className="text-xs font-mono text-[#ffb4ab]">
                      Backtest halted early: {result.halt_reason}
                    </p>
                  </div>
                )}

                {/* Equity curve */}
                <div data-tour="equity-chart" className="bg-[#181c21] p-5">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a]">
                      Equity Growth vs Buy &amp; Hold
                    </h3>
                    <div className="flex gap-5">
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-0.5 bg-[#00ffb2]" />
                        <span className="text-[10px] font-mono text-[#83958a] uppercase">
                          {result.strategy_label}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <svg width="24" height="2">
                          <line x1="0" y1="1" x2="24" y2="1" stroke="#83958a" strokeWidth="1.5" strokeDasharray="4 3" />
                        </svg>
                        <span className="text-[10px] font-mono text-[#83958a] uppercase">
                          Buy &amp; Hold
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="h-[260px]">
                    <EquityCurveChart
                      equityCurve={result.equity_curve}
                      benchmark={result.benchmark}
                    />
                  </div>
                </div>

                {/* Bottom grid */}
                <div data-tour="trade-section" className="grid grid-cols-12 gap-5">
                  {/* Histogram */}
                  <div className="col-span-12 lg:col-span-4 bg-[#181c21] p-5">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a] mb-5">
                      Trade P/L Distribution
                    </h3>
                    <div className="h-[140px]">
                      <TradeDistribution trips={roundTrips} />
                    </div>
                    <p className="text-[10px] font-mono text-[#83958a] mt-3">
                      {roundTrips.filter((t) => t.pnlPct >= 0).length} winners ·{" "}
                      {roundTrips.filter((t) => t.pnlPct < 0).length} losers ·{" "}
                      {roundTrips.length} total round-trips
                    </p>
                  </div>

                  {/* Trade log */}
                  <div className="col-span-12 lg:col-span-8 bg-[#181c21]">
                    <div className="px-5 py-4 border-b border-[#3a4a41]/20 flex justify-between items-center">
                      <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a]">
                        Detailed Trade Log
                      </h3>
                      <span className="text-[10px] font-mono text-[#83958a]">
                        {roundTrips.length} round-trips
                      </span>
                    </div>
                    <TradeLog trips={roundTrips} />
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ============================================================
            OPTIMIZER VIEW
            ============================================================ */}
        {view === "optimizer" && (
          <div className="p-6 space-y-5 flex-1">
            <div className="flex justify-between items-end">
              <div>
                <h2 className="text-2xl font-black font-headline tracking-tighter uppercase">
                  Optimization Lab
                </h2>
                <p className="text-xs font-mono text-[#83958a] mt-1">
                  {optFor
                    ? `${strategies.find((s) => s.key === optFor.strategy)?.label ?? optFor.strategy} · ${optFor.symbol} · parameter grid search + walk-forward`
                    : "Select strategy + symbol, then click Run Optimization"}
                </p>
              </div>
              <button
                onClick={runOptimization}
                disabled={optLoading || !selStrategy || !selSymbol}
                className="bg-[#00ffb2] text-[#003824] px-5 py-2 text-[10px] font-mono font-bold uppercase tracking-widest hover:opacity-90 transition-opacity disabled:opacity-40"
              >
                {optLoading ? "Running…" : "⚡ Run Optimization"}
              </button>
            </div>

            {optError && (
              <div className="bg-[#93000a]/20 border-l-4 border-[#ffb4ab] p-4">
                <p className="text-sm font-mono text-[#ffb4ab]">{optError}</p>
              </div>
            )}

            {optLoading && (
              <div className="space-y-4">
                <div className="bg-[#1c2025] p-6 flex items-center gap-5">
                  <div className="w-5 h-5 border-2 border-[#00ffb2] border-t-transparent rounded-full animate-spin shrink-0" />
                  <div>
                    <p className="text-sm font-mono text-[#e0e2ea]">Running parameter grid search…</p>
                    <p className="text-xs font-mono text-[#83958a] mt-1">
                      Testing all valid combinations + 2-fold walk-forward validation. This takes 1–5 minutes.
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  {["Grid Search", "Walk-Forward Fold 1", "Walk-Forward Fold 2"].map((s) => (
                    <div key={s} className="bg-[#1c2025] p-5 border border-[#3a4a41]/10">
                      <p className="text-[9px] font-mono text-[#83958a] uppercase tracking-wider mb-2">{s}</p>
                      <Skeleton className="h-4 w-3/4 mb-1" />
                      <Skeleton className="h-3 w-1/2" />
                    </div>
                  ))}
                </div>
                <Skeleton className="h-40 w-full" />
              </div>
            )}

            {!optLoading && !optResult && !optError && (
              <div className="space-y-5">
                <div className="bg-[#1c2025] p-10 text-center space-y-3">
                  <p className="text-sm font-mono text-[#e0e2ea]">No optimization run yet</p>
                  <p className="text-xs font-mono text-[#83958a]">
                    Select a strategy + symbol, then click "Run Optimization" in the sidebar or above. Or queue multiple combinations below.
                  </p>
                </div>
                {/* Queue panel visible even before first run */}
                <div className="bg-[#181c21]">
                  <div className="px-5 py-4 border-b border-[#3a4a41]/20 flex items-center justify-between">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a]">
                      Optimization Queue
                    </h3>
                    <div className="flex items-center gap-3">
                      {queue.filter(q => q.status === "pending").length > 0 && (
                        <button
                          onClick={runQueue}
                          disabled={queueRunning}
                          className="bg-[#00ffb2] text-[#003824] px-4 py-1.5 text-[10px] font-mono font-bold uppercase tracking-widest hover:opacity-90 transition-opacity disabled:opacity-40"
                        >
                          {queueRunning ? "Running…" : `▶ Run All (${queue.filter(q => q.status === "pending").length})`}
                        </button>
                      )}
                      {queue.length > 0 && !queueRunning && (
                        <button onClick={() => setQueue([])} className="text-[10px] font-mono text-[#3a4a41] hover:text-[#83958a] uppercase tracking-widest transition-colors">
                          Clear
                        </button>
                      )}
                    </div>
                  </div>
                  {queue.length === 0 ? (
                    <div className="px-5 py-6 text-center">
                      <p className="text-[10px] font-mono text-[#3a4a41]">
                        Use "+ Add to Queue" in the sidebar to batch-optimize multiple strategy × symbol combinations, then click "Run All".
                      </p>
                    </div>
                  ) : (
                    <div className="divide-y divide-[#3a4a41]/10">
                      {queue.map((item) => (
                        <div key={item.id} className="px-5 py-3 flex items-center gap-4">
                          <div className="shrink-0 w-16 text-center">
                            {item.status === "pending" && <span className="text-[9px] font-mono text-[#83958a] uppercase">pending</span>}
                            {item.status === "running" && (
                              <div className="flex items-center gap-1.5 justify-center">
                                <div className="w-3 h-3 border border-[#00ffb2] border-t-transparent rounded-full animate-spin" />
                                <span className="text-[9px] font-mono text-[#00ffb2]">running</span>
                              </div>
                            )}
                            {item.status === "done" && <span className="text-[9px] font-mono text-[#00ffb2] font-bold">✓ done</span>}
                            {item.status === "error" && <span className="text-[9px] font-mono text-[#ffb3ac]">✗ error</span>}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-mono font-bold text-[#e0e2ea] truncate">
                              {item.strategyLabel} · {item.symbol} · {item.timeframe}
                            </p>
                            <p className="text-[9px] font-mono text-[#3a4a41]">
                              objective: {item.objective}
                              {item.result && ` · Sharpe ${item.result.best_sharpe.toFixed(3)} · Gate2: ${item.result.gate2_pass ? "✓" : "✗"}`}
                              {item.errorMsg && ` · ${item.errorMsg.slice(0, 60)}`}
                            </p>
                          </div>
                          <button onClick={() => setQueue(prev => prev.filter(q => q.id !== item.id))} disabled={item.status === "running"} className="shrink-0 text-[#3a4a41] hover:text-[#83958a] text-xs transition-colors disabled:opacity-20">✕</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {optResult && !optLoading && (
              <>
                {/* Gate 2 badge */}
                <div className={`flex items-center gap-3 p-4 border-l-4 ${
                  optResult.gate2_pass ? "border-[#00ffb2] bg-[#00ffb2]/5" : "border-[#ffb3ac] bg-[#ffb3ac]/5"
                }`}>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`w-2 h-2 rounded-full ${optResult.gate2_pass ? "bg-[#00ffb2]" : "bg-[#ffb3ac]"}`} />
                      <span className="text-[10px] font-mono text-[#83958a] uppercase tracking-widest">Gate 2 Status — Optimization Stability</span>
                    </div>
                    <p className="text-xs font-headline font-bold text-[#e0e2ea]">
                      {optResult.gate2_pass
                        ? "STABILITY CONFIRMED — OOS/IS RATIO ≥ 0.70"
                        : "INSTABILITY DETECTED — OOS PERFORMANCE DEGRADES SIGNIFICANTLY"}
                    </p>
                    <p className="text-[10px] font-mono text-[#83958a] mt-1">
                      Optimized for: <span className="text-[#00ffb2]">{
                        optResult.objective === "cagr" ? "Max CAGR"
                        : optResult.objective === "max_drawdown" ? "Min Max Drawdown"
                        : optResult.objective === "profit_factor" ? "Max Profit Factor"
                        : "Max Sharpe Ratio"
                      }</span>
                    </p>
                  </div>
                  <span className={`shrink-0 px-4 py-2 text-[10px] font-headline font-black uppercase tracking-widest border ${
                    optResult.gate2_pass
                      ? "border-[#00ffb2]/40 text-[#00ffb2] bg-[#00ffb2]/10"
                      : "border-[#ffb3ac]/40 text-[#ffb3ac] bg-[#ffb3ac]/10"
                  }`}>
                    {optResult.gate2_pass ? "READY FOR PAPER TRADING" : "CURVE-FIT RISK"}
                  </span>
                </div>

                {/* Summary metrics */}
                <div className="grid grid-cols-4 bg-[#1c2025] border border-[#3a4a41]/20">
                  <MetricCard label="Combos Tested" value={String(optResult.total_combos)} />
                  <MetricCard
                    label="Best Sharpe"
                    value={optResult.best_sharpe.toFixed(3)}
                    color={optResult.best_sharpe >= 1.2 ? "text-[#00ffb2]" : "text-[#e0e2ea]"}
                  />
                  <MetricCard
                    label="Best CAGR"
                    value={pct(optResult.best_cagr)}
                    color={optResult.best_cagr >= 0 ? "text-[#00ffb2]" : "text-[#ffb3ac]"}
                  />
                  <MetricCard
                    label="OOS/IS Ratio"
                    value={optResult.overfitting_score !== null ? optResult.overfitting_score.toFixed(3) : "N/A"}
                    color={
                      optResult.overfitting_score !== null
                        ? optResult.overfitting_score >= 0.7 ? "text-[#00ffb2]" : "text-[#ffb3ac]"
                        : "text-[#83958a]"
                    }
                  />
                </div>

                {/* Best params */}
                <div className="bg-[#181c21] p-5">
                  <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a] mb-4">
                    Best Parameters Found (In-Sample)
                  </h3>
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(optResult.best_params).map(([k, v]) => (
                      <div key={k} className="bg-[#262a30] px-4 py-2 border border-[#00ffb2]/20">
                        <p className="text-[9px] font-mono text-[#83958a] uppercase tracking-wider">{k}</p>
                        <p className="text-lg font-mono font-bold text-[#00ffb2]">{v}</p>
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] font-mono text-[#83958a] mt-3">
                    Sharpe {optResult.best_sharpe.toFixed(3)} · CAGR {pct(optResult.best_cagr)} · MaxDD {pct(optResult.best_max_drawdown)} · {optResult.best_trade_count} trades
                  </p>
                  <div className="mt-4 flex items-center gap-3">
                    {(() => {
                      const key = optFor ? `${optFor.strategy}::${optFor.symbol}::${selTimeframe}` : "";
                      const alreadySaved = key in savedOptParams;
                      return (
                        <button
                          onClick={saveCurrentOpt}
                          className={`flex items-center gap-2 px-4 py-2 text-[10px] font-mono font-bold uppercase tracking-widest transition-all ${
                            alreadySaved
                              ? "border border-[#00ffb2]/40 text-[#00ffb2] bg-[#00ffb2]/5"
                              : "border border-[#3a4a41]/40 text-[#83958a] hover:text-[#00ffb2] hover:border-[#00ffb2]/40 bg-[#1c2025]"
                          }`}
                        >
                          {alreadySaved ? "✦ Saved to All Results" : "✦ Save to All Results"}
                        </button>
                      );
                    })()}
                    <span className="text-[9px] font-mono text-[#3a4a41]">
                      Saved results use optimized params when All Results refreshes
                    </span>
                  </div>
                </div>

                {/* Walk-forward table */}
                {optResult.walk_forward.length > 0 && (
                  <div className="bg-[#181c21]">
                    <div className="px-5 py-4 border-b border-[#3a4a41]/20">
                      <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a]">
                        Walk-Forward Validation — IS vs OOS Performance
                      </h3>
                    </div>
                    <div className="overflow-x-auto hide-scrollbar">
                      <table className="w-full text-left border-collapse">
                        <thead className="sticky top-0 bg-[#262a30]">
                          <tr>
                            {["Fold", "IS Period", "IS Sharpe", "OOS Period", "OOS Sharpe", "OOS/IS", "Best IS Params"].map((h) => (
                              <th key={h} className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider whitespace-nowrap">
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#3a4a41]/10">
                          {optResult.walk_forward.map((wf) => {
                            const ratio = wf.oos_sharpe !== null && wf.is_sharpe > 0 ? wf.oos_sharpe / wf.is_sharpe : null;
                            return (
                              <tr key={wf.fold} className="hover:bg-[#1c2025] transition-colors">
                                <td className="px-4 py-3 text-xs font-mono text-[#83958a]">#{wf.fold}</td>
                                <td className="px-4 py-3 text-xs font-mono text-[#b9cbbe] whitespace-nowrap">{wf.is_period}</td>
                                <td className={`px-4 py-3 text-xs font-mono font-bold ${wf.is_sharpe >= 1.2 ? "text-[#00ffb2]" : "text-[#e0e2ea]"}`}>
                                  {wf.is_sharpe.toFixed(3)}
                                </td>
                                <td className="px-4 py-3 text-xs font-mono text-[#b9cbbe] whitespace-nowrap">{wf.oos_period}</td>
                                <td className={`px-4 py-3 text-xs font-mono font-bold ${
                                  wf.oos_sharpe !== null
                                    ? wf.oos_sharpe >= 1.2 ? "text-[#00ffb2]" : wf.oos_sharpe >= 0 ? "text-[#e0e2ea]" : "text-[#ffb3ac]"
                                    : "text-[#83958a]"
                                }`}>
                                  {wf.oos_sharpe !== null ? wf.oos_sharpe.toFixed(3) : "—"}
                                </td>
                                <td className={`px-4 py-3 text-xs font-mono font-bold ${
                                  ratio !== null ? ratio >= 0.7 ? "text-[#00ffb2]" : "text-[#ffb3ac]" : "text-[#83958a]"
                                }`}>
                                  {ratio !== null ? ratio.toFixed(3) : "—"}
                                </td>
                                <td className="px-4 py-3 text-xs font-mono text-[#83958a]">
                                  {Object.entries(wf.best_is_params).map(([k, v]) => `${k}=${v}`).join(", ")}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <div className="px-5 py-3 border-t border-[#3a4a41]/20">
                      <p className="text-[10px] font-mono text-[#83958a]">
                        Gate 2 requires OOS/IS ratio ≥ 0.70 across all folds. Ratio &lt; 0.70 indicates curve-fitting — the strategy memorised in-sample noise.
                      </p>
                    </div>
                  </div>
                )}

                {/* Stability map */}
                <div className="bg-[#181c21] p-5">
                  <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a] mb-5">
                    Parameter Stability Map — Sharpe Across Parameter Space
                  </h3>
                  <StabilityHeatmap map={optResult.stability_map} />
                  <p className="text-[10px] font-mono text-[#83958a] mt-4">
                    Broad high-Sharpe regions indicate robust parameters. Narrow peaks suggest the strategy is sensitive to exact values — a curve-fit risk.
                  </p>
                </div>

                {/* Queue panel — always visible when optResult exists */}
                <div className="bg-[#181c21]">
                  <div className="px-5 py-4 border-b border-[#3a4a41]/20 flex items-center justify-between">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a]">
                      Optimization Queue
                    </h3>
                    <div className="flex items-center gap-3">
                      {queue.filter(q => q.status === "pending").length > 0 && (
                        <button
                          onClick={runQueue}
                          disabled={queueRunning}
                          className="bg-[#00ffb2] text-[#003824] px-4 py-1.5 text-[10px] font-mono font-bold uppercase tracking-widest hover:opacity-90 transition-opacity disabled:opacity-40"
                        >
                          {queueRunning ? "Running…" : `▶ Run All (${queue.filter(q => q.status === "pending").length})`}
                        </button>
                      )}
                      {queue.length > 0 && !queueRunning && (
                        <button
                          onClick={() => setQueue([])}
                          className="text-[10px] font-mono text-[#3a4a41] hover:text-[#83958a] uppercase tracking-widest transition-colors"
                        >
                          Clear
                        </button>
                      )}
                    </div>
                  </div>
                  {queue.length === 0 ? (
                    <div className="px-5 py-6 text-center">
                      <p className="text-[10px] font-mono text-[#3a4a41]">
                        No items queued. Use "+ Add to Queue" in the sidebar to batch-optimize multiple strategy × symbol combinations.
                      </p>
                    </div>
                  ) : (
                    <div className="divide-y divide-[#3a4a41]/10">
                      {queue.map((item) => (
                        <div key={item.id} className="px-5 py-3 flex items-center gap-4">
                          <div className="shrink-0 w-16 text-center">
                            {item.status === "pending" && (
                              <span className="text-[9px] font-mono text-[#83958a] uppercase">pending</span>
                            )}
                            {item.status === "running" && (
                              <div className="flex items-center gap-1.5 justify-center">
                                <div className="w-3 h-3 border border-[#00ffb2] border-t-transparent rounded-full animate-spin" />
                                <span className="text-[9px] font-mono text-[#00ffb2]">running</span>
                              </div>
                            )}
                            {item.status === "done" && (
                              <span className="text-[9px] font-mono text-[#00ffb2] font-bold">✓ done</span>
                            )}
                            {item.status === "error" && (
                              <span className="text-[9px] font-mono text-[#ffb3ac]">✗ error</span>
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-mono font-bold text-[#e0e2ea] truncate">
                              {item.strategyLabel} · {item.symbol} · {item.timeframe}
                            </p>
                            <p className="text-[9px] font-mono text-[#3a4a41]">
                              objective: {item.objective}
                              {item.result && ` · Sharpe ${item.result.best_sharpe.toFixed(3)} · Gate2: ${item.result.gate2_pass ? "✓" : "✗"}`}
                              {item.errorMsg && ` · ${item.errorMsg.slice(0, 60)}`}
                            </p>
                          </div>
                          <button
                            onClick={() => setQueue(prev => prev.filter(q => q.id !== item.id))}
                            disabled={item.status === "running"}
                            className="shrink-0 text-[#3a4a41] hover:text-[#83958a] text-xs transition-colors disabled:opacity-20"
                          >
                            ✕
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Top 10 grid results */}
                <div className="bg-[#181c21]">
                  <div className="px-5 py-4 border-b border-[#3a4a41]/20 flex justify-between items-center">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a]">
                      Top Parameter Combinations (Full Dataset)
                    </h3>
                    <span className="text-[10px] font-mono text-[#83958a]">
                      {optResult.valid_combos} / {optResult.total_combos} combos
                    </span>
                  </div>
                  <div className="overflow-x-auto hide-scrollbar">
                    <table className="w-full text-left border-collapse">
                      <thead className="sticky top-0 bg-[#262a30]">
                        <tr>
                          <th className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider">#</th>
                          <th className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider">Params</th>
                          <th className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider">Sharpe</th>
                          <th className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider">CAGR</th>
                          <th className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider">Max DD</th>
                          <th className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider">Win %</th>
                          <th className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider">Trades</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#3a4a41]/10">
                        {optResult.grid_results.slice(0, 10).map((row, i) => (
                          <tr key={i} className={`hover:bg-[#1c2025] transition-colors ${i === 0 ? "bg-[#00ffb2]/5" : ""}`}>
                            <td className="px-4 py-3 text-xs font-mono text-[#83958a]">
                              {i === 0 ? "★" : `#${i + 1}`}
                            </td>
                            <td className="px-4 py-3 text-xs font-mono text-[#e0e2ea]">
                              {Object.entries(row.params).map(([k, v]) => `${k}=${v}`).join(", ")}
                            </td>
                            <td className={`px-4 py-3 text-xs font-mono font-bold ${row.sharpe >= 1.2 ? "text-[#00ffb2]" : "text-[#e0e2ea]"}`}>
                              {row.sharpe.toFixed(3)}
                            </td>
                            <td className={`px-4 py-3 text-xs font-mono ${row.cagr >= 0 ? "text-[#00ffb2]" : "text-[#ffb3ac]"}`}>
                              {pct(row.cagr)}
                            </td>
                            <td className="px-4 py-3 text-xs font-mono text-[#ffb3ac]">{pct(row.max_drawdown)}</td>
                            <td className="px-4 py-3 text-xs font-mono">{pct(row.win_rate)}</td>
                            <td className="px-4 py-3 text-xs font-mono">{row.trade_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ============================================================
            AI INSIGHTS VIEW
            ============================================================ */}
        {view === "insights" && (
          <div className="p-6 space-y-5 flex-1">
            <div className="flex justify-between items-end">
              <div>
                <h2 className="text-2xl font-black font-headline tracking-tighter uppercase">
                  AI Insights
                </h2>
                <p className="text-xs font-mono text-[#83958a] mt-1">
                  {insightsFor
                    ? `${strategies.find((s) => s.key === insightsFor.strategy)?.label ?? insightsFor.strategy} · ${insightsFor.symbol} · Claude ${String.fromCodePoint(0x1F916)} analytical copilot`
                    : "Select strategy + symbol, then click AI Insights"}
                </p>
              </div>
              <button
                onClick={runInsights}
                disabled={insightsLoading || !selStrategy || !selSymbol}
                className="bg-[#1c2025] border border-[#3a4a41]/40 text-[#00ffb2] px-5 py-2 text-[10px] font-mono font-bold uppercase tracking-widest hover:bg-[#262a30] transition-colors disabled:opacity-40"
              >
                {insightsLoading ? "Analyzing…" : "🤖 Run Analysis"}
              </button>
            </div>

            {/* API key missing */}
            {insightsNeedsKey && (
              <div className="bg-[#1c2025] border border-[#ffd580]/20 p-6 space-y-3">
                <div className="flex items-center gap-3">
                  <span className="text-[#ffd580] text-lg">🔑</span>
                  <h3 className="font-headline font-bold text-[#e0e2ea] text-sm uppercase tracking-wide">
                    Anthropic API Key Required
                  </h3>
                </div>
                <p className="text-xs font-mono text-[#83958a] leading-relaxed">
                  AI Insights uses Claude to classify market regime, flag risks, and assess strategy robustness.
                  Add your API key to enable this feature:
                </p>
                <div className="bg-[#0a0e13] p-4 border border-[#3a4a41]/40 font-mono text-xs text-[#00ffb2]">
                  <p className="text-[#83958a] mb-1"># alphasmart/.env</p>
                  <p>ANTHROPIC_API_KEY=sk-ant-api03-...</p>
                </div>
                <p className="text-[10px] font-mono text-[#83958a]">
                  Get your key at console.anthropic.com · The LLM is analytical only — it cannot place orders or modify parameters.
                </p>
              </div>
            )}

            {insightsError && (
              <div className="bg-[#93000a]/20 border-l-4 border-[#ffb4ab] p-4">
                <p className="text-sm font-mono text-[#ffb4ab]">{insightsError}</p>
              </div>
            )}

            {insightsLoading && (
              <div className="space-y-4">
                <div className="bg-[#1c2025] p-6 flex items-center gap-5">
                  <div className="w-5 h-5 border-2 border-[#00ffb2] border-t-transparent rounded-full animate-spin shrink-0" />
                  <div>
                    <p className="text-sm font-mono text-[#e0e2ea]">Running backtest + consulting Claude…</p>
                    <p className="text-xs font-mono text-[#83958a] mt-1">
                      Classifying market regime · flagging risks · generating assessment
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <Skeleton className="h-32" />
                  <Skeleton className="h-32" />
                </div>
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            )}

            {!insightsLoading && !insights && !insightsError && !insightsNeedsKey && (
              <div className="bg-[#1c2025] p-10 text-center space-y-3">
                <p className="text-2xl">🤖</p>
                <p className="text-sm font-mono text-[#e0e2ea]">No analysis yet</p>
                <p className="text-xs font-mono text-[#83958a]">
                  Select a strategy + symbol in the sidebar, then click "Run Analysis" above.
                </p>
              </div>
            )}

            {insights && !insightsLoading && (
              <>
                {/* Regime card */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-[#181c21] p-5">
                    <p className="text-[10px] font-mono text-[#83958a] uppercase tracking-widest mb-3">Market Regime</p>
                    <div className="flex items-center gap-3 mb-3">
                      <div className={`w-3 h-3 rounded-full ${
                        insights.regime.includes("bull") ? "bg-[#00ffb2]" :
                        insights.regime.includes("bear") ? "bg-[#ffb3ac]" :
                        "bg-[#ffd580]"
                      }`} />
                      <span className="text-lg font-headline font-bold text-[#e0e2ea] uppercase tracking-wide">
                        {insights.regime_label}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mb-3">
                      <div className="flex-1 bg-[#262a30] h-1.5">
                        <div
                          className="h-full bg-[#00ffb2]"
                          style={{ width: `${insights.regime_confidence * 100}%` }}
                        />
                      </div>
                      <span className="text-[10px] font-mono text-[#83958a]">
                        {(insights.regime_confidence * 100).toFixed(0)}% confidence
                      </span>
                    </div>
                    <p className="text-xs font-mono text-[#b9cbbe] leading-relaxed">
                      {insights.regime_explanation}
                    </p>
                  </div>

                  {/* Gate 2 readiness */}
                  <div className={`p-5 border-l-4 ${
                    insights.gate2_readiness === "ready" ? "bg-[#00ffb2]/5 border-[#00ffb2]" :
                    insights.gate2_readiness === "conditional" ? "bg-[#ffd580]/5 border-[#ffd580]" :
                    "bg-[#ffb3ac]/5 border-[#ffb3ac]"
                  }`}>
                    <p className="text-[10px] font-mono text-[#83958a] uppercase tracking-widest mb-2">Gate 2 Readiness (AI Assessment)</p>
                    <div className="flex items-center gap-2 mb-3">
                      <span className={`text-sm font-headline font-bold uppercase tracking-wide ${
                        insights.gate2_readiness === "ready" ? "text-[#00ffb2]" :
                        insights.gate2_readiness === "conditional" ? "text-[#ffd580]" :
                        "text-[#ffb3ac]"
                      }`}>
                        {insights.gate2_readiness === "ready" ? "✓ Ready" :
                         insights.gate2_readiness === "conditional" ? "⚡ Conditional" : "✗ Not Ready"}
                      </span>
                    </div>
                    <p className="text-xs font-mono text-[#b9cbbe] leading-relaxed">{insights.gate2_rationale}</p>
                  </div>
                </div>

                {/* Risk flags */}
                {insights.risk_flags.length > 0 && (
                  <div className="bg-[#181c21] p-5">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a] mb-4">
                      Risk Flags ({insights.risk_flags.length})
                    </h3>
                    <div className="space-y-2">
                      {insights.risk_flags.map((flag, i) => (
                        <div
                          key={i}
                          className={`flex items-start gap-3 p-3 border-l-2 ${
                            flag.severity === "high" ? "border-[#ffb3ac] bg-[#ffb3ac]/5" :
                            flag.severity === "medium" ? "border-[#ffd580] bg-[#ffd580]/5" :
                            "border-[#83958a]/40 bg-[#83958a]/5"
                          }`}
                        >
                          <span className={`text-[9px] font-mono uppercase tracking-widest px-1.5 py-0.5 font-bold shrink-0 mt-0.5 ${
                            flag.severity === "high" ? "bg-[#ffb3ac]/20 text-[#ffb3ac]" :
                            flag.severity === "medium" ? "bg-[#ffd580]/20 text-[#ffd580]" :
                            "bg-[#83958a]/20 text-[#83958a]"
                          }`}>
                            {flag.severity}
                          </span>
                          <div>
                            <p className="text-xs font-mono font-bold text-[#e0e2ea]">{flag.flag}</p>
                            <p className="text-xs font-mono text-[#b9cbbe] mt-0.5">{flag.detail}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Strategy assessment */}
                <div className="bg-[#181c21] p-5">
                  <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a] mb-3">
                    Strategy Assessment
                  </h3>
                  <p className="text-sm font-mono text-[#b9cbbe] leading-relaxed mb-5">
                    {insights.strategy_assessment}
                  </p>
                  <div className="grid grid-cols-2 gap-5">
                    <div>
                      <p className="text-[10px] font-mono text-[#00ffb2] uppercase tracking-wider mb-2">Strengths</p>
                      <ul className="space-y-1">
                        {insights.strengths.map((s, i) => (
                          <li key={i} className="flex items-start gap-2 text-xs font-mono text-[#b9cbbe]">
                            <span className="text-[#00ffb2] shrink-0">+</span>
                            <span>{s}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <p className="text-[10px] font-mono text-[#ffb3ac] uppercase tracking-wider mb-2">Weaknesses</p>
                      <ul className="space-y-1">
                        {insights.weaknesses.map((w, i) => (
                          <li key={i} className="flex items-start gap-2 text-xs font-mono text-[#b9cbbe]">
                            <span className="text-[#ffb3ac] shrink-0">−</span>
                            <span>{w}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>

                {/* Recommendations */}
                {insights.recommendations.length > 0 && (
                  <div className="bg-[#1c2025] border border-[#00ffb2]/10 p-5">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a] mb-3">
                      Recommendations
                    </h3>
                    <ol className="space-y-2">
                      {insights.recommendations.map((rec, i) => (
                        <li key={i} className="flex items-start gap-3 text-xs font-mono text-[#b9cbbe]">
                          <span className="text-[#00ffb2] font-bold shrink-0 w-5">{i + 1}.</span>
                          <span>{rec}</span>
                        </li>
                      ))}
                    </ol>
                    <p className="text-[9px] font-mono text-[#3a4a41] mt-4">
                      These are analytical observations only. The LLM cannot place orders, modify parameters, or affect execution.
                    </p>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ============================================================
            SIMULATION VIEW
            ============================================================ */}
        {view === "simulation" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-headline font-bold text-lg uppercase tracking-widest text-[#e0e2ea]">
                  Bootstrapping Simulation
                </h2>
                <p className="text-xs font-mono text-[#83958a] mt-1">
                  Generate synthetic price paths from historical data to stress-test strategy robustness.
                </p>
              </div>
              <button
                onClick={runSimulation}
                disabled={simLoading || !selStrategy || !selSymbol}
                className="bg-[#1c2025] border border-[#3a4a41]/40 text-[#00ffb2] px-5 py-2 font-headline font-bold text-xs uppercase tracking-widest hover:bg-[#262a30] disabled:opacity-40 transition-all"
              >
                {simLoading ? "Simulating…" : "🎲 Re-Run"}
              </button>
            </div>

            {simLoading && (
              <div className="bg-[#1c2025] p-8 flex items-center gap-5">
                <div className="w-5 h-5 border-2 border-[#00ffb2] border-t-transparent rounded-full animate-spin shrink-0" />
                <div>
                  <p className="text-sm font-mono text-[#e0e2ea]">
                    Running {simType === "block_bootstrap" ? "block bootstrap" : simType === "monte_carlo" ? "Monte Carlo GBM" : "jackknife"} simulation…
                  </p>
                  <p className="text-xs font-mono text-[#83958a] mt-1">
                    {simType === "jackknife" ? "Leaving out each monthly block in turn." : `Generating ${simNSims} synthetic price paths.`}
                  </p>
                </div>
              </div>
            )}

            {simError && (
              <div className="bg-[#93000a]/20 border border-[#ffb4ab]/20 p-4">
                <p className="text-xs font-mono text-[#ffb4ab]">{simError}</p>
              </div>
            )}

            {!simLoading && !simResult && !simError && (
              <div className="bg-[#1c2025] p-10 text-center space-y-3">
                <p className="text-sm font-mono text-[#e0e2ea]">No simulation run yet</p>
                <p className="text-xs font-mono text-[#83958a]">
                  Select a strategy + symbol, choose a simulation method in the sidebar, and click "Run Simulation".
                </p>
                <div className="grid grid-cols-3 gap-4 mt-6 text-left">
                  {[
                    { name: "Block Bootstrap", icon: "🧱", desc: "Resamples overlapping blocks of returns. Preserves short-term autocorrelation (volatility clustering). Distribution-free." },
                    { name: "Monte Carlo (GBM)", icon: "📊", desc: "Fits drift & volatility from history, simulates N Geometric Brownian Motion paths. Fast and parametric." },
                    { name: "Jackknife", icon: "✂️", desc: "Leaves out each monthly block in turn. Reveals which periods your strategy depends on most." },
                  ].map((m) => (
                    <div key={m.name} className="bg-[#181c21] p-4 border border-[#3a4a41]/20">
                      <p className="text-lg mb-2">{m.icon}</p>
                      <p className="text-xs font-mono text-[#00ffb2] mb-1">{m.name}</p>
                      <p className="text-[10px] font-mono text-[#83958a] leading-relaxed">{m.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {simResult && !simLoading && (
              <>
                {/* Header info */}
                <div className="bg-[#1c2025] px-5 py-4 flex items-center justify-between">
                  <div>
                    <p className="text-xs font-mono text-[#83958a]">
                      {simResult.strategy_key} · {simResult.symbol} · {simResult.timeframe.toUpperCase()}
                    </p>
                    <p className="text-sm font-mono text-[#e0e2ea] mt-0.5">
                      {simResult.n_simulations} synthetic paths via{" "}
                      <span className="text-[#00ffb2]">
                        {simResult.simulation_type === "block_bootstrap" ? "Block Bootstrap"
                          : simResult.simulation_type === "monte_carlo" ? "Monte Carlo GBM"
                          : "Jackknife"}
                      </span>
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] font-mono text-[#3a4a41] uppercase tracking-wider">Original Sharpe</p>
                    <p className={`text-2xl font-mono font-bold ${simResult.original_metrics.sharpe >= 1.2 ? "text-[#00ffb2]" : "text-[#e0e2ea]"}`}>
                      {simResult.original_metrics.sharpe.toFixed(3)}
                    </p>
                  </div>
                </div>

                {/* Percentile table */}
                <div className="bg-[#181c21] border border-[#3a4a41]/20">
                  <div className="px-5 py-4 border-b border-[#3a4a41]/20">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a]">
                      Metric Distribution Across Simulated Paths
                    </h3>
                  </div>
                  <div className="overflow-x-auto hide-scrollbar">
                    <table className="w-full text-left border-collapse">
                      <thead className="bg-[#262a30]">
                        <tr>
                          {["Metric", "Original", "p5", "p25", "Median", "p75", "p95", "Mean ± Std"].map((h) => (
                            <th key={h} className="px-4 py-3 text-[10px] font-mono text-[#83958a] uppercase tracking-wider whitespace-nowrap">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(
                          [
                            { label: "Sharpe", key: "sharpe", orig: simResult.original_metrics.sharpe, fmt: (v: number) => v.toFixed(3), good: (v: number) => v >= 1.2 },
                            { label: "CAGR", key: "cagr", orig: simResult.original_metrics.cagr, fmt: (v: number) => pct(v), good: (v: number) => v >= 0 },
                            { label: "Max Drawdown", key: "max_drawdown", orig: simResult.original_metrics.max_drawdown, fmt: (v: number) => pct(v), good: (v: number) => v < 0.25 },
                            { label: "Win Rate", key: "win_rate", orig: simResult.original_metrics.win_rate, fmt: (v: number) => pct(v), good: (v: number) => v >= 0.5 },
                          ] as Array<{ label: string; key: keyof SimulationResult["percentiles"]; orig: number; fmt: (v: number) => string; good: (v: number) => boolean }>
                        ).map(({ label, key, orig, fmt, good }) => {
                          const p = simResult.percentiles[key];
                          return (
                            <tr key={key} className="border-t border-[#3a4a41]/10 hover:bg-[#1c2025]/50">
                              <td className="px-4 py-3 text-xs font-mono text-[#83958a]">{label}</td>
                              <td className={`px-4 py-3 text-xs font-mono font-bold ${good(orig) ? "text-[#00ffb2]" : "text-[#ffb3ac]"}`}>{fmt(orig)}</td>
                              {p ? (
                                <>
                                  <td className="px-4 py-3 text-xs font-mono text-[#83958a]">{fmt(p.p5)}</td>
                                  <td className="px-4 py-3 text-xs font-mono text-[#b9cbbe]">{fmt(p.p25)}</td>
                                  <td className="px-4 py-3 text-xs font-mono text-[#e0e2ea] font-bold">{fmt(p.p50)}</td>
                                  <td className="px-4 py-3 text-xs font-mono text-[#b9cbbe]">{fmt(p.p75)}</td>
                                  <td className="px-4 py-3 text-xs font-mono text-[#83958a]">{fmt(p.p95)}</td>
                                  <td className="px-4 py-3 text-[10px] font-mono text-[#83958a]">{fmt(p.mean)} ± {fmt(p.std)}</td>
                                </>
                              ) : (
                                <td colSpan={6} className="px-4 py-3 text-xs font-mono text-[#3a4a41]">No data</td>
                              )}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Sharpe distribution mini-histogram */}
                {simResult.sim_sharpes.length > 0 && (
                  <div className="bg-[#181c21] p-5">
                    <h3 className="font-headline font-bold uppercase tracking-widest text-xs text-[#83958a] mb-4">
                      Sharpe Distribution Across Simulated Paths
                    </h3>
                    <SimHistogram
                      values={simResult.sim_sharpes}
                      original={simResult.original_metrics.sharpe}
                      label="Sharpe"
                      goodThreshold={1.2}
                    />
                    <p className="text-[10px] font-mono text-[#3a4a41] mt-3">
                      Green bar = original strategy Sharpe. Distribution width indicates sensitivity to market conditions.
                      A narrow distribution centered above 1.2 indicates robust performance.
                    </p>
                  </div>
                )}

                {/* Robustness verdict */}
                {simResult.percentiles.sharpe && (
                  <SimRobustnessCard
                    origSharpe={simResult.original_metrics.sharpe}
                    p25Sharpe={simResult.percentiles.sharpe.p25}
                    p50Sharpe={simResult.percentiles.sharpe.p50}
                    simType={simResult.simulation_type}
                  />
                )}
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
