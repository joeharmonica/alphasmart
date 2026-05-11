# Strategies — backtest types & recipes

## 1. Two kinds of backtest in this repo

### Per-ticker backtest
`main.py backtest` / `main.py backtest-all` — each strategy runs on **one symbol at a time**.

- A strategy (e.g. `EMACrossoverStrategy`, `RSIMeanReversionStrategy`) produces buy/sell signals from a single OHLCV stream.
- The engine simulates fills, position sizing, risk halts (`src/strategy/risk_manager.py`), and reports per-symbol Sharpe / CAGR / MaxDD.
- Output: one row per (strategy × symbol × timeframe). Symbols never interact.
- Use when: evaluating whether a *signal* (cross, threshold, breakout) works on a specific instrument.
- Files: `src/backtest/{engine,runner}.py`, `src/strategy/*.py`.

### Portfolio cross-sectional momentum
`run_xsec_pipeline*.py`, `run_regime_filter_v2.py`, paper-trade runner — operates on **a whole universe at once**.

- At each rebalance bar, **rank** the universe by trailing N-day return and **hold the top K** equal-weighted.
- An optional regime filter (e.g. SPY > 200d MA → 1.0, else → 0.0) scales the entire portfolio's return — either fully invested or fully cash.
- Output: one daily portfolio return series for the whole basket.
- Use when: you want a relative-strength portfolio that rotates among assets, not a per-asset entry/exit rule.
- Files: `run_xsec_pipeline.py` (`run_xsec_momentum`), `src/execution/strategy_runner.py` (`xsec_momentum_target_weights`).

### Key differences
| | Per-ticker | Portfolio xsec |
|---|---|---|
| Output | N×M result rows | 1 portfolio return series |
| Symbols interact | No | Yes — ranking is relative |
| Adding a ticker | New row, no impact on others | Changes ranks → changes everyone's allocation |
| Regime filter | Each strategy decides | Applied to the whole portfolio post-signal |
| What "works on TQQQ" means | Strategy signal profitable on TQQQ alone | TQQQ ranks into top-K often enough to be picked, and including it improves portfolio Sharpe |

The paper-trade live strategy is **portfolio xsec**, not per-ticker — `build_equity_spec()` in `src/execution/runner_main.py:75`.

---

## 2. The live paper-trade strategy: `equity_xsec_momentum_B`

Source of truth: `src/execution/runner_main.py:75-83` + `src/execution/strategy_runner.py:45-87`.

```
signal_fn:        xsec_momentum_target_weights
signal_params:    lookback_days=126, skip_days=0, top_k=5
filter_fn:        binary_200ma_filter
filter_input:     SPY
universe v2 (17): AAPL AMD AMZN ASML AVGO GOOG LLY MA META
                  MSFT NOW NVDA NVO QQQ SPY TSLA V
```

Rebalance cadence is **not encoded in the spec** — it's driven by the external cron that calls `runner_main rebalance`. Backtests use `rebal_days=21` (monthly) as the convention (see `run_regime_filter_v2.py:129`).

### Universe history

| Version | Date | N | Change | Rationale |
|---|---|---|---|---|
| v1 | initial | 15 | AAPL AMZN ASML AVGO GOOG MA META MSFT NOW NVDA NVO QQQ SPY TSLA V | Hand-curated US large/mega-cap tech-led set |
| **v2** | **2026-05-11** | **17** | **+AMD, +LLY** | Added after evaluating 10 candidates via `run_xsec_add_ticker.py`; this pair improved full-window MaxDD by −2.3pp and CAGR by +0.7pp, costing only −0.07 Sharpe. AMD picked ~47% of days, LLY ~39%. See `reports/xsec_addticker_SOXL_TECL_MU_AMD_NFLX_ORCL_JPM_LLY_COST_HD_20260511_100222.json` for the full comparison. |

### v2 full-window baseline metrics (10y, SPY-filtered)

| Metric | v1 (15-sym) | v2 (17-sym) | Δ |
|---|---|---|---|
| Sharpe | 1.908 | 1.834 | −0.074 |
| CAGR | 51.7% | 52.4% | +0.7pp |
| MaxDD | 21.5% | **19.2%** | **−2.3pp** |

Rejected candidates (from the same evaluation):
- **SOXL, TECL**: high pick-rate (51-61%) but ΔMaxDD +4-9pp. Need a per-symbol weight cap before they're acceptable.
- **MU**: +3pp CAGR but +1.8pp DD. Marginal — revisit if a vol-cap is added.
- **JPM**: ~neutral Sharpe but no CAGR contribution. Dropped from the +AMD+LLY+JPM trio in favor of +AMD+LLY.
- **NFLX, ORCL, COST, HD**: small Sharpe drag, DD-neutral; no compelling reason to add.

---

## 3. Recipe: test a new ticker against `equity_xsec_momentum_B`

### Step 1 — fetch data
The new ticker needs ≥10y of daily data to be comparable with the baseline universe:

```bash
python main.py fetch <SYMBOL> --period 10y --timeframe 1d
# optional, for the wider data set:
python main.py fetch <SYMBOL> --period 5y  --timeframe 1wk
python main.py fetch <SYMBOL> --period 2y  --timeframe 1h
```

### Step 2 — run the candidate backtest
`run_xsec_add_ticker.py` mirrors the paper-trade spec exactly (same lookback / skip / top_k / SPY filter) and compares baseline vs baseline+candidate(s):

```bash
# Test one ticker (baseline vs +SYMBOL)
python run_xsec_add_ticker.py SOXL

# Test multiple individually plus combined
python run_xsec_add_ticker.py SOXL TECL NVDL

# Only test the all-combined variant
python run_xsec_add_ticker.py --combo SOXL TECL
```

Reports go to `reports/xsec_addticker_<tickers>_<timestamp>.json`. Console output shows:
- Sharpe / CAGR / MaxDD for each universe variant, unfiltered and SPY-200dMA-filtered
- Selection frequency for each candidate (% of days held in top-K)
- Top-5 most-held names — to see who got bumped

### Step 3 — decision rule
The candidate is a **net win for the live strategy** if the SPY-filtered variant produces:
- ΔSharpe ≥ 0 vs baseline, **and**
- ΔMaxDD ≤ 0 (or within ~+2pp if ΔCAGR is meaningfully positive)

If ΔSharpe < 0 but ΔCAGR > 0 and ΔMaxDD ≥ 0, the candidate adds beta without alpha — usually not worth adding without a position-size cap.

### Step 4 — if accepting, update the universe
Edit `EQUITY_UNIVERSE` in `src/execution/runner_main.py:69`. This is the only place to change for the live runner; the backtest baseline in `run_xsec_add_ticker.py` should be updated to match in the same commit.

---

## 4. Caveats

- **Per-symbol caps**: the live spec gives every name a `1/top_k = 20%` slot. Leveraged ETFs (e.g. TQQQ, UPRO) inherit the same slot and concentrate beta. There is no half-weight logic today — if you want it, add it to `xsec_momentum_target_weights` or apply post-hoc weight scaling.
- **Filter is binary**: in-market or fully cash. Variants C–F in `run_regime_filter_v2.py` (soft ramp, breadth, combined) were evaluated but the live spec uses B (binary). Don't conflate the two.
- **Survivorship**: the baseline universe is hand-curated mega-caps. Adding a candidate that has only existed since 2020 (e.g. PLTR) shortens the aligned window via `dropna()` — re-check `n_bars` in the report.
- **Rebal cadence drift**: backtests use 21 trading days; the live cron may run more frequently. The signal is the same — only fill timing differs.
