# AlphaSMART — Lessons Learned

_Updated: 2026-04-07 (Steps 3–5: regime filter, V2 composites, intraday mini-batch)_

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

## 14. yfinance Aggressively Rate-Limits Sequential Single-Ticker Requests

**Symptom:** `StockDataFetcher failed for AAPL: Too Many Requests. Rate limited. Try after a while.` on the very first ticker when running a loop of `python main.py fetch <TICKER>` calls sequentially. Retry after 10s still fails for most tickers.

**Root Cause:** yfinance 0.2.54 uses a session-level cookie + crumb that gets flagged as a bot when many separate Python processes each initialise a new `yf.Ticker()` session in rapid succession. Each `main.py fetch` invocation is a fresh process; Yahoo Finance sees burst traffic from the same IP.

**Fix:** Use `yf.download(tickers=" ".join(symbols), period="5y", interval="1d", group_by="ticker")` in a single Python process. This fetches all tickers in one HTTP session with one crumb, circumventing per-ticker throttling entirely. The result is a MultiIndex DataFrame; slice each symbol with `raw[sym]` and store individually.

**Rule:** Always batch-download equities with `yf.download()` in a single call rather than looping `yf.Ticker(sym).history()`. For scheduled refreshes, fetch all symbols at once and upsert.

---

## 15. Binance CCXT `fetch_ohlcv` Is Hard-Capped at 1,000 Bars Per Request

**Symptom:** Requested 2,190 4h bars (2yr) for BTC/USDT but only received 1,000 bars (~166 days back), giving a date range of 2025-10-22 → 2026-04-06 — far short of the 2yr target.

**Root Cause:** Binance REST API hard-limits OHLCV responses to 1,000 candles per request regardless of the `limit` parameter. CCXT respects this limit.

**Fix:** Paginate manually: record `last_ts = bars[-1][0]`, set `since = last_ts + bar_ms`, loop until `len(bars) < 1000`. Accumulate all pages, deduplicate by index, then upsert the full history. For BTC/USDT 4h × 2yr this requires 5 requests yielding 4,380 bars.

**Rule:** For Binance (and many other exchanges), assume a maximum of 1,000 bars per call. Always paginate with `since=` rather than relying on `limit` for multi-year histories.

---

## 16. High Sharpe + High Trade Count Is Mutually Exclusive on 2021–2026 Daily Data

**Symptom:** Zero Gate 1 passes across 231 default runs AND 66 optimized runs. Top Sharpe results (> 1.2) all have trade counts of 1–13; strategies with ≥ 100 trades all have Sharpe < 1.2.

**Root Cause:** The 2021–2026 period contains the 2022 bear market (S&P −19%, NASDAQ −33%) embedded in an otherwise bull market. The 20% circuit-breaker drawdown halts most trend-following strategies before they accumulate enough trades. High-Sharpe parameter combos select for very long hold periods (few entries) to survive 2022 intact. Mean-reversion strategies generate many trades but suffer degraded Sharpe in trending volatile regimes.

**Impact:** The ≥ 100 trade Gate 1 criterion is the binding constraint, not Sharpe. The optimiser maximises Sharpe but is agnostic to trade count — a separate penalty or constraint is needed.

**Lesson:** For a multi-regime backtesting period, consider: (a) regime-conditional Gate 1 (separate bull/bear thresholds), (b) a minimum-trade-count constraint in the optimiser objective, or (c) relaxing the trade count to ≥ 30 for strategies with mean-reversion logic (fewer signals are structurally expected).

---

## 17. `alpha_composite` Grid Search Is Disproportionately Slow — ~60s per Symbol

**Symptom:** The optimizer took ~10 minutes just for `alpha_composite` on SPY during walk-forward, while all other 10 strategies completed in < 2 minutes combined.

**Root Cause:** `alpha_composite` has 7 parameter dimensions. After filtering invalid combos (weights must sum to ~1.0, fast_ema < slow_ema), ~100+ valid combinations remain. With IS=2yr + 6 walk-forward folds, each optimization run performs ~700 backtests (100 combos × 7 pass), vs. ~50 for simple strategies like `donchian_bo` (7 combos × 7 = 49).

**Impact:** A full optimization of all 11 strategies × 19 symbols would take several hours. Batch optimization at scale requires either (a) reducing the alpha_composite grid, (b) parallelising with `multiprocessing`, or (c) running a two-phase search (coarse then fine).

**Rule:** When adding a composite strategy with many parameters, cap the per-dimension grid to ≤ 3 values × ≤ 4 dimensions = ≤ 81 combos. Profile the optimizer on a small symbol before scheduling a full-universe run. Include alpha_composite in time estimates separately — it can cost as much as all other strategies combined.

---

## 18. `requirements.txt` Listed Unused Packages that Block Installation on Newer Python

