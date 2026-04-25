"""Unit tests for RiskEngine — order validation, halt detection, cost modeling."""
import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategy.base import Fill, Order
from src.strategy.portfolio import Portfolio
from src.strategy.risk_manager import RiskConfig, RiskEngine


def _make_portfolio(capital: float = 100_000) -> Portfolio:
    return Portfolio(capital)


def _buy_position(portfolio: Portfolio, symbol: str, qty: float, price: float) -> None:
    """Helper: put a buy fill into portfolio (no commission)."""
    order = Order(symbol=symbol, side="buy", quantity=qty)
    fill = Fill(
        order=order,
        fill_price=price,
        commission=0.0,
        slippage_cost=0.0,
        timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
    )
    portfolio.apply_fill(fill)


class TestRiskConfig:
    def test_defaults(self):
        cfg = RiskConfig()
        assert cfg.max_position_pct == 0.05
        assert cfg.max_daily_loss_pct == 0.02
        assert cfg.max_drawdown_pct == 0.20
        assert cfg.max_open_positions == 10
        assert cfg.commission_pct == 0.001
        assert cfg.slippage_pct == 0.0005

    def test_custom_config(self):
        cfg = RiskConfig(max_position_pct=0.10, commission_pct=0.002)
        assert cfg.max_position_pct == 0.10
        assert cfg.commission_pct == 0.002


class TestCheckOrder:
    def test_valid_buy_allowed(self):
        engine = RiskEngine(RiskConfig(max_position_pct=0.10))
        portfolio = _make_portfolio(100_000)
        order = Order(symbol="AAPL", side="buy", quantity=50.0)  # 50 * 100 = 5000 = 5% ✓
        allowed, reason = engine.check_order(order, portfolio, 100.0)
        assert allowed is True
        assert reason == ""

    def test_invalid_price_blocked(self):
        engine = RiskEngine()
        portfolio = _make_portfolio(100_000)
        order = Order(symbol="AAPL", side="buy", quantity=10.0)
        allowed, reason = engine.check_order(order, portfolio, 0.0)
        assert allowed is False
        assert "price" in reason.lower()

    def test_negative_price_blocked(self):
        engine = RiskEngine()
        portfolio = _make_portfolio(100_000)
        order = Order(symbol="AAPL", side="buy", quantity=10.0)
        allowed, reason = engine.check_order(order, portfolio, -50.0)
        assert allowed is False

    def test_oversized_order_blocked(self):
        """Order value exceeds max_position_pct * 1.1 of equity."""
        cfg = RiskConfig(max_position_pct=0.05)
        engine = RiskEngine(cfg)
        portfolio = _make_portfolio(100_000)
        # 10% of 100k = 10000, max is 5% * 1.1 = 5.5%, so >5500 should be blocked
        order = Order(symbol="AAPL", side="buy", quantity=100.0)  # 100*100 = 10000 = 10% → blocked
        allowed, reason = engine.check_order(order, portfolio, 100.0)
        assert allowed is False
        assert "exceed" in reason.lower() or "max position" in reason.lower()

    def test_insufficient_cash_blocked(self):
        engine = RiskEngine(RiskConfig(max_position_pct=1.0))  # no size limit
        portfolio = _make_portfolio(1_000)
        # 10.5 shares @ $100 = $1050 = 105% of equity < 110% tolerance → passes position check
        # But total cost ($1051+) exceeds available cash ($1000) → blocked by cash check
        order = Order(symbol="AAPL", side="buy", quantity=10.5)
        allowed, reason = engine.check_order(order, portfolio, 100.0)
        assert allowed is False
        assert "cash" in reason.lower() or "insufficient" in reason.lower()

    def test_sell_allowed_without_cash_check(self):
        """Sells are not blocked by cash check."""
        engine = RiskEngine(RiskConfig(max_position_pct=1.0))
        portfolio = _make_portfolio(1_000)
        _buy_position(portfolio, "AAPL", qty=5.0, price=100.0)
        order = Order(symbol="AAPL", side="sell", quantity=5.0)
        allowed, _ = engine.check_order(order, portfolio, 100.0)
        assert allowed is True

    def test_max_open_positions_blocked(self):
        """Can't open new symbol when at max positions."""
        cfg = RiskConfig(max_open_positions=2, max_position_pct=1.0)
        engine = RiskEngine(cfg)
        portfolio = _make_portfolio(100_000)
        # Fill 2 positions
        _buy_position(portfolio, "AAPL", qty=1.0, price=100.0)
        _buy_position(portfolio, "MSFT", qty=1.0, price=100.0)
        # Try to open a 3rd
        order = Order(symbol="GOOG", side="buy", quantity=0.01)
        allowed, reason = engine.check_order(order, portfolio, 100.0)
        assert allowed is False
        assert "positions" in reason.lower()

    def test_adding_to_existing_position_allowed_at_max(self):
        """Can add to existing position even when at max_open_positions."""
        cfg = RiskConfig(max_open_positions=1, max_position_pct=1.0,
                         commission_pct=0.0, slippage_pct=0.0)
        engine = RiskEngine(cfg)
        portfolio = _make_portfolio(100_000)
        _buy_position(portfolio, "AAPL", qty=1.0, price=100.0)
        order = Order(symbol="AAPL", side="buy", quantity=0.01)
        allowed, _ = engine.check_order(order, portfolio, 100.0)
        assert allowed is True


