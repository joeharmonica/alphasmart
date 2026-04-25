"""
MACD Momentum Strategy — trend-following with momentum confirmation.

Signal logic:
  Long:  MACD histogram crosses from negative to positive (MACD > signal)
  Flat:  MACD histogram crosses from positive to negative (MACD < signal) → exit

Signal strength is normalised by the rolling mean of absolute histogram values,
so large momentum swings produce stronger (larger) positions.

Position sizing: fixed-fractional (allocation_pct of portfolio equity).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import macd as compute_macd

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class MACDMomentumStrategy(Strategy):
    """
    Momentum strategy using MACD histogram crossover.

    Parameters:
        fast_period:    Fast EMA period (default 12)
        slow_period:    Slow EMA period (default 26)
        signal_period:  Signal EMA period (default 9)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
        symbol:         Asset to trade
    """

    name = "macd_momentum"

    def __init__(
        self,
        symbol: str,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        allocation_pct: float = 0.95,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError(f"fast_period ({fast_period}) must be < slow_period ({slow_period})")
        if not 0 < allocation_pct <= 1:
            raise ValueError(f"allocation_pct must be in (0, 1], got {allocation_pct}")

        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.allocation_pct = allocation_pct

        # Minimum bars: slow EMA warmup + signal EMA warmup + 2 bars to detect crossover
        self._min_bars = slow_period + signal_period + 2

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        """
        Generate signal based on MACD histogram crossover at the latest bar.
        """
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        m = compute_macd(data, fast=self.fast_period, slow=self.slow_period, signal=self.signal_period)

        hist_now = m["macd_hist"].iloc[-1]
        hist_prev = m["macd_hist"].iloc[-2]
        macd_now = m["macd"].iloc[-1]

        # Normalise strength: abs(hist) / rolling mean of abs(hist) over last 14 bars
        abs_hist = m["macd_hist"].abs()
        rolling_mean = abs_hist.iloc[-14:].mean()
        if rolling_mean > 0:
            raw_strength = abs_hist.iloc[-1] / rolling_mean
            strength = float(min(1.0, max(0.1, raw_strength * 0.5)))
        else:
            strength = 0.5

        if hist_now > 0:
            # MACD histogram is positive — bullish momentum
            crossed_up = hist_prev <= 0  # just crossed into positive
            reason = (
                f"MACD hist={hist_now:.4f} positive"
                + (" (crossover↑)" if crossed_up else "")
            )
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=reason,
                metadata={"macd": macd_now, "hist": hist_now},
            )

        # MACD histogram negative — bearish, exit
        reason = f"MACD hist={hist_now:.4f} negative"
        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=reason,
            metadata={"macd": macd_now, "hist": hist_now},
        )

    def size_position(self, signal: Signal, portfolio: "Portfolio", price: float) -> Optional[Order]:
        """
        Long signal + no position → buy.
        Flat signal + has position → sell.
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
