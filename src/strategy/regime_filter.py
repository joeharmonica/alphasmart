"""
Market regime filter for AlphaSMART strategies.

RegimeFilteredStrategy wraps any existing Strategy and suppresses BUY signals
when the market is in a bear regime (SPY close below its 200-day SMA).

Design:
  - SPY SMA200 is pre-computed at construction time from DB data (no lookahead).
  - At each bar, the current date is looked up in the pre-computed regime Series.
  - If regime = bear (False), long signals are converted to flat.
  - Exit signals (flat when holding) are always passed through — no forced holding.
  - Default = bullish if SPY data is unavailable for a given date (fail-safe).

Usage:
    # From database
    base = EMACrossoverStrategy("NVDA")
    filtered = RegimeFilteredStrategy.from_db(base, "sqlite:///alphasmart_dev.db")

    # From pre-computed series (e.g. in walk-forward slices)
    filtered = RegimeFilteredStrategy(base, spy_regime_series)

Integration:
  - BatchRunner: pass regime-filtered factories to run_all()
  - Optimizer: wrap strategy at instantiation; SPY series sliced to IS/OOS window
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import pandas as pd

from src.strategy.base import Order, Signal, Strategy

if TYPE_CHECKING:
    from src.strategy.portfolio import Portfolio


class RegimeFilteredStrategy(Strategy):
    """
    Transparent wrapper: passes all signals through when SPY > SMA200,
    converts 'long' signals to 'flat' when SPY < SMA200 (bear regime).

    Args:
        base_strategy:   The underlying strategy to wrap.
        spy_regime:      pd.Series[bool], True = bull regime (SPY >= SMA200).
                         Index must be tz-naive pd.DatetimeIndex at daily frequency.
        sma_period:      Lookback used to compute SMA (stored for repr only).
    """

    def __init__(
        self,
        base_strategy: Strategy,
        spy_regime: pd.Series,
        sma_period: int = 200,
    ) -> None:
        self._base = base_strategy
        self._spy_regime = spy_regime
        self._sma_period = sma_period
        # Expose required Strategy attributes
        self.symbol = base_strategy.symbol
        self.name = f"{base_strategy.name}+regime"

    @classmethod
    def from_db(
        cls,
        base_strategy: Strategy,
        db_url: str,
        spy_symbol: str = "SPY",
        sma_period: int = 200,
    ) -> "RegimeFilteredStrategy":
        """
        Load SPY daily data from DB, compute rolling SMA200 regime, and wrap strategy.

        The rolling SMA only uses data up to each date (causal) — no lookahead.
        """
        from src.data.database import Database
        db = Database(db_url)
        spy = db.query_ohlcv(spy_symbol, timeframe="1d")
        if spy.empty:
            raise ValueError(
                f"No {spy_symbol} data in DB. Run: python main.py fetch {spy_symbol} --period 5y"
            )
        regime = cls._compute_regime(spy["close"], sma_period)
        return cls(base_strategy, regime, sma_period)

    @staticmethod
    def _compute_regime(close: pd.Series, sma_period: int) -> pd.Series:
        """Compute bull/bear regime: True when close >= rolling SMA."""
        sma = close.rolling(sma_period, min_periods=sma_period).mean()
        regime = close >= sma
        # NaN during warmup → default to True (give benefit of doubt early in history)
        regime = regime.fillna(True)
        # Normalise index to tz-naive date
        idx = regime.index
        if hasattr(idx, "tz") and idx.tz is not None:
            idx = idx.tz_localize(None)
        regime.index = pd.DatetimeIndex(idx).normalize()
        return regime

    def _is_bull(self, data: pd.DataFrame) -> bool:
        """Return True if the current bar's date is in bull regime."""
        bar_ts = data.index[-1]
        # Normalise to tz-naive day
        ts = pd.Timestamp(bar_ts)
        if ts.tz is not None:
            ts = ts.tz_localize(None)
        bar_day = ts.normalize()
        # Use .get() equivalent: locate nearest prior date if exact miss
        if bar_day in self._spy_regime.index:
            return bool(self._spy_regime[bar_day])
        # Find the last available regime reading on or before this date
        prior = self._spy_regime[self._spy_regime.index <= bar_day]
        if not prior.empty:
            return bool(prior.iloc[-1])
        return True  # default: bullish if no prior data

    def generate_signals(self, data: pd.DataFrame) -> Signal:
        signal = self._base.generate_signals(data)
        if signal.direction == "long" and not self._is_bull(data):
            return Signal(
                symbol=signal.symbol,
                direction="flat",
                reason=f"Regime filter: SPY below {self._sma_period}-day SMA — staying flat",
                metadata={**signal.metadata, "regime_filtered": True},
            )
        return signal

    def size_position(self, signal: Signal, portfolio: "Portfolio", price: float) -> Optional[Order]:
        return self._base.size_position(signal, portfolio, price)

    def __repr__(self) -> str:
        return f"RegimeFilteredStrategy(base={self._base!r}, sma={self._sma_period})"
