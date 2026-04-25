"""
Portfolio — tracks cash, positions, equity curve, and fills.
Pure state container: no trading logic here.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd

from src.strategy.base import Fill
from src.monitoring.logger import logger


class Portfolio:
    """
    Tracks portfolio state during a backtest or live run.

    Attributes:
        initial_capital: Starting cash
        cash:            Current cash balance
        positions:       {symbol: quantity} — only non-zero positions stored
        fills:           All fills in chronological order
        peak_equity:     Highest equity seen (for drawdown calculation)
    """

    def __init__(self, initial_capital: float) -> None:
        if initial_capital <= 0:
            raise ValueError(f"initial_capital must be positive, got {initial_capital}")

        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, float] = {}
        self.fills: list[Fill] = []
        self.peak_equity: float = initial_capital

        self._equity_curve: list[tuple[datetime, float]] = []
        self._day_start_equity: float = initial_capital
        self._current_day: Optional[date] = None

    # ------------------------------------------------------------------
    # Equity
    # ------------------------------------------------------------------

    def equity(self, prices: dict[str, float]) -> float:
        """Total portfolio value: cash + sum(position * price)."""
        position_value = sum(
            qty * prices.get(sym, 0.0)
            for sym, qty in self.positions.items()
        )
        return self.cash + position_value

    def position_value(self, symbol: str, price: float) -> float:
        """Value of a single position."""
        return self.positions.get(symbol, 0.0) * price

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions and self.positions[symbol] != 0.0

    def is_long(self, symbol: str) -> bool:
        return self.positions.get(symbol, 0.0) > 0

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------

    def apply_fill(self, fill: Fill) -> None:
        """Apply a confirmed fill to portfolio state."""
        sym = fill.order.symbol
        qty = fill.order.quantity

        if fill.order.side == "buy":
            self.positions[sym] = self.positions.get(sym, 0.0) + qty
        else:
            current_qty = self.positions.get(sym, 0.0)
            new_qty = current_qty - qty
            if abs(new_qty) < 1e-9:
                self.positions.pop(sym, None)
            else:
                self.positions[sym] = new_qty

        self.cash += fill.net_cash_impact
        self.fills.append(fill)
        logger.debug(
            f"Fill applied: {fill.order.side.upper()} {qty:.4f} {sym} "
            f"@ {fill.fill_price:.4f} | cash={self.cash:.2f}"
        )

    def record_equity(self, timestamp: datetime, prices: dict[str, float]) -> None:
        """Record equity snapshot, update peak, track daily start."""
        eq = self.equity(prices)
        self._equity_curve.append((timestamp, eq))
        self.peak_equity = max(self.peak_equity, eq)

        # Track day boundary for daily PnL
        current_date = timestamp.date() if hasattr(timestamp, "date") else None
        if current_date and current_date != self._current_day:
            self._day_start_equity = eq
            self._current_day = current_date

    # ------------------------------------------------------------------
    # Risk metrics (live snapshots)
    # ------------------------------------------------------------------

    def drawdown(self, prices: dict[str, float]) -> float:
        """Current drawdown as a fraction: (peak - current) / peak."""
        if self.peak_equity <= 0:
            return 0.0
        current = self.equity(prices)
        return max(0.0, (self.peak_equity - current) / self.peak_equity)

    def daily_pnl_pct(self, prices: dict[str, float]) -> float:
        """Today's PnL as a fraction of day-start equity."""
        if self._day_start_equity <= 0:
            return 0.0
        current = self.equity(prices)
        return (current - self._day_start_equity) / self._day_start_equity

    def total_return(self, prices: dict[str, float]) -> float:
        """Total return since inception."""
        return (self.equity(prices) / self.initial_capital) - 1.0

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def to_equity_df(self) -> pd.DataFrame:
        """Return equity curve as a DataFrame with columns [equity]."""
        if not self._equity_curve:
            return pd.DataFrame(columns=["equity"])
        timestamps, values = zip(*self._equity_curve)
        return pd.DataFrame({"equity": values}, index=pd.DatetimeIndex(timestamps))

    def open_positions_value(self, prices: dict[str, float]) -> float:
        """Total value of all open positions."""
        return sum(
            qty * prices.get(sym, 0.0)
            for sym, qty in self.positions.items()
        )

    def summary(self, prices: dict[str, float]) -> dict:
        return {
            "cash": round(self.cash, 2),
            "positions": dict(self.positions),
            "equity": round(self.equity(prices), 2),
            "total_return_pct": round(self.total_return(prices) * 100, 2),
            "drawdown_pct": round(self.drawdown(prices) * 100, 2),
            "fills": len(self.fills),
        }
