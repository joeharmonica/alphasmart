# ALPHASMART — PRODUCT REQUIREMENTS DOCUMENT

> **Tagline:** Research. Validate. Deploy. Only alpha that survives reality gets capital.

---

## ANALYSIS: PRD vs. GUIDE ALIGNMENT

**Issues identified in the previous PRD:**
1. Three conflicting product names (ALPHA FORGE, Aegis Trader, NexusTrader) — no single identity
2. LLM treated as a Phase 5 afterthought; the guide positions LLM as the core analytical brain from inception
3. Tech stack conflicts throughout: TimescaleDB vs PostgreSQL, backtesting.py vs VectorBT vs Backtrader
4. Stage gates and phases repeated 3x with contradictory requirements
5. Architecture diagram didn't reflect LLM's role in the data → signal pipeline
6. Dashboard deprioritised; guide integrates it alongside the core engine build

**Resolution:** Single product identity (AlphaSMART), guide-aligned architecture, one canonical tech stack, LLM integrated at Phase 3, deduplicated phases with hard gates.

---

## 1. PRODUCT VISION

AlphaSMART is a full-stack algorithmic trading platform that lets systematic traders:

- Design multi-strategy systems with deterministic signal logic
- Backtest with realistic market constraints (slippage, fees, latency)
- Optimize without overfitting via walk-forward validation
- Use an LLM as an analytical copilot — regime classification, risk flags, post-trade analysis
- Forward test in real market conditions before deploying capital
- Deploy with institutional-grade risk controls and hard kill switches

**Core Philosophy:**
If it doesn't survive forward testing, it doesn't deserve capital.
LLM advises. The risk engine decides. The stage gate enforces.

---

## 2. TARGET USERS

**Primary**
- Retail quants building systematic strategies
- Crypto-native traders transitioning to automation
- Engineers entering the quant space

**Secondary**
- Small funds / prop traders
- Portfolio managers overseeing automated strategies

---

## 3. SYSTEM ARCHITECTURE

Following the guide's layered model:

```
┌──────────────────────────────────────────────────────────┐
│  DATA LAYER         Market feeds, OHLCV, news, on-chain  │
│  ─────────────►     yfinance / ccxt / Polygon.io          │
├──────────────────────────────────────────────────────────┤
│  LLM COPILOT        Regime analysis → structured signal  │
│  ─────────────►     Claude API (JSON-only output)         │
├──────────────────────────────────────────────────────────┤
│  STRATEGY ENGINE    Signal generation, position sizing   │
│  ─────────────►     Multi-strategy, deterministic         │
├──────────────────────────────────────────────────────────┤
│  BACKTEST / FWD     Vectorized research + event-driven   │
│  ─────────────►     simulation, walk-forward validation   │
├──────────────────────────────────────────────────────────┤
│  RISK ENGINE        Hard limits, kill switches           │
│  ─────────────►     NON-NEGOTIABLE — blocks execution     │
├──────────────────────────────────────────────────────────┤
│  EXECUTION LAYER    Broker abstraction, order lifecycle  │
│  ─────────────►     Paper → Live (Alpaca / CCXT)          │
├──────────────────────────────────────────────────────────┤
│  MONITORING         Dashboard, logs, P&L, alerts         │
│  ─────────────►     React UI + Prometheus + Grafana       │
└──────────────────────────────────────────────────────────┘
```

---

## 4. PROJECT STRUCTURE

```
alphasmart/
├── config/
│   ├── settings.yaml          # API keys, risk params
│   └── strategies.yaml        # Strategy configs
├── src/
│   ├── data/
│   │   ├── fetcher.py         # Market data (stocks + crypto)
│   │   ├── preprocessor.py    # Clean & transform
│   │   └── indicators.py      # Technical indicators
│   ├── llm/
│   │   ├── client.py          # Claude API wrapper
│   │   ├── prompts.py         # Prompt templates
│   │   └── parser.py          # JSON response validation
│   ├── strategy/
│   │   ├── base.py            # Strategy interface
│   │   ├── signal_generator.py
│   │   ├── risk_manager.py
│   │   └── position_sizer.py
│   ├── backtest/
│   │   ├── engine.py          # Event-driven engine
│   │   ├── metrics.py         # Sharpe, DD, CAGR, etc.
│   │   └── optimizer.py       # Walk-forward + Optuna
│   ├── execution/
│   │   ├── broker.py          # Broker abstraction layer
│   │   ├── order_manager.py   # Lifecycle + idempotency
│   │   └── paper_trader.py
│   └── monitoring/
│       ├── logger.py
│       ├── dashboard.py
│       └── alerts.py
├── frontend/                  # React + Next.js
├── tests/
├── notebooks/                 # Research/exploration
├── tasks/
│   ├── todo.md
│   └── lessons.md
├── .env                       # NEVER commit
├── requirements.txt
└── main.py
```

