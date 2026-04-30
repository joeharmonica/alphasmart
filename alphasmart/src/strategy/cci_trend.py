"""
CCI Trend Strategy with Volume Confirmation.

Signal logic:
  Entry: CCI crosses above +entry_level AND volume > vol_threshold × vol_MA
  Hold:  CCI remains above exit_level (0)
  Exit:  CCI drops below exit_level (0)

Commodity Channel Index uses mean absolute deviation rather than standard
deviation, making it more robust to outliers than Bollinger/Z-score.
Volume confirmation filters low-conviction breakouts.

Internal state tracks whether we are in an active trade so that entry only
occurs on the initial CCI cross above the entry level, not on every bar
where CCI > entry_level.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import cci as compute_cci, volume_ma as compute_vol_ma

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class CCITrendStrategy(Strategy):
    """
    Trend-following strategy using CCI threshold crossings with volume filter.

    Parameters:
        period:         CCI rolling window (default 20)
        entry_level:    CCI level that must be crossed up to trigger entry (default 100)
        exit_level:     CCI level below which the trade is exited (default 0)
        vol_period:     Volume MA period for the volume filter (default 20)
        vol_threshold:  Volume must be >= this multiple of vol_MA to enter (default 1.0)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "cci_trend"

    def __init__(
        self,
        symbol: str,
        period: int = 20,
        entry_level: float = 100.0,
        exit_level: float = 0.0,
        vol_period: int = 20,
        vol_threshold: float = 1.0,
        allocation_pct: float = 0.95,
    ) -> None:
        if entry_level <= exit_level:
            raise ValueError("entry_level must be > exit_level")
        self.symbol = symbol
        self.period = period
        self.entry_level = entry_level
        self.exit_level = exit_level
        self.vol_period = vol_period
        self.vol_threshold = vol_threshold
        self.allocation_pct = allocation_pct
        self._min_bars = max(period, vol_period) + 2
        self._in_trade: bool = False

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        cci_vals = compute_cci(data, self.period)
        vol_ma = compute_vol_ma(data, self.vol_period)

        cci_now = float(cci_vals.iloc[-1])
        cci_prev = float(cci_vals.iloc[-2])
        vol_now = float(data["volume"].iloc[-1])
        vol_ma_now = float(vol_ma.iloc[-1])

        if pd.isna(cci_now) or pd.isna(vol_ma_now):
            return Signal(symbol=self.symbol, direction="flat", reason="indicator NaN")

        # Exit: CCI drops below exit_level — trend reversal
        if cci_now < self.exit_level:
            self._in_trade = False
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"CCI={cci_now:.1f} < exit_level={self.exit_level:.0f}",
                metadata={"cci": cci_now},
            )

        # Hold: already in trade, CCI still above exit_level
        if self._in_trade:
            strength = min(1.0, max(0.3, cci_now / 200.0))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=f"CCI={cci_now:.1f} holding above exit_level={self.exit_level:.0f}",
                metadata={"cci": cci_now},
            )

        # Entry: CCI crossing above entry_level with volume confirmation
        crossing_up = cci_prev <= self.entry_level < cci_now
        vol_ok = vol_now >= self.vol_threshold * vol_ma_now

        if crossing_up and vol_ok:
            self._in_trade = True
            strength = min(1.0, max(0.4, (cci_now - self.entry_level) / 100.0 + 0.5))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=(
                    f"CCI crossed {self.entry_level:.0f}: {cci_prev:.1f} → {cci_now:.1f}, "
                    f"vol={vol_now:.0f} ({vol_now/vol_ma_now:.1f}x avg)"
                ),
                metadata={"cci": cci_now, "cci_prev": cci_prev, "vol_ratio": vol_now / vol_ma_now},
            )

        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=f"CCI={cci_now:.1f} — awaiting cross above {self.entry_level:.0f}",
            metadata={"cci": cci_now},
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
