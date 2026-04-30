"""
ATR trailing-stop wrapper for AlphaSMART.

TrailingStopStrategy wraps any base Strategy and overrides long signals with
flat signals when an ATR-based trailing stop is hit:

    stop_level = max(close since entry) - atr_mult * ATR(atr_period)

This shifts the burden of drawdown protection from the portfolio-level 20%
circuit breaker (which halts the entire backtest) to a per-trade stop. The
circuit breaker remains as a last-resort safety net.

Behaviour:
  - Forwards inner.generate_signals() unchanged when flat or when ATR is not
    yet computable.
  - Tracks the running max(close) since the most recent long entry.
  - Once close drops below the stop level, emits a flat signal regardless of
    what the inner strategy returned, and sets metadata['trailing_stop_hit'].
  - After a stop-out, blocks subsequent long signals until the inner strategy
    itself emits a flat signal — this prevents instant re-entry on the same
    fading trend (the inner must explicitly acknowledge the regime change).

No lookahead: ATR is computed from the same data slice the engine passes to
the inner (data[0:i+1]).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import atr as compute_atr

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class TrailingStopStrategy(Strategy):
    """
    Wraps a base Strategy and adds an ATR-based trailing stop on long
    positions.

    Parameters:
        inner:      Base Strategy instance to wrap (must expose .symbol).
        atr_period: ATR window for stop sizing (default 14).
        atr_mult:   Stop distance = atr_mult * ATR (default 2.0 — Chandelier-style).
    """

    def __init__(
        self,
        inner: Strategy,
        atr_period: int = 14,
        atr_mult: float = 2.0,
    ) -> None:
        if atr_mult <= 0:
            raise ValueError("atr_mult must be positive")
        if atr_period < 2:
            raise ValueError("atr_period must be >= 2")

        symbol = getattr(inner, "symbol", None)
        if symbol is None:
            raise ValueError("inner strategy must have a .symbol attribute")

        self.inner = inner
        self.symbol = symbol
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.name = f"{inner.name}+stop"

        self._in_trade: bool = False
        self._max_close: float = 0.0
        self._blocked_until_flat: bool = False

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        inner_signal = self.inner.generate_signals(data)

        # Inner says flat: reset all state, pass through.
        if inner_signal.direction == "flat":
            self._in_trade = False
            self._max_close = 0.0
            self._blocked_until_flat = False
            return inner_signal

        # Need ATR to evaluate the stop. If we don't have enough bars yet,
        # pass through without tracking — too early in the series.
        if len(data) < self.atr_period + 2:
            return inner_signal

        close_now = float(data["close"].iloc[-1])
        atr_vals = compute_atr(data, self.atr_period)
        atr_now = float(atr_vals.iloc[-1])

        # Stopped out previously and the inner hasn't reset yet: keep blocking.
        if self._blocked_until_flat:
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason="trailing_stop: blocked, awaiting inner flat",
                metadata={**inner_signal.metadata, "trailing_stop_blocked": True},
            )

        # First long bar of a new trade: arm the stop.
        if not self._in_trade:
            self._in_trade = True
            self._max_close = close_now
            return inner_signal

        # In-trade: update high-water mark.
        if close_now > self._max_close:
            self._max_close = close_now

        if pd.isna(atr_now) or atr_now <= 0:
            return inner_signal

        stop_level = self._max_close - self.atr_mult * atr_now
        if close_now < stop_level:
            stopped_max = self._max_close
            self._in_trade = False
            self._blocked_until_flat = True
            self._max_close = 0.0
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=(
                    f"trailing_stop: close={close_now:.2f} < "
                    f"max={stopped_max:.2f} - {self.atr_mult}*ATR={stop_level:.2f}"
                ),
                metadata={
                    **inner_signal.metadata,
                    "trailing_stop_hit": True,
                    "stop_level": stop_level,
                    "max_close": stopped_max,
                },
            )

        return inner_signal

    def size_position(
        self,
        signal: Signal,
        portfolio: "Portfolio",
        price: float,
    ) -> Optional[Order]:
        return self.inner.size_position(signal, portfolio, price)
