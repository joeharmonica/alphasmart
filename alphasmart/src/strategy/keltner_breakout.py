"""
Keltner Channel Breakout strategy — optimised for 1H timeframe.

Logic:
  Mid-line  = EMA(close, period)
  Upper/lower = Mid ± atr_mult × ATR(atr_period)

  Entry: close crosses above upper Keltner band AND close > EMA(trend_period)
         → momentum expansion into a trending move
  Hold:  close stays above kc_mid
  Exit:  close drops below kc_mid — momentum fading, revert to mean

Keltner channels adapt to intraday ATR, so the breakout threshold widens
in high-volatility sessions (earnings, macro events) and narrows in quiet
sessions — far fewer false breakouts than fixed-pip thresholds.

No lookahead: all indicators computed on data[0:i+1] slices from the engine.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import keltner_channel, ema as compute_ema

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class KeltnerBreakoutStrategy(Strategy):
    """
    Keltner channel momentum breakout with trend filter.

    Parameters:
        period:       EMA period for Keltner mid-line (default 20)
        atr_period:   ATR period for channel width (default 14)
        atr_mult:     ATR multiplier for band distance (default 1.5)
        trend_period: Long EMA for bull-regime filter (default 200)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "keltner_breakout"

    def __init__(
        self,
        symbol: str,
        period: int = 20,
        atr_period: int = 14,
        atr_mult: float = 1.5,
        trend_period: int = 200,
        allocation_pct: float = 0.95,
    ) -> None:
        self.symbol = symbol
        self.period = period
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.trend_period = trend_period
        self.allocation_pct = allocation_pct
        self._min_bars = max(period, atr_period, trend_period) + 2
        self._in_trade: bool = False

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        kc = keltner_channel(data, period=self.period, atr_period=self.atr_period, atr_mult=self.atr_mult)
        trend_ema = compute_ema(data, self.trend_period)

        close_now  = float(data["close"].iloc[-1])
        close_prev = float(data["close"].iloc[-2])
        kc_upper   = float(kc["kc_upper"].iloc[-1])
        kc_mid     = float(kc["kc_mid"].iloc[-1])
        kc_upper_prev = float(kc["kc_upper"].iloc[-2])
        trend_now  = float(trend_ema.iloc[-1])

        import pandas as _pd
        if _pd.isna(kc_upper) or _pd.isna(kc_mid) or _pd.isna(trend_now):
            return Signal(symbol=self.symbol, direction="flat", reason="indicator NaN")

        in_bull = close_now > trend_now

        if self._in_trade:
            if not in_bull:
                self._in_trade = False
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=f"Regime exit: close={close_now:.2f} < EMA({self.trend_period})={trend_now:.2f}",
                )
            if close_now < kc_mid:
                self._in_trade = False
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=f"Keltner mid exit: close={close_now:.2f} < mid={kc_mid:.2f}",
                    metadata={"kc_mid": kc_mid},
                )
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=0.8,
                reason=f"Keltner holding: close={close_now:.2f} > mid={kc_mid:.2f}",
                metadata={"kc_upper": kc_upper, "kc_mid": kc_mid},
            )

        # Entry: close crosses above upper band (was below, now above) AND bull regime
        crossed_up = close_prev <= kc_upper_prev and close_now > kc_upper
        if crossed_up and in_bull:
            self._in_trade = True
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=0.9,
                reason=f"Keltner breakout: close={close_now:.2f} > upper={kc_upper:.2f}",
                metadata={"kc_upper": kc_upper, "kc_mid": kc_mid, "trend": trend_now},
            )

        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=(
                f"Keltner waiting: close={close_now:.2f} "
                + (f"< upper={kc_upper:.2f}" if in_bull else f"(bear regime < EMA{self.trend_period})")
            ),
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
