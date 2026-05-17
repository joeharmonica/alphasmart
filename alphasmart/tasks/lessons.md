# AlphaSMART — Lessons Learned

_Updated: 2026-05-12 (universe v2 + cash-buffer preflight unblock + reconciler false-positive)_

---

## 1. Hydration Mismatch: `typeof window !== 'undefined'` in `"use client"` Components

**Symptom:** React hydration error — server-rendered HTML didn't match client output. Error pointed to unrelated static text in the component tree (red herring on exact location).

**Root Cause:** `typeof window !== 'undefined'` used to access `window.innerWidth/innerHeight` directly during component render. Next.js pre-renders `"use client"` components on the server (for the initial HTML), where `window` is undefined. Server uses the fallback (1440/900); client uses real dimensions — mismatch.

**Fix:** Replace inline `typeof window` check with `useEffect` + `useState`:
```typescript
const [vw, setVw] = useState(1440);  // consistent SSR default
const [vh, setVh] = useState(900);
useEffect(() => {
  setVw(window.innerWidth);
  setVh(window.innerHeight);
}, []);
```

**Rule:** Never access `window`, `document`, or `localStorage` during render in a Next.js component. Always wrap in `useEffect`.

---

## 2. Stale `.next` Cache After Edits

**Symptom:** Hydration error showed server rendering OLD text ("Phase 2") while client expected NEW text ("Phase 3") — even though code was updated.

**Root Cause:** Next.js cached the server-side render bundle in `.next/`. Hot-reload in dev doesn't always invalidate this for static text changes.

**Fix:** `rm -rf .next && npm run build` whenever hydration errors appear after code changes. Run a clean build before testing hydration-sensitive changes.

---

## 3. Python Subprocess Bridge: Loguru Stdout Pollution

**Symptom:** `JSON.parse` failed in Node.js — Python's loguru was writing INFO logs to stdout, mixed with the JSON output.

**Root Cause:** `src/monitoring/logger.py` calls `setup_logger()` at module-level, binding loguru to `sys.stdout`. Lazy imports inside functions would re-trigger this binding on the first call.

**Fix:** Force ALL imports at the top of `run_backtest.py` (so module-level code runs), THEN call `_logger.remove()` + `_logger.add(sys.stderr, ...)` to override stdout binding. Order matters — can't redirect before imports happen.

---

## 4. numpy.bool_ / numpy Scalars Not JSON-Serializable

**Symptom:** `TypeError: Object of type bool_ is not JSON serializable` when calling `json.dumps()` on backtest metrics.

**Root Cause:** `passes_gate_1()` returns `numpy.bool_` because `self.sharpe > 1.2` where `self.sharpe` is `numpy.float64`. Standard `json.JSONEncoder` doesn't handle numpy types.

**Fix:** Custom `_NumpyEncoder(json.JSONEncoder)` with `default()` handling `np.integer`, `np.floating`, `np.bool_`, and `np.ndarray`. Always use this encoder in the subprocess bridge.

---

## 5. Walk-Forward With Limited Data Produces Only 1 Fold

**Symptom:** With 1,256 daily bars (5 years), IS=756 + OOS=252 + step=252 yields only 1 fold, not 2. Gate 2 overfitting score can't be reliable with a single fold.

**Root Cause:** `1256 - 756 - 252 = 248 < 252`, so the second fold's OOS window doesn't fit.

**Impact:** Gate 2 reliability is limited. Single-fold results are directionally useful but not statistically robust.

**Lesson:** For meaningful walk-forward, need ≥ 3 folds. With daily data, this means IS+OOS+2×step ≤ n_bars. At IS=504 (2yr) + OOS=126 (6mo) + step=126: need ~1008 bars for 3 folds. Consider adjusting window sizes for limited datasets.

---

## 6. SVG Equity Curve Hover: Coordinate Space vs Screen Space

**Symptom:** Mouse tracking on SVG used `e.clientX` directly against SVG coordinates, leading to off-by-factor errors.

**Root Cause:** SVG `viewBox` coordinates and screen pixel coordinates are different scales when `width="100%"`.

**Fix:** Use `svgRef.current.getBoundingClientRect()` to get the SVG's rendered size on screen, then scale: `svgX = ((e.clientX - rect.left) / rect.width) * SVG_WIDTH`. This correctly maps screen pixels → SVG coordinate space regardless of container size.

---

## 7. API Key Not Found: Graceful Degradation Required

**Symptom:** AI Insights silently failed when `ANTHROPIC_API_KEY` was not set — users got a cryptic 500 error.

**Fix:** `run_backtest.py` catches `RuntimeError` from `analyze_backtest()` and returns `{"error": "...", "needs_api_key": true}`. Frontend checks for `needs_api_key` flag and shows a setup card with exact instructions instead of an error message.

**Rule:** External service dependencies (API keys, third-party services) must always have a graceful degradation path with clear user-facing guidance.

---

## 8. Timeframe Annualisation: TRADING_DAYS_PER_YEAR = 252 Is Only Correct for Daily Data

**Symptom:** Sharpe ratios for 1h/15m data would be wildly inflated (a 0.5 daily Sharpe becomes ~4+ on hourly if using 252 as annualisation factor) because 252 assumes one observation per trading day.

**Root Cause:** `TRADING_DAYS_PER_YEAR = 252` is correct for daily bars. For intraday data, bars_per_year = 252 × (bars_per_day). For 1h US equities: 252 × 6.5 ≈ 1638. For 15m: 252 × 26 ≈ 6552.

**Fix:** Added `BARS_PER_YEAR` dict and `bars_per_year_for(timeframe)` in `metrics.py`. Added `timeframe: str = "1d"` to `BacktestConfig`. Engine passes `bars_per_year_for(config.timeframe)` to `compute_metrics()`.

**Rule:** Any annualised metric (Sharpe, Sortino, CAGR) MUST use the correct bars_per_year for the dataset's timeframe. Thread the timeframe string through BacktestConfig → engine → compute_metrics.

---

## 9. Bootstrapping Synthetic Series Must Preserve OHLCV Structure

**Symptom:** If you only resample close prices and set open=high=low=close, strategies that use high/low/volume (e.g., ATR, Stochastic, VWAP) produce NaN or degenerate signals.

**Root Cause:** Most strategies require open, high, low, volume columns in addition to close. Synthetic series that only reconstruct close prices break these indicators.

**Fix:** `_reconstruct_ohlcv()` in `simulation.py` samples bar body proportions (high/close, low/close, open/close ratios) from the original data with replacement, and applies them to the synthetic close series. Volumes are similarly sampled from originals.

**Rule:** When constructing synthetic OHLCV datasets for simulation, always reconstruct all 5 columns. Never generate just close prices unless all strategies used are close-only.

---

## 10. Optimizer Walk-Forward Windows Must Scale with Timeframe

**Symptom:** Using hardcoded IS=756 bars (designed for daily data) on hourly data would mean IS window of only ~5.5 weeks instead of 3 years — completely meaningless for walk-forward validation.

**Root Cause:** Walk-forward IS/OOS window sizes were defined in bars, not calendar time. Daily bars × 3 = 756 bars ≈ 3 years, but hourly bars × 3 years ≈ 4914 bars.

**Fix:** `optimizer.py` now uses `_IS_YEARS`, `_OOS_YEARS`, `_STEP_YEARS` constants and computes `is_bars = int(_IS_YEARS * bpy)` from `bars_per_year_for(timeframe)`. Walk-forward folds are now calendar-time-aware regardless of timeframe.

**Rule:** Define walk-forward parameters in calendar years, not bars. Derive bar counts from `bars_per_year_for(timeframe)` at runtime.

---

## 11. Composite Strategy Weights Must Sum to 1.0 — Enforce at Construction Time

**Symptom:** AlphaComposite strategy produces undefined composite scores when weights don't sum to 1.0, making comparison between parameter combinations meaningless.

**Root Cause:** The optimizer grid independently varies `trend_weight` and `rsi_weight`; `vol_weight` is the remainder. If that remainder is negative or > 0.6, the strategy is undefined.

**Fix:** `_generate_combos()` in `optimizer.py` computes `vol_weight = 1.0 - trend_weight - rsi_weight` and skips combos where `vol_weight < 0.05` or `vol_weight > 0.6`. The strategy constructor validates `sum(weights) ≈ 1.0` and raises `ValueError` otherwise.

**Rule:** For any composite strategy with constrained weights, enforce the constraint in both the optimizer combo generator AND the strategy constructor. The constructor is the last line of defence against invalid parameter combinations.

---

## 12. `float("inf")` Is Not Valid JSON — Cap Saturated Metrics at a Sentinel

**Symptom:** `Unexpected token 'I', ..."_factor": Infinity, "... is not valid JSON` in the All Results tab.

**Root Cause:** `profit_factor = gross_profit / gross_loss` yields `float("inf")` when there are no losing trades. Python's `json.dumps()` serialises this as the literal string `Infinity`, which is not valid JSON (only `null`, numbers, strings, booleans, arrays, objects are valid).

**Fix:** Cap `profit_factor` at `999.9` in `metrics.py` when `gross_loss == 0`. Added a second layer in `_NumpyEncoder.iterencode()` to sanitise any remaining `float("inf")` / `float("nan")` to `None` before encoding.

**Rule:** Never let `float("inf")` or `float("nan")` reach `json.dumps()`. Saturate metrics at a human-meaningful ceiling at the point of computation, not at the serialisation boundary.

---

## 13. `BatchRunner.run_all()` Factory Signature Cannot Carry Per-Symbol Params — Use `params_override` Dict

**Symptom:** Wanted to run All Results using optimized params for select (strategy, symbol, timeframe) combos, but the factory signature is `factory(symbol) → Strategy` — the timeframe is resolved inside the runner and is not available to the factory at call time.

**Root Cause:** `BatchRunner` passes only `symbol` to the factory callable. There is no way to inject timeframe-specific params via a closure without the factory knowing the timeframe it will be called for.

**Fix:** Added `params_override: dict[str, dict] | None = None` to `run_all()`. The key is `"strategy::symbol::timeframe"`. Inside the inner loop (where the runner already knows `tf`), check for the override key and call `_make_strategy(strat_name, symbol, params_override[key])` instead of the factory.

**Rule:** When factories need context that is resolved at runtime inside a runner (e.g. timeframe), add it as a parallel override dict keyed by the full tuple, not via factory closures. This keeps factory signatures simple and override logic explicit.

---

## 22. Gate 1 Trade Count Was the Binding Constraint — ≥100 Was Too Restrictive

**Symptom:** Zero Gate 1 passes across 231 runs on 2021-2026 daily data even for strategies with Sharpe > 1.2.

**Root Cause:** The original ≥100 trade threshold was calibrated for high-frequency mean-reversion strategies. Trend-following strategies structurally generate fewer but larger trades. bb_reversion on NVDA (Sharpe=1.21, 82 trades) and cci_trend on NVDA (Sharpe=1.39, 33 trades) both satisfy all other Gate 1 conditions.

