"""
AlphaSMART FastAPI server — Phase 4 Dashboard Backend.

Run with:
    cd alphasmart/
    uvicorn api:app --reload --port 8000

Endpoints:
    GET /api/symbols       — list symbols available in DB
    GET /api/strategies    — list available strategy keys
    GET /api/backtest      — run a single backtest (strategy, symbol, timeframe)
    GET /api/summary       — run all strategies × all DB symbols
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make src/ importable when run from any directory
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool

import json as _json

from src.data.database import Database
from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.runner import BatchRunner
from src.strategy.risk_manager import RiskConfig
from src.strategy.trend import EMACrossoverStrategy
from src.strategy.mean_reversion import RSIMeanReversionStrategy
from src.strategy.breakout import DonchianBreakoutStrategy
from src.strategy.macd_momentum import MACDMomentumStrategy
from src.strategy.bollinger_reversion import BollingerReversionStrategy
from src.strategy.triple_screen import TripleScreenStrategy
from src.strategy.atr_breakout import ATRBreakoutStrategy
from src.strategy.zscore_reversion import ZScoreReversionStrategy
from src.strategy.momentum_long import MomentumLongStrategy
from src.strategy.vwap_reversion import VWAPReversionStrategy
from src.strategy.alpha_composite import AlphaCompositeStrategy
from src.strategy.alpha_composite_v2 import AlphaCompositeTrendV2, AlphaMomentumV2
from src.strategy.regime_filter import RegimeFilteredStrategy

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
INITIAL_CAPITAL = 100_000.0
OPT_PARAMS_PATH = _ROOT / "optimized_params.json"


def _load_opt_params() -> dict:
    """Load saved optimized params. Returns {} if file missing or malformed."""
    try:
        return _json.loads(OPT_PARAMS_PATH.read_text())
    except (FileNotFoundError, _json.JSONDecodeError):
        return {}


def _save_opt_params(
    strategy: str,
    symbol: str,
    timeframe: str,
    objective: str,
    params: dict,
    sharpe: float,
    cagr: float,
    max_drawdown: float,
    gate2_pass: bool,
) -> None:
    """Atomically merge a new entry into optimized_params.json."""
    import os
    store = _load_opt_params()
    key = f"{strategy}::{symbol}::{timeframe}"
    store[key] = {
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "objective": objective,
        "params": params,
        "sharpe": sharpe,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "gate2_pass": gate2_pass,
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }
    tmp = OPT_PARAMS_PATH.with_suffix(".tmp")
    tmp.write_text(_json.dumps(store, indent=2))
    os.replace(tmp, OPT_PARAMS_PATH)

def _regime(sym: str, base_factory) -> RegimeFilteredStrategy:
    """Wrap a base strategy with the SPY SMA200 regime filter."""
    try:
        return RegimeFilteredStrategy.from_db(base_factory(sym), DB_URL)
    except ValueError:
        # SPY data not in DB — fall back to unfiltered base strategy
        return base_factory(sym)


STRATEGY_MAP = {
    # --- Original 5 ---
    "ema_crossover":    lambda sym: EMACrossoverStrategy(sym),
    "rsi_reversion":    lambda sym: RSIMeanReversionStrategy(sym),
    "donchian_bo":      lambda sym: DonchianBreakoutStrategy(sym),
    "macd_momentum":    lambda sym: MACDMomentumStrategy(sym),
    "bb_reversion":     lambda sym: BollingerReversionStrategy(sym),
    # --- New trend/momentum ---
    "triple_screen":    lambda sym: TripleScreenStrategy(sym),
    "atr_breakout":     lambda sym: ATRBreakoutStrategy(sym),
    "momentum_long":    lambda sym: MomentumLongStrategy(sym),
    # --- New mean reversion ---
    "zscore_reversion": lambda sym: ZScoreReversionStrategy(sym),
    "vwap_reversion":   lambda sym: VWAPReversionStrategy(sym),
    # --- Proprietary ---
    "alpha_composite":  lambda sym: AlphaCompositeStrategy(sym),
    # --- V2 data-driven composites (Step 4) ---
    "alpha_trend_v2":   lambda sym: AlphaCompositeTrendV2(sym),
    "alpha_momentum_v2": lambda sym: AlphaMomentumV2(sym),
    # --- Regime-filtered variants (Step 3) — SPY SMA200 bear filter ---
    "ema_crossover+regime":    lambda sym: _regime(sym, EMACrossoverStrategy),
    "donchian_bo+regime":      lambda sym: _regime(sym, DonchianBreakoutStrategy),
    "macd_momentum+regime":    lambda sym: _regime(sym, MACDMomentumStrategy),
    "triple_screen+regime":    lambda sym: _regime(sym, TripleScreenStrategy),
    "atr_breakout+regime":     lambda sym: _regime(sym, ATRBreakoutStrategy),
    "momentum_long+regime":    lambda sym: _regime(sym, MomentumLongStrategy),
    "alpha_composite+regime":  lambda sym: _regime(sym, AlphaCompositeStrategy),
    "alpha_trend_v2+regime":   lambda sym: _regime(sym, AlphaCompositeTrendV2),
    "alpha_momentum_v2+regime": lambda sym: _regime(sym, AlphaMomentumV2),
}

STRATEGY_LABELS = {
    # --- Original 5 ---
    "ema_crossover":    "EMA Crossover",
    "rsi_reversion":    "RSI Mean Reversion",
    "donchian_bo":      "Donchian Breakout",
    "macd_momentum":    "MACD Momentum",
    "bb_reversion":     "Bollinger Reversion",
    # --- New trend/momentum ---
    "triple_screen":    "Triple Screen",
    "atr_breakout":     "ATR Breakout",
    "momentum_long":    "Momentum (ROC)",
    # --- New mean reversion ---
    "zscore_reversion": "Z-Score Reversion",
    "vwap_reversion":   "VWAP Reversion",
    # --- Proprietary ---
    "alpha_composite":  "Alpha Composite ✦",
    # --- V2 data-driven composites ---
    "alpha_trend_v2":   "Alpha Trend V2 ✦",
    "alpha_momentum_v2": "Alpha Momentum V2 ✦",
    # --- Regime-filtered variants ---
    "ema_crossover+regime":    "EMA Crossover + Regime",
    "donchian_bo+regime":      "Donchian BO + Regime",
    "macd_momentum+regime":    "MACD Momentum + Regime",
    "triple_screen+regime":    "Triple Screen + Regime",
    "atr_breakout+regime":     "ATR Breakout + Regime",
    "momentum_long+regime":    "Momentum + Regime",
    "alpha_composite+regime":  "Alpha Composite + Regime ✦",
    "alpha_trend_v2+regime":   "Alpha Trend V2 + Regime ✦",
    "alpha_momentum_v2+regime": "Alpha Momentum V2 + Regime ✦",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="AlphaSMART API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/symbols")
def get_symbols():
    """Return all symbols and timeframes currently stored in the database."""
    db = Database(DB_URL)
    rows = db.fetch_status()
    # Serialize datetimes to strings
    serialized = [
        {
            "symbol": r["symbol"],
            "timeframe": r["timeframe"],
            "record_count": r["record_count"],
            "last_fetched_at": str(r["last_fetched_at"]) if r["last_fetched_at"] else None,
        }
        for r in rows
    ]
    return {"symbols": serialized}


@app.get("/api/strategies")
def get_strategies():
    """Return available strategy keys and display labels."""
    return {
        "strategies": [
            {"key": k, "label": STRATEGY_LABELS[k]}
            for k in STRATEGY_MAP
        ]
    }


@app.get("/api/backtest")
async def run_backtest(
    strategy: str = Query(..., description="Strategy key"),
    symbol: str = Query(..., description="Symbol (e.g. AAPL, BTC/USDT)"),
    timeframe: str = Query("1d", description="Bar interval"),
    capital: float = Query(INITIAL_CAPITAL, description="Starting capital"),
):
    """
    Run a single backtest and return metrics, equity curve, fills, and
    a buy-and-hold benchmark for comparison.
    """
    if strategy not in STRATEGY_MAP:
        raise HTTPException(400, f"Unknown strategy '{strategy}'. Valid: {list(STRATEGY_MAP)}")

    result = await run_in_threadpool(
        _run_backtest_sync, strategy, symbol, timeframe, capital
    )
    return result


@app.get("/api/simulate")
async def run_simulate(
    strategy: str = Query(..., description="Strategy key"),
    symbol: str = Query(..., description="Symbol"),
    timeframe: str = Query("1d", description="Bar interval"),
    sim_type: str = Query("block_bootstrap", description="Simulation type: block_bootstrap | jackknife | monte_carlo"),
    n_sims: int = Query(50, description="Number of simulations (block_bootstrap/monte_carlo)"),
    capital: float = Query(INITIAL_CAPITAL, description="Starting capital"),
):
    """
    Run bootstrapping / Monte Carlo simulation for a strategy.
    Returns metric distributions across N synthetic price paths.
    """
    if strategy not in STRATEGY_MAP:
        raise HTTPException(400, f"Unknown strategy '{strategy}'")
    if sim_type not in ("block_bootstrap", "jackknife", "monte_carlo"):
        raise HTTPException(400, f"Invalid sim_type: {sim_type}")

    result = await run_in_threadpool(
        _run_simulate_sync, strategy, symbol, timeframe, sim_type, n_sims, capital
    )
    return result


@app.get("/api/summary")
async def run_summary():
    """
    Run all strategies across all symbols in the database.
    Returns a ranked table sorted by composite score.
    This may take 30–120 seconds depending on data volume.
    """
    result = await run_in_threadpool(_run_summary_sync)
    return result


# ---------------------------------------------------------------------------
# Sync worker functions (run in threadpool so they don't block the event loop)
# ---------------------------------------------------------------------------

def _run_backtest_sync(
    strategy_key: str,
    symbol: str,
    timeframe: str,
    capital: float,
) -> dict:
    db = Database(DB_URL)
    data = db.query_ohlcv(symbol, timeframe=timeframe)

    if data.empty:
        raise HTTPException(
            404,
            f"No data for {symbol}/{timeframe}. "
            f"Run: python main.py fetch {symbol}"
        )

    strat = STRATEGY_MAP[strategy_key](symbol)
    config = BacktestConfig(
        initial_capital=capital,
        risk_config=RiskConfig(max_position_pct=1.0),
        timeframe=timeframe,
    )
    engine = BacktestEngine()
    result = engine.run(strat, data, config)
    m = result.metrics

    # Equity curve: [{date, equity}]
    equity_curve = [
        {"date": str(ts.date()), "equity": round(float(eq), 2)}
        for ts, eq in zip(result.equity_df.index, result.equity_df["equity"])
    ]

    # Buy-and-hold benchmark aligned to equity curve dates
    benchmark = _compute_benchmark(data, result.equity_df.index, capital)

    # Fills: individual order events
    fills = [
        {
            "date": str(f.timestamp.date()),
            "side": f.order.side,
            "price": round(f.fill_price, 4),
            "quantity": round(f.order.quantity, 6),
            "commission": round(f.commission, 4),
        }
        for f in result.fills
    ]

    # Date range metadata
    date_range = ""
    if equity_curve:
        date_range = f"{equity_curve[0]['date']} → {equity_curve[-1]['date']}"

    return {
        "strategy": strategy_key,
        "strategy_label": STRATEGY_LABELS[strategy_key],
        "symbol": symbol,
        "timeframe": timeframe,
        "initial_capital": capital,
        "date_range": date_range,
        "halted": result.halted,
        "halt_reason": result.halt_reason,
        "metrics": {
            "sharpe": m.sharpe,
            "sortino": m.sortino,
            "cagr": m.cagr,
            "max_drawdown": m.max_drawdown,
            "win_rate": m.win_rate,
            "profit_factor": m.profit_factor,
            "total_return": m.total_return,
            "trade_count": m.trade_count,
            "exposure": m.exposure,
            "avg_trade_return": m.avg_trade_return,
            "best_trade": m.best_trade,
            "worst_trade": m.worst_trade,
            "n_bars": m.n_bars,
            "gate1_pass": m.passes_gate_1(),
        },
        "equity_curve": equity_curve,
        "benchmark": benchmark,
        "fills": fills,
    }


def _run_simulate_sync(
    strategy_key: str,
    symbol: str,
    timeframe: str,
    sim_type: str,
    n_sims: int,
    capital: float,
) -> dict:
    from src.backtest.simulation import run_simulation
    from src.backtest.optimizer import PARAM_GRIDS

    db = Database(DB_URL)
    data = db.query_ohlcv(symbol, timeframe=timeframe)
    if data.empty:
        raise HTTPException(404, f"No data for {symbol}/{timeframe}")

    # Use best default params from the grid (first combo) or strategy defaults
    params = {}
    result = run_simulation(
        strategy_key=strategy_key,
        symbol=symbol,
        data=data,
        simulation_type=sim_type,
        n_simulations=n_sims,
        params=params,
        capital=capital,
        timeframe=timeframe,
    )
    return result.to_dict()


def _compute_benchmark(data, equity_index, capital: float) -> list[dict]:
    """Buy-and-hold: invest full capital at first bar, hold to last bar."""
    if data.empty or len(equity_index) == 0:
        return []

    first_close = float(data["close"].iloc[0])
    if first_close <= 0:
        return []

    n_units = capital / first_close

    # Align benchmark to equity curve dates
    benchmark = []
    for ts in equity_index:
        if ts in data.index:
            eq = n_units * float(data.loc[ts, "close"])
        else:
            # Use last known price before this timestamp
            prior = data[data.index <= ts]
            eq = n_units * float(prior["close"].iloc[-1]) if not prior.empty else capital
        benchmark.append({"date": str(ts.date()), "equity": round(eq, 2)})

    return benchmark


def _run_summary_sync() -> dict:
    """Run all strategies × all DB symbols. Returns ranked results."""
    db = Database(DB_URL)
    status_rows = db.fetch_status()

    if not status_rows:
        return {"results": [], "message": "No data in database. Run: python main.py fetch AAPL"}

    # Only use symbols actually in DB
    symbols_in_db = list({r["symbol"] for r in status_rows})
    stocks = [s for s in symbols_in_db if "/" not in s]
    cryptos = [s for s in symbols_in_db if "/" in s]

    # Load any saved optimized params; fall back to defaults for unoptimized combos
    opt_store = _load_opt_params()
    params_override = {k: v["params"] for k, v in opt_store.items()} if opt_store else None

    runner = BatchRunner(
        db_url=DB_URL,
        initial_capital=INITIAL_CAPITAL,
        stocks=stocks if stocks else ["AAPL"],
        cryptos=cryptos if cryptos else [],
    )

    df = runner.run_all(STRATEGY_MAP, fetch_if_missing=False, params_override=params_override)

    if df.empty:
        return {"results": [], "message": "All backtest runs failed or no data available."}

    # Ensure is_optimized column exists
    if "is_optimized" not in df.columns:
        df["is_optimized"] = False

    # Compute composite score (same formula as report.py)
    def composite_score(row) -> float:
        if row.get("total_return", 0) <= 0:
            return 0.0
        return max(0.0,
            float(row.get("sharpe", 0)) * 0.40
            + float(row.get("cagr", 0)) * 10 * 0.30
            + (1 - float(row.get("max_drawdown", 1))) * 0.20
            + float(row.get("win_rate", 0)) * 0.10
        )

    df["score"] = df.apply(composite_score, axis=1)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    df["strategy_label"] = df["strategy"].map(STRATEGY_LABELS)

    # Serialize booleans
    df["gate1_pass"] = df["gate1_pass"].astype(bool)
    df["halted"] = df["halted"].astype(bool)
    df["is_optimized"] = df["is_optimized"].astype(bool)

    records = df.to_dict(orient="records")
    return {
        "results": records,
        "total_runs": len(records),
        "gate1_passes": int(df["gate1_pass"].sum()),
        "opt_params_used": int(df["is_optimized"].sum()),
    }
