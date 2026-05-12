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
| 5 — Forward Testing | Paper trading, 30-day run | 🟢 **Running** — 2-strategy regime-filtered ensemble (Sharpe 1.89, MaxDD 9.2%, ρ=0.18) |
| 6 — Live Deployment | Real capital, broker integration | 🔜 Planned |

> The current paper-trade run uses the equity leg only (`equity_xsec_momentum_B`): **17-symbol** mega-cap cross-sectional 6-month momentum, top-5 equal-weight, monthly rebalance, gated by SPY > 200d-MA. Universe v2 (2026-05-11) added AMD + LLY for a −2.3pp MaxDD / +0.7pp CAGR trade-off; see `alphasmart/tasks/strategies.md` for the universe-history audit trail and `alphasmart/tasks/paper_trade_design.md` for the full design and pass/fail rubric.

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

# 7. Install cron (US Eastern equity close = 16:00 ET ≈ 21:00 UTC during DST)
crontab -e
```

Add these two lines to crontab (paths assume clone at `$HOME/alphasmart` — adjust if different):

```cron
# AlphaSMART paper-trade — equity rebalance, weekdays 17:00 local (after US close)
0 17 * * 1-5 cd $HOME/alphasmart/alphasmart && $HOME/alphasmart/alphasmart/venv/bin/python -m src.execution.runner_main rebalance --mode paper --fetch-before-rebalance >> $HOME/alphasmart/alphasmart/logs/cron.log 2>&1

# AlphaSMART smoke check — shadow rebalance every day 17:40, alerts if preflight or signal goes sideways
40 17 * * * cd $HOME/alphasmart/alphasmart && $HOME/alphasmart/alphasmart/venv/bin/python -m src.execution.runner_main rebalance --mode shadow --kind smoke --stale-after-hours 240 >> $HOME/alphasmart/alphasmart/logs/cron_test.log 2>&1
```

> ⚠️ `cron` does not expand `$HOME` on every system. If your `crontab -l` shows the literal `$HOME` instead of `/Users/you` or `/home/you`, replace `$HOME` with the absolute path before saving.

> ⚠️ **Pre-market rebalance can write a false-positive halt.** If the cron first fires before US market open (or you run a manual `rebalance --mode paper` outside market hours), the reconciler will halt the channel because pending SELLs aren't credited against phantom positions (`reconciler.py:138-147`; see `alphasmart/tasks/lessons.md` #43). Wait for fills, verify positions match the target weights, then `python -m src.execution.runner_main clear-halt`. Daytime weekday cron firings are not affected.

**Verify cron fired:**

```bash
tail -f ~/alphasmart/alphasmart/logs/cron.log
# After the next scheduled run you should see: "rebalance_id": "rb-...", "drift_pct" < 0.01
python -m src.execution.runner_main status   # confirms last_updated_utc moved forward
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
