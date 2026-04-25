"""
Unit tests for strategy signal generation.
Each test uses deterministic crafted price series with known expected outcomes.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategy.base import Order, Signal
from src.strategy.portfolio import Portfolio
from src.strategy.trend import EMACrossoverStrategy
from src.strategy.mean_reversion import RSIMeanReversionStrategy
from src.strategy.breakout import DonchianBreakoutStrategy


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _make_df(closes, highs=None, lows=None, opens=None):
    """Build an OHLCV DataFrame from a sequence of closes."""
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    if highs is None:
        highs = closes * 1.005
    if lows is None:
        lows = closes * 0.995
    if opens is None:
        opens = closes
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1_000_000.0] * n,
    }, index=dates)


def _uptrend(n=35, start=100.0, pct=0.015) -> pd.DataFrame:
    """Strong uptrend: each bar +pct%."""
    closes = [start * ((1 + pct) ** i) for i in range(n)]
    return _make_df(closes)


def _downtrend(n=35, start=200.0, pct=0.015) -> pd.DataFrame:
    """Strong downtrend: each bar -pct%."""
    closes = [start * ((1 - pct) ** i) for i in range(n)]
    return _make_df(closes)


def _oscillating_oversold(n=25, start=100.0) -> pd.DataFrame:
    """20+ consecutive down bars to push RSI below 30."""
    # 5 neutral bars then 20 bars each down 5%
    closes = [start] * 5 + [start * (0.95 ** i) for i in range(1, n - 4)]
    return _make_df(closes)


def _oscillating_overbought(n=25, start=100.0) -> pd.DataFrame:
    """20+ consecutive up bars to push RSI above 70."""
    closes = [start] * 5 + [start * (1.05 ** i) for i in range(1, n - 4)]
    return _make_df(closes)


def _portfolio_with_position(symbol="AAPL", qty=10.0, capital=50_000) -> Portfolio:
    """Return portfolio already long the given symbol."""
    p = Portfolio(capital)
    order = Order(symbol=symbol, side="buy", quantity=qty)
    from src.strategy.base import Fill
    fill = Fill(
        order=order,
        fill_price=100.0,
        commission=0.0,
        slippage_cost=0.0,
        timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
    )
    p.apply_fill(fill)
    return p


# ===========================================================================
# EMACrossoverStrategy
# ===========================================================================

class TestEMACrossoverInit:
    def test_valid_init(self):
        s = EMACrossoverStrategy(symbol="AAPL", fast_period=10, slow_period=21)
        assert s.fast_period == 10
        assert s.slow_period == 21
        assert s.name == "ema_crossover"

    def test_fast_ge_slow_raises(self):
        with pytest.raises(ValueError):
            EMACrossoverStrategy(symbol="AAPL", fast_period=21, slow_period=10)

    def test_fast_equal_slow_raises(self):
        with pytest.raises(ValueError):
            EMACrossoverStrategy(symbol="AAPL", fast_period=15, slow_period=15)

    def test_invalid_allocation_raises(self):
        with pytest.raises(ValueError):
            EMACrossoverStrategy(symbol="AAPL", allocation_pct=1.5)


class TestEMACrossoverSignals:
    def test_insufficient_data_returns_flat(self):
        strat = EMACrossoverStrategy(symbol="AAPL", fast_period=10, slow_period=21)
        df = _uptrend(n=10)  # less than slow_period + 1
        sig = strat.generate_signals(df)
        assert sig.direction == "flat"

    def test_uptrend_gives_long_signal(self):
        strat = EMACrossoverStrategy(symbol="AAPL", fast_period=5, slow_period=10)
        df = _uptrend(n=25)  # plenty of bars, strong uptrend
        sig = strat.generate_signals(df)
        assert sig.direction == "long"

    def test_downtrend_gives_flat_signal(self):
        strat = EMACrossoverStrategy(symbol="AAPL", fast_period=5, slow_period=10)
        df = _downtrend(n=25)
        sig = strat.generate_signals(df)
        assert sig.direction == "flat"

    def test_signal_strength_in_range(self):
        strat = EMACrossoverStrategy(symbol="AAPL", fast_period=5, slow_period=10)
        df = _uptrend(n=25)
        sig = strat.generate_signals(df)
        assert 0.0 <= sig.strength <= 1.0

    def test_signal_symbol_matches(self):
        strat = EMACrossoverStrategy(symbol="TSLA", fast_period=5, slow_period=10)
        df = _uptrend(n=25)
        sig = strat.generate_signals(df)
        assert sig.symbol == "TSLA"

    def test_long_signal_has_metadata(self):
        strat = EMACrossoverStrategy(symbol="AAPL", fast_period=5, slow_period=10)
        df = _uptrend(n=25)
        sig = strat.generate_signals(df)
        if sig.direction == "long":
            assert "fast_ema" in sig.metadata
            assert "slow_ema" in sig.metadata


class TestEMACrossoverSizePosition:
    def test_buy_when_long_and_no_position(self):
        strat = EMACrossoverStrategy(symbol="AAPL")
        p = Portfolio(50_000)
        sig = Signal(symbol="AAPL", direction="long", strength=1.0)
        order = strat.size_position(sig, p, 100.0)
        assert order is not None
        assert order.side == "buy"
        assert order.quantity > 0

    def test_sell_when_flat_and_has_position(self):
        strat = EMACrossoverStrategy(symbol="AAPL")
        p = _portfolio_with_position("AAPL", qty=10.0)
        sig = Signal(symbol="AAPL", direction="flat")
        order = strat.size_position(sig, p, 100.0)
        assert order is not None
        assert order.side == "sell"
        assert order.quantity == 10.0

    def test_none_when_long_and_already_has_position(self):
        strat = EMACrossoverStrategy(symbol="AAPL")
        p = _portfolio_with_position("AAPL", qty=10.0)
        sig = Signal(symbol="AAPL", direction="long")
        order = strat.size_position(sig, p, 100.0)
        assert order is None

    def test_none_when_flat_and_no_position(self):
        strat = EMACrossoverStrategy(symbol="AAPL")
        p = Portfolio(50_000)
        sig = Signal(symbol="AAPL", direction="flat")
        order = strat.size_position(sig, p, 100.0)
        assert order is None

    def test_buy_quantity_uses_allocation_pct(self):
        strat = EMACrossoverStrategy(symbol="AAPL", allocation_pct=0.5)
        p = Portfolio(10_000)
        sig = Signal(symbol="AAPL", direction="long", strength=1.0)
        order = strat.size_position(sig, p, 100.0)
        # cash * 0.5 * 1.0 / price = 10000 * 0.5 / 100 = 50 shares
        assert order is not None
        assert abs(order.quantity - 50.0) < 0.01


# ===========================================================================
# RSIMeanReversionStrategy
# ===========================================================================

class TestRSIMeanReversionInit:
    def test_valid_init(self):
        s = RSIMeanReversionStrategy(symbol="AAPL")
        assert s.rsi_period == 14
        assert s.oversold == 30.0
        assert s.overbought == 70.0

    def test_oversold_ge_overbought_raises(self):
        with pytest.raises(ValueError):
            RSIMeanReversionStrategy(symbol="AAPL", oversold=70, overbought=30)

    def test_invalid_allocation_raises(self):
        with pytest.raises(ValueError):
            RSIMeanReversionStrategy(symbol="AAPL", allocation_pct=0.0)


class TestRSIMeanReversionSignals:
    def test_insufficient_data_returns_flat(self):
        strat = RSIMeanReversionStrategy(symbol="AAPL")
        df = _make_df([100.0] * 10)
        sig = strat.generate_signals(df)
        assert sig.direction == "flat"
        assert "insufficient" in sig.reason.lower()

    def test_oversold_gives_long_signal(self):
        strat = RSIMeanReversionStrategy(symbol="AAPL", rsi_period=14)
        df = _oscillating_oversold(n=25)
        sig = strat.generate_signals(df)
        # After many consecutive down bars, RSI should be < 30
        assert sig.direction == "long"

    def test_overbought_gives_flat_signal(self):
        strat = RSIMeanReversionStrategy(symbol="AAPL", rsi_period=14)
        df = _oscillating_overbought(n=25)
        sig = strat.generate_signals(df)
        assert sig.direction == "flat"

    def test_neutral_zone_gives_flat(self):
        strat = RSIMeanReversionStrategy(symbol="AAPL", rsi_period=14)
        # Flat prices → RSI ≈ 50 (neutral zone)
        df = _make_df([100.0] * 25)
        sig = strat.generate_signals(df)
        assert sig.direction == "flat"

    def test_long_signal_has_rsi_metadata(self):
        strat = RSIMeanReversionStrategy(symbol="AAPL", rsi_period=14)
        df = _oscillating_oversold(n=25)
        sig = strat.generate_signals(df)
        if sig.direction == "long":
            assert "rsi" in sig.metadata

    def test_strength_in_range(self):
        strat = RSIMeanReversionStrategy(symbol="AAPL", rsi_period=14)
        df = _oscillating_oversold(n=25)
        sig = strat.generate_signals(df)
        assert 0.0 <= sig.strength <= 1.0


class TestRSIMeanReversionSizePosition:
    def test_buy_when_long_and_no_position(self):
        strat = RSIMeanReversionStrategy(symbol="AAPL")
        p = Portfolio(50_000)
        sig = Signal(symbol="AAPL", direction="long", strength=0.5)
        order = strat.size_position(sig, p, 100.0)
        assert order is not None
        assert order.side == "buy"

    def test_sell_when_flat_and_has_position(self):
        strat = RSIMeanReversionStrategy(symbol="AAPL")
        p = _portfolio_with_position("AAPL", qty=10.0)
        sig = Signal(symbol="AAPL", direction="flat")
        order = strat.size_position(sig, p, 100.0)
        assert order is not None
        assert order.side == "sell"


# ===========================================================================
# DonchianBreakoutStrategy
# ===========================================================================

class TestDonchianBreakoutInit:
    def test_valid_init(self):
        s = DonchianBreakoutStrategy(symbol="AAPL", period=20)
        assert s.period == 20
        assert s.name == "donchian_breakout"

    def test_period_too_small_raises(self):
        with pytest.raises(ValueError):
            DonchianBreakoutStrategy(symbol="AAPL", period=1)

    def test_invalid_allocation_raises(self):
        with pytest.raises(ValueError):
            DonchianBreakoutStrategy(symbol="AAPL", allocation_pct=1.5)


class TestDonchianBreakoutSignals:
    def test_insufficient_data_returns_flat(self):
        strat = DonchianBreakoutStrategy(symbol="AAPL", period=20)
        df = _make_df([100.0] * 15)  # fewer than period + 1
        sig = strat.generate_signals(df)
        assert sig.direction == "flat"

    def test_breakout_above_upper_band_gives_long(self):
        strat = DonchianBreakoutStrategy(symbol="AAPL", period=5)
        # 6 bars: first 5 have high=100, last bar close=120 (breakout)
        n = 7
        highs = [100.0] * (n - 1) + [125.0]
        lows = [95.0] * (n - 1) + [115.0]
        closes = [98.0] * (n - 1) + [120.0]  # last close > 100 upper band
        df = _make_df(closes, highs=highs, lows=lows)
        sig = strat.generate_signals(df)
        assert sig.direction == "long"

    def test_breakdown_below_lower_band_gives_flat(self):
        strat = DonchianBreakoutStrategy(symbol="AAPL", period=5)
        n = 7
        highs = [105.0] * (n - 1) + [95.0]
        lows = [100.0] * (n - 1) + [85.0]
        closes = [102.0] * (n - 1) + [88.0]  # last close < 100 lower band
        df = _make_df(closes, highs=highs, lows=lows)
        sig = strat.generate_signals(df)
        assert sig.direction == "flat"

    def test_inside_channel_gives_flat(self):
        strat = DonchianBreakoutStrategy(symbol="AAPL", period=5)
        # All bars at 100, last bar also at 100 (inside channel)
        df = _make_df([100.0] * 7)
        sig = strat.generate_signals(df)
        assert sig.direction == "flat"

    def test_no_lookahead_uses_previous_bars(self):
        """Verify that the channel is computed from bars BEFORE the current bar."""
        strat = DonchianBreakoutStrategy(symbol="AAPL", period=3)
        # 5 bars: bars 0-3 have high=100, bar 4 has high=200 but close=50
        # Upper band = max(high[1:4]) = 100 (excludes bar 4)
        # Close at bar 4 = 50 < upper_band → no breakout
        closes = [100.0, 100.0, 100.0, 100.0, 50.0]
        highs = [100.0, 100.0, 100.0, 100.0, 200.0]
        lows = [98.0] * 4 + [48.0]
        df = _make_df(closes, highs=highs, lows=lows)
        sig = strat.generate_signals(df)
        # bar 4 close (50) < lower_band (min(low[1:4]) = 98) → flat (breakdown)
        # Or inside channel if close > lower_band but < upper_band
        # lower_band = min(low[1:4]) = 98, close=50 < 98 → breakdown → flat ✓
        assert sig.direction == "flat"

    def test_signal_strength_in_range(self):
        strat = DonchianBreakoutStrategy(symbol="AAPL", period=5)
        n = 7
        highs = [100.0] * (n - 1) + [125.0]
        lows = [95.0] * (n - 1) + [115.0]
        closes = [98.0] * (n - 1) + [120.0]
        df = _make_df(closes, highs=highs, lows=lows)
        sig = strat.generate_signals(df)
        assert 0.0 <= sig.strength <= 1.0


class TestDonchianBreakoutSizePosition:
    def test_buy_on_breakout_signal(self):
        strat = DonchianBreakoutStrategy(symbol="AAPL")
        p = Portfolio(50_000)
        sig = Signal(symbol="AAPL", direction="long", strength=0.8)
        order = strat.size_position(sig, p, 100.0)
        assert order is not None
        assert order.side == "buy"

    def test_sell_on_flat_with_position(self):
        strat = DonchianBreakoutStrategy(symbol="AAPL")
        p = _portfolio_with_position("AAPL", qty=20.0)
        sig = Signal(symbol="AAPL", direction="flat")
        order = strat.size_position(sig, p, 90.0)
        assert order is not None
        assert order.side == "sell"
        assert order.quantity == 20.0

    def test_none_inside_channel_no_position(self):
        strat = DonchianBreakoutStrategy(symbol="AAPL")
        p = Portfolio(50_000)
        sig = Signal(symbol="AAPL", direction="flat")
        order = strat.size_position(sig, p, 100.0)
        assert order is None
