"""
Volatility-targeting wrapper for AlphaSMART.

VolTargetStrategy wraps any base Strategy and rescales the position size so
that realized vol of the position is approximately `target_vol` (annualised).

    scale = target_vol / max(realized_vol, vol_floor)
    new_quantity = inner_quantity * clip(scale, 0, max_leverage)

Hypothesis (lessons.md #33): the dominant failure mode in the project's
bootstrap pipeline is path-dependence on a specific volatility regime.
Strategies tuned on a 5-yr window inherit that window's vol structure;
when block-bootstrap reshuffles return blocks, the strategy's position
sizing is mismatched to the realised vol → drawdown. Constant-vol
position sizing breaks that link.

Caveats:
  - Sharpe is *scale-invariant* — vol-targeting alone won't lift a
    fundamentally weak signal. It compresses the *distribution* of
    bootstrap outcomes (narrower tails) but the median may not shift.
  - Risk engine caps position at max_position_pct of equity. If the
    inner already requested >= the cap, scaling up gets rejected.
  - Compose with `+stop` as `<base>+stop+vol`: TrailingStop on the
    inside (overrides direction), VolTarget on the outside (overrides
    quantity). See `_make_strategy` for the suffix-chain dispatch.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from src.strategy.base import Order, Signal, Strategy

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


class VolTargetStrategy(Strategy):
    """
    Wraps a base Strategy and rescales position size to target a constant
    realised volatility.

    Parameters:
        inner:        Base Strategy instance (must expose .symbol).
        target_vol:   Annualised target volatility (default 0.15 = 15%).
        vol_period:   Rolling window for realised vol (default 20 bars).
        bars_per_year: Annualisation factor (default 252 — daily). Caller
                       should override for non-daily timeframes.
        max_leverage: Cap on the scale factor (default 1.5x). Prevents
                       blowing past the risk engine's max-position cap
                       in low-vol regimes; also suppresses divide-by-zero
                       blow-ups.
        vol_floor:    Floor on realised_vol used in the denominator
                       (default 0.05 = 5% annualised). Prevents extreme
                       upscaling when the trailing window is artificially
                       quiet.
    """

    def __init__(
        self,
        inner: Strategy,
        target_vol: float = 0.15,
        vol_period: int = 20,
        bars_per_year: int = 252,
        max_leverage: float = 1.5,
        vol_floor: float = 0.05,
    ) -> None:
        if target_vol <= 0:
            raise ValueError("target_vol must be positive")
        if vol_period < 2:
            raise ValueError("vol_period must be >= 2")
        if max_leverage <= 0:
            raise ValueError("max_leverage must be positive")

        symbol = getattr(inner, "symbol", None)
        if symbol is None:
            raise ValueError("inner strategy must have a .symbol attribute")

        self.inner = inner
        self.symbol = symbol
        self.target_vol = float(target_vol)
        self.vol_period = int(vol_period)
        self.bars_per_year = int(bars_per_year)
        self.max_leverage = float(max_leverage)
        self.vol_floor = float(vol_floor)
        self.name = f"{inner.name}+vol"

        # Updated in generate_signals(); read in size_position(). The wrapper
        # contract requires the engine to call generate_signals() before
        # size_position() at every bar — same contract as TrailingStop.
        self._scale: float = 1.0

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        # Compute realised vol on log returns over the last vol_period bars.
        if len(data) >= self.vol_period + 1:
            log_returns = np.log(data["close"] / data["close"].shift(1)).dropna()
            window = log_returns.iloc[-self.vol_period:]
            std_per_bar = float(window.std(ddof=1)) if len(window) >= 2 else 0.0
            realised_vol = std_per_bar * math.sqrt(self.bars_per_year)
            denom = max(realised_vol, self.vol_floor)
            self._scale = min(self.target_vol / denom, self.max_leverage)
        else:
            # Pre-window: pass through with no scaling.
            self._scale = 1.0

        return self.inner.generate_signals(data)

    def size_position(
        self,
        signal: Signal,
        portfolio: "Portfolio",
        price: float,
    ) -> Optional[Order]:
        order = self.inner.size_position(signal, portfolio, price)
        if order is None:
            return None
        # Rescale quantity. Floor at small positive value; engine rejects
        # zero/negative quantities so prefer skipping the order.
        new_qty = order.quantity * self._scale
        if new_qty <= 0:
            return None
        return Order(
            symbol=order.symbol,
            side=order.side,
            quantity=new_qty,
            order_type=order.order_type,
            timestamp=order.timestamp,
            strategy_name=order.strategy_name,
        )
