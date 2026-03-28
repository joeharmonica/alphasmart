"""Unit tests for Portfolio state management."""
import sys
from pathlib import Path
from datetime import datetime, timezone, date

import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategy.base import Fill, Order
from src.strategy.portfolio import Portfolio


def _make_fill(side: str, qty: float, price: float, symbol: str = "AAPL",
               commission: float | None = None, timestamp=None) -> Fill:
    order = Order(symbol=symbol, side=side, quantity=qty)
    if commission is None:
        commission = price * qty * 0.001
    if timestamp is None:
        timestamp = datetime(2023, 6, 1, tzinfo=timezone.utc)
    return Fill(
        order=order,
        fill_price=price,
        commission=commission,
        slippage_cost=0.0,
        timestamp=timestamp,
    )


class TestPortfolioInit:
    def test_initial_cash(self):
        p = Portfolio(10_000)
        assert p.cash == 10_000

    def test_initial_no_positions(self):
        p = Portfolio(10_000)
        assert p.positions == {}

    def test_initial_no_fills(self):
        p = Portfolio(10_000)
        assert p.fills == []

    def test_peak_equity_starts_at_capital(self):
        p = Portfolio(50_000)
        assert p.peak_equity == 50_000

    def test_invalid_capital_raises(self):
        with pytest.raises(ValueError):
            Portfolio(0)

    def test_negative_capital_raises(self):
        with pytest.raises(ValueError):
            Portfolio(-100)


class TestPortfolioEquity:
    def test_equity_no_positions(self):
        p = Portfolio(10_000)
        assert p.equity({}) == 10_000

    def test_equity_with_position(self):
        p = Portfolio(10_000)
        fill = _make_fill("buy", qty=10.0, price=100.0, commission=1.0)
        p.apply_fill(fill)
        # cash = 10000 - (100*10 + 1) = 10000 - 1001 = 8999
        # equity = 8999 + 10 * 110 = 8999 + 1100 = 10099
        assert abs(p.equity({"AAPL": 110.0}) - 10_099.0) < 0.01

    def test_equity_missing_price_treated_as_zero(self):
        p = Portfolio(10_000)
        fill = _make_fill("buy", qty=10.0, price=100.0, commission=0.0)
        p.apply_fill(fill)
        # If price not provided, position contributes 0
        assert p.equity({}) == p.cash

    def test_position_value(self):
        p = Portfolio(10_000)
        fill = _make_fill("buy", qty=5.0, price=200.0, commission=0.0)
        p.apply_fill(fill)
        assert p.position_value("AAPL", 200.0) == 1000.0

    def test_position_value_no_position(self):
        p = Portfolio(10_000)
        assert p.position_value("AAPL", 100.0) == 0.0


class TestPortfolioApplyFill:
    def test_buy_increases_position(self):
        p = Portfolio(10_000)
        fill = _make_fill("buy", qty=10.0, price=100.0, commission=0.0)
        p.apply_fill(fill)
        assert p.positions["AAPL"] == 10.0

    def test_buy_decreases_cash(self):
        p = Portfolio(10_000)
        fill = _make_fill("buy", qty=10.0, price=100.0, commission=1.0)
        p.apply_fill(fill)
        assert abs(p.cash - (10_000 - 1001.0)) < 0.01

    def test_sell_decreases_position(self):
        p = Portfolio(10_000)
        p.apply_fill(_make_fill("buy", qty=10.0, price=100.0, commission=0.0))
        p.apply_fill(_make_fill("sell", qty=5.0, price=110.0, commission=0.0))
        assert p.positions["AAPL"] == 5.0

    def test_sell_increases_cash(self):
        p = Portfolio(10_000)
        p.apply_fill(_make_fill("buy", qty=10.0, price=100.0, commission=0.0))
        cash_after_buy = p.cash
        p.apply_fill(_make_fill("sell", qty=10.0, price=110.0, commission=1.1))
        assert p.cash > cash_after_buy

    def test_full_sell_removes_position(self):
        p = Portfolio(10_000)
        p.apply_fill(_make_fill("buy", qty=10.0, price=100.0, commission=0.0))
        p.apply_fill(_make_fill("sell", qty=10.0, price=100.0, commission=0.0))
        assert "AAPL" not in p.positions

    def test_fill_recorded(self):
        p = Portfolio(10_000)
        p.apply_fill(_make_fill("buy", qty=10.0, price=100.0))
        assert len(p.fills) == 1

    def test_multiple_fills_accumulated(self):
        p = Portfolio(50_000)
        p.apply_fill(_make_fill("buy", qty=10.0, price=100.0, commission=0.0))
        p.apply_fill(_make_fill("buy", qty=5.0, price=105.0, commission=0.0,
                                symbol="MSFT"))
        assert "AAPL" in p.positions
        assert "MSFT" in p.positions
        assert len(p.fills) == 2


