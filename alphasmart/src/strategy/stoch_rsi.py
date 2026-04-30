"""
Stochastic RSI — momentum crossover strategy.

StochRSI applies the Stochastic formula to RSI values rather than raw price,
producing a faster oscillator that detects RSI exhaustion before price reversal.

Signal logic:
  Entry: %K crosses above oversold (20) from below, with %K > %D (momentum alignment)
  Hold:  %K between oversold and overbought
  Exit:  %K crosses above overbought (80) — take profit at momentum peak
         OR %K falls back below oversold — failed bounce

Parameters:
  rsi_period:   RSI calculation period (default 14)
  stoch_period: Stochastic lookback on RSI values (default 14)
  smooth_k:     SMA smoothing on raw stochastic (default 3)
  smooth_d:     SMA of %K — signal line (default 3)
  oversold:     %K threshold for entry zone (default 20)
  overbought:   %K threshold for exit zone (default 80)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import stoch_rsi as compute_stoch_rsi, ema as compute_ema

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class StochRSIStrategy(Strategy):
    """
    Momentum crossover strategy using Stochastic RSI.

    Parameters:
        rsi_period:     RSI period (default 14)
        stoch_period:   Stochastic window applied to RSI (default 14)
        smooth_k:       %K smoothing period (default 3)
        smooth_d:       %D smoothing period (default 3)
        oversold:       %K level for oversold entry zone (default 20)
        overbought:     %K level for overbought exit zone (default 80)
        allocation_pct: Fraction of portfolio equity per trade (default 0.95)
    """

    name = "stoch_rsi"

    def __init__(
        self,
        symbol: str,
        rsi_period: int = 14,
        stoch_period: int = 14,
        smooth_k: int = 3,
        smooth_d: int = 3,
        oversold: float = 20.0,
        overbought: float = 80.0,
        sma_period: int = 200,
        allocation_pct: float = 0.95,
    ) -> None:
        if oversold >= overbought:
            raise ValueError("oversold must be < overbought")
        self.symbol = symbol
        self.rsi_period = rsi_period
        self.stoch_period = stoch_period
        self.smooth_k = smooth_k
        self.smooth_d = smooth_d
        self.oversold = oversold
        self.overbought = overbought
        self.sma_period = sma_period
        self.allocation_pct = allocation_pct
        self._min_bars = max(rsi_period + stoch_period + smooth_k + smooth_d + 4, sma_period + 1)
        self._in_trade: bool = False

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        if len(data) < self._min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        sr = compute_stoch_rsi(
            data,
            rsi_period=self.rsi_period,
            stoch_period=self.stoch_period,
            smooth_k=self.smooth_k,
            smooth_d=self.smooth_d,
        )

        k_now = float(sr["stochrsi_k"].iloc[-1])
        k_prev = float(sr["stochrsi_k"].iloc[-2])
        d_now = float(sr["stochrsi_d"].iloc[-1])
        close_now = float(data["close"].iloc[-1])

        # SMA trend filter — only trade in bull regime
        sma = compute_ema(data, self.sma_period)
        sma_now = float(sma.iloc[-1])
        in_bull_regime = not pd.isna(sma_now) and close_now > sma_now

        if pd.isna(k_now) or pd.isna(d_now):
            return Signal(symbol=self.symbol, direction="flat", reason="indicator NaN")

        # Exit conditions
        if self._in_trade:
            # Regime exit: trend flipped to bear
            if not in_bull_regime:
                self._in_trade = False
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=f"Regime exit: close={close_now:.2f} < SMA({self.sma_period})={sma_now:.2f}",
                    metadata={"k": k_now, "sma": sma_now},
                )
            # Take profit: %K reaches overbought
            if k_now >= self.overbought:
                self._in_trade = False
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=f"StochRSI %K={k_now:.1f} ≥ overbought={self.overbought:.0f}",
                    metadata={"k": k_now, "d": d_now},
                )
            # Failed bounce: %K fell back below oversold
            if k_now < self.oversold:
                self._in_trade = False
                return Signal(
                    symbol=self.symbol,
                    direction="flat",
                    reason=f"StochRSI %K={k_now:.1f} failed — back below oversold",
                    metadata={"k": k_now, "d": d_now},
                )
            # Hold: in bull regime, between oversold and overbought
            strength = min(1.0, max(0.3, k_now / 100.0))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=f"StochRSI holding: %K={k_now:.1f}, %D={d_now:.1f}",
                metadata={"k": k_now, "d": d_now},
            )

        # Entry: %K crosses above oversold from below, %K > %D, and in bull regime
        k_cross_up = k_prev <= self.oversold < k_now
        momentum_aligned = k_now > d_now

        if k_cross_up and momentum_aligned and in_bull_regime:
            self._in_trade = True
            strength = min(1.0, max(0.4, (k_now - self.oversold) / (self.overbought - self.oversold) + 0.3))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=strength,
                reason=(
                    f"StochRSI crossed up: %K {k_prev:.1f}→{k_now:.1f} "
                    f"| %K > %D ({d_now:.1f}) | SMA OK"
                ),
                metadata={"k": k_now, "k_prev": k_prev, "d": d_now, "sma": sma_now},
            )

        return Signal(
            symbol=self.symbol,
            direction="flat",
            reason=(
                f"StochRSI %K={k_now:.1f} — "
                + ("awaiting oversold cross" if in_bull_regime else f"bear regime (close < SMA{self.sma_period})")
            ),
            metadata={"k": k_now, "d": d_now, "in_bull": in_bull_regime},
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
