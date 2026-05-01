# AlphaSMART — Next-Session Pickup

_Updated: 2026-05-01 — sweep + bootstrap + portfolio decision complete; verdict: NONE_

## Where we left off

The full-universe walk-forward sweep (top-4 trend +stop strategies × 17 1d
symbols) **finished 2026-05-01** in 8,437 s (2 h 20 min) wall-clock with
trimmed grids on `keltner_breakout+stop` and `rsi_vwap+stop`. See lessons.md
#29 for the per-strategy breakdown.

**Strict Gate 1 + Gate 2 result: 1 passer**
- `cci_trend+stop` on NVDA — Sh=1.388 / CAGR=41.7% / MaxDD=21.4% / 33 trades / OFR=0.82.
- Reproduces lessons #27 baseline exactly.

**Relaxed Gate 1 (Sh ≥ 1.0, trades ≥ 15, strict Gate 2 OFR ≥ 0.70): 2 passers**
- `cci_trend+stop` NVDA — same as above, semis.
- `rsi_vwap+stop` V — Sh=1.095 / CAGR=7.2% / MaxDD=5.1% / 22 trades / OFR=1.042 / payments.

**Block bootstrap (n=200, threshold 0.65): both FRAGILE — see lessons.md #33**
- NVDA cci_trend+stop: sim p50=0.10 vs orig 1.39, ratio=0.07 → FRAGILE.
- V rsi_vwap+stop:     sim p50=0.41 vs orig 1.10, ratio=0.37 → FRAGILE.
- Headline finding (lessons #33): **strong OFR + weak bootstrap = path-dependent
  edge.** Both passers had OFR ≥ 0.82, but OFR tests temporal generalisation on
  the real series while bootstrap tests sequence-independence. Trend strategies
  on assets with strong narratives (NVDA's bear→AI-rally arc) clear the first
  but fail the second — what looks robust within the real timeline is actually
  fitted to the timeline.

**Portfolio decision: `NONE`** (`reports/portfolio_decision_20260501.json`).
Zero ROBUST passers → no defensible paper-trading composition. Both are
persisted to `optimized_params.json` for record-keeping but should not be
deployed. Relaxed list at `reports/walkforward_top4_20260430_passers_relaxed.json`
(strict file at `..._passers.json` is unchanged; the strict version remains
the institutional record per lessons #31).

## Order of operations for next session

### 1. Widen the strategy search (highest priority)

The bootstrap-FRAGILE result (lessons #33) reframes this from "we need 2
more passers to reach 3" to "we need passers whose mechanic isn't path-
dependent on a single asset's macro arc." That favours mean-reversion
mechanics (rsi_vwap-style, bb_reversion-style) and cross-asset replicators
over single-asset trend rides.

Run another walk-forward sweep across:
- `momentum_long+stop` — momentum / ROC-based, similar in spirit to cci_trend
  but on different parameter axes (different failure modes possible).
- `donchian_bo+stop` — channel breakout, less narrative-dependent than
  cci_trend in principle.
- `alpha_composite+stop` — proprietary multi-signal composite; weight
  constraints (lessons #11) keep it well-defined.
- Plus broader mean-reversion: `bb_reversion+stop` (note: not currently in
  `_STOP_WRAPPED`; would need to register it in both `optimizer.py` and
  `api.py` first). Mean reversion historically clears bootstrap better than
  trend (see V's ratio=0.37 vs NVDA's 0.07).

On the same 17-symbol universe, with trimmed grids where applicable
(donchian's 7-value period grid is fine; alpha_composite's 7-D grid needs
care). Estimated runtime: ~2 h with current serialism. Outputs same shape
as the previous sweep (`walkforward_top4_<date>.csv`, etc.).

After the widened sweep, **bootstrap is a hard gate, not optional.** Any
passer must clear both OFR ≥ 0.70 AND bootstrap ratio ≥ 0.65 to be
considered for paper trading.

### 2. Watch for cross-asset replication

The pattern that *would* be defensible is the same strategy passing both
gates on multiple uncorrelated symbols (e.g. rsi_vwap+stop on V AND MA AND
NVO with all three ROBUST). Per lessons #33, that cross-asset replication
is the actual robustness signal — not single-symbol OFR + bootstrap. Watch
for it explicitly when reviewing the widened-sweep CSV.

### 3. If still nothing: extend history (more expensive)

Re-fetch 7-yr or 10-yr daily for the universe to give walk-forward more
folds (currently 4 folds on 5-yr daily). Tradeoffs:
- yfinance reliability degrades for older bars; may need Polygon upgrade.
- Crypto pairs may not have 10 yr history at all.
- More folds = stronger OFR signal, *but doesn't fix path-dependence* —
  longer history of NVDA still has just one bear→AI-rally arc.

### 4. Re-bucket the universe (long-term)

Drop highly-correlated tickers (SPY, QQQ act like benchmark filters; MA
correlates strongly with V → either V or MA, not both) and add sector-
tilted symbols (utilities, energy, healthcare). Goal: maximise the
diversity of macro shapes the strategies are tested against.

### 5. Export sanitised opt-params (cosmetic, do anytime)

```bash
./venv/bin/python export_opt_params.py
```

Writes `reports/optimized_params_<UTC date>.json` with `gate2_pass=true`
entries only, timestamps stripped (machine-specific). Good for sharing
across machines because the live file is gitignored.

### 6. Only after step 1 surfaces ≥ 3 uncorrelated passers that clear BOTH OFR and bootstrap — execution layer

Same as the previous session's plan; `alphasmart/src/execution/` is
still only `__init__.py`. Build:
- `src/execution/alpaca_broker.py` — paper endpoint adapter
- Live data poller (yfinance, or upgrade to Polygon)
- Signal/order loop mirroring the backtester's bar-close → next-open semantics
- Position reconciliation (local Portfolio vs broker)
- Daily P&L + reconciliation report

Run ≥ 1 week in **shadow mode** before flipping to actual paper orders.

## One-liner pipeline

After step 1 has been kicked off with the relaxed JSON (or after a future
sweep that produces a passers file matching the strict glob pattern):

```bash
./run_phase4_pipeline.sh                      # auto-discover strict passers
./run_phase4_pipeline.sh --workers 4          # cap bootstrap pool size
./run_phase4_pipeline.sh --corr-threshold 0.6 # loosen portfolio selection
```

Note: the pipeline script's auto-discovery glob is
`walkforward_top4_*_passers.json` (won't match `_passers_relaxed.json`).
For the relaxed run, invoke `run_bootstrap_passers.py` with an explicit
path, then call `decide_portfolio.py` and `export_opt_params.py` directly.

## Things to know for context

- **Walk-forward windows:** `run_walkforward_top4.py` patches
  `_IS_YEARS=2, _OOS_YEARS=1, _STEP_YEARS=0.5` BEFORE importing the optimizer.
  Default in `optimizer.py` is 3/1/1 which yields only 1 fold on 5-yr daily.
- **`+stop` registration:** Lives in `optimizer.py`'s `_STOP_WRAPPED` tuple
  and `api.py`'s `_STOP_BASES` tuple. Add a key to both when registering a
  new wrapped strategy. PARAM_GRIDS aliasing happens automatically.
- **Risk halt is still active:** The 20% portfolio-level circuit breaker
  fires on `cci_trend+stop` NVDA at bar 950 (2025-01-07) when the trailing
  stop is redundant (CCI exit_level=50 was tighter than 2×ATR). On configs
  with looser inner exits, the stop fires first and the halt won't trigger
  — that's lesson #26.
- **`optimized_params.json` is gitignored.** Anything saved by the runner
  is local-only. Use `export_opt_params.py` for a sanitised export.
- **Trimmed grids saved ~30 min:** `keltner_breakout+stop` and
  `rsi_vwap+stop` were trimmed to 24 combos each (from 108 / 96
  full-grid). Strict cci/hull stayed at full grid.
- **Trade-count floor (lessons #22) is the binding constraint:** TSLA
  cci_trend+stop (Sh=1.526) and Hull NVDA (Sh=1.576) both look great on
  Sharpe but fail on trade count. Lesson #31 covers when to relax it.
- **OFR (lessons #30) is the real Gate 2 number** — sort by it, not by
  `gate2_pass`. Relax it last, not first.
