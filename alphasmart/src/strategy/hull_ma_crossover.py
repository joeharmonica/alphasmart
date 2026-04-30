"""
Hull Moving Average (HMA) Crossover strategy — optimised for 1H timeframe.

Hull MA eliminates lag while preserving smoothness, making it ideal for
intraday trend following where standard EMA crossovers are too slow.

Formula:
  WMA(n) = weighted moving average period n
  HMA(n) = WMA( 2×WMA(n/2) − WMA(n),  √n )

Signal logic:
  Entry: fast HMA(fast_period) crosses above slow HMA(slow_period)
  Exit:  fast HMA crosses below slow HMA
  Trend filter: close > EMA(trend_period) — only long in bull regime

HMA advantage over EMA crossover: near-zero lag, responds to direction
changes in 1-2 bars rather than 4-6, drastically reducing whipsaw hold
time while keeping the signal clean.

No lookahead: all indicators computed on data[0:i+1] slices from the engine.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import ema as compute_ema

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


def _wma(series: pd.Series, period: int) -> pd.Series:
    """Linearly weighted moving average."""
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def _hma(series: pd.Series, period: int) -> pd.Series:
    """Hull Moving Average."""
    half = max(1, period // 2)
    sqrt_n = max(2, int(np.sqrt(period)))
    raw = 2.0 * _wma(series, half) - _wma(series, period)
    return _wma(raw, sqrt_n)


class HullMACrossoverStrategy(Strategy):
    """
    Hull Moving Average crossover with bull-regime filter.

    Parameters:
        fast_period:  HMA period for fast line (default 21)
        slow_period:  HMA period for slow line (default 50)
        trend_period: EMA period for regime filter (default 200)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "hull_ma_crossover"

    def __init__(
        self,
        symbol: str,
        fast_period: int = 21,
        slow_period: int = 50,
        trend_period: int = 200,
        allocation_pct: float = 0.95,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")
        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.trend_period = trend_period
        self.allocation_pct = allocation_pct
        # HMA(n) needs n + √n + n/2 bars to warm up
        sqrt_fast = max(2, int(np.sqrt(fast_period)))
        sqrt_slow = max(2, int(np.sqrt(slow_period)))
        self._min_bars = max(
            slow_period + sqrt_slow + slow_period // 2,
            trend_period,
        ) + 4
        self._in_trade: bool = False

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        fast = _hma(data["close"], self.fast_period)
        slow = _hma(data["close"], self.slow_period)
        trend = compute_ema(data, self.trend_period)

        fast_now  = float(fast.iloc[-1])
        fast_prev = float(fast.iloc[-2])
        slow_now  = float(slow.iloc[-1])
        slow_prev = float(slow.iloc[-2])
        trend_now = float(trend.iloc[-1])
        close_now = float(data["close"].iloc[-1])

        if pd.isna(fast_now) or pd.isna(slow_now) or pd.isna(trend_now):
            return Signal(symbol=self.symbol, direction="flat", reason="indicator NaN")

        in_bull = close_now > trend_now

        cross_up   = fast_prev <= slow_prev and fast_now > slow_now
        cross_down = fast_prev >= slow_prev and fast_now < slow_now

        if self._in_trade:
            if cross_down or not in_bull:
                self._in_trade = False
                reason = "HMA bearish cross" if cross_down else f"Bear regime (close < EMA{self.trend_period})"
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=reason,
                    metadata={"fast": fast_now, "slow": slow_now},
                )
            gap = (fast_now - slow_now) / slow_now
            strength = min(1.0, 0.6 + gap * 20)
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=f"HMA holding: fast={fast_now:.2f} > slow={slow_now:.2f}",
                metadata={"fast": fast_now, "slow": slow_now},
            )

        if cross_up and in_bull:
            self._in_trade = True
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=0.85,
                reason=f"HMA bullish cross: fast={fast_now:.2f} crossed above slow={slow_now:.2f}",
                metadata={"fast": fast_now, "slow": slow_now, "trend": trend_now},
            )

        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=(
                f"HMA waiting: fast={fast_now:.2f} vs slow={slow_now:.2f} "
                + ("(bear regime)" if not in_bull else "")
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
