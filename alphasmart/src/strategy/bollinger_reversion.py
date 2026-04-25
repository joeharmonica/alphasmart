"""
Bollinger Band Mean Reversion Strategy.

Signal logic:
  Long:  close < bb_lower (price breaks below lower band — oversold dip)
  Flat:  close > bb_mid   (price returns to middle band — take profit)
  Flat:  close > bb_upper (price breaks above upper band — overextended, exit)

Signal strength: how far below the midline (normalised), capped at 1.0.
The further below the midline, the stronger the reversion opportunity.

Position sizing: fixed-fractional (allocation_pct of portfolio equity).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import bollinger_bands as compute_bb

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class BollingerReversionStrategy(Strategy):
    """
    Mean-reversion strategy using Bollinger Band extremes.

    Parameters:
        period:         Bollinger Band rolling window (default 20)
        std_dev:        Number of standard deviations for bands (default 2.0)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
        symbol:         Asset to trade
    """

    name = "bb_reversion"

    def __init__(
        self,
        symbol: str,
        period: int = 20,
        std_dev: float = 2.0,
        allocation_pct: float = 0.95,
    ) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}")
        if std_dev <= 0:
            raise ValueError(f"std_dev must be > 0, got {std_dev}")
        if not 0 < allocation_pct <= 1:
            raise ValueError(f"allocation_pct must be in (0, 1], got {allocation_pct}")

        self.symbol = symbol
        self.period = period
        self.std_dev = std_dev
        self.allocation_pct = allocation_pct
        self._min_bars = period + 1

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        """
        Generate signal based on Bollinger Band position at the latest bar.
        """
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        bb = compute_bb(data, period=self.period, std_dev=self.std_dev)

        close = float(data["close"].iloc[-1])
        bb_lower = float(bb["bb_lower"].iloc[-1])
        bb_mid = float(bb["bb_mid"].iloc[-1])
        bb_upper = float(bb["bb_upper"].iloc[-1])
        pct_b = float(bb["bb_pct_b"].iloc[-1]) if not pd.isna(bb["bb_pct_b"].iloc[-1]) else 0.5

        # Long: price at or below lower band
        if close <= bb_lower:
            # Strength: how far below the midline relative to band width
            band_width = bb_upper - bb_lower if bb_upper > bb_lower else 1.0
            distance_below_mid = max(0, bb_mid - close)
            strength = float(min(1.0, max(0.1, distance_below_mid / (band_width * 0.5))))
            reason = f"close={close:.4f} ≤ bb_lower={bb_lower:.4f} (%B={pct_b:.2f})"
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=reason,
                metadata={"bb_lower": bb_lower, "bb_mid": bb_mid, "bb_upper": bb_upper, "pct_b": pct_b},
            )

        # Flat: price returned to or above midline → exit
        if close >= bb_mid:
            reason = f"close={close:.4f} ≥ bb_mid={bb_mid:.4f} — mean reversion complete"
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=reason,
                metadata={"bb_lower": bb_lower, "bb_mid": bb_mid, "bb_upper": bb_upper, "pct_b": pct_b},
            )

        # Between lower band and midline — hold existing position (flat = no new entry)
        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=f"close={close:.4f} between bb_lower and bb_mid — no signal",
            metadata={"bb_lower": bb_lower, "bb_mid": bb_mid, "bb_upper": bb_upper, "pct_b": pct_b},
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
