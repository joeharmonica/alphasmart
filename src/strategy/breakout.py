"""
Donchian Channel Breakout Strategy — momentum / breakout.

Signal logic:
  Long:  Close breaks above N-period highest high → momentum entry
  Flat:  Close breaks below N-period lowest low   → exit signal

The Donchian channel defines a price range:
  Upper band = max(high, N periods)
  Lower band = min(low,  N periods)

A close above the upper band signals a breakout (new N-day high).
A close below the lower band signals a breakdown (new N-day low → exit).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class DonchianBreakoutStrategy(Strategy):
    """
    Breakout strategy using Donchian channels.

    Parameters:
        symbol:         Asset to trade
        period:         Lookback period for channel calculation (default 20)
        allocation_pct: Fraction of portfolio equity to allocate per trade (default 0.95)
    """

    name = "donchian_breakout"

    def __init__(
        self,
        symbol: str,
        period: int = 20,
        allocation_pct: float = 0.95,
    ) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}")
        if not 0 < allocation_pct <= 1:
            raise ValueError(f"allocation_pct must be in (0, 1], got {allocation_pct}")

        self.symbol = symbol
        self.period = period
        self.allocation_pct = allocation_pct

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        """
        Generate Donchian breakout signal at the latest bar.
        Uses previous N bars' high/low (excludes current bar to avoid lookahead).
        Requires at least period + 1 bars.
        """
        if len(data) < self.period + 1:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        # Use data EXCLUDING current bar for channel calculation → no lookahead
        lookback = data.iloc[-(self.period + 1):-1]
        upper_band = lookback["high"].max()
        lower_band = lookback["low"].min()

        current_close = data["close"].iloc[-1]
        current_high = data["high"].iloc[-1]
        current_low = data["low"].iloc[-1]

        if current_close > upper_band:
            # Breakout above upper band
            strength = min(1.0, (current_close - upper_band) / upper_band * 10)
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.1, strength),
                reason=f"Close {current_close:.2f} > {self.period}d high {upper_band:.2f}",
                metadata={"upper_band": upper_band, "lower_band": lower_band},
            )

        if current_close < lower_band:
            # Breakdown below lower band → exit
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"Close {current_close:.2f} < {self.period}d low {lower_band:.2f}",
                metadata={"upper_band": upper_band, "lower_band": lower_band},
            )

        # Inside channel — neutral
        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=f"Close {current_close:.2f} inside channel [{lower_band:.2f}, {upper_band:.2f}]",
            metadata={"upper_band": upper_band, "lower_band": lower_band},
        )

    def size_position(self, signal: Signal, portfolio: "Portfolio", price: float) -> Optional[Order]:
        """
        Long signal + no position → buy breakout.
        Flat signal + has position → sell (breakdown exit).
        Inside channel + has position → hold (return None).
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
