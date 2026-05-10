# AlphaSMART

> Research. Validate. Deploy. Only alpha that survives reality gets capital.

A full-stack algorithmic trading platform: strategy research → backtesting → optimization → bootstrapping simulation → forward testing → live deployment, with an LLM analytical copilot and institutional-grade risk controls.

> **🚀 Status update (2026-05-03):** Phase 8 (cross-sectional pivot) executed. Cross-sectional 6-month momentum on a 15-symbol mega-cap universe with vol-targeting overlay, optimized on 10-yr daily data, **cleared all 5 stages of the fail-fast pipeline as `PORTFOLIO_READY`** — Sharpe 1.503, MaxDD 19.6%, OFR 1.552, bootstrap ratio 0.820. Two further mechanics (cross-sectional low-vol and short-term reversal) also produced individual `PORTFOLIO_READY` verdicts. This is the project's first deployable signal. Lessons #34 architectural falsification was correct; lessons #35-37 capture how the cross-sectional pivot worked and what the new binding constraint is (universe homogeneity / inter-strategy correlation).

---

## Current Status

| Phase | Scope | Status |
|-------|-------|--------|
| **1 — Foundation** | Data pipeline, indicators, DB, CLI | ✅ Complete |
| **2 — Core Engine** | Strategy abstraction, backtester, risk engine | ✅ Complete |
| **3 — Optimization + LLM** | Walk-forward, grid search, Claude copilot, simulation | ✅ Complete |
| **4 — Dashboard** | React UI, Next.js, optimization queue, opt-params persistence | ✅ Complete |
| **6a — Per-trade stops** | ATR trailing-stop wrapper (`+stop` variants) | ✅ 2026-04-26 |
| **6b — Robustness sweep** | Walk-forward on top-4 +stop × 17-symbol universe | ✅ 2026-05-01 |
| **6c — Bootstrap + decision** | Block bootstrap on passers, portfolio decision gate | ✅ 2026-05-01 (verdict: NONE) |
| **6d — Widening sweep** | `momentum_long+stop`, `donchian_bo+stop`, `alpha_composite+stop`, `bb_reversion+stop` | ✅ 2026-05-02 (verdict: NONE) |
| **6e — Cross-timeframe (1wk)** | Same 8 strategies, weekly bars, 17-symbol universe | ✅ 2026-05-02 (verdict: NONE) |
| **6f — Pair spreads** | `zscore_reversion+stop`, `bb_reversion+stop` on 5 sector pairs | ✅ 2026-05-02 (verdict: NONE) |
| **6g — Vol-targeting overlay** | `+stop+vol` wrapper, re-bootstrap 9 fragile candidates | ✅ 2026-05-02 (verdict: NONE) |
| **6h — Extended history (10-yr)** | Re-optimize 1d candidates on 2016–2026 daily | ✅ 2026-05-02 (verdict: NONE) |
| **6 — Architectural conclusion** | Single-asset 1d/1wk universe falsified across all levers | 🔚 **2026-05-02 — see lessons.md #34** |
| **8 — Cross-sectional pipeline (v2)** | Fail-fast 5-stage pipeline + xsec momentum/lowvol/reversal on 15-sym 10-yr 1d | ✅ **2026-05-03 — 3 individual PORTFOLIO_READY** |
| **8b — Multi-timeframe sweep** | Same xsec mechanic on 1d (10y), 1wk (5y), 1h (3y) | ✅ **2026-05-03 — all 3 PORTFOLIO_READY but ρ ~0.97 equity-curve, 1 effective signal (lesson #38)** |
| **9 — Multi-universe diversification** | Crypto (9 pairs) + bonds (9 ETFs) + sector ETFs (11) | ✅ **2026-05-03 — crypto PORTFOLIO_READY, bonds/sectors killed at Stage 3** |
| **9 — First uncorrelated pair** | Equity xsec mom + crypto xsec mom, monthly ρ=0.40, var-reduction 32% | ✅ **2026-05-03 — 2 of ≥3 needed (lesson #39)** |
| **10 — Regime filter** | Asset > 200d-MA gate (SPY for equity, BTC for crypto) | ✅ **2026-05-03 — Sharpe +0.4 to +0.5, MaxDD halved, 2022 dodged (lesson #40)** |
| 5 — Forward Testing | Paper trading, 30-day run | 🟢 **2-strategy regime-filtered ensemble deployable** (Sharpe 1.89, MaxDD 9.2%, ρ=0.18) |
| 7 — Live Deployment | Real capital, broker integration | ⏸ Pending Phase 5 |

### Gate 1 Scoreboard (historical record — see lessons.md #34 for the architectural conclusion)

> **⚠ Falsification note (2026-05-02):** the strategies below are preserved as the institutional record of what passed *strict Gate 1 + Gate 2 on 5-yr daily data*, not as recommendations. **All candidates that reached the bootstrap stage came back FRAGILE.** The 10-yr re-optimization (lessons #34) further showed that the 5-yr Sharpes were inflated 30–50% by post-2022 macro-arc fitting — `cci_trend+stop` NVDA's optimal Sharpe on 10-yr daily data is **0.81**, not 1.39. The Gate 1 / Gate 2 framework is sound; the single-asset architecture cannot pass the full pipeline on this universe.

**Strict Gate 1 + Gate 2** (5-yr 1d, Sharpe > 1.2, MaxDD < 25%, ≥ 30 trades, OFR ≥ 0.70):

| # | Strategy | Symbol | 5-yr Sharpe | 10-yr Sharpe | OFR | Bootstrap ratio | Verdict |
|---|----------|--------|------:|------:|------:|------:|---|
| 1 | `cci_trend+stop` (entry=75, exit=50, vol=0.8) | NVDA | 1.39 | **0.81** | 0.82 | **0.07** (5-yr) / **0.52** (10-yr) | FRAGILE |

**Relaxed Gate 1 + strict Gate 2** (Sharpe ≥ 1.0, ≥ 15 trades, OFR ≥ 0.70):

| # | Strategy | Symbol | 5-yr Sharpe | OFR | Bootstrap ratio | Verdict |
|---|----------|--------|------:|------:|------:|---|
| 2 | `rsi_vwap+stop` (vwap=12, rsi=10, os=35, ob=60) | V | 1.10 | 1.04 | 0.37 | FRAGILE |
| 3 | `bb_reversion+stop` (period=20, std=2.0) | NVDA | 1.17 | 0.93 | -0.39 | FRAGILE |

**Session summary (2026-04-30 → 05-02):** 4 walk-forward sweeps (top-4 1d, widening 1d, weekly 1wk, pair spreads 1d) covering 230 (strategy, symbol) runs and ~28,000 backtests; 3 bootstrap rounds across 12 unique candidates with vol-targeting wrapper retrofit; final 10-yr history extension on the 3 strongest candidates. **Final verdict: NONE.** The architecture has been systematically falsified — see `tasks/lessons.md` #34 for the full reasoning.

The 2021–2026 period embeds a 2022 bear market (NVDA –65%, broad tech –30%+) that eliminates most strategies through the 20% drawdown circuit breaker or insufficient trade count. Single-passer (or even 2-passer) concentration is **not** a paper-tradable portfolio — lessons #27 sets the bar at ≥ 3 uncorrelated ROBUST passers across sectors. Next steps: bootstrap the relaxed set, then either (a) widen the strategy search to `momentum_long+stop`, `donchian_bo+stop`, `alpha_composite+stop` or (b) extend history to 7–10 yr daily for more walk-forward folds. See `tasks/todo.md`.

### Strategy-level trailing stop

`src/strategy/trailing_stop.py` adds `TrailingStopStrategy(inner, atr_period=14, atr_mult=2.0)` — a Chandelier-style ATR trailing stop that wraps any base strategy and converts `long` → `flat` when `close < max_close_since_entry - 2 * ATR(14)`. Registered as `<strategy>+stop` variants for trend/momentum strategies in both the optimizer and the dashboard. The portfolio-level 20% drawdown circuit breaker remains as a last-resort safety net; per-trade risk now sits with the wrapper.

---

## Paper-Trade Runner

The live paper-trade orchestrator lives in `src/execution/`. CLI entrypoint: `python -m src.execution.runner_main`.

```bash
# One-shot rebalance against the equity strategy in shadow mode (no orders)
python -m src.execution.runner_main rebalance --mode shadow --kind manual --verbose

# Same in paper mode (submits to Alpaca paper account)
python -m src.execution.runner_main rebalance --mode paper --fetch-before-rebalance

# Standalone OHLCV fetch (rebuilds alphasmart_dev.db cache)
python -m src.execution.runner_main fetch --lookback 1y --verbose

# Inspect current state + halt flag
python -m src.execution.runner_main status

# Lift a halt after operator review
python -m src.execution.runner_main clear-halt
```

**State files** live under `../reports/paper_trade/`:
- `state/<channel>.json` — current positions (committed to git as a migration aid; reconciler validates against the broker on every run)
- `state/<channel>.history.jsonl` — append-only audit log of every state write
- `state/halt.<channel>.json` — kill-switch; while present, rebalance refuses to run
- `<YYYYMMDD>/<channel>.jsonl` — daily structured event logs (preflight, signals, fills, drift)

**Strategy spec (built-in):** `equity_xsec_momentum_B` — 15-symbol mega-cap cross-sectional 6-month momentum, top-5 equal-weight, 21-day rebalance, gated by SPY > 200d-MA. Defined in `src/execution/runner_main.py::build_equity_spec`. See `tasks/paper_trade_design.md` for the full design, pre-flight checks, and 7-day shadow / 30-day paper pass rubric.

**Cron schedule (production, weekdays after US close):**

```cron
0 17 * * 1-5 cd $HOME/alphasmart/alphasmart && $HOME/alphasmart/alphasmart/venv/bin/python -m src.execution.runner_main rebalance --mode paper --fetch-before-rebalance >> $HOME/alphasmart/alphasmart/logs/cron.log 2>&1
```

For full clone-and-resume instructions (migrating the runner to a new machine), see [`../README.md` → "Paper-Trade — Clone & Resume on Another Machine"](../README.md#paper-trade--clone--resume-on-another-machine).

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

The optimizer runs a **grid search** across all parameter combinations followed by **walk-forward validation** (3-year in-sample, 1-year out-of-sample). Windows scale automatically with the timeframe.

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
- ≥ 30 trades (lowered from 100 in 2026-04 — see lessons.md #22)
- Positive total return

### Gate 2 (optimization stability — OFR)
- **OFR (Overfitting Ratio)** = mean over folds of `max(OOS_Sharpe, 0) / IS_Sharpe`
- Gate passes when OFR ≥ 0.70 (see lessons.md #30 for calibration)

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
│   │   └── alpha_composite.py      # Proprietary weighted composite strategy
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
│  STRATEGY ENGINE  11 strategies across trend / reversion / prop  │ ✅
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
