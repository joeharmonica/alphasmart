"""
Batch backtest runner for AlphaSMART.

Runs N strategies × M symbols × K timeframes in one pass.
Auto-fetches data if not already in the database.
Returns a DataFrame of all results ready for ranking and reporting.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.data.database import Database
from src.data.fetcher import DataFetcher
from src.data.preprocessor import preprocess, PreprocessError
from src.monitoring.logger import logger
from src.strategy.base import Strategy
from src.strategy.risk_manager import RiskConfig


# ---------------------------------------------------------------------------
# Default universe
# ---------------------------------------------------------------------------

DEFAULT_STOCKS = ["AAPL", "MSFT", "SPY"]
DEFAULT_CRYPTOS = ["BTC/USDT", "ETH/USDT"]

# Timeframes per asset class: stocks use daily only (long history);
# crypto uses daily + 4h (Binance provides years of 4h history).
DEFAULT_TIMEFRAME_MAP: dict[str, list[str]] = {
    "stock":  ["1d"],
    "crypto": ["1d", "4h"],
}

# Data fetch parameters per timeframe
_FETCH_PARAMS: dict[str, dict] = {
    "1d":  {"period": "5y",  "limit": 1825},   # ~5 years daily
    "4h":  {"period": "2y",  "limit": 2190},   # ~2 years 4h (2190 = 365*6 bars/day)
    "1wk": {"period": "10y", "limit": 520},
}


# ---------------------------------------------------------------------------
# BatchRunner
# ---------------------------------------------------------------------------

class BatchRunner:
    """
    Run all strategies over all symbols and timeframes.

    Usage:
        runner = BatchRunner(db_url="sqlite:///alphasmart_dev.db")
        df = runner.run_all(strategy_factories)
        # df has one row per (strategy, symbol, timeframe) combination
    """

    def __init__(
        self,
        db_url: str = "sqlite:///alphasmart_dev.db",
        initial_capital: float = 100_000.0,
        stocks: list[str] | None = None,
        cryptos: list[str] | None = None,
        timeframe_map: dict[str, list[str]] | None = None,
    ) -> None:
        self.db_url = db_url
        self.initial_capital = initial_capital
        self.stocks = stocks if stocks is not None else DEFAULT_STOCKS
        self.cryptos = cryptos if cryptos is not None else DEFAULT_CRYPTOS
        self.timeframe_map = timeframe_map if timeframe_map is not None else DEFAULT_TIMEFRAME_MAP
        self._db = Database(db_url)
        self._fetcher = DataFetcher()
        self._engine = BacktestEngine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(
        self,
        strategy_factories: dict[str, Callable[[str], Strategy]],
        fetch_if_missing: bool = True,
        params_override: dict[str, dict] | None = None,
    ) -> pd.DataFrame:
        """
        Run all strategies over all symbols and timeframes.

        Args:
            strategy_factories: dict mapping strategy name → callable(symbol) → Strategy
            fetch_if_missing:   If True, auto-fetch and store data not already in DB
            params_override:    Optional dict keyed by "strategy::symbol::timeframe" →
                                params dict. When present, instantiates the strategy with
                                those params instead of the factory defaults.

        Returns:
            pd.DataFrame with one row per (strategy, symbol, timeframe) combination.
            Columns include all BacktestMetrics fields plus strategy/symbol/timeframe/gate1_pass.
        """
        from src.backtest.optimizer import _make_strategy as _opt_make

        symbols = self.stocks + self.cryptos
        rows: list[dict] = []
        total = sum(
            len(self._timeframes_for(sym)) for sym in symbols
        ) * len(strategy_factories)
        done = 0

        logger.info(
            f"BatchRunner: {len(strategy_factories)} strategies × {len(symbols)} symbols "
            f"= up to {total} backtest runs"
        )

        for symbol in symbols:
            timeframes = self._timeframes_for(symbol)
            for tf in timeframes:
                data = self._load_data(symbol, tf, fetch_if_missing)
                if data is None or len(data) < 50:
                    logger.warning(f"Skipping {symbol}/{tf}: insufficient data ({len(data) if data is not None else 0} bars)")
                    done += len(strategy_factories)
                    continue

                for strat_name, factory in strategy_factories.items():
                    done += 1
                    logger.info(f"[{done}/{total}] {strat_name} | {symbol} | {tf}")
                    try:
                        override_key = f"{strat_name}::{symbol}::{tf}"
                        is_optimized = bool(params_override and override_key in params_override)
                        if is_optimized:
                            strategy = _opt_make(strat_name, symbol, params_override[override_key])
                        else:
                            strategy = factory(symbol)
                        config = BacktestConfig(
                            initial_capital=self.initial_capital,
                            # Allow full-portfolio sizing for backtesting.
                            # Strategies use allocation_pct (0.95) to control
                            # position size; the 5% risk limit is for live trading.
                            risk_config=RiskConfig(max_position_pct=1.0),
                            timeframe=tf,
                        )
                        result = self._engine.run(strategy, data, config)
                        m = result.metrics
                        rows.append({
                            "rank":           0,           # filled in by report
                            "strategy":       strat_name,
                            "symbol":         symbol,
                            "timeframe":      tf,
                            "sharpe":         m.sharpe,
                            "sortino":        m.sortino,
                            "cagr":           m.cagr,
                            "max_drawdown":   m.max_drawdown,
                            "win_rate":       m.win_rate,
                            "profit_factor":  m.profit_factor,
                            "total_return":   m.total_return,
                            "trade_count":    m.trade_count,
                            "exposure":       m.exposure,
                            "avg_trade":      m.avg_trade_return,
                            "best_trade":     m.best_trade,
                            "worst_trade":    m.worst_trade,
                            "n_bars":         m.n_bars,
                            "gate1_pass":     m.passes_gate_1(),
                            "halted":         result.halted,
                            "is_optimized":   is_optimized,
                        })
                    except Exception as exc:
                        logger.error(f"Backtest failed for {strat_name}/{symbol}/{tf}: {exc}")

        if not rows:
            logger.warning("BatchRunner: no results produced (all runs skipped or failed)")
            return pd.DataFrame()

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _timeframes_for(self, symbol: str) -> list[str]:
        """Return the applicable timeframes for a symbol."""
        if self._fetcher.is_crypto(symbol):
            return self.timeframe_map.get("crypto", ["1d"])
        return self.timeframe_map.get("stock", ["1d"])

    def _load_data(
        self, symbol: str, timeframe: str, fetch_if_missing: bool
    ) -> pd.DataFrame | None:
        """Load OHLCV from DB; optionally fetch from exchange if missing."""
        df = self._db.query_ohlcv(symbol, timeframe=timeframe)
        if not df.empty:
            return df

        if not fetch_if_missing:
            logger.warning(f"No data for {symbol}/{timeframe} and fetch_if_missing=False")
            return None

        logger.info(f"Data not in DB for {symbol}/{timeframe} — fetching...")
        params = _FETCH_PARAMS.get(timeframe, {"period": "2y", "limit": 730})
        try:
            raw = self._fetcher.get_ohlcv(
                symbol,
                timeframe=timeframe,
                period=params["period"],
                limit=params["limit"],
            )
            if raw.empty:
                logger.warning(f"Fetch returned empty data for {symbol}/{timeframe}")
                return None

            clean = preprocess(raw, symbol=symbol)
            source = "binance" if self._fetcher.is_crypto(symbol) else "yfinance"
            inserted = self._db.upsert_ohlcv(clean, symbol=symbol, timeframe=timeframe, source=source)
            logger.info(f"Stored {inserted} new bars for {symbol}/{timeframe}")
            return clean

        except PreprocessError as exc:
            logger.error(f"Preprocess failed for {symbol}/{timeframe}: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Fetch failed for {symbol}/{timeframe}: {exc}")
            return None
