# AlphaSMART — Next-Session Pickup

_Updated: 2026-04-26 — end of session 6_

## Where we left off

Session 6 wired in the **ATR trailing-stop wrapper** (`src/strategy/trailing_stop.py`)
and confirmed it on NVDA: `cci_trend+stop` with `entry_level=75, exit_level=50,
vol_threshold=0.8` produced **Sharpe 1.39 / MaxDD 21% / 33 trades / OOS-IS ratio
0.82 across 4 walk-forward folds** — the project's first combined Gate1+Gate2
pass. Lessons 26–28 in `tasks/lessons.md` capture the details.

The runner script `run_walkforward_top4.py` is written and tested on a single
symbol but **the full-universe sweep was not launched** because the projected
runtime is 6–8 hours (lesson #28) and we want to trim grids first.

## Order of operations for next session

### 1. Trim grids for the heavy strategies, then launch the full sweep

In `run_walkforward_top4.py`, pass `custom_param_grid` overrides for
`keltner_breakout+stop` and `rsi_vwap+stop` to bring per-strategy combo counts
into roughly the same ballpark as `cci_trend+stop` (~33 combos). Suggested
trims (4 dims × 2–3 values ≈ 18–27 combos):

```python
TRIMMED_GRIDS = {
    "keltner_breakout+stop": {
        "period":       [15, 30],
        "atr_period":   [10, 14],
        "atr_mult":     [1.5, 2.0, 2.5],
        "trend_period": [100, 200],
    },
    "rsi_vwap+stop": {
        "vwap_period": [12, 24],
        "rsi_period":  [10, 14],
        "oversold":    [25.0, 30.0, 35.0],
        "overbought":  [60.0, 70.0],
    },
}
```

Then plumb these through `run_optimization(..., custom_param_grid=...)`. Expected
total wall-clock with trims: ~3 hours. Run it in the background (`nohup` or a
`tmux` session) — don't tie up an interactive shell.

Outputs:
- `reports/walkforward_top4_<UTC date>.csv` — every (strategy, symbol) row
- `optimized_params.json` — Gate1+Gate2 passers persisted (auto-saved)
- `reports/walkforward_top4_<UTC date>_passers.json` — passer summary

### 2. Bootstrap the passers

Step 3 of the original plan. Once the walk-forward CSV is in, write
`run_bootstrap_passers.py` that:
- reads `walkforward_top4_<date>_passers.json`
- runs `block_bootstrap` simulation (n=200) on each passer using
  `src.backtest.simulation.run_simulation`
- writes ROBUST/FRAGILE verdict per passer
  (ROBUST = median sim Sharpe ≥ 65% of original)
- emits `reports/bootstrap_passers_<UTC date>.json`

The simulation harness is already in `src/backtest/simulation.py` — just need
the loop. See `_run_simulate_sync` in `api.py` for the call pattern.

### 3. Decide on portfolio composition

If we get ≥ 3 uncorrelated ROBUST passers across different sectors, build a
paper-trading portfolio. If we get ≤ 2, we have a concentration problem and
should:
- (a) widen the strategy search (try momentum_long+stop, donchian_bo+stop,
  alpha_composite+stop in a follow-up sweep), or
- (b) fetch more history (try 7-yr or 10-yr daily data, if the data sources
  permit) to give walk-forward more folds.

### 4. Only after step 3 — start on the execution layer

`alphasmart/src/execution/` contains only `__init__.py`. To paper-trade we
still need:
- `src/execution/alpaca_broker.py` — paper endpoint adapter (Alpaca SDK)
- A live data poller (poll yfinance or upgrade to Polygon for stocks)
- A signal/order loop that mirrors the backtester's bar-close → order-at-next-open
- Position reconciliation (compare local Portfolio state vs broker positions)
- A daily P&L + reconciliation report

Run for ≥ 1 week in **shadow mode** (log signals, don't submit) before
flipping to actual paper orders. This catches divergence between live and
backtest signal generation.

## Things to know for context

- **Walk-forward window override:** `run_walkforward_top4.py` patches
  `_IS_YEARS=2, _OOS_YEARS=1, _STEP_YEARS=0.5` BEFORE importing the optimizer.
  Default in `optimizer.py` is 3/1/1 which yields only 1 fold on 5-yr data.
- **`+stop` registration:** Lives in `optimizer.py`'s `_STOP_WRAPPED` tuple
  and `api.py`'s `_STOP_BASES` tuple. To add another strategy, add the key to
  both. PARAM_GRIDS aliasing happens automatically.
- **Risk halt is still active:** The 20% portfolio-level circuit breaker still
  fires on cci_trend+stop NVDA at bar 950 (2025-01-07) because the trailing
  stop was redundant for that config (CCI exit_level=50 was tighter than
  2×ATR). On configs with looser inner exits, the stop fires first and the
  halt won't trigger — that's the whole point of lesson #26.
- **`optimized_params.json` is gitignored.** Anything saved by the runner is
  local-only. To share across machines, commit a sanitised export.
