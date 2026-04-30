"""
Williams %R with Trend Filter — mean-reversion within confirmed uptrends.

Signal logic:
  Entry: Williams %R crosses UP from oversold zone (< oversold_level)
         AND close > SMA(sma_period) [bull regime filter]
  Hold:  %R above oversold_level AND close > SMA
  Exit:  %R reaches overbought zone (> overbought_level)
         OR close crosses below SMA (regime change)

Williams %R uses the price range (highest high / lowest low) rather than
momentum-based smoothing, giving it a different signal character from RSI.
The SMA(200) trend filter restricts entries to confirmed bull regimes,
avoiding pullback entries during sustained downtrends.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import williams_r as compute_wr, ema as compute_ema

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class WilliamsRStrategy(Strategy):
    """
    Mean-reversion pullback strategy using Williams %R with a trend filter.

    Parameters:
        period:         Lookback period for Williams %R (default 14)
        oversold:       %R threshold for oversold entry zone (default -80)
        overbought:     %R threshold for overbought exit zone (default -20)
        sma_period:     Trend filter SMA period; must be above this to enter (default 200)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "williams_r"

    def __init__(
        self,
        symbol: str,
        period: int = 14,
        oversold: float = -80.0,
        overbought: float = -20.0,
        sma_period: int = 200,
        allocation_pct: float = 0.95,
    ) -> None:
        if oversold >= overbought:
            raise ValueError("oversold must be < overbought (both negative, e.g. -80, -20)")
        self.symbol = symbol
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.sma_period = sma_period
        self.allocation_pct = allocation_pct
        self._min_bars = max(period, sma_period) + 2
        self._in_trade: bool = False

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        wr = compute_wr(data, self.period)
        sma = compute_ema(data, self.sma_period)  # use EMA for smoothness

        wr_now = float(wr.iloc[-1])
        wr_prev = float(wr.iloc[-2])
        close_now = float(data["close"].iloc[-1])
        sma_now = float(sma.iloc[-1])

        if pd.isna(wr_now) or pd.isna(sma_now):
            return Signal(symbol=self.symbol, direction="flat", reason="indicator NaN")

        in_bull_regime = close_now > sma_now

        # Exit conditions (checked first to close positions promptly)
        if self._in_trade:
            # Take profit: price reached overbought zone
            if wr_now > self.overbought:
                self._in_trade = False
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=f"%R={wr_now:.1f} > overbought={self.overbought:.0f} — take profit",
                    metadata={"wr": wr_now, "sma": sma_now},
                )
            # Stop: regime flipped to bear
            if not in_bull_regime:
                self._in_trade = False
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=f"close={close_now:.2f} < SMA({self.sma_period})={sma_now:.2f} — regime exit",
                    metadata={"wr": wr_now, "sma": sma_now},
                )
            # Hold: still in bull regime and not yet overbought
            strength = min(1.0, max(0.3, (-wr_now) / 100.0))  # stronger when deeper in range
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=f"%R={wr_now:.1f} holding | SMA OK",
                metadata={"wr": wr_now, "sma": sma_now},
            )

        # Entry: %R crosses up from oversold AND in bull regime
        crossing_up_from_oversold = wr_prev <= self.oversold and wr_now > self.oversold
        if crossing_up_from_oversold and in_bull_regime:
            self._in_trade = True
            # Strength: how deeply oversold we were at entry
            strength = min(1.0, max(0.4, abs(wr_prev) / 100.0))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=(
                    f"%R crossed up from oversold: {wr_prev:.1f} → {wr_now:.1f} "
                    f"| close={close_now:.2f} > SMA={sma_now:.2f}"
                ),
                metadata={"wr": wr_now, "wr_prev": wr_prev, "sma": sma_now},
            )

        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=f"%R={wr_now:.1f} | bull_regime={in_bull_regime} — no entry",
            metadata={"wr": wr_now, "sma": sma_now},
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
