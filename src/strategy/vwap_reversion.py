"""
Rolling VWAP Mean Reversion strategy.

Logic:
  Compute rolling VWAP over a fixed window (not cumulative, so it adapts over time).
  Measure deviation: z = (close - vwap_mean) / vwap_std  over the same window.
  Long  when z < -entry_z  (price significantly below rolling VWAP — buy the dip)
  Flat  when z > exit_z    (price reverted back to/above VWAP — take profit)

Uses rolling windows so the VWAP adapts to recent price action rather than anchoring
to the start of the dataset — this makes it meaningful for both intraday and daily data.

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


def _rolling_vwap(df: pd.DataFrame, period: int) -> pd.Series:
    """Rolling VWAP over a fixed window (adapts over time)."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]
    return tp_vol.rolling(period).sum() / df["volume"].rolling(period).sum().replace(0, np.nan)


class VWAPReversionStrategy(Strategy):
    """
    Rolling VWAP mean reversion strategy.

    Parameters:
        vwap_period:    Rolling window for VWAP computation (default 20)
        entry_z:        Z-score threshold to go long (default 1.5, i.e. z < -1.5)
        exit_z:         Z-score threshold to exit (default 0.0 — at VWAP)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "vwap_reversion"

    def __init__(
        self,
        symbol: str,
        vwap_period: int = 20,
        entry_z: float = 1.5,
        exit_z: float = 0.0,
        allocation_pct: float = 0.95,
    ) -> None:
        if vwap_period < 5:
            raise ValueError("vwap_period must be >= 5")
        self.symbol = symbol
        self.vwap_period = vwap_period
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.allocation_pct = allocation_pct

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        min_bars = self.vwap_period * 2 + 2
        if len(data) < min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        if data["volume"].sum() == 0:
            return Signal(symbol=self.symbol, direction="flat", reason="no volume data")

        rolling_vwap = _rolling_vwap(data, self.vwap_period)
        vwap_now = float(rolling_vwap.iloc[-1])

        if pd.isna(vwap_now) or vwap_now <= 0:
            return Signal(symbol=self.symbol, direction="flat", reason="VWAP is NaN or zero")

        close_now = float(data["close"].iloc[-1])

        # Compute deviation Z-score: normalize by rolling std of (close - vwap) distance
        recent_vwap = rolling_vwap.iloc[-self.vwap_period:]
        recent_close = data["close"].iloc[-self.vwap_period:]
        deviation = recent_close.values - recent_vwap.values
        valid = deviation[~np.isnan(deviation)]

        if len(valid) < 5:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient deviation history")

        dev_std = float(np.std(valid, ddof=1))
        if dev_std <= 0:
            return Signal(symbol=self.symbol, direction="flat", reason="zero deviation std")

        current_dev = close_now - vwap_now
        z_now = current_dev / dev_std

        if z_now < -self.entry_z:
            # Significantly below VWAP — mean reversion opportunity
            strength = min(1.0, abs(z_now) / (self.entry_z + 1.0))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.2, strength),
                reason=f"VWAP fade: z={z_now:.2f} < -{self.entry_z} (close {close_now:.2f} vs VWAP {vwap_now:.2f})",
                metadata={"z_score": z_now, "vwap": vwap_now, "deviation": current_dev},
            )

        if z_now > self.exit_z:
            # Price reverted to/above VWAP — exit
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"VWAP reverted: z={z_now:.2f} > {self.exit_z}",
                metadata={"z_score": z_now, "vwap": vwap_now},
            )

        # Still below VWAP but above entry threshold — hold if long
        return Signal(
            symbol=self.symbol,
            direction="long",
            strength=0.3,
            reason=f"VWAP neutral: z={z_now:.2f}",
            metadata={"z_score": z_now, "vwap": vwap_now},
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
