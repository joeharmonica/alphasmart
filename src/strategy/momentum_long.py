"""
Price Momentum (Rate-of-Change) strategy — Long Only.

Logic:
  momentum = (close - close[lookback_period]) / close[lookback_period]  — ROC
  Long  when momentum > entry_threshold  (sustained uptrend over lookback window)
  Flat  when momentum < exit_threshold   (trend faded or reversed)

Inspired by Cross-Sectional Momentum research (Jegadeesh & Titman, 1993).
Adapted to single-asset long-only format for AlphaSMART's current framework.

No lookahead: all computations use only data[0:i+1] slices provided by the engine.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class MomentumLongStrategy(Strategy):
    """
    Rate-of-change momentum strategy (long only).

    Parameters:
        lookback_period:   Bars over which to measure momentum (default 126 ≈ 6 months daily)
        entry_threshold:   Minimum ROC to enter long (default 0.05 = +5%)
        exit_threshold:    ROC below which to exit (default -0.02 = -2%)
        smooth_period:     Optional SMA smoothing on ROC to reduce noise (default 5, 0 = off)
        allocation_pct:    Fraction of portfolio equity per trade (default 0.95)
    """

    name = "momentum_long"

    def __init__(
        self,
        symbol: str,
        lookback_period: int = 126,
        entry_threshold: float = 0.05,
        exit_threshold: float = -0.02,
        smooth_period: int = 5,
        allocation_pct: float = 0.95,
    ) -> None:
        self.symbol = symbol
        self.lookback_period = lookback_period
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.smooth_period = smooth_period
        self.allocation_pct = allocation_pct

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        min_bars = self.lookback_period + max(self.smooth_period, 1) + 1
        if len(data) < min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        close = data["close"]
        # Rate of Change over lookback window
        roc = (close - close.shift(self.lookback_period)) / close.shift(self.lookback_period)

        # Optional smoothing to reduce noise
        if self.smooth_period > 1:
            roc_signal = roc.rolling(self.smooth_period).mean()
        else:
            roc_signal = roc

        roc_now = float(roc_signal.iloc[-1])

        if pd.isna(roc_now):
            return Signal(symbol=self.symbol, direction="flat", reason="ROC is NaN")

        if roc_now > self.entry_threshold:
            # Strong upward momentum
            strength = min(1.0, roc_now / (self.entry_threshold * 3))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.3, strength),
                reason=f"Momentum: ROC={roc_now:.2%} > {self.entry_threshold:.2%}",
                metadata={"roc": roc_now},
            )

        if roc_now < self.exit_threshold:
            # Momentum faded — exit
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"Momentum faded: ROC={roc_now:.2%} < {self.exit_threshold:.2%}",
                metadata={"roc": roc_now},
            )

        # Between thresholds — hold if long, don't enter new
        return Signal(
            symbol=self.symbol,
            direction="long",
            strength=0.3,
            reason=f"Momentum neutral: ROC={roc_now:.2%}",
            metadata={"roc": roc_now},
        )

    def size_position(self, signal: Signal, portfolio: "Portfolio", price: float) -> Optional[Order]:
        has_pos = portfolio.has_position(signal.symbol)

        if signal.direction == "long" and not has_pos:
            if price <= 0:
                return None
            capital = portfolio.cash * self.allocation_pct * signal.strength
            qty = capital / price
            if qty < 1e-6:
                return None
            return Order(symbol=signal.symbol, side="buy", quantity=qty, strategy_name=self.name)

        if signal.direction == "flat" and has_pos:
            qty = portfolio.positions[signal.symbol]
            return Order(symbol=signal.symbol, side="sell", quantity=qty, strategy_name=self.name)

        return None
