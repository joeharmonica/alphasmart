"""
Rolling Z-Score Mean Reversion strategy.

Logic:
  z_score = (close - rolling_mean(period)) / rolling_std(period)
  Long  when z < -entry_z  (statistically oversold — price too far below mean)
  Flat  when z > exit_z    (mean reversion complete — close back above mean)

A purely statistical approach that ignores traditional indicators, making it an
effective diversifier alongside momentum/trend strategies.

No lookahead: all computations use only data[0:i+1] slices provided by the engine.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.strategy.base import Order, Signal, Strategy

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class ZScoreReversionStrategy(Strategy):
    """
    Rolling Z-score mean reversion.

    Parameters:
        period:       Rolling window for mean/std computation (default 30)
        entry_z:      Z-score threshold to enter long (default 2.0, i.e. z < -2)
        exit_z:       Z-score threshold to exit (default 0.0, i.e. z > 0 = mean reversion)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "zscore_reversion"

    def __init__(
        self,
        symbol: str,
        period: int = 30,
        entry_z: float = 2.0,
        exit_z: float = 0.0,
        allocation_pct: float = 0.95,
    ) -> None:
        if period < 5:
            raise ValueError("period must be >= 5")
        self.symbol = symbol
        self.period = period
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.allocation_pct = allocation_pct

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if len(data) < self.period + 2:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        close = data["close"]
        rolling_mean = close.rolling(self.period).mean()
        rolling_std = close.rolling(self.period).std(ddof=1)

        mean_now = float(rolling_mean.iloc[-1])
        std_now = float(rolling_std.iloc[-1])
        close_now = float(close.iloc[-1])

        if pd.isna(mean_now) or pd.isna(std_now) or std_now <= 0:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data for Z-score")

        z_now = (close_now - mean_now) / std_now

        if z_now < -self.entry_z:
            # Statistically oversold — high probability mean reversion
            strength = min(1.0, abs(z_now) / (self.entry_z + 1.0))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.2, strength),
                reason=f"Z-score oversold: z={z_now:.2f} < -{self.entry_z}",
                metadata={"z_score": z_now, "mean": mean_now, "std": std_now},
            )

        if z_now > self.exit_z:
            # Price reverted above mean — take profit
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"Z-score reverted: z={z_now:.2f} > {self.exit_z}",
                metadata={"z_score": z_now},
            )

        # Between -entry_z and exit_z — hold position if long, otherwise stay flat
        return Signal(
            symbol=self.symbol,
            direction="long",
            strength=0.3,
            reason=f"Z-score in range: z={z_now:.2f}",
            metadata={"z_score": z_now},
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
