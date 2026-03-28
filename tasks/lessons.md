# AlphaSMART — Lessons Learned

_Updated: 2026-03-28 (session 3: optimization queue, opt-params persistence, JSON Infinity fix, 10 new symbols)_

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
