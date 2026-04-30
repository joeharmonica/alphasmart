"""
Unit tests for TrailingStopStrategy (src/strategy/trailing_stop.py).

Spec under test (from the wrapper's own docstring + lessons.md #26):
  - Forward inner.generate_signals() unchanged when flat or pre-ATR.
  - Track running max(close) since the latest long entry.
  - Emit flat (overriding inner long) when close < max - atr_mult * ATR.
  - After a stop, block subsequent long signals until the inner emits flat.
  - size_position() delegates to inner.

NOTE: These assertions encode the wrapper's documented contract — the only
real-world validation so far is cci_trend+stop NVDA (lessons.md #27), where
the stop did NOT fire (lessons #26 caveat). Re-validate against a config
where the stop is observed to trip once one is identified.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import pytest

from src.strategy.base import Order, Signal, Strategy
from src.strategy.trailing_stop import TrailingStopStrategy


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _ScriptedInner(Strategy):
    """Inner strategy that emits a pre-scripted sequence of directions."""

    name = "scripted"

    def __init__(self, symbol: str, directions: list[str]):
        self.symbol = symbol
        self._directions = list(directions)
        self._i = 0
        self.size_calls: list[Signal] = []

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        # Allow the wrapper to pass us shorter slices early; map by data length.
        idx = min(len(data) - 1, len(self._directions) - 1)
        d = self._directions[idx]
        return Signal(symbol=self.symbol, direction=d, reason=f"scripted[{idx}]={d}")

    def size_position(self, signal: Signal, portfolio, price: float) -> Optional[Order]:
        self.size_calls.append(signal)
        if signal.direction == "long":
            return Order(symbol=self.symbol, side="buy", quantity=1.0,
                         strategy_name=self.name)
        return None


def _flat_ohlcv(closes: list[float]) -> pd.DataFrame:
    """Build OHLCV with open=high=low=close — ATR is purely close-to-close jumps."""
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    arr = np.array(closes, dtype=float)
    return pd.DataFrame(
        {"open": arr, "high": arr, "low": arr, "close": arr,
         "volume": np.full(n, 1_000_000.0)},
        index=idx,
    )


def _walk(strategy: TrailingStopStrategy, data: pd.DataFrame) -> list[Signal]:
    """Replay generate_signals() bar-by-bar like the engine does."""
    out = []
    for i in range(1, len(data) + 1):
        out.append(strategy.generate_signals(data.iloc[:i]))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_constructor_validates_inputs():
    inner = _ScriptedInner("AAPL", ["flat"])
    with pytest.raises(ValueError, match="atr_mult"):
        TrailingStopStrategy(inner, atr_mult=0)
    with pytest.raises(ValueError, match="atr_period"):
        TrailingStopStrategy(inner, atr_period=1)

    class _NoSymbol:
        pass
    with pytest.raises(ValueError, match="symbol"):
        TrailingStopStrategy(_NoSymbol())  # type: ignore[arg-type]


def test_inner_flat_passes_through_and_resets_state():
    n = 30
    inner = _ScriptedInner("AAPL", ["flat"] * n)
    wrapper = TrailingStopStrategy(inner, atr_period=5, atr_mult=2.0)
    data = _flat_ohlcv([100.0 + i for i in range(n)])

    signals = _walk(wrapper, data)
    assert all(s.direction == "flat" for s in signals)
    # Internal state should never engage when inner is always flat.
    assert wrapper._in_trade is False
    assert wrapper._blocked_until_flat is False


def test_pre_atr_window_passes_inner_signal_through():
    # atr_period=14 → wrapper requires len(data) >= 16 before evaluating stop.
    n = 10
    inner = _ScriptedInner("AAPL", ["long"] * n)
    wrapper = TrailingStopStrategy(inner, atr_period=14, atr_mult=2.0)
    data = _flat_ohlcv([100.0 + i for i in range(n)])

    signals = _walk(wrapper, data)
    # All bars are pre-ATR-window: wrapper must not override.
    assert all(s.direction == "long" for s in signals)
    assert wrapper._in_trade is False  # stop arming requires post-window bar


def test_long_then_drop_triggers_stop_and_blocks_until_flat():
    """Phase 1: rise (arm). Phase 2: small drop (no stop). Phase 3: large drop (stop)."""
    rise = list(np.linspace(100, 200, 60))      # 60 bars, peak at 200
    crash = list(np.linspace(200, 100, 20))     # sharp drop — stop must fire
    after_crash_long = [100.0] * 10             # inner still says long → blocked
    inner_flat_zone = [100.0] * 5               # inner says flat → block clears
    new_rise = list(np.linspace(100, 130, 10))  # inner says long → allowed again
    closes = rise + crash + after_crash_long + inner_flat_zone + new_rise
    n = len(closes)

    # Inner: long for the first len(rise+crash+after_crash_long), flat next, long again.
    n_long = len(rise) + len(crash) + len(after_crash_long)
    n_flat = len(inner_flat_zone)
    n_long2 = len(new_rise)
    inner = _ScriptedInner("AAPL", ["long"] * n_long + ["flat"] * n_flat + ["long"] * n_long2)

    wrapper = TrailingStopStrategy(inner, atr_period=14, atr_mult=2.0)
    data = _flat_ohlcv(closes)
    signals = _walk(wrapper, data)

    directions = [s.direction for s in signals]

    # Phase 1: ATR window passed and price still rising → inner long should pass.
    rise_after_atr = directions[15 : len(rise)]
    assert all(d == "long" for d in rise_after_atr), \
        f"Expected long during rise after ATR warmup, got {rise_after_atr[:5]}..."

    # Phase 2 + 3: somewhere during the crash the stop must trip — at least one bar
    # in this range must be a flat overriding the inner's long.
    crash_zone = directions[len(rise) : len(rise) + len(crash)]
    assert any(d == "flat" for d in crash_zone), \
        "Expected at least one stop-out flat during the crash"

    # The stop bar must carry trailing_stop_hit metadata.
    crash_signals = signals[len(rise) : len(rise) + len(crash)]
    stop_signals = [s for s in crash_signals if s.metadata.get("trailing_stop_hit")]
    assert stop_signals, "No signal carried trailing_stop_hit metadata"
    s = stop_signals[0]
    assert s.metadata["max_close"] >= 200 - 1e-6, \
        f"max_close should equal the rise peak (~200), got {s.metadata['max_close']}"
    assert s.metadata["stop_level"] < s.metadata["max_close"]

    # Phase 4 (inner still long after stop): wrapper must keep emitting flat.
    block_zone = directions[len(rise) + len(crash) : n_long]
    assert all(d == "flat" for d in block_zone), \
        f"Expected blocked flats while inner still long, got {block_zone[:5]}..."
    block_signals = signals[len(rise) + len(crash) : n_long]
    assert any(s.metadata.get("trailing_stop_blocked") for s in block_signals), \
        "Block phase should mark trailing_stop_blocked in metadata"

    # Phase 5: inner emits flat → block clears.
    flat_zone = directions[n_long : n_long + n_flat]
    assert all(d == "flat" for d in flat_zone)

    # Phase 6: inner long again, block lifted, ATR is computable, prices rising → long passes.
    long2_zone = directions[n_long + n_flat : n_long + n_flat + n_long2]
    assert any(d == "long" for d in long2_zone), \
        "After inner flat, new long signals should be allowed again"


def test_size_position_delegates_to_inner():
    inner = _ScriptedInner("AAPL", ["long"])
    wrapper = TrailingStopStrategy(inner)
    sig = Signal(symbol="AAPL", direction="long")
    order = wrapper.size_position(sig, portfolio=None, price=100.0)
    assert order is not None
    assert order.symbol == "AAPL"
    assert order.side == "buy"
    assert inner.size_calls == [sig]


def test_no_lookahead_each_call_uses_only_provided_slice():
    """Wrapper must not peek beyond data passed to generate_signals()."""
    n = 50
    closes = list(np.linspace(100, 200, n))
    inner = _ScriptedInner("AAPL", ["long"] * n)
    wrapper = TrailingStopStrategy(inner, atr_period=5, atr_mult=2.0)
    full = _flat_ohlcv(closes)

    # Replay incrementally and capture the max_close at each step.
    incremental_max = []
    for i in range(1, n + 1):
        wrapper.generate_signals(full.iloc[:i])
        if wrapper._in_trade:
            incremental_max.append(wrapper._max_close)

    # The high-water mark must never exceed the highest close seen so far.
    for i, m in enumerate(incremental_max):
        bars_seen = i + 1 + 5  # rough offset (after ATR warmup); be permissive
        observed_so_far = float(np.max(closes[:bars_seen + 1])) if bars_seen < n else float(np.max(closes))
        assert m <= observed_so_far + 1e-9, \
            f"max_close {m} exceeded observed max {observed_so_far} at step {i}"


def test_name_marker():
    inner = _ScriptedInner("AAPL", ["flat"])
    inner.name = "cci_trend"
    wrapper = TrailingStopStrategy(inner)
    assert wrapper.name == "cci_trend+stop"