class TestCheckHalt:
    def test_all_clear(self):
        engine = RiskEngine()
        portfolio = _make_portfolio(100_000)
        halt, reason = engine.check_halt(portfolio, {})
        assert halt is False
        assert reason == ""

    def test_daily_loss_triggers_halt(self):
        engine = RiskEngine(RiskConfig(max_daily_loss_pct=0.02))
        portfolio = _make_portfolio(100_000)
        # Simulate a 3% day loss
        ts = datetime(2023, 6, 1, tzinfo=timezone.utc)
        portfolio.record_equity(ts, {})  # day starts at 100k
        portfolio.cash = 96_000  # 4% loss today
        halt, reason = engine.check_halt(portfolio, {})
        assert halt is True
        assert "daily loss" in reason.lower() or "loss" in reason.lower()

    def test_drawdown_triggers_halt(self):
        # Set daily loss limit very high so only drawdown check fires
        engine = RiskEngine(RiskConfig(max_drawdown_pct=0.20, max_daily_loss_pct=0.99))
        portfolio = _make_portfolio(100_000)
        portfolio.peak_equity = 100_000
        portfolio.cash = 75_000  # 25% drawdown > 20% limit
        halt, reason = engine.check_halt(portfolio, {})
        assert halt is True
        assert "drawdown" in reason.lower()

    def test_small_drawdown_no_halt(self):
        engine = RiskEngine(RiskConfig(max_drawdown_pct=0.20, max_daily_loss_pct=0.99))
        portfolio = _make_portfolio(100_000)
        portfolio.peak_equity = 100_000
        portfolio.cash = 95_000  # 5% drawdown — within limit
        halt, _ = engine.check_halt(portfolio, {})
        assert halt is False


class TestSlippage:
    def test_buy_slips_higher(self):
        engine = RiskEngine(RiskConfig(slippage_pct=0.001))
        fill_price = engine.apply_slippage("buy", 100.0)
        assert fill_price == pytest.approx(100.1, rel=1e-6)

    def test_sell_slips_lower(self):
        engine = RiskEngine(RiskConfig(slippage_pct=0.001))
        fill_price = engine.apply_slippage("sell", 100.0)
        assert fill_price == pytest.approx(99.9, rel=1e-6)

    def test_zero_slippage(self):
        engine = RiskEngine(RiskConfig(slippage_pct=0.0))
        assert engine.apply_slippage("buy", 100.0) == 100.0
        assert engine.apply_slippage("sell", 100.0) == 100.0

    def test_buy_fills_above_open(self):
        engine = RiskEngine(RiskConfig(slippage_pct=0.0005))
        assert engine.apply_slippage("buy", 200.0) > 200.0

    def test_sell_fills_below_open(self):
        engine = RiskEngine(RiskConfig(slippage_pct=0.0005))
        assert engine.apply_slippage("sell", 200.0) < 200.0


class TestCommission:
    def test_commission_proportional_to_value(self):
        engine = RiskEngine(RiskConfig(commission_pct=0.001))
        assert engine.apply_commission(10_000.0) == pytest.approx(10.0, rel=1e-6)

    def test_commission_scales_with_size(self):
        engine = RiskEngine(RiskConfig(commission_pct=0.001))
        assert engine.apply_commission(5_000.0) == pytest.approx(5.0, rel=1e-6)

    def test_zero_commission(self):
        engine = RiskEngine(RiskConfig(commission_pct=0.0))
        assert engine.apply_commission(100_000.0) == 0.0

    def test_higher_commission_rate(self):
        engine = RiskEngine(RiskConfig(commission_pct=0.01))
        assert engine.apply_commission(1_000.0) == pytest.approx(10.0, rel=1e-6)
