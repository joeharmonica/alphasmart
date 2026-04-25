"""Unit tests for Signal, Order, Fill data structures."""
import sys
from pathlib import Path
from datetime import datetime, timezone
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategy.base import Signal, Order, Fill


class TestSignal:
    def test_valid_long_signal(self):
        s = Signal(symbol="AAPL", direction="long", strength=0.8)
        assert s.direction == "long"
        assert s.strength == 0.8

    def test_valid_flat_signal(self):
        s = Signal(symbol="AAPL", direction="flat")
        assert s.direction == "flat"
        assert s.strength == 1.0  # default

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            Signal(symbol="AAPL", direction="short")  # Phase 2: no short

    def test_strength_out_of_range_raises(self):
        with pytest.raises(ValueError):
            Signal(symbol="AAPL", direction="long", strength=1.5)

    def test_strength_negative_raises(self):
        with pytest.raises(ValueError):
            Signal(symbol="AAPL", direction="long", strength=-0.1)

    def test_metadata_default_empty(self):
        s = Signal(symbol="AAPL", direction="long")
        assert s.metadata == {}

    def test_metadata_stored(self):
        s = Signal(symbol="AAPL", direction="long", metadata={"rsi": 28.5})
        assert s.metadata["rsi"] == 28.5


class TestOrder:
    def test_valid_buy_order(self):
        o = Order(symbol="AAPL", side="buy", quantity=10.0)
        assert o.side == "buy"
        assert o.quantity == 10.0

    def test_valid_sell_order(self):
        o = Order(symbol="AAPL", side="sell", quantity=5.0)
        assert o.side == "sell"

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            Order(symbol="AAPL", side="hold", quantity=10.0)

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError):
            Order(symbol="AAPL", side="buy", quantity=0.0)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError):
            Order(symbol="AAPL", side="buy", quantity=-5.0)

    def test_default_order_type_is_market(self):
        o = Order(symbol="AAPL", side="buy", quantity=1.0)
        assert o.order_type == "market"


class TestFill:
    def _make_fill(self, side="buy", qty=10.0, price=150.0, commission=0.15):
        order = Order(symbol="AAPL", side=side, quantity=qty)
        return Fill(
            order=order,
            fill_price=price,
            commission=commission,
            slippage_cost=0.05,
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )

    def test_gross_value_buy(self):
        fill = self._make_fill(side="buy", qty=10.0, price=150.0)
        assert abs(fill.gross_value - 1500.0) < 1e-6

    def test_net_cash_impact_buy(self):
        fill = self._make_fill(side="buy", qty=10.0, price=150.0, commission=1.50)
        # Buy: -(price * qty + commission)
        assert abs(fill.net_cash_impact - (-1501.50)) < 1e-6

    def test_net_cash_impact_sell(self):
        fill = self._make_fill(side="sell", qty=10.0, price=160.0, commission=1.60)
        # Sell: +(price * qty - commission)
        assert abs(fill.net_cash_impact - (1598.40)) < 1e-6

    def test_cash_impact_sign_buy_negative(self):
        fill = self._make_fill(side="buy")
        assert fill.net_cash_impact < 0  # Cash decreases on buy

    def test_cash_impact_sign_sell_positive(self):
        fill = self._make_fill(side="sell")
        assert fill.net_cash_impact > 0  # Cash increases on sell
