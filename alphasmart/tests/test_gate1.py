"""
Gate 1 end-to-end test.
Runs all 3 strategies through the full backtest pipeline and verifies:
  1. All strategies complete without error and return valid BacktestResult
  2. Metrics are computed (sharpe, drawdown, trade_count, total_return present)
  3. passes_gate_1() logic evaluates correctly
  4. At least one strategy passes Gate 1 on a crafted dataset

Crafted dataset design (make_gate1_data):
  - 1200 bars, sine-wave oscillation (period 8) with upward drift
  - Uses RSI(4) strategy with rapid oversold/overbought cycling
  - Each 8-bar cycle gives ~1 completed round-trip → ~150 trades > 100 ✓
  - Buying at troughs, selling at peaks → profitable → Sharpe > 1.2 ✓
  - Small amplitude + cash periods → MaxDD < 25% ✓
  - Upward drift → total_return > 0 ✓
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.backtest.metrics import BacktestMetrics
from src.strategy.risk_manager import RiskConfig
from src.strategy.trend import EMACrossoverStrategy
from src.strategy.mean_reversion import RSIMeanReversionStrategy
from src.strategy.breakout import DonchianBreakoutStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SYMBOL = "SYNTH"


def make_random_data(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Moderate random-walk data for smoke tests."""
    np.random.seed(seed)
    dates = pd.date_range("2018-01-01", periods=n, freq="D", tz="UTC")
    returns = np.random.normal(0.0005, 0.015, n)
    closes = 100.0 * np.exp(np.cumsum(returns))
    noise = np.abs(np.random.normal(0, 0.005, n))
    highs = closes * (1 + noise)
    lows = closes * (1 - noise)
    opens = closes * (1 + np.random.normal(0, 0.003, n))
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": [1_000_000.0] * n,
    }, index=dates)


def make_gate1_data(n: int = 1200) -> pd.DataFrame:
    """
    Crafted sine-wave dataset optimised for Gate 1 passage with RSI(4).

    Structure: price = trend + amplitude * sin(2π*t/period)
      - trend rises slowly (ensures total_return > 0)
      - oscillation creates regular oversold/overbought RSI signals
      - ~n/period completed round-trips expected (target ≥ 100)
    """
    t = np.arange(n)
    period = 8
    trend = 100.0 + t * 0.04           # gentle upward drift
    amplitude = 12.0                   # large enough to push RSI(4) to extremes
    prices = trend + amplitude * np.sin(2 * np.pi * t / period)

    # Ensure all prices are positive
    prices = np.maximum(prices, 1.0)
    dates = pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC")
    noise_h = np.abs(np.random.default_rng(0).normal(0, 0.2, n))
    noise_l = np.abs(np.random.default_rng(1).normal(0, 0.2, n))
    highs = prices + noise_h
    lows = prices - noise_l
    opens = prices * 0.999
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": prices,
        "volume": [1_000_000.0] * n,
    }, index=dates)


def _permissive_config(capital: float = 100_000) -> BacktestConfig:
    """Config with generous risk limits so strategy isn't halted early."""
    return BacktestConfig(
        initial_capital=capital,
        risk_config=RiskConfig(
            max_position_pct=1.0,
            max_daily_loss_pct=0.50,
            max_drawdown_pct=0.90,
            max_open_positions=10,
            commission_pct=0.001,
            slippage_pct=0.0005,
        ),
    )


# ---------------------------------------------------------------------------
# Smoke tests: all 3 strategies run without error
# ---------------------------------------------------------------------------

class TestAllStrategiesRun:
    def test_ema_crossover_completes(self):
        engine = BacktestEngine()
        data = make_random_data(n=300)
        strat = EMACrossoverStrategy(symbol=SYMBOL, fast_period=5, slow_period=10)
        result = engine.run(strat, data, _permissive_config())
        assert isinstance(result, BacktestResult)
        assert isinstance(result.metrics, BacktestMetrics)
        assert not result.halted

    def test_rsi_mean_reversion_completes(self):
        engine = BacktestEngine()
        data = make_random_data(n=300)
        strat = RSIMeanReversionStrategy(symbol=SYMBOL, rsi_period=14)
        result = engine.run(strat, data, _permissive_config())
        assert isinstance(result, BacktestResult)
        assert isinstance(result.metrics, BacktestMetrics)

    def test_donchian_breakout_completes(self):
        engine = BacktestEngine()
        data = make_random_data(n=300)
        strat = DonchianBreakoutStrategy(symbol=SYMBOL, period=20)
        result = engine.run(strat, data, _permissive_config())
        assert isinstance(result, BacktestResult)
        assert isinstance(result.metrics, BacktestMetrics)


# ---------------------------------------------------------------------------
# Metrics validity: all fields are finite and in expected ranges
# ---------------------------------------------------------------------------

class TestMetricsValidity:
    @pytest.fixture(autouse=True)
    def _setup(self):
        engine = BacktestEngine()
        data = make_random_data(n=300)
        strat = EMACrossoverStrategy(symbol=SYMBOL, fast_period=5, slow_period=10)
        self.result = engine.run(strat, data, _permissive_config())

    def test_sharpe_is_finite(self):
        import math
        assert math.isfinite(self.result.metrics.sharpe)

    def test_max_drawdown_in_range(self):
        assert 0.0 <= self.result.metrics.max_drawdown <= 1.0

    def test_win_rate_in_range(self):
        assert 0.0 <= self.result.metrics.win_rate <= 1.0

    def test_exposure_in_range(self):
        assert 0.0 <= self.result.metrics.exposure <= 1.0

    def test_trade_count_non_negative(self):
        assert self.result.metrics.trade_count >= 0

    def test_equity_df_non_empty(self):
        assert not self.result.equity_df.empty


