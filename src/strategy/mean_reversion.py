"""
RSI Mean Reversion Strategy.

Signal logic:
  Long:  RSI drops below oversold threshold → buy the dip
  Flat:  RSI rises above overbought threshold → take profit / exit
  Hold:  RSI between thresholds → maintain current position

Position sizing: fixed-fractional (allocation_pct of portfolio equity)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import rsi as compute_rsi

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class RSIMeanReversionStrategy(Strategy):
    """
    Mean-reversion strategy: buy oversold, sell overbought.

    Parameters:
        symbol:         Asset to trade
        rsi_period:     RSI lookback period (default 14)
        oversold:       RSI level to trigger buy (default 30)
        overbought:     RSI level to trigger sell/exit (default 70)
        allocation_pct: Fraction of portfolio equity to allocate per trade (default 0.95)
    """

    name = "rsi_mean_reversion"

    def __init__(
        self,
        symbol: str,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        allocation_pct: float = 0.95,
    ) -> None:
        if oversold >= overbought:
            raise ValueError(f"oversold ({oversold}) must be < overbought ({overbought})")
        if not 0 < allocation_pct <= 1:
            raise ValueError(f"allocation_pct must be in (0, 1], got {allocation_pct}")

        self.symbol = symbol
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.allocation_pct = allocation_pct

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        """
        Generate RSI-based mean reversion signal at the latest bar.
        Requires at least rsi_period + 2 bars.
        """
        min_bars = self.rsi_period + 2
        if len(data) < min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        rsi_series = compute_rsi(data, self.rsi_period)
        current_rsi = rsi_series.iloc[-1]

        if pd.isna(current_rsi):
            return Signal(symbol=self.symbol, direction="flat", reason="RSI is NaN")

        if current_rsi < self.oversold:
            # Oversold — buy signal (higher strength the more oversold)
            strength = min(1.0, (self.oversold - current_rsi) / self.oversold)
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.1, strength),
                reason=f"RSI={current_rsi:.1f} < oversold={self.oversold}",
                metadata={"rsi": current_rsi},
            )

        if current_rsi > self.overbought:
            # Overbought — exit signal
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"RSI={current_rsi:.1f} > overbought={self.overbought}",
                metadata={"rsi": current_rsi},
            )

        # Neutral zone — maintain current position (return flat to let engine decide)
        # Return the current position intent: if we're in, stay in; if out, stay out
        # Engine handles this by checking portfolio state
        return Signal(
            symbol=self.symbol,
            direction="flat",  # neutral = don't initiate new positions
            reason=f"RSI={current_rsi:.1f} in neutral zone [{self.oversold}, {self.overbought}]",
            metadata={"rsi": current_rsi},
        )

    def size_position(self, signal: Signal, portfolio: "Portfolio", price: float) -> Optional[Order]:
        """
        Long signal + no position → buy.
        Flat signal + has position → sell.
        Neutral zone + has position → hold (return None, engine keeps position).
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
