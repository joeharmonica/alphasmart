# AlphaSMART

> Build. Test. Break. Refine. Deploy alpha that survives reality.

A full-stack algorithmic trading platform: strategy research → backtesting → optimization → forward testing → live deployment, with an LLM analytical copilot and institutional-grade risk controls.

---

## Current Status

**Phase 1 — Foundation** ✅

Data pipeline, preprocessing, indicators, and storage layer are complete and tested.

| Module | Status |
|--------|--------|
| Data Fetcher (stocks + crypto) | ✅ |
| Preprocessor | ✅ |
| Indicators (EMA, RSI, BB, ATR, VWAP, Volume MA) | ✅ |
| Database (SQLite dev / PostgreSQL prod) | ✅ |
| CLI | ✅ |
| Tests (70/70) | ✅ |

---

## Setup

**Requirements:** Python 3.11+ (tested on 3.13)

```bash
cd alphasmart

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and fill in your API keys
cp .env.example .env
# Edit .env — add exchange/broker keys as needed
# yfinance works without any API keys for stock data
```

---

## CLI Usage

### Fetch OHLCV data

```bash
# Stocks (yfinance — no API key needed)
python main.py fetch AAPL
python main.py fetch AAPL --period 2y --timeframe 1d
python main.py fetch SPY --period 5y

# Crypto (Binance public endpoint — no key needed for historical)
python main.py fetch BTC/USDT --timeframe 1d --limit 365
python main.py fetch ETH/USDT --timeframe 4h --limit 500
```

### View indicators for a stored symbol

```bash
python main.py indicators AAPL
python main.py indicators BTC/USDT
```

### Check what's stored

```bash
python main.py db-status
```

---

## Run Tests

```bash
# All tests
python -m pytest tests/ -v

# With coverage report
python -m pytest tests/ --cov=src --cov-report=term-missing

# Individual test modules
python -m pytest tests/test_preprocessor.py -v
python -m pytest tests/test_indicators.py -v
python -m pytest tests/test_database.py -v
python -m pytest tests/test_pipeline.py -v
```

**Phase 1 test suite:** 70 tests, 0 failures. No network calls required.

---

## Project Structure

```
alphasmart/
├── config/
│   ├── settings.yaml          # API keys, risk params, DB config
│   └── (secrets in .env only — never commit)
├── src/
│   ├── data/
│   │   ├── fetcher.py         # StockDataFetcher, CryptoDataFetcher, DataFetcher
│   │   ├── preprocessor.py    # Clean, validate, normalise OHLCV
│   │   ├── indicators.py      # EMA, RSI, Bollinger Bands, ATR, VWAP, Volume MA
│   │   └── database.py        # SQLAlchemy ORM, OHLCV CRUD, metadata tracking
│   ├── monitoring/
│   │   └── logger.py          # loguru logger (console + rotating file)
│   └── (strategy/, backtest/, execution/, llm/ — Phase 2+)
├── tests/
│   ├── conftest.py            # Shared fixtures, synthetic data generator
│   ├── test_preprocessor.py   # 14 unit tests
│   ├── test_indicators.py     # 26 unit tests
│   ├── test_database.py       # 15 unit tests
│   └── test_pipeline.py       # 6 end-to-end tests
├── tasks/
│   └── todo.md                # Build plan + stage gate checklist
├── main.py                    # CLI entrypoint
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  DATA LAYER         Market feeds, OHLCV, news, on-chain  │
│  ─────────────►     yfinance / ccxt / Polygon.io          │ ← Phase 1 ✅
├──────────────────────────────────────────────────────────┤
│  LLM COPILOT        Regime analysis → structured signal  │
│  ─────────────►     Claude API (JSON-only output)         │ ← Phase 3
├──────────────────────────────────────────────────────────┤
│  STRATEGY ENGINE    Signal generation, position sizing   │
│  ─────────────►     Multi-strategy, deterministic         │ ← Phase 2
├──────────────────────────────────────────────────────────┤
│  BACKTEST / FWD     Vectorized research + event-driven   │
│  ─────────────►     simulation, walk-forward validation   │ ← Phase 2
├──────────────────────────────────────────────────────────┤
│  RISK ENGINE        Hard limits, kill switches           │
│  ─────────────►     NON-NEGOTIABLE — blocks execution     │ ← Phase 2
├──────────────────────────────────────────────────────────┤
│  EXECUTION LAYER    Broker abstraction, order lifecycle  │
│  ─────────────►     Paper → Live (Alpaca / CCXT)          │ ← Phase 5
├──────────────────────────────────────────────────────────┤
│  MONITORING         Dashboard, logs, P&L, alerts         │
│  ─────────────►     React UI + Prometheus + Grafana       │ ← Phase 4
└──────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.13 |
| LLM | Anthropic Claude API (Phase 3) |
| Market Data | yfinance (dev) → Polygon.io (prod) / CCXT |
| Backtesting | VectorBT + custom event-driven engine |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy |
| Cache | Redis (Phase 4+) |
| Execution | Alpaca (stocks) / CCXT (crypto) |
| API | FastAPI (Phase 4) |
| Frontend | React + Next.js + TailwindCSS (Phase 4) |
| Charts | TradingView Lightweight Charts |
| Infra | Docker |
| Monitoring | Prometheus + Grafana |

---

## Phase Roadmap

| Phase | Scope | Gate |
|-------|-------|------|
| **1 — Foundation** ✅ | Data pipeline, indicators, DB, CLI | Pipeline fetches + stores correctly |
| 2 — Core Engine | Strategy abstraction, backtester, risk engine | Sharpe > 1.2, MaxDD < 25% on 3 strategies |
| 3 — Optimization + LLM | Walk-forward, Optuna, Claude copilot | OOS Sharpe ≥ 70% of in-sample |
| 4 — Dashboard | React UI, FastAPI, WebSocket charts | Full visibility, kill switch live |
| 5 — Forward Testing | Paper trading, 30-day run | PnL correlation to backtest > 0.85 |
| 6 — Live Deployment | Real capital, 5% allocation → scale | Kill switch tested, monitoring active |

---

## Stage Gate (Phase 1)

- [x] Data pipeline fetches stocks + crypto OHLCV correctly
- [x] No API keys in code or git history
- [x] Logging captures all data events
- [x] SQLite schema created, data inserts working
- [x] All unit tests pass (70/70)
- [x] CLI functional (fetch, indicators, db-status)

---

## Safety Rules

1. **Never commit `.env`** — it's in `.gitignore`, keep it that way
2. **Paper trading by default** — Alpaca paper URL is the default until Gate 4 passes
3. **Risk engine is non-negotiable** — it blocks execution, not just alerts
4. **LLM advises only** — JSON output, schema-validated, zero write access to orders

---

## Development

```bash
# Run tests
python -m pytest tests/ -v --cov=src

# Lint (if ruff installed)
ruff check src/ tests/
```
