"""
Volatility-Adjusted ATR Breakout strategy.

Logic:
  Entry: close > EMA(ema_period) + atr_mult * ATR(atr_period)  [explosive upside breakout]
  Exit:  close < EMA(ema_period)                                 [price returns to mean]

Adapts to market volatility: wide-range markets require larger moves to trigger entry,
reducing false signals in choppy conditions. The parameter surface (atr_mult) produces
a smooth stability region suitable for Gate 2 optimization.

No lookahead: all indicators computed from data[0:i+1] slices provided by the engine.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import ema as compute_ema, atr as compute_atr

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class ATRBreakoutStrategy(Strategy):
    """
    Volatility-adjusted breakout using ATR channel.

    Parameters:
        ema_period:    EMA period for trend baseline (default 20)
        atr_period:    ATR period for volatility measurement (default 14)
        atr_mult:      ATR multiplier for breakout threshold (default 2.0)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "atr_breakout"

    def __init__(
        self,
        symbol: str,
        ema_period: int = 20,
        atr_period: int = 14,
        atr_mult: float = 2.0,
        allocation_pct: float = 0.95,
    ) -> None:
        if atr_mult <= 0:
            raise ValueError("atr_mult must be positive")
        self.symbol = symbol
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.allocation_pct = allocation_pct

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        min_bars = max(self.ema_period, self.atr_period) + 2
        if len(data) < min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        ema_vals = compute_ema(data, self.ema_period)
        atr_vals = compute_atr(data, self.atr_period)

        ema_now = float(ema_vals.iloc[-1])
        atr_now = float(atr_vals.iloc[-1])
        close_now = float(data["close"].iloc[-1])

        if pd.isna(ema_now) or pd.isna(atr_now) or atr_now <= 0:
            return Signal(symbol=self.symbol, direction="flat", reason="indicator NaN")

        upper_band = ema_now + self.atr_mult * atr_now

        if close_now > upper_band:
            # Breakout above volatility band — strong uptrend signal
            strength = min(1.0, (close_now - upper_band) / atr_now)
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.3, strength),
                reason=f"ATR breakout: close {close_now:.2f} > EMA+{self.atr_mult}xATR ({upper_band:.2f})",
                metadata={"ema": ema_now, "atr": atr_now, "upper_band": upper_band},
            )

        if close_now < ema_now:
            # Price fell back below EMA — trend exhausted
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"Below EMA: close {close_now:.2f} < EMA {ema_now:.2f}",
                metadata={"ema": ema_now},
            )

        # Between EMA and upper band — hold existing position, don't enter new
        return Signal(
            symbol=self.symbol,
            direction="long",
            strength=0.4,
            reason=f"In ATR channel: {ema_now:.2f} < close < {upper_band:.2f}",
            metadata={"ema": ema_now, "atr": atr_now},
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