# ---------------------------------------------------------------------------
# Gate 1 logic: passes_gate_1() correctly evaluates all criteria
# ---------------------------------------------------------------------------

class TestGate1Logic:
    def test_passes_gate1_when_all_criteria_met(self):
        m = BacktestMetrics(
            sharpe=1.5, sortino=2.0, cagr=0.15, max_drawdown=0.10,
            win_rate=0.55, profit_factor=1.8, total_return=0.15,
            trade_count=120, exposure=0.6, avg_trade_return=0.01,
            best_trade=0.08, worst_trade=-0.03, n_bars=500,
        )
        assert m.passes_gate_1() is True

    def test_fails_gate1_low_sharpe(self):
        m = BacktestMetrics(
            sharpe=1.0, sortino=1.5, cagr=0.10, max_drawdown=0.10,
            win_rate=0.55, profit_factor=1.5, total_return=0.10,
            trade_count=120, exposure=0.5, avg_trade_return=0.01,
            best_trade=0.05, worst_trade=-0.02, n_bars=500,
        )
        assert m.passes_gate_1() is False

    def test_fails_gate1_high_drawdown(self):
        m = BacktestMetrics(
            sharpe=1.5, sortino=2.0, cagr=0.15, max_drawdown=0.30,
            win_rate=0.55, profit_factor=1.5, total_return=0.15,
            trade_count=120, exposure=0.5, avg_trade_return=0.01,
            best_trade=0.05, worst_trade=-0.02, n_bars=500,
        )
        assert m.passes_gate_1() is False

    def test_fails_gate1_too_few_trades(self):
        m = BacktestMetrics(
            sharpe=1.5, sortino=2.0, cagr=0.15, max_drawdown=0.10,
            win_rate=0.55, profit_factor=1.5, total_return=0.15,
            trade_count=50, exposure=0.5, avg_trade_return=0.01,
            best_trade=0.05, worst_trade=-0.02, n_bars=500,
        )
        assert m.passes_gate_1() is False

    def test_fails_gate1_negative_return(self):
        m = BacktestMetrics(
            sharpe=1.5, sortino=2.0, cagr=-0.05, max_drawdown=0.10,
            win_rate=0.55, profit_factor=1.5, total_return=-0.05,
            trade_count=120, exposure=0.5, avg_trade_return=-0.001,
            best_trade=0.05, worst_trade=-0.02, n_bars=500,
        )
        assert m.passes_gate_1() is False


# ---------------------------------------------------------------------------
# End-to-end Gate 1 passage: at least one strategy passes on crafted data
# ---------------------------------------------------------------------------

class TestGate1EndToEnd:
    """
    Verify that at least one strategy achieves Gate 1 on a dataset designed
    to produce consistent buy-low/sell-high round-trips.

    Uses RSI(4) on a sine-wave price series:
      - Short RSI period captures rapid oscillations
      - Regular oversold/overbought → 100+ completed trades
      - Buying at troughs, selling at peaks → strong Sharpe
    """

    def test_at_least_one_strategy_passes_gate1(self):
        data = make_gate1_data(n=1200)
        engine = BacktestEngine()
        cfg = _permissive_config(capital=100_000)

        strategies = [
            RSIMeanReversionStrategy(symbol=SYMBOL, rsi_period=4,
                                      oversold=30, overbought=70),
            EMACrossoverStrategy(symbol=SYMBOL, fast_period=3, slow_period=6),
            DonchianBreakoutStrategy(symbol=SYMBOL, period=4),
        ]

        results = [engine.run(s, data, cfg) for s in strategies]
        gate1_passed = [r.metrics.passes_gate_1() for r in results]

        # Print diagnostics if none pass (helpful for debugging)
        if not any(gate1_passed):
            for strat, result in zip(strategies, results):
                m = result.metrics
                print(f"\n{strat.name}: Sharpe={m.sharpe:.2f}, "
                      f"MaxDD={m.max_drawdown:.2%}, "
                      f"Trades={m.trade_count}, Return={m.total_return:.2%}")

        assert any(gate1_passed), (
            "No strategy passed Gate 1 on crafted dataset. "
            "Expected RSI(4) on sine-wave data to pass. "
            "Check make_gate1_data() or strategy implementations."
        )

    def test_rsi_generates_enough_trades_on_crafted_data(self):
        """Verify the crafted data produces ≥ 100 trades for RSI(4)."""
        data = make_gate1_data(n=1200)
        engine = BacktestEngine()
        cfg = _permissive_config()
        strat = RSIMeanReversionStrategy(symbol=SYMBOL, rsi_period=4,
                                          oversold=30, overbought=70)
        result = engine.run(strat, data, cfg)
        assert result.metrics.trade_count >= 100, (
            f"Expected ≥ 100 trades, got {result.metrics.trade_count}. "
            "Increase n or adjust sine-wave parameters."
        )
