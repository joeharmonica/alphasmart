"""
Squeeze Momentum Breakout — volatility compression + directional release.

Based on the TTM Squeeze concept: when Bollinger Bands contract inside a
Keltner Channel, the market is in a low-volatility squeeze. When the bands
expand beyond the Keltner Channel, the squeeze releases — energy is
discharged directionally. Enter on release when momentum is positive.

Signal logic:
  Squeeze ON:  BB_upper < KC_upper AND BB_lower > KC_lower
  Squeeze OFF: BB expands back outside Keltner
  Entry:  squeeze was ON last bar AND is now OFF AND momentum > 0
  Hold:   momentum remains positive (price above midpoint benchmark)
  Exit:   momentum turns negative (price falls below midpoint benchmark)

Momentum benchmark = (max_high(mom_period) + min_low(mom_period)) / 2
                   — the midpoint of the recent price range.
Positive momentum: close > benchmark (upward release).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import numpy as np

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import (
    bollinger_bands as compute_bb,
    keltner_channel as compute_kc,
)

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class SqueezeMomentumStrategy(Strategy):
    """
    Breakout strategy triggered by Bollinger/Keltner squeeze release.

    Parameters:
        bb_period:      Bollinger Band rolling window (default 20)
        bb_std:         Bollinger Band standard deviation multiplier (default 2.0)
        kc_period:      Keltner Channel EMA period (default 20)
        kc_atr_period:  ATR period for Keltner width (default 14)
        kc_mult:        Keltner ATR multiplier (default 1.5)
        mom_period:     Momentum benchmark lookback (default 20)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "squeeze_momentum"

    def __init__(
        self,
        symbol: str,
        bb_period: int = 20,
        bb_std: float = 2.0,
        kc_period: int = 20,
        kc_atr_period: int = 14,
        kc_mult: float = 1.5,
        mom_period: int = 20,
        allocation_pct: float = 0.95,
    ) -> None:
        self.symbol = symbol
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.kc_period = kc_period
        self.kc_atr_period = kc_atr_period
        self.kc_mult = kc_mult
        self.mom_period = mom_period
        self.allocation_pct = allocation_pct
        self._min_bars = max(bb_period, kc_period, kc_atr_period, mom_period) + 4
        self._in_trade: bool = False

    def _squeeze_state(
        self, bb_upper: float, bb_lower: float, kc_upper: float, kc_lower: float
    ) -> bool:
        """Return True if BB is inside Keltner (squeeze is ON)."""
        return bb_upper < kc_upper and bb_lower > kc_lower

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        bb = compute_bb(data, period=self.bb_period, std_dev=self.bb_std)
        kc = compute_kc(data, period=self.kc_period, atr_period=self.kc_atr_period, atr_mult=self.kc_mult)

        bb_upper_now = float(bb["bb_upper"].iloc[-1])
        bb_lower_now = float(bb["bb_lower"].iloc[-1])
        bb_upper_prev = float(bb["bb_upper"].iloc[-2])
        bb_lower_prev = float(bb["bb_lower"].iloc[-2])

        kc_upper_now = float(kc["kc_upper"].iloc[-1])
        kc_lower_now = float(kc["kc_lower"].iloc[-1])
        kc_upper_prev = float(kc["kc_upper"].iloc[-2])
        kc_lower_prev = float(kc["kc_lower"].iloc[-2])

        if any(pd.isna(v) for v in [bb_upper_now, kc_upper_now, bb_lower_now, kc_lower_now]):
            return Signal(symbol=self.symbol, direction="flat", reason="indicator NaN")

        squeeze_now = self._squeeze_state(bb_upper_now, bb_lower_now, kc_upper_now, kc_lower_now)
        squeeze_prev = self._squeeze_state(bb_upper_prev, bb_lower_prev, kc_upper_prev, kc_lower_prev)

        # Momentum: close vs. midpoint of highest-high / lowest-low range
        high_max = float(data["high"].rolling(self.mom_period).max().iloc[-1])
        low_min = float(data["low"].rolling(self.mom_period).min().iloc[-1])
        close_now = float(data["close"].iloc[-1])
        benchmark = (high_max + low_min) / 2.0
        momentum = close_now - benchmark  # positive = upward pressure

        squeeze_released = squeeze_prev and not squeeze_now
        momentum_positive = momentum > 0

        # Exit: momentum turned negative
        if self._in_trade and not momentum_positive:
            self._in_trade = False
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"Momentum turned negative ({momentum:.2f}) — exit",
                metadata={"squeeze_now": squeeze_now, "momentum": momentum},
            )

        # Hold: in trade, momentum still positive
        if self._in_trade and momentum_positive:
            strength = min(1.0, max(0.3, momentum / (high_max - low_min + 1e-9)))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=f"Squeeze hold: momentum={momentum:.2f}",
                metadata={"squeeze_now": squeeze_now, "momentum": momentum},
            )

        # Entry: squeeze just released with positive momentum
        if squeeze_released and momentum_positive:
            self._in_trade = True
            strength = min(1.0, max(0.5, momentum / (high_max - low_min + 1e-9)))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=(
                    f"Squeeze released! BB expanded outside Keltner. "
                    f"Momentum={momentum:.2f} > 0"
                ),
                metadata={"squeeze_now": squeeze_now, "squeeze_prev": squeeze_prev, "momentum": momentum},
            )

        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=(
                f"Squeeze={'ON' if squeeze_now else 'OFF (awaiting)'}. "
                f"Momentum={'↑' if momentum_positive else '↓'} ({momentum:.2f})"
            ),
            metadata={"squeeze_now": squeeze_now, "momentum": momentum},
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
