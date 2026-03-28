"""
EMA Crossover Strategy — trend following.

Signal logic:
  Long:  fast EMA crosses above slow EMA (golden cross)
  Flat:  fast EMA crosses below slow EMA (death cross) → exit

Position sizing: fixed-fractional (allocation_pct of portfolio equity)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import ema as compute_ema

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class EMACrossoverStrategy(Strategy):
    """
    Trend-following strategy using exponential moving average crossover.

    Parameters:
        fast_period:    Short EMA period (default 10)
        slow_period:    Long EMA period (default 21)
        allocation_pct: Fraction of portfolio equity to allocate per trade (default 0.95)
        symbol:         Asset to trade
    """

    name = "ema_crossover"

    def __init__(
        self,
        symbol: str,
        fast_period: int = 10,
        slow_period: int = 21,
        allocation_pct: float = 0.95,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError(f"fast_period ({fast_period}) must be < slow_period ({slow_period})")
        if not 0 < allocation_pct <= 1:
            raise ValueError(f"allocation_pct must be in (0, 1], got {allocation_pct}")

        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.allocation_pct = allocation_pct

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        """
        Generate signal based on EMA crossover at the latest bar.
        Requires at least slow_period + 1 bars.
        """
        if len(data) < self.slow_period + 1:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        fast = compute_ema(data, self.fast_period)
        slow = compute_ema(data, self.slow_period)

        fast_now = fast.iloc[-1]
        slow_now = slow.iloc[-1]
        fast_prev = fast.iloc[-2]
        slow_prev = slow.iloc[-2]

        if fast_now > slow_now:
            # Bullish — in uptrend
            # Strength: how far above slow EMA (capped at 1)
            strength = min(1.0, (fast_now - slow_now) / slow_now * 20)
            reason = f"EMA{self.fast_period}={fast_now:.2f} > EMA{self.slow_period}={slow_now:.2f}"
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.1, strength),
                reason=reason,
                metadata={"fast_ema": fast_now, "slow_ema": slow_now},
            )

        # Bearish — below slow EMA, stay flat
        reason = f"EMA{self.fast_period}={fast_now:.2f} < EMA{self.slow_period}={slow_now:.2f}"
        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=reason,
            metadata={"fast_ema": fast_now, "slow_ema": slow_now},
        )

    def size_position(self, signal: Signal, portfolio: "Portfolio", price: float) -> Optional[Order]:
        """
        Convert signal to order.
        Long signal + no position → buy.
        Flat signal + has position → sell.
        Otherwise → None.
        """
        has_pos = portfolio.has_position(signal.symbol)

        if signal.direction == "long" and not has_pos:
            if price <= 0:
                return None
            capital_to_deploy = portfolio.cash * self.allocation_pct * signal.strength
            quantity = capital_to_deploy / price
            if quantity < 1e-6:
                return None
            return Order(
                symbol=signal.symbol,
                side="buy",
                quantity=quantity,
                strategy_name=self.name,
            )

        if signal.direction == "flat" and has_pos:
            qty = portfolio.positions[signal.symbol]
            return Order(
                symbol=signal.symbol,
                side="sell",
                quantity=qty,
                strategy_name=self.name,
            )

        return None