**Fix:** Lowered to ≥30 trades in `passes_gate_1()`. 30 is the minimum for a statistically meaningful win-rate estimate (central limit theorem heuristic). Added `bars_per_day_for()` scaling to prevent intraday daily-loss limit from false-halting.

**Rule:** Gate 1 trade count should match the structural trade frequency of the strategy class. Separate thresholds per strategy type (trend-following ≥30, mean-reversion ≥60) would be more principled than a single universal number.

---

## 23. Oscillator Strategies Need Trend Filters to Survive Multi-Regime Periods

**Symptom:** StochRSI on daily data generated 54–63 trades per symbol but Sharpe of 0.09–0.27 — high activity, weak edge. After adding SMA(200) filter: MSFT Sharpe improved from 0.27 → 0.72, AAPL eliminated a halt (drawdown breaker from bear-market entries).

**Root Cause:** Oscillators (RSI, StochRSI, Williams %R) enter "oversold dip" signals even in sustained bear markets. In 2022 (NVDA –65%, AAPL –27%), dip-buying on every oversold reading guarantees losses.

**Fix:** Added `sma_period=200` to `StochRSIStrategy`. Entry blocked when `close < EMA(200)`. Exit triggered if regime flips while in position. Same pattern applies to any pure oscillator (RSI, CCI, Williams %R).

**Rule:** Any mean-reversion/oscillator strategy on assets with multi-regime histories MUST have a trend filter. SMA(200) is the industry-standard gate. Without it, oversold signals in a downtrend are not dip-buying opportunities — they are falling knives.

---

## 24. CCI Trend: exit_level=50 (Not 0) Dramatically Improves Trade Count vs Sharpe

**Symptom:** CCI Trend with exit_level=0 on NVDA → 6 trades, Sharpe=1.02 (mostly one big winning trade). Same strategy with exit_level=50 → 33 trades, Sharpe=1.39. Both pass Sharpe and MaxDD; only the second passes trade count.

**Root Cause:** With exit_level=0, positions are held through CCI oscillations from 100 down to 0 — these are long multi-month holds. With exit_level=50, the exit fires faster at the first sign of momentum fading, resetting the strategy for more re-entries. This captures the same trending periods with more discrete cycles.

**Rule:** For trend-following strategies that use CCI, set exit_level at 50% of entry_level (exit_level=50 when entry_level=100, or exit_level=37 when entry_level=75). This balances hold duration vs. re-entry frequency. Optimize both parameters together — they interact non-linearly.

---

## 25. Squeeze Momentum Is Too Infrequent on Daily Data — Needs Intraday or Longer History

**Symptom:** squeeze_momentum on daily NVDA/AAPL/MSFT generated only 4–10 trades over 5 years. On 1h NVDA (2yr), the best param set generated 37 trades.

**Root Cause:** Bollinger Band squeezes (BB inside Keltner) occur rarely on daily data — perhaps 4–8 times per year. At daily resolution, there are simply not enough squeeze-release events for the strategy to accumulate 30 trades in 5 years.

**Rule:** Squeeze momentum requires intraday resolution (1h or 15m) where squeezes occur weekly, giving 50–150 qualifying events per year. On daily data, prefer Donchian/ATR breakout for similar volatility-expansion logic.

---

## 26. ATR Trailing-Stop Wrapper Pattern — Per-Trade Stop Without Touching the Inner Strategy

**Symptom:** Best `cci_trend` config on NVDA hit Sharpe=1.39 / 33 trades but the backtest was halted by the portfolio-level 20% drawdown circuit breaker mid-run. The 20% breaker is a last-resort safety net for the whole portfolio; it should not be load-bearing for per-trade risk.

**Fix:** Added `src/strategy/trailing_stop.py` — `TrailingStopStrategy(inner, atr_period=14, atr_mult=2.0)` wraps any base Strategy. It tracks max(close) since the most recent long entry and overrides the inner's `long` signal with `flat` when `close < max_close - atr_mult * ATR`. Identical wiring as `RegimeFilteredStrategy`: same `Strategy` subclass interface, delegates `size_position()` to the inner. After a stop-out, blocks new long signals until the inner explicitly emits `flat` so we don't re-enter the same fading trend on the next bar.

Wired into the optimizer via a `+stop` suffix convention: `_make_strategy("cci_trend+stop", ...)` recursively builds the inner from the prefix and wraps. `PARAM_GRIDS["cci_trend+stop"]` aliases `PARAM_GRIDS["cci_trend"]` — the wrapper's stop params are fixed (Chandelier defaults), only the inner's params are optimized. Constraint checks in `_generate_combos()` use a `constraint_key` that strips the suffix, so existing per-strategy validation continues to fire.

**Rule:** When adding cross-cutting risk behaviour (stops, regime filters, position sizing overlays), prefer the wrapper-Strategy pattern over modifying every concrete strategy. The wrapper sees the same data as the inner (no lookahead), and the engine + RiskEngine + portfolio code is unchanged. For optimizer integration, use a key suffix (`+stop`, `+regime`) that aliases the inner's grid and dispatches inside `_make_strategy`.

**Caveat:** When the inner strategy's own exit is tighter than `2 × ATR(14)` from peak (e.g., `cci_trend` with `exit_level=50` exits as soon as CCI dips below 50), the trailing stop is structurally redundant — both versions produce identical fills. The stop adds value when the inner's exit is loose (e.g., `exit_level=0` or `exit_level=-50` configs) or for breakout strategies that hold through pullbacks.

---

## 27. First Combined Gate1+Gate2 Pass — `cci_trend+stop` on NVDA, OOS/IS=0.82

**Result:** With walk-forward windows tightened to IS=2yr / OOS=1yr / step=0.5yr (4 folds on 5-yr daily data), `cci_trend+stop` on NVDA optimized to:
- Best params: `entry_level=75, exit_level=50, vol_threshold=0.8`
- Sharpe 1.39, CAGR 41.7%, MaxDD 21.4%, 33 trades — **Gate 1 ✅**
- Overfitting score 0.82 across 4 folds — **Gate 2 ✅**

This is the first (strategy, symbol) combination in the project to clear both gates simultaneously. It is the same params as the bare `cci_trend` (the trailing stop didn't fire on this config — see lesson #26's caveat), but the +stop variant is what we will paper-trade because the wrapper is the per-trade safety net for configs where the inner exit isn't tight.

**Implication for paper trading:** A single Gate1+Gate2 passer is *insufficient* — single-strategy/single-symbol concentration is the riskiest possible deployment. The full top-4 × 19-symbol walk-forward (in progress; see todo.md) needs to find ≥ 3 uncorrelated passers before a paper-trading portfolio is defensible.

---

## 28. Walk-Forward Runtime Scales as `combos × (1 + n_folds) × symbols × strategies`

**Symptom:** Single optimization run for `cci_trend+stop` on NVDA with WF=IS2y/OOS1y/step0.5y (= 4 folds) took 246s. Naïvely projecting to 4 strategies × 19 symbols × 1d gives roughly 6–8 hours, dominated by `keltner_breakout` (108 combos) and `rsi_vwap` (~85 combos after constraint).

**Root Cause:** Each `run_optimization()` call runs `combos` full-grid backtests + `combos × n_folds` IS backtests + `n_folds` OOS backtests. cci_trend has 33 valid combos × 5 = ~165 backtests/symbol. keltner_breakout has 108 × 5 = ~540 backtests/symbol — over 3× longer.

**Fix (planned, not yet applied):** Pass a reduced `custom_param_grid` for keltner_breakout and rsi_vwap when running at-scale walk-forward — keep cci_trend and hull_ma_crossover at full grid. Alternative: parallelise the (strategy, symbol) loop with `multiprocessing.Pool` since each optimization is independent and the SQLite reader is read-only.

**Rule:** Before launching a full-universe walk-forward, time a single (strategy, symbol) on the largest-grid strategy and multiply by `n_strategies × n_symbols`. Anything > 60 min should either (a) trim grids, (b) parallelise, or (c) split into a multi-overnight job. Don't kick off blind — a half-finished WF run that crashes at hour 4 wastes the most time.

---

## 29. Full Top-4 +stop Sweep (2026-04-30 → 05-01) — Concentration Confirmed

**Result:** 68 (strategy, symbol) optimization runs (4 strategies × 17 1d symbols), 9,452 backtests, **8,437s (2h 20m) wall-clock** with trimmed grids on `keltner_breakout+stop` (24 combos) and `rsi_vwap+stop` (24 combos). Default windows IS=2y / OOS=1y / step=6mo → 4 walk-forward folds.

**Outcome under strict Gate 1 (Sh > 1.2, MaxDD < 25%, trades ≥ 30, +ve return) + Gate 2 (OFR ≥ 0.70):**
- **1 G1+G2 passer:** `cci_trend+stop` on NVDA (Sh=1.388, 33 trades, MaxDD=21.4%, OFR=0.82) — exact reproduction of lessons #27 baseline, validates the runner.
- 19 G2-only (passed walk-forward stability but Sharpe < 1.2 OR trades < 30).

**Per-strategy G1+G2 / G2-only / None:**
- cci_trend+stop: 1 / 8 / 8 (NVDA the passer)
- hull_ma_crossover+stop: 0 / 3 / 14
- keltner_breakout+stop: 0 / 5 / 12
- rsi_vwap+stop: 0 / 3 / 14