---

## 5. CANONICAL TECH STACK

| Layer | Technology | Decision |
|-------|-----------|----------|
| Backend | Python 3.11+ + FastAPI | Async, native quant library support |
| LLM | Anthropic Claude API (claude-sonnet) | Structured JSON outputs, low temp |
| Research/Backtest | VectorBT | Vectorized, fast multi-strategy |
| Event-Driven Sim | Custom engine (Phase 2) | Full control over fills + latency |
| Optimization | Optuna + walk-forward | No black-box tuning |
| Database | PostgreSQL | Primary store (trades, logs, configs) |
| Cache/State | Redis | Real-time state, live signals |
| Market Data | yfinance (free) → Polygon.io (prod) | Stocks |
| Crypto Data | CCXT / Binance WebSocket | Crypto |
| Execution | Alpaca API (stocks), CCXT (crypto) | Paper + live |
| Frontend | React + Next.js + TailwindCSS | Component-based, TypeScript |
| Charts | TradingView Lightweight Charts | Industry standard |
| Infra | Docker | Dev/prod parity |
| Monitoring | Prometheus + Grafana | Alerts + dashboards |
| Error tracking | Sentry | Production errors |

---

## 6. CORE FUNCTIONAL REQUIREMENTS

### 6.1 Strategy System
```python
class Strategy:
    def generate_signals(self, data: pd.DataFrame) -> Signal
    def size_position(self, signal: Signal, portfolio: Portfolio) -> Order
```
- Deterministic signal generation (no randomness)
- Multi-strategy portfolio support
- Strategy types: Trend, Mean Reversion, Breakout (Market-Neutral: Phase 3+)

### 6.2 Backtesting Engine
- Event-driven simulation with realistic fills
- Fee modeling, slippage modeling, latency modeling
- Multi-asset support
- No lookahead bias (enforced by gate check)
- Outputs: trade log, equity curve, full risk metrics

### 6.3 Optimization Engine
- Grid search + random search
- Walk-forward optimization (rolling windows)
- Output: **stability region** (not just best params)
- Overfitting score / parameter sensitivity maps
- Rule: reject if improvement only exists in-sample

### 6.4 LLM Copilot (Analytical Only)
**Allowed:**
- Market regime classification (trending / ranging / volatile)
- News summarization → structured signal
- Risk flag generation
- Post-trade analysis reports

**Strictly forbidden:**
- LLM cannot place or modify orders
- LLM cannot override the risk engine
- LLM cannot change live parameters
- All LLM output: JSON-only, schema-validated

### 6.5 Risk Engine (NON-NEGOTIABLE)
Hard limits enforced at execution time:
- Max position size: 5% of portfolio per position
- Max portfolio risk: 15% gross exposure
- Stop loss: 3% per position
- Max daily loss: 2% portfolio
- Max drawdown circuit breaker: 20% (halts all live strategies)
- Max open orders: configurable per strategy
- Kill switch: halts all execution immediately

### 6.6 Execution Engine
- Broker abstraction layer (swap Alpaca ↔ CCXT without strategy changes)
- Order lifecycle management (pending → filled → rejected)
- Idempotency (no duplicate orders)
- Retry logic with backoff
- Audit log for every order

### 6.7 Forward Testing
- Historical replay (event-driven, same engine as live)
- Live paper trading with real-time data
- State persistence across restarts
- Execution drift monitoring (paper vs backtest expectation)

---

## 7. BRANDING & UI

**Product Name:** AlphaSMART
**Tone:** Sharp, technical, no-BS, institutional-grade
**Theme:** Dark-first (trader-native)

**Color Palette:**
| Token | Hex | Use |
|-------|-----|-----|
| Background | `#0B0F14` | Base |
| Accent (Alpha) | `#00FFB2` | Profit, signals, primary CTA |
| Risk | `#FF3B3B` | Drawdown, losses, alerts |
| Neutral | `#8A93A6` | Labels, secondary text |
| Surface | `#131920` | Cards, panels |

**Typography:**
- Headers: Space Grotesk Bold
- Data: JetBrains Mono
- UI Body: Inter

**Dashboard Modules (Priority Order):**