**Symptom:** `pip install -r requirements.txt` failed with `ERROR: No matching distribution found for pandas-ta==0.3.14b` and `ERROR: No matching distribution found for alpaca-trade-api==3.3.2` on Python 3.11 / macOS ARM64.

**Root Cause:** `pandas-ta==0.3.14b` was removed from PyPI (the `b` suffix is a non-standard version tag). `alpaca-trade-api==3.3.2` does not exist on PyPI (the package was superseded by `alpaca-py`). Neither package is imported anywhere in `src/`. Additionally, `vectorbt==0.26.2` conflicts with `numpy==2.2.4` (requires `<2.0.0`), and vectorbt is also unused in `src/`.

**Fix:** Installed dependencies excluding the three unused packages. All functionality worked without them.

**Rule:** Audit `requirements.txt` against actual imports in `src/` at least once per session. Use `grep -r "import vectorbt\|import pandas_ta\|import alpaca" src/` before assuming a listed package is required. Prune unused or broken dependencies early.

---

## 19. Intraday Risk Parameters Must Be Timeframe-Aware

**Symptom:** The 2% daily loss circuit breaker tripped on bar 36 (9 days) for BTC/USDT 4h — a single 4h candle moved 3.6%, immediately halting the strategy before meaningful testing could occur.

**Root Cause:** `RiskConfig.max_daily_loss_pct = 0.02` was designed for daily bars where a 2% single-bar loss is severe. For 4h crypto bars, a 2-6% single-bar move is routine. The check fires per-bar, not per-calendar-day, so it trips on normal 4h volatility.

**Impact:** Most 4h crypto strategies are halted within the first few weeks, making results meaningless. The `halted=True` flag and extremely low trade counts (2-5) are symptoms.

**Fix:** Risk limits need timeframe-aware defaults — or the `RiskConfig` should expose a `max_bar_loss_pct` vs `max_daily_loss_pct` distinction. For 4h backtest research, consider setting `max_daily_loss_pct=0.06` or disabling it and relying on the drawdown circuit breaker alone.

**Rule:** When running backtests on intraday timeframes, review `RiskConfig` defaults. The drawdown circuit breaker (20%) is timeframe-agnostic and appropriate. The daily loss limit (2%) is calibrated for daily bars — multiply by `bars_per_day` for intraday equivalence.

---

## 20. Regime Filter Shifts Trade Count vs Sharpe Trade-Off — Does Not Resolve It

**Symptom:** After adding the SPY SMA200 regime filter, still 0/171 Gate 1 passes across all trend strategies. Regime-filtered `alpha_momentum_v2` on NVDA improved from 9 trades (Sharpe=2.03) to 54 trades (Sharpe=1.05), but still below the ≥100 threshold.

**Root Cause:** The regime filter prevents entries during SPY bear phases (primarily the 2022 drawdown). This removes some loss-generating trades, improving Sharpe, but also eliminates some recovery trades, reducing trade count. The fundamental constraint — the 2021-2026 period punishes both high trade count and low Sharpe simultaneously — is unchanged.

**What the filter actually does:** Converts bear-period `long` → `flat`, which (a) prevents drawdowns from the 2022 bear market, (b) increases effective Sharpe by removing bad trades, (c) but also reduces trade count by ~25-40% for trend strategies.

**Lesson:** The regime filter is a valid risk management tool (prevents entering trends during confirmed bear markets) but does not fix the Gate 1 trade count constraint. For that, consider: (a) lowering the Gate 1 trade count threshold to ≥30 for composite strategies that structurally have fewer signals, (b) running on multiple symbols simultaneously with portfolio-level counting, or (c) testing on a purely bull market period where more entries trigger.

---

## 21. Optimizer V2 Grid Must Fix Weights When Fewer Dimensions Are Optimized

**Symptom:** `_generate_combos('alpha_trend_v2')` returned 0 combos when the V2 grid omitted `trend_weight` and `rsi_weight`. The weight-sum constraint computed `vol_weight = 1.0 - 0 - 0 = 1.0`, which exceeded the `> 0.6` cap, filtering every combination.

**Root Cause:** The alpha_composite family's constraint in `_generate_combos` reads `trend_weight` and `rsi_weight` from the combo params and computes the remainder. If those keys aren't in the grid (because V2 fixes them at data-driven defaults), `params.get("trend_weight", 0)` returns 0, producing an invalid `vol_weight`.

**Fix:** Guard the weight constraint with `if "trend_weight" in params and "rsi_weight" in params:`. When weights are fixed at strategy defaults (not in the grid), skip the constraint check — the constructor validates the weights independently at instantiation.

**Rule:** When reducing a parameter grid for a strategy subclass, check whether the parent class's optimizer constraints reference those omitted parameters. Guard constraints with `in params` checks rather than relying on `.get(..., 0)` defaults.
