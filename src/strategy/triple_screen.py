"""
Triple Screen (Multi-Timeframe Trend Alignment) strategy.

Inspired by Dr. Alexander Elder's Triple Screen system.
Simulates multi-timeframe analysis on a single timeframe by using:
  1. Macro filter:  50-SMA direction — defines the regime (bullish/bearish)
  2. Entry trigger: Stochastic %K drops below oversold_level in uptrend (buy the dip)
  3. Exit:          Stochastic %K rises above overbought_level OR macro flips bearish

No lookahead: all signals computed only from data[0:i+1] via the engine's history slice.
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


def _stochastic_k(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Stochastic %K = 100 * (close - lowest_low) / (highest_high - lowest_low)."""
    lowest_low = df["low"].rolling(period).min()
    highest_high = df["high"].rolling(period).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    return 100.0 * (df["close"] - lowest_low) / denom


class TripleScreenStrategy(Strategy):
    """
    Triple Screen trend-following / pullback entry strategy.

    Parameters:
        macro_period:     SMA period for macro trend filter (default 50)
        stoch_period:     Stochastic %K lookback period (default 14)
        oversold_level:   %K threshold to trigger entry in uptrend (default 20)
        overbought_level: %K threshold to trigger exit (default 80)
        allocation_pct:   Fraction of portfolio equity per trade (default 0.95)
    """

    name = "triple_screen"

    def __init__(
        self,
        symbol: str,
        macro_period: int = 50,
        stoch_period: int = 14,
        oversold_level: float = 20.0,
        overbought_level: float = 80.0,
        allocation_pct: float = 0.95,
    ) -> None:
        if oversold_level >= overbought_level:
            raise ValueError("oversold_level must be < overbought_level")
        self.symbol = symbol
        self.macro_period = macro_period
        self.stoch_period = stoch_period
        self.oversold_level = oversold_level
        self.overbought_level = overbought_level
        self.allocation_pct = allocation_pct

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        min_bars = self.macro_period + self.stoch_period + 1
        if len(data) < min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        # ---- Screen 1: Macro trend via 50-SMA ----
        sma = data["close"].rolling(self.macro_period).mean()
        macro_bullish = float(data["close"].iloc[-1]) > float(sma.iloc[-1])

        if not macro_bullish:
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"Macro bearish: close below SMA{self.macro_period}",
                metadata={"sma": float(sma.iloc[-1])},
            )

        # ---- Screen 2: Stochastic %K pullback entry ----
        stoch_k = _stochastic_k(data, self.stoch_period)
        k_now = float(stoch_k.iloc[-1])
        k_prev = float(stoch_k.iloc[-2]) if len(stoch_k) > 1 else k_now

        if pd.isna(k_now):
            return Signal(symbol=self.symbol, direction="flat", reason="stochastic NaN")

        # Entry: %K crosses up from oversold (confirms pullback-then-bounce)
        if k_prev < self.oversold_level and k_now >= self.oversold_level:
            strength = min(1.0, (self.overbought_level - k_now) / self.overbought_level)
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.2, strength),
                reason=f"Stochastic bounce: %K {k_prev:.1f}→{k_now:.1f} from oversold in uptrend",
                metadata={"stoch_k": k_now, "sma": float(sma.iloc[-1])},
            )

        # Exit: overbought OR macro turned (macro already handled above)
        if k_now >= self.overbought_level:
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"Stochastic overbought: %K={k_now:.1f}",
                metadata={"stoch_k": k_now},
            )

        # Hold existing position or stay flat — emit "long" if %K < overbought in uptrend
        if k_now < self.overbought_level:
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=0.5,
                reason=f"Holding: uptrend + stoch %K={k_now:.1f}",
                metadata={"stoch_k": k_now},
            )

        return Signal(symbol=self.symbol, direction="flat", reason="no signal")

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