1. **Risk Command Center** — Kill switch, drawdown meter, exposure limits, alerts
2. **Portfolio Overview** — Equity curve, positions, daily PnL, gross/net exposure
3. **Strategy Control Panel** — Enable/disable, capital allocation, status (Running / Paper / Halted)
4. **Backtest Explorer** — Strategy selector, metrics (Sharpe, MaxDD, CAGR), equity curve, trade distribution
5. **Optimization Lab** — Stability map, walk-forward results, overfitting score
6. **Forward Testing Monitor** — Live paper trades, slippage vs expected, latency tracking
7. **Execution Monitor** — Orders (pending/filled/rejected), fill quality, order logs
8. **LLM Insights Panel** — Regime classification, news summary, risk flags, post-trade analysis

---

## 8. STAGE-GATE SYSTEM

A strategy cannot advance without passing the gate. Gates are hardcoded — UI locks deployment buttons.

### Gate 1: Backtest Validation
| Requirement | Threshold |
|-------------|-----------|
| Sharpe Ratio | > 1.2 |
| Max Drawdown | < 25% |
| Trade Count | > 100 |
| Positive Expectancy | Required |
| Beats buy-and-hold | Required |

Failure → rejected or returned to coding phase.

### Gate 2: Optimization Stability
| Requirement | Check |
|-------------|-------|
| OOS performance | Must maintain ≥ 70% of in-sample Sharpe |
| Parameter surface | No narrow peaks (smooth stability region) |
| Walk-forward | Consistent across rolling windows |
| Overfitting score | Within acceptable range |

Failure → flagged "Curve-Fitted", quarantined.

### Gate 3: Forward Test (Paper Trading)
| Requirement | Threshold |
|-------------|-----------|
| Run duration | Minimum 30 days |
| PnL correlation to backtest | > 0.85 |
| Execution drift | Within tolerance |
| System uptime | 7 consecutive days without critical error |
| Signal-to-execution latency | < 500ms |

Failure → rework execution logic, re-run paper test.

### Gate 4: Live Readiness
| Requirement | Check |
|-------------|-------|
| Risk constraints | All validated and tested |
| Kill switch | Tested and confirmed |
| Monitoring | Active (Grafana dashboards live) |
| Capital allocation | Approved (starts at 5% of intended) |
| Audit logs | Confirmed working |

---

## 9. PERFORMANCE METRICS

| Metric | Description |
|--------|-------------|
| CAGR | Compound annual growth rate |
| Sharpe Ratio | Risk-adjusted return (E[R-Rf] / σ) |
| Sortino Ratio | Downside-adjusted return |
| Max Drawdown | Peak-to-trough loss |
| Win Rate | % winning trades |
| Profit Factor | Gross profit / gross loss |
| Exposure | % time in market |
| Turnover | Trade frequency |

---

## 10. REQUIRED INTEGRATIONS

**Market Data (Priority Order):**
1. yfinance — free, stocks (dev/research)
2. Binance / CCXT — crypto (dev + prod)
3. Polygon.io — stocks (prod, paid)

**Execution:**
1. Alpaca API — stocks (paper + live)
2. CCXT — crypto (paper + live via exchange testnet)

**Monitoring:**
- Prometheus + Grafana (metrics + dashboards)
- Sentry (error tracking)

**Notifications:**
- Email alerts (SMTP or SendGrid)
- Optional: Slack webhook for critical events

---

## 11. SECURITY & RELIABILITY

- API keys in `.env` only — never committed
- Paper trading endpoints default until Gate 4 passed
- Order idempotency (no duplicate execution)
- Retry logic with exponential backoff
- Fail-safe shutdown on unhandled exceptions
- Full audit log for every order event
- Secret rotation supported via config layer

---

## 12. FUTURE EXPANSION (Post-Live Only)

Locked until baseline is working and profitable in live:
- Reinforcement learning execution agents
- Multi-exchange arbitrage
- Options strategies
- Copy trading layer
- AI/ML signal models (only after deterministic baseline validated)

---

## 13. IMPLEMENTATION PLAN — PHASED BUILD

---

### PHASE 1: Foundation — Environment + Data Pipeline
**Duration:** Weeks 1–2
**Goal:** Working data layer, project scaffold, safety infrastructure

**Deliverables:**
- Clean project structure (as per §4)
- API keys secured in `.env`, gitignored
- yfinance + CCXT data fetchers
- OHLCV pipeline: fetch → clean → store (PostgreSQL)
- Technical indicators module
- Basic logging (loguru)
- git initialized, CI stub

**Stage Gate:**
- [ ] Data pipeline fetches stocks + crypto OHLCV correctly
- [ ] No API keys in code or git history
- [ ] Logging captures all data events
- [ ] PostgreSQL schema created, data inserts working

---

