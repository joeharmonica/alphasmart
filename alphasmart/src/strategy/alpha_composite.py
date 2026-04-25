"""
AlphaSMART Proprietary Composite Strategy.

Combines three independent signal families into a weighted score:
  1. Trend signal:   EMA crossover ratio (fast/slow EMA gap → 0…1)
  2. Momentum signal: RSI normalized to entry zone (oversold → 0…1)
  3. Volume signal:  Volume > vol_ma confirmation (binary, 0 or 1)

Entry when composite score ≥ entry_threshold.
Exit  when composite score < exit_threshold.

The optimization engine can sweep:
  - Signal weights (trend_weight, rsi_weight, vol_weight)
  - Entry/exit thresholds
  - Indicator parameters (fast_ema, slow_ema, rsi_period, rsi_oversold, vol_period)
  - Objective: maximize Sharpe, CAGR, ProfitFactor, or minimize MaxDrawdown

No lookahead: all indicators computed from data[0:i+1] slices via the engine.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.strategy.base import Order, Signal, Strategy
from src.data.indicators import ema as compute_ema, rsi as compute_rsi, volume_ma

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class AlphaCompositeStrategy(Strategy):
    """
    Proprietary weighted composite strategy.

    Parameters (all user-configurable via the Optimizer UI):
        fast_ema:        Fast EMA period for trend signal (default 10)
        slow_ema:        Slow EMA period for trend signal (default 30)
        rsi_period:      RSI lookback (default 14)
        rsi_oversold:    RSI threshold defining "momentum buy zone" (default 45)
        vol_period:      Volume MA period for confirmation (default 20)
        trend_weight:    Weight for EMA trend signal in composite (default 0.45)
        rsi_weight:      Weight for RSI momentum signal (default 0.35)
        vol_weight:      Weight for volume confirmation signal (default 0.20)
        entry_threshold: Composite score required to enter (default 0.50)
        exit_threshold:  Composite score below which to exit (default 0.30)
        allocation_pct:  Fraction of portfolio equity per trade (default 0.95)
    """

    name = "alpha_composite"

    def __init__(
        self,
        symbol: str,
        fast_ema: int = 10,
        slow_ema: int = 30,
        rsi_period: int = 14,
        rsi_oversold: float = 45.0,
        vol_period: int = 20,
        trend_weight: float = 0.45,
        rsi_weight: float = 0.35,
        vol_weight: float = 0.20,
        entry_threshold: float = 0.50,
        exit_threshold: float = 0.30,
        allocation_pct: float = 0.95,
    ) -> None:
        if fast_ema >= slow_ema:
            raise ValueError(f"fast_ema ({fast_ema}) must be < slow_ema ({slow_ema})")
        total_weight = trend_weight + rsi_weight + vol_weight
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total_weight:.2f}")
        if not (0 < entry_threshold <= 1):
            raise ValueError("entry_threshold must be in (0, 1]")
        if not (0 <= exit_threshold < entry_threshold):
            raise ValueError("exit_threshold must be < entry_threshold")

        self.symbol = symbol
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.vol_period = vol_period
        self.trend_weight = trend_weight
        self.rsi_weight = rsi_weight
        self.vol_weight = vol_weight
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.allocation_pct = allocation_pct

    def _compute_composite(self, data: pd.DataFrame) -> tuple[float, dict]:
        """Compute weighted composite score [0, 1] and metadata."""
        # --- Signal 1: EMA Trend (0 to 1) ---
        fast_vals = compute_ema(data, self.fast_ema)
        slow_vals = compute_ema(data, self.slow_ema)
        fast_now = float(fast_vals.iloc[-1])
        slow_now = float(slow_vals.iloc[-1])

        if slow_now > 0 and not (pd.isna(fast_now) or pd.isna(slow_now)):
            gap_ratio = (fast_now - slow_now) / slow_now  # positive = bullish
            # Normalize: gap_ratio 0 to 0.05+ maps to signal 0 to 1
            trend_signal = float(np.clip(gap_ratio / 0.05, 0.0, 1.0))
        else:
            trend_signal = 0.0

        # --- Signal 2: RSI Momentum (0 to 1) ---
        rsi_vals = compute_rsi(data, self.rsi_period)
        rsi_now = float(rsi_vals.iloc[-1])

        if not pd.isna(rsi_now):
            # RSI below rsi_oversold is the "buy zone" — maps RSI 0…oversold to 1…0
            # RSI at oversold = signal 0.8, RSI at 50 = signal 0.4, RSI at 70+ = signal 0
            rsi_signal = float(np.clip(1.0 - (rsi_now / 100.0), 0.0, 1.0))
        else:
            rsi_signal = 0.0

        # --- Signal 3: Volume Confirmation (0 or 1) ---
        vol_ma_vals = volume_ma(data, self.vol_period)
        vol_now = float(data["volume"].iloc[-1])
        vol_ma_now = float(vol_ma_vals.iloc[-1])

        if not pd.isna(vol_ma_now) and vol_ma_now > 0:
            vol_signal = 1.0 if vol_now > vol_ma_now else 0.0
        else:
            vol_signal = 0.0

        # --- Weighted composite ---
        composite = (
            self.trend_weight * trend_signal
            + self.rsi_weight * rsi_signal
            + self.vol_weight * vol_signal
        )

        metadata = {
            "composite": round(composite, 4),
            "trend_signal": round(trend_signal, 4),
            "rsi_signal": round(rsi_signal, 4),
            "vol_signal": vol_signal,
            "rsi": round(rsi_now, 2) if not pd.isna(rsi_now) else None,
            "fast_ema": round(fast_now, 4),
            "slow_ema": round(slow_now, 4),
        }
        return composite, metadata

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        min_bars = max(self.slow_ema, self.rsi_period, self.vol_period) + 2
        if len(data) < min_bars:
            return Signal(symbol=self.symbol, direction="flat", reason="insufficient data")

        composite, meta = self._compute_composite(data)

        if composite >= self.entry_threshold:
            strength = min(1.0, composite / max(self.entry_threshold, 0.01))
            return Signal(
                symbol=self.symbol,
                direction="long",
                strength=max(0.2, min(1.0, strength)),
                reason=f"Alpha composite score {composite:.3f} ≥ {self.entry_threshold}",
                metadata=meta,
            )

        if composite < self.exit_threshold:
            return Signal(
                symbol=self.symbol,
                direction="flat",
                reason=f"Alpha composite score {composite:.3f} < {self.exit_threshold} (exit)",
                metadata=meta,
            )

        # Neutral zone — hold if long, don't initiate new position
        return Signal(
            symbol=self.symbol,
            direction="long",
            strength=0.3,
            reason=f"Alpha composite neutral: {composite:.3f}",
            metadata=meta,
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
