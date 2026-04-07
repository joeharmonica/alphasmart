"""
AlphaSMART Alpha Composite V2 — data-driven variants.

Two variants derived from Step 1/4 optimization feedback analysis:

AlphaCompositeTrendV2 — "Trend-Heavy"
  Parameters from top optimizer runs (NVDA/SPY/QQQ):
  - trend_weight=0.50 (+0.05 vs default): EMA crossover dominates
  - rsi_weight=0.30  (unchanged)
  - vol_weight=0.20  (-0.05): volume confirmation de-emphasised
  - rsi_oversold=40.0: less conservative buy zone (consistent finding across symbols)
  - entry_threshold=0.50 (default)
  - fast_ema=13, slow_ema=30: consistent top-performing values

AlphaMomentumV2 — "Momentum-Focused"
  Parameters: RSI/momentum signal upweighted
  - trend_weight=0.35 (-0.10 vs default)
  - rsi_weight=0.40  (+0.05): RSI momentum leads
  - vol_weight=0.25  (+0.05): moderate volume confirmation
  - rsi_oversold=40.0: same data-driven threshold
  - entry_threshold=0.45: slightly easier entry (regime filter compensates for false positives)
  - fast_ema=10, slow_ema=25: tighter crossover for more signals

Both variants expose the same optimizer-compatible interface as AlphaCompositeStrategy.
"""
from __future__ import annotations

from src.strategy.alpha_composite import AlphaCompositeStrategy


class AlphaCompositeTrendV2(AlphaCompositeStrategy):
    """
    Trend-Heavy composite — EMA crossover weighted 0.50.

    Data-driven defaults from Step 1 optimization feedback:
      fast_ema=13, slow_ema=30, rsi_oversold=40, trend_weight=0.50,
      rsi_weight=0.30, vol_weight=0.20, entry_threshold=0.50
    """

    name = "alpha_trend_v2"

    def __init__(
        self,
        symbol: str,
        fast_ema: int = 13,
        slow_ema: int = 30,
        rsi_period: int = 10,
        rsi_oversold: float = 40.0,
        vol_period: int = 20,
        trend_weight: float = 0.50,
        rsi_weight: float = 0.30,
        vol_weight: float = 0.20,
        entry_threshold: float = 0.50,
        exit_threshold: float = 0.30,
        allocation_pct: float = 0.95,
    ) -> None:
        super().__init__(
            symbol=symbol,
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            rsi_period=rsi_period,
            rsi_oversold=rsi_oversold,
            vol_period=vol_period,
            trend_weight=trend_weight,
            rsi_weight=rsi_weight,
            vol_weight=vol_weight,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            allocation_pct=allocation_pct,
        )


class AlphaMomentumV2(AlphaCompositeStrategy):
    """
    Momentum-Focused composite — RSI signal weighted 0.40.

    Data-driven defaults from Step 1 optimization feedback:
      fast_ema=10, slow_ema=25, rsi_oversold=40, trend_weight=0.35,
      rsi_weight=0.40, vol_weight=0.25, entry_threshold=0.45
    """

    name = "alpha_momentum_v2"

    def __init__(
        self,
        symbol: str,
        fast_ema: int = 10,
        slow_ema: int = 25,
        rsi_period: int = 10,
        rsi_oversold: float = 40.0,
        vol_period: int = 20,
        trend_weight: float = 0.35,
        rsi_weight: float = 0.40,
        vol_weight: float = 0.25,
        entry_threshold: float = 0.45,
        exit_threshold: float = 0.25,
        allocation_pct: float = 0.95,
    ) -> None:
        super().__init__(
            symbol=symbol,
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            rsi_period=rsi_period,
            rsi_oversold=rsi_oversold,
            vol_period=vol_period,
            trend_weight=trend_weight,
            rsi_weight=rsi_weight,
            vol_weight=vol_weight,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            allocation_pct=allocation_pct,
        )