### PHASE 2: Core Engine — Strategy + Backtest + Risk
**Duration:** Weeks 3–5
**Goal:** Working backtest engine with risk enforcement

**Deliverables:**
- Strategy base class with `generate_signals()` / `size_position()` interface
- 3 strategy implementations: Trend (EMA crossover), Mean Reversion (RSI), Breakout (Donchian)
- Event-driven backtesting engine (custom, not vectorbt — for live parity)
- Fee + slippage + latency modeling
- Full metrics module: Sharpe, Sortino, CAGR, MaxDD, Win Rate, Profit Factor
- Risk engine with hard limits (all from §6.5)
- CLI to run backtests and view results

**Stage Gate (Gate 1):**
- [ ] Backtest runs without lookahead bias
- [ ] All 3 strategies produce valid metrics
- [ ] Risk engine blocks trades exceeding limits
- [ ] At least one strategy meets Sharpe > 1.2, MaxDD < 25%
- [ ] 80% unit test coverage on core engine

---

### PHASE 3: Optimization Lab + LLM Copilot
**Duration:** Weeks 5–7
**Goal:** Walk-forward optimization, overfitting detection, LLM integrated as analytical layer

**Deliverables:**
- Optuna integration for parameter sweeps
- Walk-forward optimization (rolling windows)
- Stability region output (not just best params)
- Overfitting detection score
- LLM module: Claude API wrapper, prompt templates, JSON parser + schema validator
- LLM roles: regime classification, news summarization, risk flagging
- LLM output validation layer (no schema = rejected)

**Stage Gate (Gate 2):**
- [ ] Stability regions identified and visualised
- [ ] OOS Sharpe ≥ 70% of in-sample Sharpe
- [ ] No curve-fitted strategies advance
- [ ] LLM outputs JSON-only, validated against schema
- [ ] LLM has zero write access to orders or risk engine

---

### PHASE 4: Dashboard
**Duration:** Weeks 7–9
**Goal:** Full visibility into all strategies, metrics, and system state

**Deliverables:**
- React + Next.js + TailwindCSS frontend
- FastAPI backend serving data via REST + WebSocket
- TradingView Lightweight Charts for equity curves
- Dashboard modules (§7): Risk Command Center first, then Portfolio, Strategy Control, Backtest Explorer, Optimization Lab
- Real-time WebSocket updates for live data
- LLM Insights Panel (read-only)
- Docker setup for full-stack local dev

**Stage Gate:**
- [ ] All 8 dashboard modules functional
- [ ] Data accuracy: dashboard matches backend calculations to within 0.01%
- [ ] Risk Command Center: kill switch visible and functional
- [ ] Real-time charts update without page refresh

---

### PHASE 5: Forward Testing (Paper Trading)
**Duration:** Weeks 9–11 + 30-day paper run
**Goal:** Validate strategies in real market conditions with fake capital

**Deliverables:**
- Real-time market data ingestion via WebSocket
- Paper trading engine (same execution path as live)
- Alpaca paper API + Binance testnet integration
- State persistence across restarts
- Execution drift monitoring vs backtest expectations
- Forward testing dashboard module active
- Notification system (email alerts for key events)

**Stage Gate (Gate 3):**
- [ ] Paper bot runs 30 consecutive days
- [ ] PnL correlation to backtest > 0.85
- [ ] Latency: signal → decision < 500ms
- [ ] No critical errors for 7 consecutive days
- [ ] Execution drift within tolerance

---

### PHASE 6: Live Deployment
**Duration:** Weeks 12+
**Goal:** Real capital deployment with hardened risk controls

**Deliverables:**
- Live execution via Alpaca (stocks) + CCXT (crypto)
- Risk engine running in enforcement mode (not advisory)
- Capital allocation: start at 5% of intended, scale on proven alpha
- Prometheus + Grafana monitoring live
- Sentry error tracking active
- Full audit log for all order events
- Gradual capital scaling protocol

**Stage Gate (Gate 4):**
- [ ] All risk constraints validated and tested
- [ ] Kill switch tested end-to-end
- [ ] Monitoring dashboards active
- [ ] Paper vs live deviation understood and documented
- [ ] Capital allocation approved

---

## 14. REALITY CHECK

Most systems fail because they:
- Over-optimize in-sample, collapse out-of-sample
- Deploy before forward testing is complete
- Let complexity accumulate before the core works

AlphaSMART wins by:
- Treating every strategy like a product that must prove ROI
- Killing bad strategies early (stage gates enforce this)
- Keeping the LLM in an advisory role, not execution
- Building simplest working version first, adding complexity only when justified

**Rule:** No phase begins without the previous gate passing. No exceptions.
