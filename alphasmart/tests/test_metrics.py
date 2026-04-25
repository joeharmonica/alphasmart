"""
Unit tests for BacktestMetrics computation.
Tests use deterministic equity curves and fill sequences with known expected values.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
import math

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategy.base import Fill, Order
from src.backtest.metrics import BacktestMetrics, compute_metrics, TRADING_DAYS_PER_YEAR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_equity_df(values: list[float], start="2023-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({"equity": values}, index=dates)


def _make_fill(side: str, qty: float, price: float, commission: float = 0.0,
               timestamp: datetime | None = None, symbol: str = "AAPL") -> Fill:
    if timestamp is None:
        timestamp = datetime(2023, 6, 1, tzinfo=timezone.utc)
    order = Order(symbol=symbol, side=side, quantity=qty)
    return Fill(
        order=order,
        fill_price=price,
        commission=commission,
        slippage_cost=0.0,
        timestamp=timestamp,
    )


def _steady_uptrend(n=252, initial=100_000.0, daily_return=0.001) -> pd.DataFrame:
    """n bars of constant daily return — predictable Sharpe."""
    values = [initial * ((1 + daily_return) ** i) for i in range(n)]
    return _make_equity_df(values)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEmptyMetrics:
    def test_empty_df_returns_zeros(self):
        df = pd.DataFrame(columns=["equity"])
        metrics = compute_metrics(df, [], 100_000)
        assert metrics.sharpe == 0.0
        assert metrics.total_return == 0.0
        assert metrics.trade_count == 0

    def test_single_bar_returns_empty_metrics(self):
        df = _make_equity_df([100_000.0])
        metrics = compute_metrics(df, [], 100_000)
        assert metrics.sharpe == 0.0

    def test_empty_fills_no_trades(self):
        df = _steady_uptrend(n=10)
        metrics = compute_metrics(df, [], 100_000)
        assert metrics.trade_count == 0
        assert metrics.win_rate == 0.0
        assert metrics.profit_factor == 0.0


# ---------------------------------------------------------------------------
# Total return
# ---------------------------------------------------------------------------

class TestTotalReturn:
    def test_positive_return(self):
        df = _make_equity_df([100_000, 100_000, 110_000])
        metrics = compute_metrics(df, [], 100_000)
        assert abs(metrics.total_return - 0.10) < 0.001

    def test_zero_return(self):
        df = _make_equity_df([100_000, 100_000, 100_000])
        metrics = compute_metrics(df, [], 100_000)
        assert abs(metrics.total_return) < 0.001

    def test_negative_return(self):
        df = _make_equity_df([100_000, 95_000, 90_000])
        metrics = compute_metrics(df, [], 100_000)
        assert metrics.total_return < 0


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------

class TestCAGR:
    def test_one_year_known_return(self):
        """252 bars with 10% total return → CAGR ≈ 10%."""
        n = 252
        initial = 100_000.0
        final = 110_000.0
        values = np.linspace(initial, final, n).tolist()
        df = _make_equity_df(values)
        metrics = compute_metrics(df, [], initial)
        # n_bars=252 → years = 251/252 ≈ 0.996 → cagr ≈ total_return^(1/0.996) ≈ 10.04%
        assert abs(metrics.cagr - 0.10) < 0.02

    def test_cagr_formula(self):
        """CAGR = (final/initial)^(252/(n-1)) - 1."""
        n = 253  # 252 trading days
        initial = 100_000.0
        final = 120_000.0
        values = [initial] * (n - 1) + [final]
        df = _make_equity_df(values)
        metrics = compute_metrics(df, [], initial)
        expected = (final / initial) ** (TRADING_DAYS_PER_YEAR / (n - 1)) - 1
        assert abs(metrics.cagr - expected) < 0.001


# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------

class TestSharpe:
    def test_positive_sharpe_for_uptrend(self):
        df = _steady_uptrend(n=252, daily_return=0.001)
        metrics = compute_metrics(df, [], 100_000)
        assert metrics.sharpe > 0

    def test_zero_std_returns_zero_sharpe(self):
        # Perfectly constant equity → std = 0 → Sharpe = 0
        df = _make_equity_df([100_000.0] * 252)
        metrics = compute_metrics(df, [], 100_000)
        assert metrics.sharpe == 0.0

    def test_sharpe_annualised_approx(self):
        """With known daily return and std, verify annualisation."""
        np.random.seed(42)
        n = 252
        mu = 0.001
        sigma = 0.01
        returns = np.random.normal(mu, sigma, n)
        values = [100_000 * np.exp(np.cumsum(returns[:i+1])[-1]) if i > 0 else 100_000
                  for i in range(n)]
        df = _make_equity_df(values)
        metrics = compute_metrics(df, [], 100_000)
        # Expected Sharpe ≈ mu/sigma * sqrt(252) ≈ 0.001/0.01 * 15.87 ≈ 1.587
        # Allow wide tolerance due to realised random noise
        assert metrics.sharpe > 0.5


# ---------------------------------------------------------------------------
# Max Drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_no_drawdown(self):
        """Monotonically increasing equity → max drawdown = 0."""
        values = [100_000 * (1.001 ** i) for i in range(50)]
        df = _make_equity_df(values)
        metrics = compute_metrics(df, [], 100_000)
        assert metrics.max_drawdown < 0.001

    def test_known_drawdown(self):
        """Known peak-to-trough drawdown: 100 → 110 → 90 → 95."""
        values = [100_000, 110_000, 90_000, 95_000]
        df = _make_equity_df(values)
        metrics = compute_metrics(df, [], 100_000)
        # Peak = 110k, trough = 90k → DD = 20k/110k ≈ 0.1818
        assert abs(metrics.max_drawdown - 20_000 / 110_000) < 0.01

    def test_drawdown_fraction_not_percent(self):
        """max_drawdown is a fraction (0–1), not a percentage."""
        values = [100_000, 80_000]
        df = _make_equity_df(values)
        metrics = compute_metrics(df, [], 100_000)
        assert 0.0 <= metrics.max_drawdown <= 1.0


# ---------------------------------------------------------------------------
# Win Rate & Profit Factor
# ---------------------------------------------------------------------------

class TestTradeStats:
    def _make_round_trip(self, buy_price, sell_price, qty=100.0,
                         commission_rate=0.001):
        """One buy + one sell fill pair."""
        buy_ts = datetime(2023, 1, 10, tzinfo=timezone.utc)
        sell_ts = datetime(2023, 1, 20, tzinfo=timezone.utc)
        buy_comm = buy_price * qty * commission_rate
        sell_comm = sell_price * qty * commission_rate
        return [
            _make_fill("buy", qty, buy_price, buy_comm, buy_ts),
            _make_fill("sell", qty, sell_price, sell_comm, sell_ts),
        ]

    def test_single_winning_trade(self):
        fills = self._make_round_trip(buy_price=100.0, sell_price=110.0)
        df = _make_equity_df([100_000] * 25)
        metrics = compute_metrics(df, fills, 100_000)
        assert metrics.trade_count == 1
        assert metrics.win_rate == 1.0
        assert metrics.profit_factor == float("inf") or metrics.profit_factor > 0

    def test_single_losing_trade(self):
        fills = self._make_round_trip(buy_price=110.0, sell_price=100.0)
        df = _make_equity_df([100_000] * 25)
        metrics = compute_metrics(df, fills, 100_000)
        assert metrics.trade_count == 1
        assert metrics.win_rate == 0.0

    def test_mixed_trades_win_rate(self):
        """1 win + 1 loss → win_rate = 0.5."""
        fills = (
            self._make_round_trip(buy_price=100.0, sell_price=110.0,
                                  commission_rate=0.0)
            + self._make_round_trip(buy_price=110.0, sell_price=105.0,
                                    commission_rate=0.0)
        )
        # Fix timestamps so they don't overlap
        fills[0].timestamp = datetime(2023, 1, 1, tzinfo=timezone.utc)
        fills[1].timestamp = datetime(2023, 1, 11, tzinfo=timezone.utc)
        fills[2].timestamp = datetime(2023, 1, 12, tzinfo=timezone.utc)
        fills[3].timestamp = datetime(2023, 1, 22, tzinfo=timezone.utc)
        df = _make_equity_df([100_000] * 30)
        metrics = compute_metrics(df, fills, 100_000)
        assert metrics.trade_count == 2
        assert abs(metrics.win_rate - 0.5) < 0.01

    def test_profit_factor_calculation(self):
        """Verify profit_factor = gross_profit / gross_loss."""
        # Trade 1: buy 100@100, sell 100@110 (no commission)
        # gross_profit = (110*100 - 100*100) / (100*100) * 100*100 = 1000
        # Trade 2: buy 100@110, sell 100@105 (no commission)
        # gross_loss = (105*100 - 110*100) / (110*100) * 110*100 = -500
        fills = (
            self._make_round_trip(buy_price=100.0, sell_price=110.0,
                                  commission_rate=0.0)
            + self._make_round_trip(buy_price=110.0, sell_price=105.0,
                                    commission_rate=0.0)
        )
        fills[0].timestamp = datetime(2023, 1, 1, tzinfo=timezone.utc)
        fills[1].timestamp = datetime(2023, 1, 11, tzinfo=timezone.utc)
        fills[2].timestamp = datetime(2023, 1, 12, tzinfo=timezone.utc)
        fills[3].timestamp = datetime(2023, 1, 22, tzinfo=timezone.utc)
        df = _make_equity_df([100_000] * 30)
        metrics = compute_metrics(df, fills, 100_000)
        assert metrics.profit_factor > 1.0  # winners > losers

    def test_no_fills_zero_stats(self):
        df = _steady_uptrend(n=50)
        metrics = compute_metrics(df, [], 100_000)
        assert metrics.trade_count == 0
        assert metrics.win_rate == 0.0
        assert metrics.profit_factor == 0.0


# ---------------------------------------------------------------------------
# passes_gate_1
# ---------------------------------------------------------------------------

class TestGate1:
    def _metrics(self, sharpe=1.5, max_dd=0.15, trades=120, ret=0.10):
        return BacktestMetrics(
            sharpe=sharpe, sortino=2.0, cagr=0.12, max_drawdown=max_dd,
            win_rate=0.55, profit_factor=1.5, total_return=ret,
            trade_count=trades, exposure=0.6, avg_trade_return=0.01,
            best_trade=0.05, worst_trade=-0.02, n_bars=252,
        )

    def test_passes_when_all_criteria_met(self):
        assert self._metrics().passes_gate_1() is True

    def test_fails_low_sharpe(self):
        assert self._metrics(sharpe=1.1).passes_gate_1() is False

    def test_fails_high_drawdown(self):
        assert self._metrics(max_dd=0.30).passes_gate_1() is False

    def test_fails_insufficient_trades(self):
        assert self._metrics(trades=99).passes_gate_1() is False

    def test_fails_negative_return(self):
        assert self._metrics(ret=-0.01).passes_gate_1() is False

    def test_boundary_sharpe_exactly_1_2(self):
        assert self._metrics(sharpe=1.2).passes_gate_1() is False  # must be > 1.2

    def test_boundary_max_dd_exactly_25pct(self):
        assert self._metrics(max_dd=0.25).passes_gate_1() is False  # must be < 0.25

    def test_boundary_exactly_100_trades(self):
        assert self._metrics(trades=100).passes_gate_1() is True  # ≥ 100
