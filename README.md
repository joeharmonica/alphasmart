# AlphaSMART

> Research. Validate. Deploy. Only alpha that survives reality gets capital.

A full-stack algorithmic trading platform: strategy research → backtesting → optimization → bootstrapping simulation → forward testing → live deployment, with an LLM analytical copilot and institutional-grade risk controls.

---

## Current Status

| Phase | Scope | Status |
|-------|-------|--------|
| **1 — Foundation** | Data pipeline, indicators, DB, CLI | ✅ Complete |
| **2 — Core Engine** | Strategy abstraction, backtester, risk engine | ✅ Complete |
| **3 — Optimization + LLM** | Walk-forward, grid search, Claude copilot, simulation | ✅ Complete |
| **4 — Dashboard** | React UI, Next.js, optimization queue, opt-params persistence | ✅ Complete |
| **Step 1 Live Run** | Full data fetch, batch backtest, optimization, reports | ✅ 2026-04-07 |
| **Steps 3–5** | Regime filter, V2 composites, intraday mini-batch | ✅ 2026-04-07 |
| 5 — Forward Testing | Paper trading, 30-day run | 🟢 **Running since 2026-05-05** — equity leg only, live broker equity ~$100k, top-5 mega-cap basket |
| 6 — Live Deployment | Real capital, broker integration | 🔜 Planned |
| **Operational hardening** | A1/A2/A3 fixes (reconciler, full-close, health-check) | ✅ Merged 2026-05-17 ([lessons.md #42-#43](alphasmart/tasks/lessons.md), [#49-#50](alphasmart/tasks/lessons.md)) |
| **Research: leveraged-ETF DCA** | 10y DCA backtest, 6 strategy variants × 5 tickers | ✅ Merged 2026-05-17 ([lessons.md #44-#50](alphasmart/tasks/lessons.md), reports under `alphasmart/reports/leveraged_etf_dca*/`) |

> The current paper-trade run uses the equity leg only (`equity_xsec_momentum_B`): **17-symbol** mega-cap cross-sectional 6-month momentum, top-5 equal-weight, monthly rebalance, gated by SPY > 200d-MA. Universe v2 (2026-05-11) added AMD + LLY for a −2.3pp MaxDD / +0.7pp CAGR trade-off; see `alphasmart/tasks/strategies.md` for the universe-history audit trail and `alphasmart/tasks/paper_trade_design.md` for the full design and pass/fail rubric.

### Latest paper-trade snapshot (live broker, 2026-05-18 post-rebalance)

| Symbol | Qty | Market value | Weight | Unrealized P/L |
|---|---:|---:|---:|---:|
| AVGO | 48.02 | $20,177.67 | 20.05% | −$102 (−0.5%) |
| AMD | 47.07 | $20,163.31 | 20.04% | −$1,657 (−7.6%) |
| NVDA | 89.10 | $20,128.18 | 20.00% | +$100 (+0.5%) |
| GOOG | 50.11 | $20,112.75 | 19.99% | +$905 (+4.7%) |
| ASML | 13.28 | $19,827.99 | 19.70% | +$781 (+4.1%) |
| **Total equity** | | **$100,635.98** | 100% | |

Last successful rebalance: **2026-05-18** — caught up via manual `launchctl kickstart` of the new `com.alphasmart.rebalance` LaunchAgent. Completed the universe-v2 target by selling QQQ and buying NVDA (4 orders, all filled at market open). Scheduler migrated from cron → launchd the same day (lessons.md #51) after three observed silent-failures on cron over a week. The `--stale-after-hours 50` flag now absorbs the HK-21:00 = ET-09:00 pre-market timing gap.

---

## Paper-Trade — Clone & Resume on Another Machine

The paper-trade orchestrator is `alphasmart/src/execution/runner_main.py`, scheduled by cron. State lives in `reports/paper_trade/` (committed) and the local OHLCV DB `alphasmart/alphasmart_dev.db` (gitignored — rebuild on each machine via `runner_main fetch`). Secrets live in `alphasmart/.env` (gitignored — copy from old machine or recreate from `.env.example`). Source of truth for actual positions is the Alpaca paper account; the local state file is a cache that the reconciler cross-checks every rebalance.

### One-time migration steps

**On the OLD machine — stop the cron and capture latest state:**

```bash
crontab -l > ~/crontab.bak.txt          # backup current schedule
crontab -r                              # disable cron (prevents double-runs during handoff)

cd ~/alphasmart
python -m src.execution.runner_main status  # verify state file is current
git add reports/paper_trade/ alphasmart/tasks/
git commit -m "paper-trade: snapshot state for machine migration"
git push
```

**On the NEW machine — clone, install, restore secrets, bootstrap data, re-arm cron:**

```bash
# 1. Clone (use lowercase path to avoid case-sensitivity surprises on Linux)
git clone https://github.com/joeharmonica/alphasmart.git ~/alphasmart
cd ~/alphasmart/alphasmart

# 2. Python env + deps (Python 3.11+ required)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Restore secrets — copy ~/.env from old machine OR recreate:
cp .env.example .env
#   Edit .env and set:
#     ALPACA_API_KEY=<paper-key from https://app.alpaca.markets/paper/dashboard/overview>
#     ALPACA_SECRET=<paper-secret>            # legacy name; ALPACA_API_SECRET also accepted
#     ANTHROPIC_API_KEY=<optional, only needed for LLM copilot>
chmod 600 .env

# 4. Smoke-test connectivity + rebuild local OHLCV DB for the v2 universe (17 symbols).
#    --lookback 10y populates enough history for re-running backtests; for operation alone,
#    1y is sufficient (the strategy only needs the trailing 126 trading days).
python -m src.execution.runner_main fetch --lookback 10y --force --verbose
#   This populates alphasmart_dev.db from yfinance and confirms broker reachability.

# 5. Verify state-file matches the broker (the reconciler runs at every rebalance,
#    but a manual shadow run lets you eyeball drift before re-enabling cron):
python -m src.execution.runner_main rebalance --mode shadow --kind manual --verbose

# 6. Inspect the latest log line — drift_pct on each symbol must be < 1%
tail -1 reports/paper_trade/$(date -u +%Y%m%d)/equity_xsec_momentum_B.jsonl | python -m json.tool

# 7. Schedule via launchd (macOS — canonical) OR cron (Linux — fallback)
# See "Scheduling" section below.
```

### Scheduling

**macOS: launchd (recommended).** Plists live at `~/Library/LaunchAgents/`. After clone, copy or recreate the two LaunchAgents using the templates committed under `alphasmart/scripts/launchd/`:

```bash
# 1. Edit the plists to point at YOUR clone path (defaults are /Users/joepong/...)
cp alphasmart/scripts/launchd/com.alphasmart.rebalance.plist  ~/Library/LaunchAgents/
cp alphasmart/scripts/launchd/com.alphasmart.healthcheck.plist ~/Library/LaunchAgents/
#    (edit both files — search/replace /Users/joepong/alphasmart with $HOME/alphasmart)

# 2. Load both (UID is your numeric user id from `id -u`)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphasmart.rebalance.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphasmart.healthcheck.plist

# 3. Verify both are loaded (status `-` = waiting for scheduled time; PID appears during runs)
launchctl list | grep alphasmart
#   -    0    com.alphasmart.rebalance
#   -    0    com.alphasmart.healthcheck

# 4. (optional) Manually fire each to validate end-to-end before the first scheduled run
launchctl kickstart -k gui/$(id -u)/com.alphasmart.healthcheck    # writes /tmp/alphasmart_health.json
launchctl kickstart -k gui/$(id -u)/com.alphasmart.rebalance      # writes logs/launchd_rebalance.log

# 5. Tail the logs
tail -f alphasmart/logs/launchd_rebalance.log
tail -f alphasmart/logs/launchd_healthcheck.log
tail -f alphasmart/logs/health-alerts.log          # populated only on failed health-checks
```

**Schedules** (defined in the plist `StartCalendarInterval` arrays):
- `com.alphasmart.rebalance` → weekdays 21:00 local, runs `runner_main rebalance --mode paper --fetch-before-rebalance --stale-after-hours 50`
- `com.alphasmart.healthcheck` → weekdays 09:00 AND 22:00 local, runs `scripts/healthcheck_wrapper.sh` (which calls `runner_main health-check --check-broker` and fires a macOS notification on nonzero exit)

**Why launchd over cron on macOS:** macOS `cron` is a legacy compat shim and goes silent after sleep/wake events without picking up its crontab on respawn (lessons.md #51). launchd survives sleep/wake, integrates with the unified log, and runs catch-up jobs if the Mac was off at the scheduled time (configurable via `StartCalendarIntervalRunAtLoadIfMissed`). To uninstall the LaunchAgents:

```bash
launchctl bootout gui/$(id -u)/com.alphasmart.rebalance
launchctl bootout gui/$(id -u)/com.alphasmart.healthcheck
rm ~/Library/LaunchAgents/com.alphasmart.*.plist
```

**Linux fallback (cron):**

```cron
# Same schedule via cron — adjust paths to your clone.
0 21 * * 1-5 cd $HOME/alphasmart/alphasmart && $HOME/alphasmart/alphasmart/venv/bin/python -m src.execution.runner_main rebalance --mode paper --fetch-before-rebalance --stale-after-hours 50 >> $HOME/alphasmart/alphasmart/logs/cron.log 2>&1
0 9,22 * * 1-5 $HOME/alphasmart/alphasmart/scripts/healthcheck_wrapper.sh
```

> ✅ **Pre-market rebalance is safe** (closed by lessons #43 / A1 / A2, merged to main 2026-05-17). The reconciler credits pending SELLs as `pending_close` (mirror of the existing `pending_fill` branch), and full closes use the broker's exact qty + bypass the rebalance threshold so fractional residuals get cleaned up in one pass. Older clones pre-this-commit can still write a false-positive halt — pull main and re-run to remove the caveat.
>
> ✅ **Silent halts are alarmed** (A3, merged same commit). The `health-check` subcommand returns distinct exit codes per failure class — wired via `scripts/healthcheck_wrapper.sh` (the launchd entrypoint) which writes to `logs/health-alerts.log` and fires a macOS notification on nonzero exit.
>
> ✅ **macOS scheduler is launchd, not cron** (since 2026-05-18). After three observed cron silent-failures over a week (daemon respawning post sleep/wake without re-reading the crontab), migrated to two LaunchAgents under `~/Library/LaunchAgents/`. launchd integrates with the unified log, survives sleep/wake, and runs catch-up jobs.

**Verify the scheduled run fired:**

```bash
# launchd (macOS): launchctl shows last exit + PID
launchctl list | grep alphasmart
tail -f ~/alphasmart/alphasmart/logs/launchd_rebalance.log
tail -f ~/alphasmart/alphasmart/logs/launchd_healthcheck.log

# cron (Linux): tail the cron log
tail -f ~/alphasmart/alphasmart/logs/cron.log

# Either way: confirm state advanced
python -m src.execution.runner_main status   # last_updated_utc should be recent
```

### What transfers via git, what doesn't

| Path | Tracked? | Notes |
|---|---|---|
| `alphasmart/src/**` | ✅ | All source code |
| `alphasmart/tasks/paper_trade_design.md`, `lessons.md`, `todo.md`, `implementation_plan_v2.md` | ✅ | Design + decision log |
| `reports/paper_trade/state/` | ✅ | Position cache + history; reconciler validates against broker on next run |
| `reports/paper_trade/<YYYYMMDD>/*.jsonl` | ✅ | Daily shadow/paper logs (audit trail) |
| `alphasmart/.env` | ❌ | Secrets — copy manually or recreate |
| `alphasmart/alphasmart_dev.db` | ❌ | OHLCV cache — rebuild via `runner_main fetch` |
| `alphasmart/venv/`, `__pycache__/`, `*.log` | ❌ | Recreate on new machine |

### Halting paper trading

```bash
# Trigger a halt manually (writes reports/paper_trade/state/halt.equity_xsec_momentum_B.json)
# — runner_main refuses to rebalance until the file is removed
echo '{"halted_at_utc":"...","reason":"manual"}' > reports/paper_trade/state/halt.equity_xsec_momentum_B.json

# Clear the halt after operator review
python -m src.execution.runner_main clear-halt
```

The reconciler also auto-halts if cumulative position drift > 1% (see `paper_trade_design.md` §6.4).

### Subsequent tasks (post-paper-trade)

After 7 shadow days + 30 paper days clear the rubric in `paper_trade_design.md` §5:
1. Add the crypto leg (`crypto_xsec_momentum_F`) — see Phase 9 in the inner README.
2. Begin Phase 7 (live deployment, real capital) — gated on the 30-day Sharpe-vs-backtest check.
3. Outstanding research items live in `alphasmart/tasks/todo.md` and `tasks/implementation_plan_v2.md`.

---

## Step 1 Live Run — Results (2026-04-07)

### Data Fetched

| Asset Class | Symbols | Timeframe | Bars | Date Range |
|-------------|---------|-----------|------|------------|
| Equities | AAPL, MSFT, META, NVDA, GOOG, AMZN, AVGO, ASML, NOW, PLTR, CRWD, TSLA, NVO, V, MA, SPY, QQQ (17) | Daily (1d) | 1,256 each | 2021-04-06 → 2026-04-06 |
| Crypto | BTC/USDT, ETH/USDT | Daily (1d) | 730 each | 2024-04-07 → 2026-04-06 |
| Crypto | BTC/USDT, ETH/USDT | 4-hour (4h) | 4,380 each | 2024-04-06 → 2026-04-06 |

**Total DB rows:** ~32,600 OHLCV bars across 21 symbol/timeframe combinations.
**Data source:** yfinance (equities, batch download), CCXT/Binance (crypto, paginated).

> **Note:** yfinance rate-limits aggressively on sequential single-ticker requests. Batch download via `yf.download()` with all tickers in one call bypasses throttling. See Lesson 14.

### Batch Backtest (Default Parameters)

- **Runs:** 231 (11 strategies × 17 stocks × 1d + 11 × 2 crypto × 2 timeframes)
- **Gate 1 passes:** 0 / 231
- **Best Sharpe (default params):** 1.10 — alpha_composite / NVDA / 1d

### Parameter Optimization (Grid Search + Walk-Forward)

Walk-forward settings: **IS = 2yr (504 bars) / OOS = 6mo (126 bars) / Step = 6mo → 5 folds** on 5-year daily data.

- **Optimization runs:** 66 (11 strategies × 6 symbol/tf combos: SPY/1d, NVDA/1d, QQQ/1d, BTC/1d, ETH/1d, BTC/4h)
- **Gate 1 passes:** 0 / 66
- **Gate 2 passes** (robustness only, ≥0.70 OOS/IS ratio): 26 / 66
- **Best optimized Sharpe:** 1.95 — alpha_composite / NVDA / 1d (13 trades — fails ≥100 trade gate)
- **Nearest Gate 1 miss:** triple_screen / NVDA / 1d — Sharpe 1.03, 111 trades (Sharpe just below 1.2)

### Batch Backtest (Optimized Parameters)

- **Runs:** 231 (same universe, optimized params injected where available)
- **Gate 1 passes:** 0 / 231
- **Top result:** alpha_composite / NVDA / 1d — Sharpe 1.95, CAGR 91%, MaxDD 21.9% (13 trades ❌)

---

## Steps 3–5 Live Run — Results (2026-04-07)

### Step 3: Market Regime Filter

Added `src/strategy/regime_filter.py` — `RegimeFilteredStrategy` wraps any base strategy and converts `long` → `flat` whenever SPY is below its 200-day SMA (bear regime). The filter is causal: rolling SMA200 is pre-computed from SPY daily data at construction time; no lookahead.

**Regime-filtered batch:** 342 runs (9 trend/composite strategies × 19 symbols × 2 variants: unfiltered + filtered)

| | Gate 1 passes | Best Sharpe |
|---|---|---|
| Unfiltered | 0 / 171 | 2.03 — alpha_momentum_v2 / NVDA (9 trades ❌) |
| Regime-filtered | 0 / 171 | 1.16 — momentum_long+regime / META (5 trades ❌) |

**Key finding:** The regime filter produces a meaningful trade-off. On NVDA, `alpha_momentum_v2` unfiltered achieves Sharpe 2.03 with only 9 trades; the regime-filtered version drops to Sharpe 1.05 but increases trade count to 54 — much closer to the ≥100 threshold. The filter prevents entries during the 2022 bear market but doesn't fix the fundamental trade count vs Sharpe conflict.

**Notable improvements from the regime filter:**
- `donchian_bo+regime` / TSLA: Sharpe 0.32 → 0.42
- `alpha_composite+regime` / TSLA: Sharpe −0.25 → +0.23
- `ema_crossover+regime` / META: Sharpe 0.82 → 1.00 (nearest miss)

Mean-reversion strategies (`rsi_reversion`, `bb_reversion`, `zscore_reversion`, `vwap_reversion`) are excluded from the regime filter — they trade against the trend by design and filtering bear regimes would suppress their core signal.

### Step 4: Data-Driven V2 Composites

Added `src/strategy/alpha_composite_v2.py` with two variants derived from Step 1 optimization analysis:

| Strategy | Key | Weights | EMA | Distinction |
|---------|-----|---------|-----|-------------|
| `AlphaCompositeTrendV2` | `alpha_trend_v2` | trend=0.50, rsi=0.30, vol=0.20 | 13/30 | EMA crossover dominates |
| `AlphaMomentumV2` | `alpha_momentum_v2` | trend=0.35, rsi=0.40, vol=0.25 | 10/25 | RSI momentum leads |

Both share `rsi_oversold=40.0` (the consistent top-performing threshold across NVDA/SPY/QQQ in Step 1 optimization). Parameter grids are bounded at 4 dimensions × 3 values = 81 combos each (vs ~700 for original `alpha_composite`).

**Top V2 result:** `alpha_momentum_v2` / NVDA / 1d — Sharpe 2.03, but only 9 trades. With regime filter: Sharpe 1.05, 54 trades.

### Step 5: Intraday Infrastructure

**1h equity data (yfinance):** Rate-limited during this session after the regime batch run. Architectural limit: yfinance provides at most ~60 days of 1h data for free — approximately 390 bars. With IS=2yr walk-forward requiring ~3,276 1h bars, 60-day history is insufficient for meaningful walk-forward validation. Production intraday requires Polygon.io or Alpaca historical data API.

**4h crypto mini-batch (16 runs):** BTC/USDT and ETH/USDT, 4,380 bars each (2yr).

| Strategy | Symbol | Sharpe | Trades | Note |
|---------|--------|--------|--------|------|
| macd_momentum | ETH/USDT | 0.83 | 10 | Halted early — daily loss circuit breaker |
| momentum_long | BTC/USDT | 0.35 | 11 | Halted |
| donchian_bo | ETH/USDT | 0.29 | 156 | Best trade count |
| atr_breakout | BTC/USDT | 0.25 | 79 | |

**Key finding:** The 2% daily loss circuit breaker fires on individual 4h candles — a single crypto 4h bar can move 2–6%, instantly tripping the limit. Risk parameters (daily loss limit, circuit breaker thresholds) need timeframe-aware calibration just like annualisation factors. This is documented as Lesson #19.

### Reports Generated (Steps 3–5)

| File | Description |
|------|-------------|
| `reports/regime_comparison_20260407_215958.csv` | 342 runs: trend strategies unfiltered vs SPY SMA200-filtered |
| `reports/intraday_4h_20260407_220231.csv` | 16 runs: 4h crypto mini-batch |

---

### Key Finding: Why Zero Gate 1 Passes

The 2021–2026 backtest period contains two distinct regime problems:

1. **2022 bear market** (S&P −19%, NASDAQ −33%): The 20% circuit-breaker drawdown limit halts most strategies mid-backtest, compressing total return and Sharpe for trend-following strategies.
2. **Trade count vs. Sharpe conflict**: High-Sharpe parameter combinations (Sharpe > 1.2) achieve their ratio through *concentration* — 1 to 13 trades — far below the ≥ 100 trade Gate 1 threshold. Strategies with ≥ 100 trades produce insufficient Sharpe in the volatile 2021–2026 regime.

**Gate 2 is more encouraging:** 26/66 optimization runs pass the OOS/IS stability threshold (≥ 0.70), meaning the optimized parameters generalise to unseen data reasonably well — the strategies aren't over-fit, they're just operating in a regime that penalises both drawdown and Sharpe simultaneously.

### Reports Generated

| File | Description |
|------|-------------|
| `reports/backtest_report_20260406_224906.csv` | Default-params batch: 231 runs |
| `reports/backtest_optimized_20260407_072056.csv` | Optimized-params batch: 231 runs |
| `reports/optimization_results.json` | Full optimizer output: 66 runs with Gate 1/2, overfitting scores, best params |
| `reports/step1_report.html` | Self-contained HTML dashboard with KPI cards, strategy summary, top-20 rankings, optimizer table |

---

## Strategy Research: Leveraged-ETF DCA (2026-05-17)

A parallel research arc on **dollar-cost-averaging into leveraged ETFs** — outside the cross-sectional momentum production system but built on the same infrastructure. Tested 6 strategy variants × 5 tickers (SPY, UPRO, QQQ, QLD, TQQQ) across two windows (10y full and 2022-start worst-entry). Full lessons in [`alphasmart/tasks/lessons.md` #44-#50](alphasmart/tasks/lessons.md).

### Six strategies tested

| Mode | Buy-side rule | Sell-side rule |
|---|---|---|
| `baseline` | $100 every month | hold |
| `dd_pl` | $200 when portfolio P/L% < 0 | hold |
| `dd_ath` | $200 when underlying ≤ −20% from all-time high | hold |
| `dd_hybrid` | $200 when (ATH ≤ −20% AND price > 200d-MA) | hold |
| `exit` | $100 every month | sell-all when regime OFF; redeploy on OFF→ON |
| `hybrid_exit` | $200 when (ATH ≤ −20% AND price > 200d-MA) | sell-all when regime OFF; redeploy on OFF→ON |

### 10-year headline (2016-06 → 2026-05, $12,000 invested baseline per ticker)

| Ticker | Best strategy | Final $ | Money mult | MaxDD | Sharpe |
|---|---|---:|---:|---:|---:|
| **TQQQ** | `exit` | $114,469 | 9.54× | **−54%** | **1.35** |
| **TQQQ** | `hybrid_exit` | $149,311 (uses +$4.9k cap) | 8.83× | −54% | 1.32 |
| TQQQ | baseline | $103,039 | 8.59× | −80% | 1.26 |
| QQQ | `hybrid_exit` | $34,867 (+$1.6k cap) | 2.56× | **−21%** | **1.48** |
| QQQ | baseline | $36,897 | 3.07× | −30% | 1.47 |
| QLD | `exit` | $62,699 | 5.22× | **−39%** | **1.42** |
| QLD | baseline | $71,412 | 5.95× | −61% | 1.36 |
| SPY | `dd_ath` | $32,316 (+$2.3k cap) | 2.26× | −32% | **1.50** |
| SPY | baseline | $27,574 | 2.30× | −32% | 1.46 |
| **UPRO** | `exit` | $47,453 | 3.95× | **−46%** | **1.37** ← `hybrid_exit` regresses on UPRO due to SPY-MA whipsaw |

### Production strategy hierarchy (lesson #50)

1. **Default**: `exit` (baseline DCA + 200d-MA exit-reenter). Triple-win for TQQQ — higher Sharpe AND lower MaxDD AND higher money mult than baseline on the same capital base. Pareto improvement.
2. **More capital available**: `hybrid_exit`. Strictly higher terminal $ than `exit` for 4 of 5 tickers at the cost of ~0.1 Sharpe and ~40-65% more capital deployed.
3. **Max aggression**: `dd_ath`. Highest absolute $ for SPY/UPRO/QQQ/QLD but with full baseline MaxDD (−55% to −80% on leveraged). Only justifiable if MaxDD tolerance is unlimited.
4. **NEVER use `dd_pl` alone**. Sample-period-dependent — fires 1-4× over 10y but 11-18× over the 2022-start sample. Looks great in bear-heavy windows, is a no-op in normal ones.
5. **For UPRO (3× SPY), use `exit` not `hybrid_exit`**. UPRO inherits SPY's 26 round-trips/decade regime-gate whipsaws, which the buy-side hybrid amplifies. Next experiment: try QQQ-MA reference for UPRO, or N-day re-entry delay.

### Key findings worth flagging

- **The regime filter (exit-reenter sell-side) is the single most powerful improvement** for leveraged-ETF DCA — mean MaxDD reduction is 38% across all 5 tickers, vs ~0% from any buy-side rule alone.
- **Buy-sizing rules don't reduce MaxDD** — MaxDD is dominated by existing capital crashing, not by new capital added at bad prices.
- **DCA's "bad-entry paradox"** (lesson #47): all 5 tickers had HIGHER Sharpe when DCA started Jan 2022 (right before the worst bear) than when started 5 years earlier. DCA mechanically loves volatility AT THE START and stability AT THE END.
- **yfinance ETF prices are already net-of-expense-ratio** (lesson #45). Applying ER to backtested returns from yfinance closes double-counts. The 0.84% TQQQ ER cost ~$5,605 on $12k DCA'd over 10y — large in absolute terms but invisible in money-mult thinking.

### Output files (each report directory is self-contained)

| Directory | Contents |
|---|---|
| `alphasmart/reports/leveraged_etf_dca/` | 10y DCA baseline analysis: monthly + daily CSVs, equity + drawdown PNGs |
| `alphasmart/reports/leveraged_etf_dca_2022/` | Same on 2022-01 worst-entry window |
| `alphasmart/reports/leveraged_etf_dca_dd/` | Double-down on negative P/L% |
| `alphasmart/reports/leveraged_etf_dca_dd_filt/` | DD + 200d-MA buy-side filter |
| `alphasmart/reports/leveraged_etf_dca_dd_ath/` | DD triggered by ATH-drawdown |
| `alphasmart/reports/leveraged_etf_dca_dd_hybrid/` | DD when (ATH ≤ −20% AND price > 200d-MA) |
| `alphasmart/reports/leveraged_etf_dca_hybrid_exit/` | Buy-side hybrid + sell-side exit-reenter (2022 window) |
| `alphasmart/reports/leveraged_etf_dca_10y_full/` | All 6 strategies × 5 tickers, full 10y window — the canonical comparison |

---

## Quick Start

**Requirements:** Python 3.11+, Node.js 18+

### 1. Python backend

```bash
cd alphasmart/

python3 -m venv venv
source venv/bin/activate       # macOS/Linux
# venv\Scripts\activate        # Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY for AI Insights (optional)
# yfinance and CCXT work without API keys for historical data
```

### 2. Fetch data

```bash
# Core equities (no API key required)
python main.py fetch AAPL --period 5y --timeframe 1d
python main.py fetch MSFT --period 5y --timeframe 1d
python main.py fetch SPY  --period 5y --timeframe 1d
python main.py fetch QQQ  --period 5y --timeframe 1d

# Extended equity universe (all fetched by default in DB)
# V MA NVO PLTR CRWD AVGO NOW ASML META NVDA TSLA AMZN GOOG

# Intraday (1h and 15m also supported)
python main.py fetch AAPL --period 60d --timeframe 1h
python main.py fetch AAPL --period 7d  --timeframe 15m

# Crypto (no API key for Binance public data)
python main.py fetch BTC/USDT --timeframe 1d --limit 730
python main.py fetch ETH/USDT --timeframe 1d --limit 365

# Check what's stored
python main.py db-status
```

### 3. Run the dashboard

```bash
cd frontend/
npm install
npm run dev
# Open http://localhost:3000
```

The dashboard auto-loads all symbols and strategies from the database. Select a strategy + symbol and the backtest runs immediately.

---

## Symbol Universe

| Ticker | Name | Sector |
|--------|------|--------|
| AAPL | Apple | Technology |
| MSFT | Microsoft | Technology |
| META | Meta | Technology |
| NVDA | NVIDIA | Semiconductors |
| AVGO | Broadcom | Semiconductors |
| ASML | ASML | Semiconductors |
| AMZN | Amazon | Consumer / Cloud |
| GOOG | Alphabet | Advertising / Cloud |
| NOW | ServiceNow | Enterprise SaaS |
| PLTR | Palantir | Data / AI |
| CRWD | CrowdStrike | Cybersecurity |
| TSLA | Tesla | Automotive / Energy |
| V | Visa | Payments |
| MA | Mastercard | Payments |
| NVO | Novo Nordisk | Pharma |
| SPY | S&P 500 ETF | Benchmark |
| QQQ | Nasdaq 100 ETF | Benchmark |
| BTC/USDT | Bitcoin | Crypto |
| ETH/USDT | Ethereum | Crypto |

All equity symbols have 5 years of daily data (1,256 bars). Weekly data is available for AAPL–GOOG. Crypto uses daily + 4h.

---

## Strategies

AlphaSMART ships with 11 strategies across three families:

### Trend Following
| Key | Name | Logic |
|-----|------|-------|
| `ema_crossover` | EMA Crossover | Fast EMA crosses above slow EMA (golden cross) |
| `macd_momentum` | MACD Momentum | MACD histogram positive = long |
| `donchian_bo` | Donchian Breakout | Price breaks above N-day rolling high |
| `triple_screen` | Triple Screen | 50-SMA macro filter + Stochastic pullback entry |
| `atr_breakout` | ATR Breakout | Price > EMA + N×ATR (volatility-adjusted channel) |
| `momentum_long` | Momentum (ROC) | 6-month rate-of-change momentum signal |

### Mean Reversion
| Key | Name | Logic |
|-----|------|-------|
| `rsi_reversion` | RSI Mean Reversion | Buy when RSI < 30, sell when RSI > 70 |
| `bb_reversion` | Bollinger Reversion | Buy at lower band, exit at midline |
| `zscore_reversion` | Z-Score Reversion | Long when price is >2σ below rolling mean |
| `vwap_reversion` | VWAP Reversion | Fade large deviations from rolling VWAP |

### Proprietary
| Key | Name | Logic |
|-----|------|-------|
| `alpha_composite` | Alpha Composite ✦ | Weighted composite: EMA trend + RSI momentum + Volume confirmation |
| `alpha_trend_v2` | Alpha Trend V2 ✦ | Trend-heavy (trend=0.50); data-driven defaults from Step 1 optimization |
| `alpha_momentum_v2` | Alpha Momentum V2 ✦ | Momentum-focused (rsi=0.40); tighter EMA for more signals |

### Regime-Filtered Variants

Any trend/momentum strategy can be wrapped with `+regime` suffix to enable the **SPY SMA200 bear filter**: when SPY is below its 200-day SMA, long signals are suppressed. Registered variants: `ema_crossover+regime`, `donchian_bo+regime`, `macd_momentum+regime`, `triple_screen+regime`, `atr_breakout+regime`, `momentum_long+regime`, `alpha_composite+regime`, `alpha_trend_v2+regime`, `alpha_momentum_v2+regime`.

All strategies are **long-only**, deterministic, and run through the same event-driven engine. No lookahead bias is possible — signals are generated from `data[0:i+1]` and executed at bar `i+1` open.

---

## Backtesting

### Single backtest (CLI)

```bash
python main.py backtest AAPL --strategy ema_crossover --capital 100000
python main.py backtest BTC/USDT --strategy zscore_reversion --timeframe 1d
```

### All strategies × all symbols

```bash
python main.py backtest-all \
  --symbols AAPL MSFT SPY BTC/USDT \
  --capital 100000 \
  --output results.csv
```

### Via subprocess bridge (used by the dashboard)

```bash
# Core operations
python run_backtest.py backtest   <strategy> <symbol> <timeframe> [capital]
python run_backtest.py optimize   <strategy> <symbol> [timeframe] [objective]
python run_backtest.py simulate   <strategy> <symbol> [timeframe] [sim_type] [n_sims]
python run_backtest.py insights   <strategy> <symbol> [timeframe]
python run_backtest.py summary
python run_backtest.py strategies
python run_backtest.py symbols

# Optimized params persistence
python run_backtest.py save_opt_params <strategy> <symbol> <timeframe> <objective> \
                                        <params_json> <sharpe> <cagr> <max_drawdown> <gate2_pass>
python run_backtest.py load_opt_params
```

### Supported timeframes

| Timeframe | String | Bars/Year | Notes |
|-----------|--------|-----------|-------|
| 15 minutes | `15m` | ~6,552 | US equities intraday |
| 1 hour | `1h` | ~1,638 | US equities intraday |
| Daily | `1d` | 252 | Default, most strategies designed for this |
| Weekly | `1wk` | 52 | Long-period trend following |

Sharpe, Sortino, and CAGR are annualised correctly for each timeframe via `bars_per_year_for(timeframe)`.

---

## Optimization

The optimizer runs a **grid search** across all parameter combinations followed by **walk-forward validation**. Default windows: **IS = 2yr / OOS = 6mo / Step = 6mo** — producing ≥ 5 folds on 5-year daily data. Windows scale automatically with the timeframe via `bars_per_year_for(timeframe)`.

### Optimization objectives

| Objective | Description |
|-----------|-------------|
| `sharpe` | Maximise Sharpe ratio (default) |
| `cagr` | Maximise compound annual growth rate |
| `max_drawdown` | Minimise maximum drawdown |
| `profit_factor` | Maximise gross profit / gross loss |

Select the objective in the **Optimizer** sidebar before running. The result shows Gate 2 status (OOS/IS ratio ≥ 0.70 = stable) and a parameter stability heatmap.

### Gate 1 (backtest qualification)
- Sharpe > 1.2
- Max Drawdown < 25%
- ≥ 100 trades
- Positive total return

### Gate 2 (optimization stability)
- OOS Sharpe ≥ 70% of in-sample Sharpe across walk-forward folds

### Optimization Queue

The Optimizer view includes a **queue** for batch-running multiple strategy × symbol × objective combinations:

1. Select a strategy + symbol + objective in the sidebar
2. Click **+ Add to Queue** (repeating for each combo)
3. Click **▶ Run All** — items execute sequentially, each saving its result automatically
4. Completed results are persisted to `optimized_params.json` and immediately surface with a **✦ OPT** badge in All Results

Each completed queue item displays its Gate 2 verdict and best Sharpe inline.

### Saving individual results

After any single optimization run, click **✦ Save to All Results** in the Best Parameters panel. The next time All Results refreshes, that strategy × symbol combination uses the optimized parameters instead of defaults.

Optimized params are stored in `alphasmart/optimized_params.json`:

```json
{
  "ema_crossover::AAPL::1d": {
    "strategy": "ema_crossover",
    "symbol": "AAPL",
    "timeframe": "1d",
    "objective": "sharpe",
    "params": { "fast_period": 10, "slow_period": 30 },
    "sharpe": 1.84,
    "cagr": 0.213,
    "max_drawdown": 0.117,
    "gate2_pass": true,
    "timestamp": "2026-03-28T14:22:00Z"
  }
}
```

---

## Bootstrapping Simulation

The **Simulation** view stress-tests any strategy by running it across hundreds of synthetic price paths derived from the historical data. Choose from:

| Method | Description |
|--------|-------------|
| **Block Bootstrap** | Resamples overlapping blocks of returns — preserves volatility clustering |
| **Monte Carlo (GBM)** | Fits μ/σ from history, generates N independent log-normal paths |
| **Jackknife** | Leave-one-monthly-block-out — reveals period dependency |

Results show metric distributions (p5/p25/median/p75/p95) and a robustness verdict:
- **ROBUST**: Sim median Sharpe ≥ 65% of original → strategy works across varied conditions
- **FRAGILE**: Large degradation → strategy may be overfitting to specific market conditions

---

## Risk Engine

All risk limits are **hard-enforced** — they block execution, not just alert:

| Rule | Default |
|------|---------|
| Max position size | 5% of portfolio per trade |
| Max daily loss | 2% of portfolio |
| Max drawdown circuit breaker | 20% |
| Max open positions | 10 |
| Commission | 0.1% per trade |
| Slippage | 0.05% per trade (adverse) |

These are set in `src/strategy/risk_manager.py`. The `RiskEngine` validates every order before queuing and monitors the portfolio after every bar.

---

## LLM Copilot (AI Insights)

Requires `ANTHROPIC_API_KEY` in `.env`. The AI Insights tab runs a fresh backtest and sends metrics + equity curve to Claude for analysis:

- Market regime classification (trending / ranging / volatile)
- Risk flag detection
- Strategy strengths and weaknesses
- Gate 2 readiness assessment
- Actionable recommendations

**Scope**: analytical only. The LLM cannot place orders, modify parameters, or affect execution.

---

## Project Structure

```
alphasmart/
├── src/
│   ├── data/
│   │   ├── fetcher.py              # StockDataFetcher, CryptoDataFetcher
│   │   ├── preprocessor.py         # OHLCV cleaning and validation
│   │   ├── indicators.py           # EMA, RSI, BB, ATR, MACD, VWAP, Volume MA
│   │   └── database.py             # SQLAlchemy ORM (SQLite dev / PostgreSQL prod)
│   ├── strategy/
│   │   ├── base.py                 # Abstract Strategy, Signal, Order, Fill types
│   │   ├── portfolio.py            # Portfolio state (cash, positions, equity curve)
│   │   ├── risk_manager.py         # Hard risk limits — blocks execution
│   │   ├── trend.py                # EMA Crossover
│   │   ├── mean_reversion.py       # RSI Mean Reversion
│   │   ├── breakout.py             # Donchian Breakout
│   │   ├── macd_momentum.py        # MACD Momentum
│   │   ├── bollinger_reversion.py  # Bollinger Band Reversion
│   │   ├── triple_screen.py        # Triple Screen (SMA + Stochastic)
│   │   ├── atr_breakout.py         # Volatility-Adjusted ATR Breakout
│   │   ├── zscore_reversion.py     # Rolling Z-Score Reversion
│   │   ├── momentum_long.py        # Rate-of-Change Momentum
│   │   ├── vwap_reversion.py       # Rolling VWAP Mean Reversion
│   │   ├── alpha_composite.py      # Proprietary weighted composite strategy
│   │   ├── alpha_composite_v2.py   # AlphaCompositeTrendV2 + AlphaMomentumV2 (data-driven)
│   │   └── regime_filter.py        # RegimeFilteredStrategy — SPY SMA200 bear filter
│   ├── backtest/
│   │   ├── engine.py               # Event-driven backtester (bar-by-bar, no lookahead)
│   │   ├── metrics.py              # 13 performance metrics, timeframe-aware annualisation
│   │   ├── optimizer.py            # Grid search + walk-forward, 11 strategies, 4 objectives
│   │   ├── runner.py               # Batch runner — supports params_override for opt results
│   │   └── simulation.py           # Block bootstrap, jackknife, Monte Carlo GBM
│   ├── llm/
│   │   ├── client.py               # Claude API wrapper (analytical only)
│   │   └── prompts.py              # Structured prompt templates + schema validation
│   ├── monitoring/
│   │   └── logger.py               # loguru logger (console + rotating file)
│   ├── reporting/
│   │   └── report.py               # CSV + HTML report generation
│   └── execution/
│       └── broker.py               # Broker abstraction stub (Phase 5)
├── frontend/
│   ├── src/app/
│   │   ├── page.tsx                # Main dashboard (5 views + optimization queue)
│   │   └── api/                    # Next.js route handlers (subprocess bridge)
│   │       ├── backtest/route.ts
│   │       ├── optimize/route.ts
│   │       ├── simulate/route.ts
│   │       ├── insights/route.ts
│   │       ├── summary/route.ts
│   │       ├── strategies/route.ts
│   │       ├── symbols/route.ts
│   │       └── opt-params/route.ts # GET load / POST save optimized params
│   └── src/lib/
│       └── python.ts               # runPython() — spawns subprocess, parses JSON stdout
├── tests/
│   ├── conftest.py                 # Pytest fixtures, synthetic OHLCV generator
│   ├── test_preprocessor.py        # 14 tests
│   ├── test_indicators.py          # 26 tests
│   ├── test_database.py            # 15 tests
│   └── test_pipeline.py            # 6 end-to-end tests
├── tasks/
│   ├── todo.md                     # Build plan with stage gate checklist
│   └── lessons.md                  # Hard-won implementation lessons (13 entries)
├── main.py                         # CLI entrypoint
├── api.py                          # FastAPI server + _load_opt_params / _save_opt_params
├── run_backtest.py                  # JSON subprocess bridge called by Next.js routes
├── optimized_params.json            # Persisted best params (auto-created, gitignored)
├── requirements.txt
├── .env.example                    # Template — copy to .env, never commit .env
└── .gitignore
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  DATA LAYER       yfinance (stocks) / CCXT (crypto)             │ ✅
│                   19 symbols · Timeframes: 15m, 1h, 1d, 1wk     │
├─────────────────────────────────────────────────────────────────┤
│  STRATEGY ENGINE  13 strategies + 9 regime-filtered variants      │ ✅
│                   Signal → Order → Fill pipeline                  │
├─────────────────────────────────────────────────────────────────┤
│  BACKTEST ENGINE  Event-driven, bar-by-bar (no lookahead bias)   │ ✅
│                   Slippage + commission at fill, risk gate        │
├─────────────────────────────────────────────────────────────────┤
│  SIMULATION       Block bootstrap / Jackknife / Monte Carlo GBM  │ ✅
│                   Metric distributions across synthetic paths     │
├─────────────────────────────────────────────────────────────────┤
│  OPTIMIZER        Grid search + walk-forward validation           │ ✅
│                   4 objectives, stability heatmap, Gate 2         │
│                   Queue: batch-run N combos, auto-save results    │
├─────────────────────────────────────────────────────────────────┤
│  OPT PARAMS       optimized_params.json — persisted best params   │ ✅
│                   All Results uses opt params where available      │
├─────────────────────────────────────────────────────────────────┤
│  RISK ENGINE      Hard limits — blocks execution, non-negotiable  │ ✅
├─────────────────────────────────────────────────────────────────┤
│  LLM COPILOT      Claude API — regime + risk analysis only        │ ✅
│                   Zero write access to orders or params           │
├─────────────────────────────────────────────────────────────────┤
│  DASHBOARD        React + Next.js + Tailwind                      │ ✅
│                   5 views: Explorer / All Results / Optimizer /   │
│                   AI Insights / Simulation                        │
├─────────────────────────────────────────────────────────────────┤
│  EXECUTION        Alpaca (stocks) / CCXT (crypto) broker stub     │ 🔜 Phase 5
├─────────────────────────────────────────────────────────────────┤
│  MONITORING       Prometheus + Grafana                            │ 🔜 Phase 6
└─────────────────────────────────────────────────────────────────┘
```

---

## Dashboard Views

| View | Description |
|------|-------------|
| **Explorer** | Single backtest — equity curve vs buy-and-hold, metrics, trade log, P&L histogram |
| **All Results** | 11 strategies × all symbols ranked by composite score; ✦ OPT badge for optimized rows |
| **Optimizer** | Grid search, walk-forward table, stability heatmap, Gate 2 verdict, optimization queue |
| **AI Insights** | Claude-powered regime classification, risk flags, strategy assessment |
| **Simulation** | Bootstrapping results — metric distributions, robustness verdict |

### All Results scoring

`Composite Score = Sharpe × 40% + CAGR × 30% + DrawdownResistance × 20% + WinRate × 10%`

Strategies with negative total return score 0 and rank last. Click any row to open it in the Explorer. Rows that used walk-forward optimized parameters are marked **✦ OPT**.

---

## Running Tests

```bash
source venv/bin/activate

# Full suite
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=src --cov-report=term-missing

# Individual modules
python -m pytest tests/test_indicators.py -v
python -m pytest tests/test_database.py   -v
```

---

## Adding a New Strategy

1. Create `src/strategy/my_strategy.py` — inherit from `Strategy`, implement `generate_signals()` and `size_position()`
2. Register in `api.py`: add to `STRATEGY_MAP` and `STRATEGY_LABELS`
3. Register in `src/backtest/optimizer.py`: add to `PARAM_GRIDS` and `STABILITY_AXES`
4. Import in `run_backtest.py` (handled via `api` import, no extra work needed)

The strategy will automatically appear in the dashboard strategy selector.

**No-lookahead rule:** `generate_signals(data)` receives `data.iloc[:i+1]` at bar `i`. Only use `data.iloc[-1]` (or earlier). Never access `data.iloc[-1+N]` for positive N.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Optional | Enables AI Insights tab (Claude API) |
| `DATABASE_URL` | Optional | PostgreSQL URL for production (default: SQLite dev DB) |
| `POLYGON_API_KEY` | Optional | Polygon.io for production stock data (default: yfinance) |
| `BINANCE_API_KEY` | Optional | For authenticated Binance endpoints |
| `BINANCE_API_SECRET` | Optional | For authenticated Binance endpoints |

---

## Safety Rules

1. **Never commit `.env`** — it's in `.gitignore`
2. **Never commit `optimized_params.json`** — it's in `.gitignore` (local tuning, not source truth)
3. **Risk engine is non-negotiable** — it blocks execution, not just alerts. No overrides exist
4. **LLM advises only** — zero write access to orders, parameters, or execution
5. **Paper trading by default** — Alpaca paper URL is the default until Gate 4 passes
6. **No lookahead bias** — strategies only receive `data[0:i+1]` via the event-driven engine
