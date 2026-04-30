"""
RSI + Rolling VWAP Confluence strategy — optimised for 1H timeframe.

Logic:
  Rolling VWAP (window-based, not session-cumulative) is used as a dynamic
  fair-value anchor. RSI confirms momentum direction.

  Entry: close < rolling VWAP  (price below fair value — buy the dip)
         AND RSI < oversold     (momentum oversold — mean-reversion setup)
         AND RSI turning up     (RSI now > RSI one bar ago — direction inflecting)
  Exit:  close >= rolling VWAP  (price reverted to fair value)
         OR RSI > overbought    (momentum exhausted)

1H advantage: rolling VWAP adapts every bar, removing the session-start
anchor problem of cumulative VWAP. RSI on 1H data has ~4-6 hour cycles —
shorter than daily (multi-day cycles), providing more trading opportunities.

No lookahead: all indicators computed on data[0:i+1] slices from the engine.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import rsi as compute_rsi

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


def _rolling_vwap(df: pd.DataFrame, period: int) -> pd.Series:
    """Rolling VWAP over a fixed window: sum(typical_price * volume) / sum(volume)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = tp * df["volume"]
    return tp_vol.rolling(period).sum() / df["volume"].rolling(period).sum().replace(0, float("nan"))


class RSIVWAPStrategy(Strategy):
    """
    RSI + rolling VWAP mean reversion.

    Parameters:
        vwap_period:   Rolling window for VWAP calculation (default 24, ~1 trading day on 1H)
        rsi_period:    RSI period (default 14)
        oversold:      RSI level for entry (default 35)
        overbought:    RSI level for exit (default 65)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "rsi_vwap"

    def __init__(
        self,
        symbol: str,
        vwap_period: int = 24,
        rsi_period: int = 14,
        oversold: float = 35.0,
        overbought: float = 65.0,
        allocation_pct: float = 0.95,
    ) -> None:
        if oversold >= overbought:
            raise ValueError("oversold must be < overbought")
        self.symbol = symbol
        self.vwap_period = vwap_period
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.allocation_pct = allocation_pct
        self._min_bars = max(vwap_period, rsi_period) + 3
        self._in_trade: bool = False

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        vwap = _rolling_vwap(data, self.vwap_period)
        rsi_vals = compute_rsi(data, self.rsi_period)

        close_now  = float(data["close"].iloc[-1])
        vwap_now   = float(vwap.iloc[-1])
        rsi_now    = float(rsi_vals.iloc[-1])
        rsi_prev   = float(rsi_vals.iloc[-2])

        if pd.isna(vwap_now) or pd.isna(rsi_now) or pd.isna(rsi_prev):
            return Signal(symbol=self.symbol, direction="flat", reason="indicator NaN")

        below_vwap   = close_now < vwap_now
        rsi_oversold = rsi_now < self.oversold
        rsi_turning  = rsi_now > rsi_prev  # RSI inflecting upward

        if self._in_trade:
            reverted = close_now >= vwap_now
            overbought = rsi_now > self.overbought
            if reverted or overbought:
                self._in_trade = False
                reason = (
                    f"VWAP reversion: close={close_now:.2f} >= VWAP={vwap_now:.2f}"
                    if reverted else
                    f"RSI overbought: {rsi_now:.1f} > {self.overbought}"
                )
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=reason,
                    metadata={"rsi": rsi_now, "vwap": vwap_now},
                )
            # Compute hold strength proportional to distance to target
            pct_to_vwap = max(0.0, (vwap_now - close_now) / vwap_now)
            strength = min(1.0, 0.5 + pct_to_vwap * 10)
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=f"RSI-VWAP holding: RSI={rsi_now:.1f}, close={close_now:.2f} vs VWAP={vwap_now:.2f}",
                metadata={"rsi": rsi_now, "vwap": vwap_now},
            )

        if below_vwap and rsi_oversold and rsi_turning:
            self._in_trade = True
            discount = (vwap_now - close_now) / vwap_now
            strength = min(1.0, 0.5 + discount * 8)
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=(
                    f"RSI-VWAP entry: RSI={rsi_now:.1f} oversold, "
                    f"close={close_now:.2f} < VWAP={vwap_now:.2f}, RSI turning up"
                ),
                metadata={"rsi": rsi_now, "vwap": vwap_now, "discount": discount},
            )

        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=f"RSI-VWAP waiting: RSI={rsi_now:.1f}, close={'<' if below_vwap else '>='} VWAP",
            metadata={"rsi": rsi_now, "vwap": vwap_now, "below_vwap": below_vwap},
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