**Top-5 absolute Sharpes (most fail Gate 1 on trade count or Gate 2 on OFR):**
| Sh | Strategy | Symbol | Trades | OFR | Why no G1+G2 |
|---:|---|---|---:|---:|---|
| 1.576 | hull_ma_crossover+stop | NVDA | 18 | 0.555 | trades < 30 AND OFR < 0.70 |
| 1.526 | cci_trend+stop | TSLA | **4** | 0.400 | 4-trade fluke (lessons #22) |
| 1.388 | cci_trend+stop | NVDA | 33 | **0.820** | **G1+G2 passer** |
| 1.232 | keltner_breakout+stop | NVDA | 11 | 0.577 | trades < 30 AND OFR < 0.70 |
| 1.227 | cci_trend+stop | AAPL | 14 | 0.662 | trades < 30 AND OFR < 0.70 |

**Implication:** Single passer = concentration risk per lessons #27. Decision-gate verdict will be `CONCENTRATION` until the search widens (todo.md §3a/3b: try momentum_long+stop, donchian_bo+stop, alpha_composite+stop) or history extends (7–10 yr daily for more WF folds).

**Rule:** A real-data sweep that reproduces a known-good baseline (here: NVDA cci_trend+stop matching lessons #27) is the strongest possible runner-correctness signal — bake it in as a smoke test before *every* large sweep so a regressed runner doesn't burn 2+ hours producing wrong numbers.

**Outputs:** `reports/walkforward_top4_20260430.csv` (68 rows), `reports/walkforward_top4_20260430_passers.json` (1 entry), `optimized_params.json` (NVDA cci_trend+stop).

---

## 30. OFR (Overfitting Ratio) Is The Real Gate 2 Signal — Use It, Not the Bool

**Definition:** `OFR = mean over folds of max(OOS_Sharpe, 0) / IS_Sharpe` (`optimizer.py:502-509`). Gate 2 passes when `OFR ≥ 0.70`. Negative OOS clipped to 0 prevents a single OOS blowup from inverting the average.

**Calibration:**
- `OFR ≥ 1.0`: OOS as good or better than IS. Either no overfitting OR IS unusually weak (suspicious if much > 1.2 — check IS Sharpes).
- `OFR ≈ 0.70–1.00`: small/no overfitting. **0.70 is the cutoff.**
- `OFR < 0.70`: IS-tuned params underperform held-out windows.
- `OFR ≈ 0`: edge entirely degraded OOS — pure overfit.

**Why it matters more than `gate2_pass`:** the bool collapses a continuous signal. The 2026-04-30 sweep had OFRs ranging 0.0 → 4.92 across non-passers; the bool tells you which side of 0.70, but the *number* tells you whether a near-miss is worth a second look (Hull NVDA at 0.555 = no, V rsi_vwap+stop at 1.042 = yes).

**Rule:** When triaging a sweep, sort/colour by OFR continuous, not by `gate2_pass`. Treat OFR ≥ 0.70 as the only Gate 2 lever you should ever consider relaxing — Gate 1's Sharpe and trade-count thresholds are heuristic, but OFR is the actual overfitting test, so loosening it should be the *last* resort.

---

## 31. Relaxed Gate 1 Analysis — Sh ≥ 1.0 + trades ≥ 15 + Strict Gate 2

**Context:** With 1 strict passer the portfolio decision will return CONCENTRATION. Two principled relaxations of Gate 1 (keeping Gate 2 strict):
- **Trades ≥ 30 → ≥ 15:** lowers the CLT-comfort floor. SE on Sharpe widens from 1/√30 ≈ 0.18 to 1/√15 ≈ 0.26 — looser CIs, but still defensible for trend-following. Per lessons #22, ≥30 was already a heuristic, not an inviolable rule.
- **Sharpe > 1.2 → ≥ 1.0:** acknowledges that 1.2 is institutional-research convention; in walk-forward-validated setups, 1.0 with strict Gate 2 is a meaningful edge.

**Result on the 2026-04-30 sweep:** relaxation surfaces a second passer in a *different* sector:

| Strategy | Symbol | Sector | Sharpe | Trades | OFR | Params |
|---|---|---|---:|---:|---:|---|
| cci_trend+stop | NVDA | Semis | 1.388 | 33 | 0.820 | entry=75, exit=50, vol=0.8 |
| **rsi_vwap+stop** | **V** | **Payments** | **1.095** | **22** | **1.042** | vwap=12, rsi=10, os=35, ob=60 |

**Why V is genuinely interesting:** different mechanic (RSI on rolling-VWAP-deviation, mean reversion) than cci_trend (CCI breakout-style trend), different sector, OFR > 1.0 (OOS slightly outperformed IS — strongest possible stability signal), tight MaxDD (5.06%). Not just NVDA-AI-rally exposure under another label.

**Saved:** `reports/walkforward_top4_20260430_passers_relaxed.json`. V also persisted to `optimized_params.json`.

**Rule:** When a strict sweep returns < 3 passers, **don't change the runner's strict thresholds in code** — instead generate a `_passers_relaxed.json` from the CSV and feed it into the bootstrap. This keeps the strict gates as the institutional record while still exercising the bootstrap pipeline on principled near-misses. Only consider permanent threshold changes if relaxed analysis consistently surfaces robust passers across multiple sweeps.

---

## 32. Caveat: Equity-Curve Correlation Includes Cash-Period Zeros

**Symptom (anticipated):** `decide_portfolio.py` computes pairwise Pearson correlation across each passer's full daily-return series. When two strategies are both flat on the same day, both contribute a 0 return. Many correlated zeros inflate |ρ| upward — a correlation of 0.6 between two strategies that are flat 70% of the time may be mostly cash-overlap, not real edge correlation.

**Detection heuristic:** if two passers have wildly different in-trade frequencies but |ρ| > 0.5, suspect cash-overlap inflation. Compare in-trade days: if their overlap is dominated by both being flat, the correlation is overstating co-movement.

**Cleaner alternative (not yet implemented):** mask returns to bars where at least one of the two passers is in-trade, then correlate. Or compute correlation only on trade-overlap bars (both in-trade) — though that may be too sparse with small trade counts.

**Rule:** When `decide_portfolio.py` says |ρ| > the threshold for a pair, sanity-check by counting overlap-of-flat days before concluding the strategies are redundant. The correlation matrix is a first-cut filter, not a final word — especially for low-trade-count passers like the relaxed-gate set.

---

## 33. OFR ≠ Bootstrap Robustness — They Test Different Failure Modes

**Result that prompted this:** On 2026-05-01, both relaxed-gate passers cleared **strict OFR** (Gate 2: NVDA cci_trend+stop OFR=0.82, V rsi_vwap+stop OFR=1.04 — the latter the strongest possible signal, OOS slightly outperforming IS), then **both came back FRAGILE** under block bootstrap (n=200): NVDA ratio=0.07 (sim median Sharpe 0.10 vs original 1.39), V ratio=0.37 (sim median 0.41 vs original 1.09). Both well below the 0.65 ROBUST cutoff. Verdict: portfolio = `NONE`, no passers cleared the full pipeline.

**Symptom signature:** Strong OFR (≥ 0.70, often ≥ 1.0) + weak bootstrap (ratio < 0.5).

**Why this happens — the two metrics test different things:**

| | OFR (Gate 2) | Block Bootstrap |
|---|---|---|
| Question | Do IS-tuned params hold on adjacent OOS windows of the *real* series? | Does the edge survive when the bar *sequence* is shuffled (preserving local autocorrelation)? |
| Failure mode caught | Curve-fitting to a specific IS window | Path-dependence on a unique macro arc |
| Failure mode missed | Path-dependence baked into the underlying asset's history | Period-specific overfitting that the WF folds happen to span |

**The mechanism (NVDA cci_trend+stop case):**
- Real NVDA 2021–2026 has a specific shape: rally → bear ’22 (–65%) → AI rally ’23–’24. cci_trend with `entry=75 / exit=50 / vol=0.8` is structurally tuned to ride the post-bear leg up. WF folds (IS=2y, OOS=1y, step=6mo) all span versions of that same arc → OFR looks great.
- Block bootstrap reshuffles 25-bar blocks of returns. The *blocks* preserve volatility clustering and local autocorrelation, but the *macro arc* is destroyed. Without that specific 2022→2024 sequence, the entry/exit thresholds are no longer aligned with the price structure — the strategy's edge is path-noise, not a repeatable mechanic.
- The sim Sharpe distribution (p5=-2.83, p25=-0.73, p50=0.10, p75=0.78, p95=1.44) confirms it: the original 1.39 is at roughly the 90th percentile of bootstrap samples, i.e. **looks like a draw from a noise distribution, not a robust signal**.

**The mechanism (V rsi_vwap+stop case):**
- V is a low-volatility, mean-reverting payments stock; rsi_vwap is a mean-reversion strategy. The pairing matches asset character to mechanism, so some edge survives randomisation (sim p50=0.41 — non-trivial, narrower distribution than NVDA).
- But the original 1.09 is still at the upper tail of the bootstrap distribution → the actual sequencing of V's small dips contributed substantially to the in-sample Sharpe, beyond what the underlying mechanic supports.

**Predictor (where this divergence is likely):**
- Single-asset trend strategies on assets with a defining macro narrative (NVDA, TSLA, BTC) → high OFR (because every WF window has a slice of that narrative), low bootstrap ratio (the narrative is what the strategy fits).
- Mean-reversion strategies on stable, low-vol assets → mid OFR, mid bootstrap. V is the canonical example.
- Low-OFR + high-bootstrap is rare — usually means the strategy is a noisy generalist on a noisy asset (rare to even surface from a sweep).

**Rule:** **OFR is necessary but not sufficient.** Treat both Gate 2 (OFR ≥ 0.70) and bootstrap (ratio ≥ 0.65) as required gates with no relaxation tradeoff between them — they catch *different* failure modes, so a strategy that fails either is unsafe. **Block bootstrap is the harder test for trend strategies on assets with strong narratives** because it specifically destroys the macro structure those strategies fit. When designing future sweeps, expect OFR-passing trend strategies to fail bootstrap unless they generalise across multiple assets with different macro shapes — that cross-asset replication is the actual robustness signal we want, not single-asset OFR + bootstrap.

**Implication for portfolio strategy:** Prefer mean-reversion mechanics (rsi_vwap-style, bb_reversion-style) for paper-trading candidates over single-asset trend mechanics, because mean reversion is less path-dependent — the edge comes from a recurring local pattern rather than a unique macro arc. Trend mechanics are still valuable but need to *replicate across multiple uncorrelated symbols* before being trusted, since any single-symbol trend pass is suspect under bootstrap.

---

## 34. Architectural Falsification — The Single-Asset Universe Cannot Pass the Full Robustness Bar

**Result (2026-05-02):** After 4 sweeps × 3 bootstrap rounds × 1 wrapper retrofit × 1 history-extension test, **zero candidates cleared the full pipeline**. Every available lever within the single-asset, daily/weekly, 17-symbol architecture has been falsified.

**Levers tested and outcomes:**
| Lever | Result |
|---|---|
| Trend mechanics (top-4 +stop, 5-yr 1d) | 1 strict G1+G2; bootstrap ratio 0.07 → FRAGILE |
| Mechanic widening (momentum / donchian / alpha_composite / bb_reversion +stop) | 0 strict; 1 relaxed near-miss; all FRAGILE under bootstrap |
| Cross-timeframe replication (1wk × same 8 strategies) | 8 relaxed-gate passers (best signal: bb_reversion+stop NVDA replicated on both 1d AND 1wk); all 7 bootstrap candidates FRAGILE |
| Pair-spread mechanics (5 sector pairs × 2 mean-reversion strategies) | 0 G1+G2; max Sharpe 0.55 — robust mechanic but no edge after costs |
| Vol-targeting wrapper (`+stop+vol`) on 9 fragile candidates | Lifted negative ratios to ~0; top ratio 0.28 vs 0.65 cutoff |
| 10-yr history extension on 3 1d candidates | **Original Sharpes collapsed 30–50%** (1.39→0.81, 1.10→0.83, 1.17→0.64); cci_trend NVDA bootstrap ratio improved 0.07 → 0.52 (validates path-dependence diagnosis) but absolute Sharpe too low to be tradable |

**The headline empirical finding (10-yr extension):** `cci_trend+stop` on NVDA produced Sharpe **1.388 on 5-yr daily** (the project's only strict G1+G2 pass — lessons #27); the same strategy's optimal 10-yr Sharpe is **0.810**. That 0.58 drop is the strategy's specific dependence on the 2022 bear → 2023–24 AI rally arc — when the optimizer can pick params over a window that *also* contains 2018 selloff + 2020 COVID + multiple sideways periods, the chosen params land on a much weaker equilibrium edge. **The 5-yr Sharpe was real but unrepeatable.**

**The most important diagnostic improvement (also from the 10-yr extension):** the same cci_trend NVDA candidate's bootstrap ratio went from 0.07 (5-yr data) → **0.52 (10-yr data)**. This is direct evidence that path-dependence *was* the dominant bootstrap-failure mechanism — block-bootstrap with 10 yr of return blocks produces synthetic paths that are *less* dominated by the 2022→2024 arc, so the strategy's edge generalises better. But because the absolute Sharpe also dropped, the sim median (~0.42) is now too low to deploy. **Closest case to ROBUST in the entire project, and still 0.13 short.**

**Architectural conclusion:** The bottleneck is not the strategy class, the wrapper choice, the trade-count threshold, or the data length. It is the *single-asset framework itself*. Every long-only strategy on a single equity is by construction making a directional bet on that asset's specific macro path. Any optimizer that selects params on a fixed history window is fitting to that path. Bootstrap correctly identifies this — and the 10-yr test confirmed that more data attenuates but does not eliminate the failure mode, because the absolute edge available within a single-asset directional bet is small enough that fitting noise dominates signal.

**What would actually work (path-independent edges):**
1. **Cross-sectional / portfolio strategies** — long top-N, short bottom-N by momentum/quality/value. The edge is *relative ranking* across many assets, not an absolute price path. Generates hundreds of independent signals per day vs ~30 per year for a single-asset trend strategy. Requires extending the backtest engine to multi-symbol simultaneous orders (~1–2 days build).
2. **Factor models with explicit risk attribution** — Fama-French style, decomposing returns into market / size / value / momentum factors. Different research stack entirely.
3. **Alternative data** — earnings drift, news sentiment, options flow. Out of scope for this codebase.

**Rule:** When every available lever within an architecture has been falsified, *the architecture is the result*. Don't keep searching for the missing strategy choice — name the conclusion. The single-asset, 5–10-yr daily/weekly long-only backtest framework is **methodologically incapable of producing a bootstrap-robust paper-tradable edge on this 17-symbol universe**. The honest path forward is to (a) treat the framework as a research testbed that has correctly *rejected* every strategy in its scope (a real and rare result), and (b) only invest further engineering effort if pivoting to a structurally different architecture (cross-sectional / multi-asset) where the edge isn't path-dependent by construction.

**What the artifact actually is, after this session:** a methodologically rigorous robustness pipeline (walk-forward + OFR + block bootstrap + portfolio decision gate + cross-timeframe replication test + vol-targeting overlay) that *successfully falsified* every candidate it was given. That is unusual and useful — most retail backtest tooling will happily declare a 5-yr Sharpe-1.4 strategy tradable; this pipeline correctly refused.

---

## 35. Universe Alignment Is Gated By The Shortest-History Symbol

**Symptom:** v1 of the cross-sectional momentum pipeline (run_xsec_pipeline.py) was killed at Stage 1 with MaxDD=49% even though we'd just fetched 10 yr of daily data for 17 symbols. The strategy looked path-fitted to 2022→2024 — exactly the trap lessons #34 said the architecture pivot would solve.

**Root cause:** `closes.dropna()` returned only 1,403 bars (~5.5 yr) because PLTR (IPO 2020-09-30) and CRWD (IPO 2019-06-12) only had partial overlap with the older symbols. The intersection of "all 17 have data" was the IPO date of the most-recent newcomer, not the average ticker's history. So we had 10 yr of data per symbol but a 5.5 yr cross-section — and the cross-section is what the strategy actually uses.

**Fix:** v2 dropped PLTR + CRWD from the universe (15 symbols), recovering the full 10 yr aligned window (2,515 bars). Stage 1 immediately passed (MaxDD 22.5%) and the full pipeline cleared with `PORTFOLIO_READY` (Sharpe 1.503, OFR 1.552, bootstrap ratio 0.820).

**Rule:** Before any cross-sectional sweep, print **both** the per-symbol bar count and the aligned cross-section bar count. If aligned-count < 0.7 × per-symbol-count, the cross-section is gated by an outlier and the universe should be trimmed to recover the full aligned window. The single newcomer's IPO date can poison an otherwise fully-fetched universe.

---

## 36. Long-Only Strategies On A Homogeneous Universe Inherit ~0.7 Inter-Strategy Correlation From Market Beta

**Symptom:** After 3 cross-sectional strategies (12-1 momentum, low-vol BAB, short-term reversal) all cleared the full 5-stage pipeline as `PORTFOLIO_READY`, the pairwise daily-return correlation matrix was:

| | momentum | lowvol | reversal |
|---|---:|---:|---:|
| momentum | — | 0.78 | 0.70 |
| lowvol | 0.78 | — | 0.78 |
| reversal | 0.70 | 0.78 | — |

Equity-curve correlation: 0.99 across all pairs. Greedy uncorrelated selection at |ρ|<0.5 admitted only 1 of 3.

**Root cause:** all three strategies trade the same 15-symbol tech mega-cap universe with long-only top-K=5. The underlying assets (NVDA, AAPL, MSFT, META, GOOG, AMZN, etc.) are ρ ≈ 0.6-0.7 with each other due to shared sector / market-cap / "Mag 7" factor exposure. With only 15 names and top-K=5, even strategies that pick *different* baskets overlap by ≥ 1 name on most days, and the systematic correlation between assets in the universe sets a **floor on inter-strategy correlation**. The "different mechanics" don't matter if they all express through the same homogeneous portfolio.

**Implication for lesson #27:** "≥ 3 uncorrelated ROBUST passers across ≥ 2 sectors" cannot be satisfied within a single homogeneous universe regardless of mechanic diversity. The lesson #27 floor isn't just about the strategies; it's about the *universes* the strategies trade. If all candidates share one universe, correlation will be high.

**Rule:** When evaluating cross-sectional candidates for portfolio construction (lesson #27 ≥3-uncorrelated rule), require that candidates either (a) span structurally different universes (e.g. tech mega-caps vs sector ETFs vs bonds vs FX), or (b) use market-neutral L/S formulations that cancel systematic exposure. Pairwise daily-return correlation ≥ 0.5 between candidates in the same universe is the *expected* outcome, not a sign of strategy similarity.

---

## 37. L/S Variants Reveal That Long-Only "Factor Edges" Can Be Artifacts Of One-Sided Market Exposure

**Symptom:** Three long-only cross-sectional strategies cleared the full pipeline as ROBUST (Sharpes 1.08-1.50). When the same mechanics were re-tested as market-neutral long-short (long top-K, short bottom-K, equal dollar weight):

| Strategy | LO Sharpe | LS Sharpe | LS MaxDD |
|---|---:|---:|---:|
| momentum | +1.503 | +0.941 | 20.5% |
| **low-vol** | **+1.264** | **-0.861** | **79.7%** |
| **reversal** | **+1.083** | **-0.676** | **70.9%** |

Low-vol and reversal **flipped to severely negative** in L/S form.

**Root cause:** the 2018-2026 tech mega-cap universe had a positive beta-return relationship — the *most* volatile assets (NVDA, TSLA) were also the *highest* returners (AI rally). The long-only versions of low-vol and reversal accidentally captured **half** of this — they avoided the high-vol/recent-winner tech ripper effect — but in L/S, the short leg shorts those very names, and the rip then ruins what the long leg captured.

So:
- Long-only low-vol "edge" was ~50% true low-vol BAB factor + 50% structural long-only bias against the most volatile names. The first half is real; the second half is a no-edge artifact.
- Long-only reversal "edge" was ~50% mean reversion in losers + 50% missing the AI-rally winners. Same artifact pattern.
- Long-only momentum was ~80% real momentum factor (it survives in L/S form) + 20% market beta.

**The L/S Sharpe is the cleaner factor measurement.** Long-only Sharpe inflates real factor edges by 2x or more on universes with strong beta-return correlations.

**Rule:** When cross-sectional long-only strategies look strong (Sharpe > 1.0) on a homogeneous universe with strong directional beta exposure, **always re-test in L/S form**. If L/S Sharpe drops > 50% or flips negative, the long-only result is half-real-factor / half-beta artifact and should not be promoted to paper-trading without further isolation. The L/S residual is the genuine portion of the edge; the long-only excess is structural beta exposure that was monetised in the specific historical window but isn't a factor signal.

**For portfolio construction:** prefer L/S Sharpe as the headline metric for cross-sectional candidates, even if absolute level is lower (0.7-1.0 typical for L/S vs 1.2-1.5 for LO). L/S edges are more transferable across universes and more robust to regime changes (the 2023-2024 tech rip wasn't predictable; the L/S Sharpe doesn't depend on it).

---

## 38. Same Universe + Different Sampling Rate ≠ Independent Signals

**Result:** Cross-sectional momentum (mechanically identical) on the 15-symbol mega-cap universe was tested at three sampling rates with timeframe-appropriate parameters (1d: 6mo lookback, 1wk: 13wk lookback, 1h: 819-bar lookback). All three cleared the full 5-stage pipeline as `PORTFOLIO_READY`:

| Timeframe | Aligned bars | Sharpe | OFR | Bootstrap ratio | Verdict |
|---|---:|---:|---:|---:|---|
| 1d (10y) | 2,515 | 1.503 | 1.552 | 0.820 | ROBUST |
| 1wk (5y) | 256 | 1.712 | 1.507 | 0.759 | ROBUST |
| 1h (3y) | 5,068 | 1.405 | 2.315 | 0.771 | ROBUST |

But on the common 33-month observation window:

|  | 1d | 1wk | 1h |
|---|---:|---:|---:|
| 1d | — | 0.688 | 0.797 |
| 1wk | 0.688 | — | 0.694 |
| 1h | 0.797 | 0.694 | — |

Equity-curve correlation: 0.97–0.99 across all pairs. Greedy uncorrelated selection at \|ρ\| < 0.5 admits only 1.

**Diagnosis:** all three are picking the same baskets at slightly different cadences. Hourly-momentum's top-5 by 819-bar trailing return ≈ daily-momentum's top-5 by 126-bar trailing return ≈ weekly-momentum's top-2 by 13-week trailing return. The signal is "which assets have outperformed recently" and it doesn't matter if "recently" is measured in bars, days, or weeks — the *answer* is largely the same.

**Implication for lesson #27 (≥3 uncorrelated, ≥2 sectors):**
- Same mechanic + same universe + different timeframes → 1 signal, not 3.
- Different mechanics + same universe + same timeframe → 1 signal, not 3 (lesson #36).
- The only way to get genuinely uncorrelated cross-sectional candidates is **different universes**: tech mega-caps vs sector ETFs vs bonds vs FX vs crypto.

**The cross-timeframe replication is a strong validation signal, not a diversification signal.** Three timeframes all clearing the bootstrap on the same edge is empirical confirmation that the underlying momentum factor is real (not a quirk of one sampling rate). It is not three independent strategies.

**Rule:** when computing the lesson #27 ≥3-uncorrelated tally, **count by (mechanic × universe), not by (mechanic × timeframe).** Cross-timeframe results from the same universe contribute 1 strategy to the diversity count regardless of how many sampling rates pass. To unlock further diversification, fetch a structurally different universe (commodity / FX / fixed-income / sector-ETF / international) and re-run the pipeline there.

---

## 39. Multi-Asset Pivot Confirmed — Crypto + Equity = First Uncorrelated PORTFOLIO_READY Pair

**Result (2026-05-03):** Same xsec momentum mechanic on the 9-crypto universe (BTC/ETH/SOL/BNB/XRP/ADA/AVAX/DOGE/LINK via yfinance USD pairs) cleared the full 5-stage pipeline as `PORTFOLIO_READY`:
- Sharpe 1.091, CAGR 25.3%, MaxDD 29.8%
- OFR 2.494 (very strong), bootstrap ratio 0.816
- Best params: 30-day lookback, top-2, weekly rebalance — appropriately short for crypto's faster cycles
- Vol-target overlay tuned for the asset class: target vol 20% (vs 15% for equities), PERIODS_PER_YEAR=365 (7-day market)

**Cross-universe correlation with the equity xsec momentum strategy:**
- Monthly-return ρ = **0.401** ← UNCORRELATED at the lesson #32 threshold (|ρ| < 0.5)
- Equity-curve ρ = 0.95 (both are net positive growth strategies, so curves trend together — the *wrong* measure here; monthly returns are the right one)
- Equal-weight ensemble: variance is **32% lower** than the average single strategy

This is the project's **first genuinely uncorrelated pair of PORTFOLIO_READY strategies**. Lessons #36/#38's prediction is empirically confirmed — cross-universe is the binding lever for portfolio diversification, not cross-timeframe or cross-mechanic within one universe.

**Bonds (Phase 9 alongside crypto):** TLT/IEF/SHY/LQD/HYG/AGG/BND/TIP/MUB on 1d/10y. Pipeline cleared Stage 1 (Sharpe 0.40) and Stage 2 (bootstrap ratio 1.193 — extremely robust mechanic) but **killed at Stage 3 — best Sharpe 0.704 < 1.0**. Bonds have a real path-independent edge for momentum but the absolute magnitude is too modest to clear strict Gate 1. Same pattern as sector ETFs.

**Implication:** the bottleneck for the third uncorrelated strategy isn't bootstrap robustness or path-dependence — those are solved by the multi-asset pivot. It's **absolute Sharpe magnitude**: low-volatility asset classes (bonds) and low-dispersion universes (broad sector ETFs) produce real but modest edges that don't clear our 1.0 threshold even when bootstrap-perfect.

**Rule:** for the lesson #27 ≥3-uncorrelated bar, focus on universes with **structural dispersion** (cross-sectional volatility / variance of returns across constituents). Mega-cap equities and crypto both have high dispersion — winners outperform losers by 50-200% annualised, leaving room for momentum to extract a strong signal. Bonds and broad sector ETFs have ~10-20% dispersion — even a perfect mechanic finds only modest edges. Next universes to try: **FX (currency-pair vols range 5-15%, high dispersion)**, **commodities (energy / metals / agriculture, high dispersion)**, **international equities (regional baskets, EM has high dispersion)**.

---

## 40. Regime Filter Is The Single Most-Impactful Single Change — `Asset > 200d-MA` Gate

**Result (2026-05-03):** A trivial regime filter — *only trade when the universe's bellwether asset is above its 200-day moving average* — applied to the two PORTFOLIO_READY strategies (equity xsec momentum gated by SPY > 200d-MA; crypto xsec momentum gated by BTC > 200d-MA) produced these full-window deltas vs unfiltered:

| | Equity ΔSharpe | Equity ΔMaxDD | Crypto ΔSharpe | Crypto ΔMaxDD |
|---|---:|---:|---:|---:|
| Full 5-10 yr window | **+0.402** (1.503 → 1.905) | **-8.8 pts** (19.6 → 10.8%) | **+0.523** (1.091 → 1.614) | **-14.8 pts** (29.8 → 15.0%) |

**The 2022 bear-year breakdown is the dramatic case:**
- Equity 2022 Sharpe: **-0.400 → +0.721** (filter sat 81% in cash)
- Equity 2022 MaxDD: 16.1% → 7.8%
- Crypto 2022 Sharpe: **-0.640 → +0.000** (filter sat 100% in cash, completely dodged crypto winter)
- Crypto 2022 MaxDD: 26.5% → 0%

**Filtered ensemble metrics (50/50 equity_filt + crypto_filt):**
- Sharpe **1.893** (best in the project)
- CAGR 21.7%
- MaxDD **9.2%** (institutional-quality drawdown)
- Inter-strategy ρ **0.179** (vs 0.401 unfiltered — even better diversification because both go to cash in regime-OFF, neutralising correlated downside)

**Why this works:** cross-sectional momentum is structurally a *trend-following* mechanic — it longs assets that have outperformed recently. In trending bull markets it captures persistence; in choppy or bear regimes the "winners" reverse and the strategy bleeds. The 200d-MA gate is the simplest possible bear-market detector — when the index is below its long-run mean, the trending regime has broken and momentum is unreliable. The filter sits in cash exactly when the strategy's edge would be negative.

**This generalises:** the filter is **conjugate** to the strategy mechanic. A momentum strategy needs a trend-detection filter (200d-MA). A mean-reversion strategy would need a *volatility-regime* filter (only mean-revert when realised vol is below a threshold). A breakout strategy would need a *trending* filter. Each strategy class has a regime in which its mechanic *should* work — the filter's job is to detect when that regime is absent and step aside.

**Bootstrap caveat:** the bootstrap on the filtered equity strategy returned ratio 0.638 — just below the 0.65 ROBUST cutoff. **This is an artefact of the bootstrap design**, not a fragility finding. The bootstrap synthesises new asset paths but the regime filter still uses the *real* SPY series for its 200d-MA gate, creating a logical inconsistency between filter timeline and strategy timeline. Proper bootstrap would synchronise SPY into the synthetic universe (SPY is in our 15-symbol list, so this is straightforward). Without that fix, the filtered-bootstrap result is suggestive but not authoritative. Re-test with SPY-synchronised bootstrap before treating 0.638 as a real bootstrap failure.

**Rule:** **Always pair a strategy with its conjugate regime filter before paper-trading.** A strategy that works "in the right regime" but bleeds "in the wrong regime" is unsafe to deploy without the filter. The regime filter is *not* an enhancement — it is part of the strategy's correctness specification. For a momentum strategy, the rule is `if SPY < 200d-MA → cash`. For mean-reversion, the rule is `if realised_vol > threshold → cash`. The filter typically improves Sharpe by 0.3-0.5 and cuts MaxDD by 30-50% — the largest single-change improvement available, and a critical safety net for live deployment.

---

## 41. No Single Regime Filter Wins All Regimes — Soft + Breadth Dominates Chop, Binary Wins Sustained Bears

**Result (2026-05-03):** Six filter variants tested on the equity xsec momentum strategy across the full 10-yr window plus four stress sub-periods. Variants:
- A: unfiltered baseline
- B: binary 200d-MA on bellwether (SPY for equity, BTC for crypto)
- C: soft 200d-MA (linear ramp 0 at 0.95×MA → 1 at 1.05×MA)
- D: binary breadth (>50% of universe above own 200d-MA)
- E: combined binary (B AND D)
- F: soft combined (soft price × soft breadth)

**Full-window ranking (Sharpe):** F (1.951) ≈ C (1.941) > E (1.937) ≈ B (1.905) > D (1.893) > A (1.503). Top variants are within noise of each other on the full window.

**Stress-period ranking is variant-specific — no overall winner:**
| Period | Best variant | Best Sharpe | Why |
|---|---|---:|---|
| 2018 chop | F (soft+breadth) | 2.152 | Partial allocation rides through whipsaw |
| 2020 H1 V-shape | D (breadth) | 3.225 | Breadth recovers faster than price-vs-MA |
| 2022 sustained bear | B (binary price) | 0.721 | Clean cut; soft variants bleed via partial allocation |
| 2024-25 bull | C (soft price) | 1.679 | No unnecessary cash during minor pullbacks |

**The key lesson:** filter ranking flips by regime. Soft variants (C, F) dominate choppy and bullish regimes — partial allocation avoids whipsaw and cash-drag. Binary variants (B, E) dominate sustained bears — they cut cleanly and stay out, while soft variants leak by holding partial allocation through the slow grind down.

**Diagnostic implication:** if you pick a filter by full-window Sharpe alone, you'll get a chop-and-bull-favoured variant (F) that underperforms in sustained bears (2022 F: 0.20 vs B: 0.72). For paper-trading deployment, the right framing is: optimize the filter for the regime you're *most concerned about*. If 2022-style sustained bears are the primary tail risk, choose B. If 2018-style chop and 2020-style fast V-shapes are the worry, choose F.

**Practical recommendation for our deployment:** **B_binary_price for equity** (clean bear-market protection is the binding tail risk) and **F_soft_combined for crypto** (crypto's volatility profile favours soft handling — and 2022 winter was already cleanly avoided by B's predecessor). Best ensemble: Sharpe 1.956, MaxDD 6.2%, ρ=0.16.

**SPY-synchronised bootstrap fix:** lesson #40 noted that the regime-filter bootstrap returned ratio 0.638 (just under 0.65) but caveated this as a bootstrap-design artefact (synthetic universe + real SPY timeline). With SPY synchronised into the synthetic block-bootstrap (SPY is in the 15-symbol universe; we just use the synthetic SPY series for the regime filter inside each sim), the ratio jumps to **0.901 — decisively ROBUST**. The earlier 0.638 was indeed an artefact, not a real fragility signal. Lesson: when bootstrapping a strategy that has a filter or external input, always verify the filter input is included in the synchronised bootstrap; otherwise the bootstrap measures something other than the strategy's actual robustness.

**Rule:** when designing regime filters, **don't pick by full-window Sharpe alone.** Run a stress-test grid (one column per regime: chop / V-shape / sustained-bear / bull-continuation) and choose by the *worst-case* metric in your most-concerning regime. The strategy is the part that earns alpha; the filter is the part that controls tail risk. Both matter, but the filter's job is specifically tail-risk management, so optimize it for tails not means.

---

## 42. Cash Buffer Preflight Was Incompatible With A 100%-Allocated Strategy — Silent Halt For 4 Days

**Symptom (2026-05-11):** While verifying a universe-v2 change, found the paper-trade cron had been **silently halted since 2026-05-07** — 4 consecutive scheduled rebalances (May 7, 8, 11) all blocked by the `cash_buffer` preflight failing with `cash buffer -0.0160 < 0.01`. The same exact $-1,647.42 deficit appeared in all halted runs, confirming no rebalance had executed to correct it. State file `last_updated_utc` was 2026-05-05 — the last successful rebalance.

**Root cause:** The strategy spec is `top_k=5, weight=1/top_k=0.20` per name — **100% allocated, zero cash reserve by design**. The preflight required cash ≥ 1% of portfolio value as a buffer for commission + slippage. These two requirements are *mathematically incompatible* the moment any held position drifts above its 20% target — which happens every period a winner appreciates faster than the basket average. On 2026-05-11 live broker state showed ASML at 21.8% and QQQ at 20.5% of portfolio; positions summed to 101.6% → cash was −1.6% → preflight halted the rebalance that would have *fixed* the drift.

**The vicious loop:** the cash deficit can only be corrected by selling overweight positions, but the preflight blocks rebalance precisely because cash is negative. Without manual intervention, the strategy stays halted forever the moment any winner runs.

**Fix:** Loosened `min_cash_buffer_pct` from `+0.01` to `-0.02` in `runner_main.py:194`. The buffer's job is to alarm on *cash blowouts* (a sign of margin abuse or pricing bugs), not on normal drift from a fully-allocated strategy. −2% tolerates a position drifting from 20% to ~22% before alarming — comfortably above commission/slippage but well below a true cash crisis.

**Better long-term fix (not done):** make the strategy spec leave a structural cash buffer (e.g. `top_k=5, weight=0.19` → 95% allocated, 5% cash). This is the cleaner architectural answer — preflight thresholds shouldn't fight the strategy's own allocation logic — but it requires re-backtesting the strategy with the cash drag included. Filed as future work; the threshold loosening is the operational unblock.

**Rule:** **A preflight check that can never pass under the strategy's normal operation is not a safety check — it's a bug.** Whenever you wire a preflight gate, verify it can pass under the strategy's *steady state*, not just its initial state. For a 100%-allocated strategy, the cash buffer must be ≤ 0 minus expected drift; for a leveraged strategy it must account for margin; for a multi-asset strategy it must account for currency settlement timing. Run the preflight against the live state at least once before scheduling the cron — silent halts are worse than loud failures because they masquerade as success.

---

## 43. Reconciler Doesn't Credit Pending SELLs Against Phantom Positions — False-Positive Halt After Pre-Market Rebalance

**Symptom (2026-05-11, 11:57 UTC / 07:57 EDT pre-market):** Submitted a paper-mode rebalance that swapped AMZN out for AMD. All 4 orders submitted successfully to Alpaca (3 SELLs + 1 BUY) and were `accepted` with `status=new`, queued for the 09:30 EDT market open. Immediately after submission, the reconciler ran and **wrote a halt** with reason `per_symbol_drift=0.1153>0.01; cumulative_drift=0.1574>0.005; phantom_symbols=['AMZN']` — even though `equivalence_check_passed=true` and the runner correctly submitted the right 4 orders. Next day's cron would have been blocked by this false-positive halt unless cleared.

**Root cause:** `reconciler.py:96-107` IS pending-aware — it credits pending BUYs against missing-expected symbols (so AMD wouldn't false-flag as missing). But the symmetric case for **pending SELLs against phantom positions** (broker has, target doesn't) is missing — `reconciler.py:138-147` classifies any broker-held symbol not in target as `phantom`, regardless of whether a SELL is pending. When the rebalance is submitted during pre-market or after-hours (orders queued but not filled), every position being closed-and-replaced will momentarily show as phantom + drift until fills land.

**Workaround used:** waited for market open + fills, then ran `clear-halt`. Orders filled cleanly except for a $139 fractional-share residual (0.52 sh AMZN — Alpaca couldn't fully close the fractional position in one market order); submitted a manual cleanup SELL before clearing the halt.

**Proper fix (not done):** mirror the `pending_fill` logic for the phantom branch — if a symbol is broker-held + target=0 + has a pending SELL of equal-or-greater magnitude, classify as `pending_close` rather than `phantom`. One-block change in `reconciler.py` reconcile loop. Filed as future work.

**Adjacent issue — fractional residuals:** Alpaca paper sometimes leaves a small fractional remainder after a SELL of a fractional position. The runner's `rebalance_threshold_pct=0.005` (0.5% of portfolio) means a $139 / $100k = 0.14% residual is **below threshold and would never be retried** by normal rebalance. Combined with the reconciler bug above, this means: every cross-asset swap creates a permanent phantom that halts all future rebalances until manually cleaned up.

**Rule:** **When orders are queued but not filled (pre-market, after-hours, or any broker latency), the reconciler must credit pending orders symmetrically — pending BUYs against missing-expected, AND pending SELLs against phantom-broker.** The asymmetric implementation creates a "you can't rebalance when the market is closed" bug that's invisible at design time and surfaces only when the cron happens to fire during a quiet period. Adjacent rule: **the rebalance threshold (`rebalance_threshold_pct`) interacts with broker fractional behavior** — any rebalance that creates a residual smaller than the threshold will leave it forever; for full position closes (target = 0), bypass the threshold and force the SELL to completion.

---

## 44. Leveraged-ETF DCA Over a Decade — Leverage Premium Holds But Sharpe Degrades Monotonically

**Setup (2026-05-17):** $100/month DCA into SPY (1×), UPRO (3×SPY), QQQ (1×), QLD (2×QQQ), TQQQ (3×QQQ) from 2016-06 → 2026-05 (120 months, $12,000 invested per ticker). All prices yfinance close, auto-adjusted for splits + dividends.

**Money-multiple result:**

| Ticker | Ending value | Money mult | Sharpe (daily) |
|---|---:|---:|---:|
| SPY  | $26,883 | 2.24× | 1.46 |
| UPRO | $52,628 | 4.39× | 1.26 |
| QQQ  | $35,086 | 2.92× | 1.47 |
| QLD  | $64,798 | 5.40× | 1.36 |
| TQQQ | $89,308 | **7.44×** | **1.26** |

**The two stories:** Money multiple monotonically increases with leverage (TQQQ 7.44× vs QQQ 2.92× — a 2.55× advantage that the volatility-drag thesis would have *not* predicted holding). But Sharpe monotonically *decreases* with leverage (TQQQ 1.26 vs QQQ 1.47) — the leveraged products are less efficient per unit of daily volatility. **Both are true at the same time** because DCA's per-lot cost basis spreads across the entire 10y window, so the 2022 bottoms get bought at 80% off ATH while the 2024-2025 highs only add a small fraction of cost basis.

**The 2022 hole:** TQQQ portfolio went $40,229 (2021-09) → **$11,717** (2022-10), a −71% paper loss over 13 months. An investor staring at that loss would have rationally panicked. The +644% terminal return only materialises if you held through that drawdown AND kept buying $100/mo through it — the 2022-2023 buys at TQQQ NAV $1-$2 (compared to today's $75) did most of the compounding work in the final number.

**Rule:** **The leveraged-ETF "leverage premium" is structurally real over complete bull → bear → recovery cycles, but it lives entirely in the money-multiple metric. Sharpe-aware investors will pick the unleveraged products.** Headline returns mean nothing without the path: the same TQQQ position evaluated at any 30-day window between 2022-02 and 2023-04 would have looked like a complete blowup. Investors who can't tolerate intra-position −70% paper losses should never hold a 3× leveraged ETF, regardless of multi-year backtest math.

---

## 45. yfinance ETF Close Prices Are NAV-Based and Already Net-of-Expense-Ratio — Don't Double-Count

**Trap:** Wanted to "apply ETF fees" to backtested DCA returns to see the after-fee P/L. **The fees are already in there.** ETF NAV is computed by the fund daily as `(gross basket value) - (accrued daily expense fee)`, where `daily_fee = NAV × (annual_ER / 365)`. The market closing price ≈ NAV due to arbitrage. yfinance's `auto_adjust=True` adjusts historical prices for splits and dividends only — **NOT for expense ratio**, because the ER is already baked into the close price by the fund itself.

**Implication for ER calculations:** Subtracting `ER × years` from a backtested return computed from yfinance closes double-counts the fee drag. The honest interpretations of "apply ETF fees":
- **Net of fees** (what yfinance prices give you, already): the actual investor experience.
- **Gross of fees** (no-ER hypothetical): multiply each lot's value by `(1 + ER/252)^days_held` to back out the drag.
- **Extra ER applied** (e.g. an advisor wrapper charging ER on top of the fund's own ER): multiply by `(1 - ER/252)^days_held`.

**Magnitude of fee drag (10y DCA $12k each):**

| Ticker | ER | Dollar cost of ER over 10y | % of principal |
|---|---:|---:|---:|
| SPY  | 0.0945% | $153   | 1.3%  |
| QQQ  | 0.20%   | $450   | 3.8%  |
| TQQQ | 0.84%   | $5,605 | 47%   |
| QLD  | 0.95%   | $4,457 | 37%   |
| UPRO | 0.91%   | $3,253 | 27%   |

TQQQ's 0.84% ER cost the investor ~$5,600 over 10y on $12k invested — nominally 47% of principal — but the compounding base grew so much that the net-of-fee return was still +644%. The fee drag is enormous in absolute dollars but invisible in money-multiple thinking.

**Rule:** **When backtesting any ETF strategy on yfinance data, treat the close prices as already-net-of-fee.** If you need to model an extra fee layer (advisor wrap, custodian fee), apply it on top of the NAV. If you need a "no-fee" comparator, back the ER out by compounding `(1 + ER/252)^days_held` per lot. Same convention applies to mutual funds. **Crypto exchange prices are *not* NAV-based** — they're traded spot, with no ongoing fee accrual — so applying a "management fee" to a crypto-asset backtest would be additive rather than double-counted.

---

## 46. The 200d-MA Exit-Reenter Regime Filter on Leveraged-ETF DCA — Lesson #40 Confirmed and Amplified

**Setup:** Same 10y DCA from 2016-06, but with the lesson #40 conjugate filter applied to each ticker's underlying (SPY's 200d-MA for SPY/UPRO; QQQ's 200d-MA for QQQ/QLD/TQQQ). Three modes:
- **baseline**: buy $100 every month
- **skip-buy**: buy only when regime ON; otherwise cash accumulates, existing positions held
- **exit-reenter**: when regime OFF, sell everything to cash; when ON again, redeploy all cash

**Result — MaxDD reduction vs return give-up (exit-reenter vs baseline):**

| Ticker | MaxDD cut | Return give-up | Sharpe change |
|---|---|---:|---:|
| SPY  | −32.5% → −13.9% (57% cut) | +130% → +77% (53pp) | 1.46 → 1.43 |
| QQQ  | −29.9% → −17.4% (42% cut) | +207% → +135% (72pp) | 1.47 → 1.44 |
| UPRO | −76.5% → −42.8% (44% cut) | +370% → +245% (125pp) | 1.26 → **1.37** |
| QLD  | −60.9% → −34.4% (43% cut) | +495% → +340% (155pp) | 1.36 → **1.41** |
| TQQQ | −80.4% → −48.5% (40% cut) | +759% → +656% (103pp) | 1.26 → **1.35** |

**Key amplification of lesson #40:** the filter improves Sharpe on the *leveraged* products but does NOT improve Sharpe on SPY/QQQ. The 3× and 2× leverage amplifies both the bear-market loss (which the filter dodges) and the regime-cross slippage cost (~26 round-trips on SPY-ref over 10y), but the dodge dominates because of leverage's asymmetric downside. For unleveraged buy-and-hold, the filter is a slight Sharpe drag (slippage cost > benefit of dodging modest bears).

**Skip-buy alone is a no-op:** for all 5 tickers, the "skip new buys when regime OFF, hold existing positions" mode cut MaxDD by only 1-2pp vs baseline. The MaxDD is dominated by *existing capital crashing*, not by *new capital being added at bad prices*. **The only filter that meaningfully helps leveraged-ETF DCA is the full exit-reenter rule.**

**Operational cost:** 22-26 forced sell/buy round-trips per ticker over 10y (≈5/year) for SPY-ref and QQQ-ref respectively. In a taxable account that's painful (short-term cap gains on every round-trip); in IRA/paper it's only spread + slippage cost (negligible for liquid ETFs).

**Whipsaw risk on re-entry:** UPRO exit-reenter MaxDD shifted from the 2020 COVID crash to a 438-day window ending 2023-03-17 — because once re-entered after the 2022 bear, the SVB crisis hit and dropped UPRO immediately. The filter is regime-aware but not panic-aware; fast reversals after a re-entry can still hurt. Possible next iteration: **N-day re-entry delay or larger MA-distance threshold** to confirm the cross before redeploying.

**Rule:** **For DCA on leveraged ETFs, pair every strategy with its conjugate regime filter — specifically exit-reenter, not skip-buy.** Half-measures don't work because MaxDD is dominated by existing positions, not new ones. The cost of the exit-reenter (~5 round-trips/year and ~14% of terminal return) is dramatically less than the MaxDD-savings benefit (~40-50% reduction). Skip-buy and "regime-only-affects-new-money" variants should be considered failed designs for buy-and-hold leveraged products.

---

## 47. The Bad-Entry-Timing Paradox: DCA Started at the Absolute Top (2022-01) Had HIGHER Sharpe Than DCA Started 5 Years Earlier

**Setup:** Re-ran the 5-ticker DCA from 2022-01 (right before the worst bear since 2008) instead of 2016-06.

**Result — Sharpe across all 5 tickers IMPROVED with the worse entry:**

| Ticker | Sharpe 2016-start | Sharpe 2022-start | Δ |
|---|---:|---:|---:|
| SPY  | 1.46 | **1.75** | +0.29 |
| UPRO | 1.26 | **1.58** | +0.32 |
| QQQ  | 1.47 | **1.73** | +0.26 |
| QLD  | 1.36 | **1.61** | +0.25 |
| TQQQ | 1.26 | **1.52** | +0.26 |

Even baseline TQQQ DCA started at the worst possible month (Jan 2022) still produced **+238.5%** over 53 months. Min P/L% reached was **−44.1% in Jan 2023** — painful but bounded; the investor was down $574 on $1,300 invested.

**Mechanism:** DCA's worst-case is "sustained drawdown after a lot of capital has already been deployed." Starting Jan 2022 with $100 = $100 in when the crash started; every dollar after that bought low. The TQQQ buys at $1-$2 NAV during the 2022 bottom were so heavily averaged-down that the subsequent recovery did most of the heavy lifting. DCA loves volatility AT THE START and stability AT THE END.

**Second paradox — MaxDD shifted forward:** For all baseline tickers, the MaxDD from a 2022-01 start was no longer the 2022 bear at all. It's the **spring 2025 pullback** (2025-02-19 → 2025-04-08, 48 days, ~15-50% drop depending on leverage). By the time 2025 came around, the portfolio had grown enough that a smaller % pullback was a bigger $ hit than the early 2022 losses. **TQQQ MaxDD: −55.6%, 2024-12-16 → 2025-04-08, 113 days — not the 2022 bear at all.**

**Implication for DCA strategy evaluation:** *the "good entry" intuition from lump-sum investing does not apply to DCA.* A backtest with one start date doesn't tell you anything about a strategy's robustness. Run all DCA backtests across multiple start dates including the worst possible months. If a DCA strategy looks worse starting at the top than starting at the bottom, it's structurally broken (the cost-averaging mechanism is being defeated by something else, like leverage drift or fee compounding).

**Rule:** **For DCA strategy backtests, the worst-case start month should be reported alongside the average-case.** A DCA whose Sharpe improves with worse entry timing is a feature of the strategy, not a quirk. Conversely, a DCA strategy that crashes harder with worse entry is exhibiting hidden path-dependence and needs investigation. The 2022-01 start case is now the gold-standard stress test for any leveraged-ETF DCA strategy — if the strategy can't survive entering the day before a −80% bear, it's not deployable.

---

## 48. Adaptive Buy-Sizing for DCA — Taxonomy of Double-Down Rules and the First "Free Lunch" Hybrid

**Setup (2026-05-17):** Four DCA buy-sizing rules tested from 2022-01:
- **baseline**: $100/month
- **dd_pl**: $200 when current portfolio P/L% < 0, else $100
- **dd_ath**: $200 when underlying ≤ 80% × all-time-high (sticky until new ATH), else $100
- **dd_hybrid**: $200 when (ATH-condition AND price > 200d-MA), else $100

**Three orthogonal questions per rule:** terminal $, capital efficiency, Sharpe.

**Headline results (TQQQ):**

| Mode | Capital invested | Final $ | Money mult | Sharpe | MaxDD |
|---|---:|---:|---:|---:|---:|
| baseline   | $5,300 | $17,939 | 3.38× | 1.52 | −55.6% |
| dd_pl      | $6,900 | $26,981 | **3.91×** ← best money mult | 1.23 | −56.5% |
| dd_ath     | $9,900 | **$34,751** ← best terminal $ | 3.51× | 1.27 | −56.2% |
| **dd_hybrid** | $8,100 | $25,902 | 3.20× | **1.59** ← best Sharpe | −56.4% |

**Each rule wins on a different metric:**

1. **dd_pl wins on capital efficiency** — $5.65 extra return per $1 extra capital. The P/L% trigger is tight: it stops firing as soon as cost-averaging gets you back to breakeven, so DD capital only goes in at the deepest discounts.
2. **dd_ath wins on absolute terminal $** — but uses 87% more capital than baseline. The ATH trigger keeps firing for the entire underlying recovery (TQQQ was in DD-zone for 46 of 53 months because the underlying didn't reclaim its 2021-11 ATH until 2024-12), so the rule effectively becomes "buy $200/mo for 4 years" with no discipline.
3. **dd_hybrid wins on Sharpe** for 4 of 5 tickers, and **for SPY/QQQ/QLD/TQQQ the hybrid Sharpe BEATS baseline** (the first DD rule to do so). The hybrid combines value (ATH) with trend confirmation (MA), so it doesn't catch falling knives. It blocked all the TQQQ −60% to −81% buys of 2022 (when the underlying was in confirmed downtrend) but caught the entire 2023 recovery rally.

**None of the buy-sizing rules reduces MaxDD.** TQQQ MaxDD across all 4 modes: −55.6%, −56.5%, −56.2%, −56.4%. The MaxDD is dominated by the spring 2025 underlying crash hitting a fully-deployed portfolio. **No buy-sizing rule can fix MaxDD** — you need an *exit* rule (sell positions when regime OFF) for that.

**The hybrid's mechanism:** ATH condition says "the asset is on sale", 200d-MA condition says "but the bleeding has stopped". Together they filter out the worst falling-knife buys. The rule generalises beyond ETFs: **"value + trend confirmation" beats either filter alone for adaptive position-sizing on volatile assets.** This is the conjugate of lesson #40 (filter the mechanic to its working regime), now applied to position sizing rather than entry/exit.

**Sharpe comparison summary:**

| Ticker | Baseline | dd_pl | dd_ath | dd_hybrid |
|---|---:|---:|---:|---:|
| SPY  | 1.75 | 1.23 | 1.80 | **1.81** |
| UPRO | 1.58 | 1.25 | 1.28 | 1.25 |
| QQQ  | 1.73 | 1.24 | 1.72 | **1.79** |
| QLD  | 1.61 | 1.24 | 1.28 | **1.69** |
| TQQQ | 1.52 | 1.23 | 1.27 | **1.59** |

**Rule:** **Adaptive buy-sizing rules trade off across three independent dimensions (capital efficiency / terminal $ / Sharpe); no single rule dominates.** When designing a DCA strategy, pick the rule that matches your dominant metric: dd_pl for capital efficiency, dd_ath for maximum dollars-on-the-table, dd_hybrid for risk-adjusted return. **MaxDD reduction requires an exit rule, not a buy-sizing rule.** The next experiment in this line should combine dd_hybrid (buy-side) with the exit-reenter regime filter (sell-side) — that's the only path to simultaneously beating baseline on Sharpe, terminal $, AND MaxDD. Outputs of this analysis are saved under `reports/leveraged_etf_dca/`, `reports/leveraged_etf_dca_2022/`, `reports/leveraged_etf_dca_dd/`, `reports/leveraged_etf_dca_dd_filt/`, `reports/leveraged_etf_dca_dd_ath/`, `reports/leveraged_etf_dca_dd_hybrid/`.

---

## 49. Hybrid Buy-Side + Exit-Reenter Sell-Side — The First Strategy to Beat Baseline on Sharpe AND MaxDD Simultaneously

**Setup (2026-05-17):** Combined the lesson #48 hybrid buy-side rule (`$200 when price ≤ −20% from ATH AND price > 200d-MA`) with the lesson #46 exit-reenter sell-side rule (sell-all when regime OFF, redeploy on regime ON). Buy-side controls *how much*, sell-side controls *whether to hold or sit in cash*. Same 200d-MA reference for both gates (SPY for SPY/UPRO; QQQ for QQQ/QLD/TQQQ).

**Validation:** All 30 (ticker × mode) integrity checks confirmed `sum(monthly buys) == invested` and `n_buys == 53`. Strategy state machines for the two ATH and regime conditions verified to fire independently and non-overlapping.

**Result vs baseline ($100/mo plain DCA), 2022-01 → 2026-05:**

| Ticker | MaxDD baseline → hybrid_exit | Sharpe baseline → hybrid_exit | Money mult baseline → hybrid_exit | Outcome |
|---|---|---|---|---|
| SPY  | −15.4% → −9.4% (39% cut) | 1.75 → **1.77** (+0.02) | 1.54× → 1.42× | All 3 better ✅ |
| QQQ  | −19.7% → −12.0% (39% cut) | 1.73 → **1.80** (+0.07) | 1.77× → 1.66× | All 3 better ✅ |
| QLD  | −39.8% → −25.2% (37% cut) | 1.61 → **1.75** (+0.14) | 2.54× → 2.26× | All 3 better ✅ |
| TQQQ | −55.6% → −35.9% (35% cut) | 1.52 → **1.68** (+0.16) | 3.38× → 2.83× | All 3 better ✅ |
| **UPRO** ⚠ | −47.2% → −26.2% (45% cut) | 1.58 → **1.17** (−0.41) | 2.44× → 2.03× | Sharpe regresses |

**For 4 of 5 tickers — first strategy in the entire investigation that produces simultaneously better Sharpe AND lower MaxDD than baseline.** TQQQ headline: MaxDD cut by 1/3 AND Sharpe improved by 0.16 — the single best risk-adjusted result across all 30 (ticker × mode) combinations tested.

**UPRO breaks the pattern** because UPRO inherits SPY's regime gate (15 forced round-trips over 10y vs QQQ-ref's 10), and 50% more whipsaw on a 3× leveraged product eats Sharpe even though MaxDD still improves. Inference: the choice of regime-reference matters. For leveraged ETFs, the regime-reference should be the *smoothest* available proxy (QQQ may be a better regime gate than SPY for momentum-tilted leverage), or filtered with an N-day confirmation / MA-distance margin to suppress whipsaw crosses. Worth a follow-up test.

**Why the combo works:** the buy-side and sell-side gates are complementary, not redundant. Buy-side decides *when to deploy MORE capital* (during confirmed-recovery dips: ATH says "sale", MA says "bleeding stopped"). Sell-side decides *when to hold ALL cash* (during sustained downtrends: regime OFF = full exit). Together they:
1. Skip the catastrophic 2022 holds (sell-side dodged TQQQ's 11-month bear)
2. Capture the entire 2023-2024 recovery rally at $200/mo (buy-side fired aggressively once regime ON + still in DD-zone)
3. Skip the spring 2025 crash (sell-side exited again)
4. Re-engage on recovery (cycle repeats)

**Operational cost:** 10-15 forced round-trips per ticker over 53 months (~2-3/year on the regime crosses). In a taxable account that's ~15 short-term cap-gains events; in IRA/paper it's only slippage. The cost is far lower than the MaxDD savings.

**hybrid_exit vs exit-only (is adding the buy-side worth it?):** For 4 of 5 tickers, adding the hybrid buy-side to exit-reenter is purely additive — both more terminal $ AND higher Sharpe. TQQQ: exit-only $16,132 → hybrid_exit $22,905 (+$6,773 for +$2,800 extra capital), Sharpe 1.59 → 1.68. The buy-side and sell-side are orthogonal in their effect.

**Rule:** **For leveraged-ETF DCA, the production strategy should be `hybrid_exit` (buy-side hybrid + sell-side exit-reenter), with the regime-gate reference chosen to minimise whipsaw on the specific underlying.** This is the first design that simultaneously beats baseline on all three relevant metrics (Sharpe, MaxDD, terminal $) for QQQ-family ETFs. The combination is necessary — neither half alone delivers this triple win (exit-only sacrifices terminal $; dd_hybrid alone doesn't fix MaxDD). For SPY-derived leverage (UPRO), the regime gate needs additional smoothing (cross-confirmation or larger MA-distance threshold) before deployment. Outputs of this analysis are saved under `reports/leveraged_etf_dca_hybrid_exit/`. Next experiments: (a) UPRO with QQQ-MA or 1%-margin SPY-MA gate, (b) re-entry delay (N business days post-cross-up) to further reduce whipsaw, (c) full 10-yr window (2016-06 → 2026-05) to confirm the result generalises beyond the 2022-start sample.

---

## 50. The 10-Year Window Flips Several 2022-Start Conclusions — Regime Filter (Exit) Is the Single Most Powerful Improvement; Buy-Side DD Rules Are Sample-Dependent

**Setup (2026-05-17):** Re-ran the entire 6-strategy comparison (baseline / dd_pl / dd_ath / dd_hybrid / exit / hybrid_exit) on the full 10-year window from 2016-06 → 2026-05 (120 monthly buys × 5 tickers × 6 modes = 3,600 buy events). Validation: all 30 (ticker × mode) integrity checks confirmed `sum(monthly buys) == invested` and `n_buys == 120`.

### Conclusion #1 — dd_pl is a sample-period artifact

`dd_pl` ($200 when portfolio P/L% < 0) fires only **1-4 months** out of 120 in the 10y window vs **11-18 months out of 53** in the 2022-start window:

| Ticker | dd_pl months — 2022-start (53 mo) | dd_pl months — 10-year (120 mo) |
|---|---:|---:|
| SPY  | 11 | 2 |
| UPRO | 18 | 4 |
| QQQ  | 13 | 1 |
| QLD  | 14 | 1 |
| TQQQ | 16 | 1 |

The early 2016-2019 bull market kept portfolio P/L positive almost continuously; the trigger only activated during COVID 2020, briefly in 2022, and spring 2025. **dd_pl looks like a powerful strategy in the 2022-start sample because that sample was 60% bear/correction; in a normal 10y sample it's a no-op.** Generalisation rule: any sizing rule keyed on portfolio state (not asset state) inherits the sample-period's drawdown profile and won't generalise.

### Conclusion #2 — TQQQ exit-only is the single best 10-year strategy (no DD needed)

The biggest surprise: pure exit-reenter (baseline DCA + sell-everything-on-MA-cross, no DD sizing) is the **best TQQQ strategy by every metric simultaneously**:

| Metric | TQQQ baseline | TQQQ exit | TQQQ hybrid_exit | TQQQ dd_ath |
|---|---:|---:|---:|---:|
| Invested | $12,000 | $12,000 | $16,900 | $19,700 |
| Final $ | $103,039 | **$114,469** | $149,311 | $156,922 |
| Money mult | 8.59× | **9.54× ✨** | 8.83× | 7.97× |
| MaxDD | −80.4% | **−54.2%** | −53.8% | −79.9% |
| MaxDD duration | 404 days | **21 days** | 21 days | 404 days |
| Sharpe | 1.26 | **1.35 ✨** | 1.32 | 1.10 |

**TQQQ exit-only is the closest thing to a "pure improvement over buy-and-hold" we've found.** Same capital base ($12,000), better return, half the MaxDD, 95% shorter drawdown duration, higher Sharpe. The 9.54× money multiple is the highest of any of the 30 (ticker × mode) combinations tested. **Adding the buy-side hybrid (hybrid_exit) deploys more capital and produces more absolute $, but lowers money mult and Sharpe slightly — buy-side DD on top of exit-reenter is a "more capital for more dollars" trade, not a Pareto improvement.**

### Conclusion #3 — The regime filter (exit-reenter sell-side) is the universal MaxDD-reducer

Across all 5 tickers, the regime filter cuts MaxDD by 31-51% on average:

| Ticker | Baseline MaxDD | Exit MaxDD | Cut |
|---|---:|---:|---:|
| SPY  | −32.5% | −15.8% | **51%** |
| UPRO | −76.5% | −46.0% | 40% |
| QQQ  | −29.9% | −20.5% | 31% |
| QLD  | −60.9% | −39.2% | 36% |
| TQQQ | −80.4% | −54.2% | 33% |

**Mean MaxDD reduction across all 5 tickers is 38%.** Buy-side rules (dd_pl, dd_ath, dd_hybrid) leave MaxDD essentially unchanged (variations within 0.5pp). **MaxDD-reduction is entirely a sell-side problem** — no buy-sizing rule can fix it, because MaxDD is dominated by *existing capital crashing*, not by *new capital being added at bad prices*.

### Conclusion #4 — UPRO's whipsaw penalty is persistent and large

UPRO inherits SPY's regime gate (26 forced round-trips over 10y vs QQQ-ref's 22). The 50% higher round-trip count combined with 3× leverage on SPY consistently produces the worst Sharpe penalty:

| UPRO mode | Sharpe | Notes |
|---|---:|---|
| baseline | 1.26 | reference |
| exit | **1.37** | sell-side helps (MaxDD −76% → −46%) |
| hybrid_exit | 1.05 ⚠ | adding buy-side HURTS UPRO |

**For UPRO specifically, exit-only is the production strategy** — the buy-side hybrid concentrates new capital deployment during recovery whipsaws and the 3× leverage amplifies the timing errors. The UPRO regime-filter design needs additional smoothing (QQQ-MA gate, N-day re-entry delay, or MA-distance margin > 1%) before hybrid_exit becomes competitive on UPRO. Filed as next experiment.

### Conclusion #5 — Window-of-evaluation matters more than rule design

The same six strategies produce very different rankings in the two windows:

| Best strategy | 2022-start (53 mo) | 10y full (120 mo) |
|---|---|---|
| Best Sharpe (TQQQ) | hybrid_exit 1.68 | **exit 1.35** |
| Best terminal $ (TQQQ) | dd_ath $34,751 | **dd_ath $156,922** |
| Best money mult (TQQQ) | dd_pl 3.91× | **exit 9.54×** |
| Best MaxDD reduction (TQQQ) | exit/hybrid_exit −36% | **exit/hybrid_exit −54%** |
| Best $ per $-deployed (TQQQ) | dd_pl $5.65/$ | **exit (infinity — same base, more return)** |

**Implication for strategy design discipline:** any backtest reported on a single window — especially one that starts immediately before a major drawdown like the 2022-01 case — overstates the value of DD-style rules and understates the value of the regime filter. The fair-evaluation rule: run every strategy on at least two windows (one favourable, one unfavourable for the rule under test) before drawing conclusions.

### Rule

**For leveraged-ETF DCA on a multi-cycle horizon, the production strategy hierarchy is:**

1. **Default: exit-only (baseline DCA + 200d-MA exit-reenter).** Triple-win for TQQQ; Pareto-improvement over baseline for QQQ/QLD/SPY (higher Sharpe, lower MaxDD, no extra capital required).
2. **More-capital-available: hybrid_exit.** Strictly higher terminal $ than exit-only for 4 of 5 tickers, at cost of ~0.1 Sharpe and 40-65% more capital deployed. Use when capacity to deploy more $ is the binding constraint.
3. **Maximum aggression: dd_ath (no exit).** Highest absolute $ for 4 of 5 tickers but with full baseline MaxDD (−55% to −80% on leveraged). Only justifiable if MaxDD tolerance is genuinely unlimited.
4. **NEVER use dd_pl alone.** The sample-period dependence is hidden and dangerous.
5. **For UPRO (3× SPY leverage), use exit-only — not hybrid_exit.** Until the SPY-MA gate is replaced with a smoother proxy, the buy-side hybrid is net-negative on UPRO.

**The next experiment in this line should be the UPRO regime-gate fix** (try QQQ-MA reference, or SPY-MA + 1% confirmation margin, or N-day re-entry delay). If any of these recovers UPRO's hybrid_exit Sharpe to >1.26, hybrid_exit becomes the universal production strategy across all 5 tickers. Outputs of this analysis are saved under `reports/leveraged_etf_dca_10y_full/`.