class TestPortfolioDrawdown:
    def test_drawdown_at_inception(self):
        p = Portfolio(10_000)
        assert p.drawdown({}) == 0.0

    def test_drawdown_after_equity_rises(self):
        p = Portfolio(10_000)
        p.peak_equity = 12_000
        # equity is still 10_000 (in cash)
        dd = p.drawdown({})
        assert abs(dd - 2_000 / 12_000) < 1e-6

    def test_drawdown_never_negative(self):
        p = Portfolio(10_000)
        p.peak_equity = 8_000  # Shouldn't happen, but guard
        # Current equity > peak → drawdown = 0 (clamped)
        assert p.drawdown({}) == 0.0

    def test_drawdown_with_position_loss(self):
        p = Portfolio(10_000)
        fill = _make_fill("buy", qty=50.0, price=100.0, commission=0.0)
        p.apply_fill(fill)
        # peak_equity is still 10_000 (no record_equity called yet)
        prices = {"AAPL": 80.0}
        # equity = 5000 + 50*80 = 5000 + 4000 = 9000
        # drawdown = (10000 - 9000) / 10000 = 0.10
        assert abs(p.drawdown(prices) - 0.10) < 0.01


class TestPortfolioDailyPnl:
    def test_daily_pnl_same_equity(self):
        p = Portfolio(10_000)
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
        p.record_equity(ts, {})
        assert abs(p.daily_pnl_pct({})) < 1e-9

    def test_daily_pnl_after_gain(self):
        p = Portfolio(10_000)
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
        p.record_equity(ts, {})
        # Give portfolio a position that's worth more
        p.cash = 11_000
        assert abs(p.daily_pnl_pct({}) - 0.10) < 1e-6


class TestPortfolioRecordEquity:
    def test_record_equity_updates_peak(self):
        p = Portfolio(10_000)
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
        p.cash = 15_000
        p.record_equity(ts, {})
        assert p.peak_equity == 15_000

    def test_to_equity_df_empty(self):
        p = Portfolio(10_000)
        df = p.to_equity_df()
        assert df.empty
        assert "equity" in df.columns

    def test_to_equity_df_shape(self):
        p = Portfolio(10_000)
        for i in range(5):
            ts = datetime(2023, 1, i + 1, tzinfo=timezone.utc)
            p.record_equity(ts, {})
        df = p.to_equity_df()
        assert len(df) == 5
        assert "equity" in df.columns
        assert isinstance(df.index, pd.DatetimeIndex)


class TestPortfolioHelpers:
    def test_has_position_true(self):
        p = Portfolio(10_000)
        p.apply_fill(_make_fill("buy", qty=5.0, price=100.0, commission=0.0))
        assert p.has_position("AAPL")

    def test_has_position_false(self):
        p = Portfolio(10_000)
        assert not p.has_position("AAPL")

    def test_is_long(self):
        p = Portfolio(10_000)
        p.apply_fill(_make_fill("buy", qty=5.0, price=100.0, commission=0.0))
        assert p.is_long("AAPL")

    def test_total_return(self):
        p = Portfolio(10_000)
        p.cash = 11_000
        assert abs(p.total_return({}) - 0.10) < 1e-6

    def test_summary_dict_keys(self):
        p = Portfolio(10_000)
        s = p.summary({})
        assert "cash" in s
        assert "equity" in s
        assert "fills" in s
