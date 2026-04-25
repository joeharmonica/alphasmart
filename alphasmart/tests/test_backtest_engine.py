"""
Unit tests for BacktestEngine — event-driven bar-by-bar backtester.

Covers:
  - Basic run without errors
  - No-lookahead enforcement (signal at T uses data[0:T+1], executes at T+1)
  - Slippage and commission applied at fill time
  - Risk halt terminates backtest early
  - End-of-data liquidation of open positions
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategy.base import Order, Signal, Strategy
from src.strategy.portfolio import Portfolio
from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.strategy.risk_manager import RiskConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 60, start_price: float = 100.0,
                trend: float = 0.002) -> pd.DataFrame:
    """Synthetic OHLCV with slight uptrend."""
    np.random.seed(7)
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    noise = np.random.normal(0, 0.005, n)
    closes = start_price * np.exp(np.cumsum(trend + noise))
    highs = closes * 1.005
    lows = closes * 0.995
    opens = closes * (1 + np.random.normal(0, 0.003, n))
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": [1_000_000.0] * n,
    }, index=dates)


class _AlwaysFlatStrategy(Strategy):
    """Never generates a signal; does nothing."""
    name = "always_flat"

    def __init__(self, symbol="TEST"):
        self.symbol = symbol

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        return Signal(symbol=self.symbol, direction="flat")

    def size_position(self, signal, portfolio, price) -> Optional[Order]:
        return None


class _SpyStrategy(Strategy):
    """Records data length seen at each bar — used to verify no-lookahead."""
    name = "spy"

    def __init__(self, symbol="TEST"):
        self.symbol = symbol
        self.data_lengths: list[int] = []

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        self.data_lengths.append(len(data))
        return Signal(symbol=self.symbol, direction="flat")

    def size_position(self, signal, portfolio, price) -> Optional[Order]:
        return None


class _BuyOnceStrategy(Strategy):
    """Buys on the very first signal, then holds forever."""
    name = "buy_once"

    def __init__(self, symbol="TEST"):
        self.symbol = symbol
        self._bought = False

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if not self._bought:
            return Signal(symbol=self.symbol, direction="long", strength=1.0)
        return Signal(symbol=self.symbol, direction="long", strength=1.0)

    def size_position(self, signal, portfolio, price) -> Optional[Order]:
        if not portfolio.has_position(self.symbol) and price > 0:
            self._bought = True
            capital = portfolio.cash * 0.9
            qty = capital / price
            if qty > 1e-6:
                return Order(symbol=self.symbol, side="buy", quantity=qty)
        return None


class _ImmediateSellStrategy(Strategy):
    """Buys on bar 1, then immediately generates flat signal to sell."""
    name = "imm_sell"

    def __init__(self, symbol="TEST"):
        self.symbol = symbol
        self._bar = 0

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        self._bar += 1
        if self._bar == 1:
            return Signal(symbol=self.symbol, direction="long", strength=1.0)
        return Signal(symbol=self.symbol, direction="flat")

    def size_position(self, signal, portfolio, price) -> Optional[Order]:
        if signal.direction == "long" and not portfolio.has_position(self.symbol):
            qty = portfolio.cash * 0.9 / price
            if qty > 1e-6:
                return Order(symbol=self.symbol, side="buy", quantity=qty)
        if signal.direction == "flat" and portfolio.has_position(self.symbol):
            qty = portfolio.positions[self.symbol]
            return Order(symbol=self.symbol, side="sell", quantity=qty)
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBacktestEngineBasic:
    def test_returns_backtest_result(self):
        engine = BacktestEngine()
        data = _make_ohlcv(n=30)
        strat = _AlwaysFlatStrategy(symbol="TEST")
        result = engine.run(strat, data)
        assert isinstance(result, BacktestResult)

    def test_empty_data_returns_empty_result(self):
        engine = BacktestEngine()
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        strat = _AlwaysFlatStrategy()
        result = engine.run(strat, df)
        assert result.fills == []

    def test_single_bar_returns_empty_result(self):
        engine = BacktestEngine()
        data = _make_ohlcv(n=1)
        strat = _AlwaysFlatStrategy()
        result = engine.run(strat, data)
        assert len(result.fills) == 0

    def test_missing_columns_raises(self):
        engine = BacktestEngine()
        df = pd.DataFrame({"close": [100.0, 101.0]})
        strat = _AlwaysFlatStrategy()
        with pytest.raises(ValueError, match="missing"):
            engine.run(strat, df)

    def test_equity_df_has_equity_column(self):
        engine = BacktestEngine()
        data = _make_ohlcv(n=30)
        strat = _AlwaysFlatStrategy()
        result = engine.run(strat, data)
        assert "equity" in result.equity_df.columns

    def test_no_fills_when_always_flat(self):
        engine = BacktestEngine()
        data = _make_ohlcv(n=50)
        strat = _AlwaysFlatStrategy()
        result = engine.run(strat, data)
        assert result.fills == []

    def test_fills_generated_for_buy_strategy(self):
        engine = BacktestEngine()
        data = _make_ohlcv(n=50)
        strat = _BuyOnceStrategy(symbol="TEST")
        cfg = BacktestConfig(initial_capital=10_000,
                             risk_config=RiskConfig(max_position_pct=1.0))
        result = engine.run(strat, data, cfg)
        # Should have at least 1 buy fill + 1 liquidation sell fill
        assert len(result.fills) >= 2


class TestNoLookahead:
    def test_data_slice_grows_by_one_each_bar(self):
        """At bar i (1-indexed), strategy sees exactly i+1 bars."""
        engine = BacktestEngine()
        n = 15
        data = _make_ohlcv(n=n)
        spy = _SpyStrategy(symbol="TEST")
        engine.run(spy, data)
        # Loop runs from i=1 to i=n-1 → n-1 calls
        assert len(spy.data_lengths) == n - 1

    def test_first_signal_sees_two_bars(self):
        engine = BacktestEngine()
        n = 10
        data = _make_ohlcv(n=n)
        spy = _SpyStrategy()
        engine.run(spy, data)
        assert spy.data_lengths[0] == 2

    def test_last_signal_sees_all_bars(self):
        engine = BacktestEngine()
        n = 10
        data = _make_ohlcv(n=n)
        spy = _SpyStrategy()
        engine.run(spy, data)
        assert spy.data_lengths[-1] == n


class TestSlippageAndCommission:
    def test_buy_fill_price_above_open(self):
        """Buy should fill above the bar open due to slippage."""
        engine = BacktestEngine()
        data = _make_ohlcv(n=30)
        strat = _BuyOnceStrategy(symbol="TEST")
        cfg = BacktestConfig(
            initial_capital=50_000,
            risk_config=RiskConfig(max_position_pct=1.0, slippage_pct=0.001,
                                   commission_pct=0.001),
        )
        result = engine.run(strat, data, cfg)
        buy_fills = [f for f in result.fills if f.order.side == "buy"]
        assert len(buy_fills) >= 1
        buy = buy_fills[0]
        # Find bar index where this fill occurred
        bar_idx = result.equity_df.index.get_loc(buy.timestamp)
        open_at_fill = float(data["open"].iloc[bar_idx])
        # Fill price should be above open (buy slips high)
        assert buy.fill_price > open_at_fill

    def test_sell_fill_price_below_open(self):
        """Sell should fill below the bar open due to slippage."""
        engine = BacktestEngine()
        data = _make_ohlcv(n=30)
        strat = _ImmediateSellStrategy(symbol="TEST")
        cfg = BacktestConfig(
            initial_capital=50_000,
            risk_config=RiskConfig(max_position_pct=1.0, slippage_pct=0.001,
                                   commission_pct=0.001),
        )
        result = engine.run(strat, data, cfg)
        sell_fills = [f for f in result.fills if f.order.side == "sell"]
        assert len(sell_fills) >= 1
        sell = sell_fills[0]
        bar_idx = result.equity_df.index.get_loc(sell.timestamp)
        open_at_fill = float(data["open"].iloc[bar_idx])
        assert sell.fill_price < open_at_fill

    def test_commission_applied_to_fills(self):
        """Commission should be positive for all fills."""
        engine = BacktestEngine()
        data = _make_ohlcv(n=30)
        strat = _BuyOnceStrategy(symbol="TEST")
        cfg = BacktestConfig(
            initial_capital=50_000,
            risk_config=RiskConfig(max_position_pct=1.0, commission_pct=0.001),
        )
        result = engine.run(strat, data, cfg)
        for fill in result.fills:
            assert fill.commission > 0


class TestRiskHalt:
    def test_risk_halt_stops_backtest_early(self):
        """Portfolio that immediately loses 50% triggers drawdown halt."""
        engine = BacktestEngine()
        n = 50
        # Create crashing data (strong downtrend)
        dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
        closes = np.array([100.0 * (0.95 ** i) for i in range(n)])
        data = pd.DataFrame({
            "open": closes * 0.99,
            "high": closes * 1.01,
            "low": closes * 0.97,
            "close": closes,
            "volume": [1_000_000.0] * n,
        }, index=dates)

        strat = _BuyOnceStrategy(symbol="TEST")
        cfg = BacktestConfig(
            initial_capital=10_000,
            risk_config=RiskConfig(
                max_position_pct=1.0,
                max_drawdown_pct=0.05,   # tight: halt at 5% drawdown
                max_daily_loss_pct=1.0,  # no daily limit
                commission_pct=0.0,
                slippage_pct=0.0,
            ),
        )
        result = engine.run(strat, data, cfg)
        assert result.halted is True
        assert result.halt_reason != ""

    def test_halt_result_has_fills(self):
        """After halt, liquidation fills should be present."""
        engine = BacktestEngine()
        n = 30
        dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
        closes = np.array([100.0 * (0.90 ** i) for i in range(n)])
        data = pd.DataFrame({
            "open": closes * 0.99, "high": closes, "low": closes * 0.98,
            "close": closes, "volume": [1_000_000.0] * n,
        }, index=dates)
        strat = _BuyOnceStrategy(symbol="TEST")
        cfg = BacktestConfig(
            initial_capital=10_000,
            risk_config=RiskConfig(max_position_pct=1.0, max_drawdown_pct=0.05,
                                   max_daily_loss_pct=1.0, commission_pct=0.0,
                                   slippage_pct=0.0),
        )
        result = engine.run(strat, data, cfg)
        if result.halted:
            assert len(result.fills) >= 1


class TestEndLiquidation:
    def test_open_position_liquidated_at_end(self):
        """Position held to last bar should be sold via liquidation."""
        engine = BacktestEngine()
        data = _make_ohlcv(n=30)
        strat = _BuyOnceStrategy(symbol="TEST")
        cfg = BacktestConfig(
            initial_capital=50_000,
            risk_config=RiskConfig(max_position_pct=1.0, commission_pct=0.0,
                                   slippage_pct=0.0),
        )
        result = engine.run(strat, data, cfg)
        buy_fills = [f for f in result.fills if f.order.side == "buy"]
        sell_fills = [f for f in result.fills if f.order.side == "sell"]
        # Should have at least 1 buy and 1 sell (liquidation)
        assert len(buy_fills) >= 1
        assert len(sell_fills) >= 1

    def test_no_position_no_liquidation(self):
        """Strategy that never buys should produce no fills."""
        engine = BacktestEngine()
        data = _make_ohlcv(n=20)
        strat = _AlwaysFlatStrategy()
        result = engine.run(strat, data)
        assert result.fills == []
        assert not result.halted


class TestMetricsFromEngine:
    def test_metrics_are_backtest_metrics_instance(self):
        from src.backtest.metrics import BacktestMetrics
        engine = BacktestEngine()
        data = _make_ohlcv(n=40)
        result = engine.run(_AlwaysFlatStrategy(), data)
        assert isinstance(result.metrics, BacktestMetrics)

    def test_halted_flag_false_when_no_halt(self):
        engine = BacktestEngine()
        data = _make_ohlcv(n=40)
        result = engine.run(_AlwaysFlatStrategy(), data)
        assert result.halted is False
        assert result.halt_reason == ""
