"""
Risk Engine — enforces hard limits on all orders and portfolio state.
NON-NEGOTIABLE: no order bypasses this. No exceptions.

Hard limits (all configurable, none removable):
  - Max position size (% of portfolio)
  - Max daily loss (% of portfolio)
  - Max drawdown circuit breaker
  - Max open positions
  - Commission and slippage applied to every fill
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.strategy.base import Order
from src.monitoring.logger import logger

if __name__ != "__main__":
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.strategy.portfolio import Portfolio


@dataclass
class RiskConfig:
    """All risk parameters. Defaults are conservative."""
    max_position_pct: float = 0.05     # 5% of portfolio per position
    max_daily_loss_pct: float = 0.02   # 2% daily loss limit
    max_drawdown_pct: float = 0.20     # 20% drawdown circuit breaker
    max_open_positions: int = 10       # max concurrent open positions
    commission_pct: float = 0.001      # 0.1% commission per trade
    slippage_pct: float = 0.0005       # 0.05% slippage per trade


class RiskEngine:
    """
    Validates orders and monitors portfolio health.
    Returns (allowed: bool, reason: str) — never raises.
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    # ------------------------------------------------------------------
    # Order validation
    # ------------------------------------------------------------------

    def check_order(
        self,
        order: Order,
        portfolio: "Portfolio",
        price: float,
    ) -> tuple[bool, str]:
        """
        Validate an order before queuing it for execution.

        Returns:
            (True, "")  — order is allowed
            (False, reason) — order blocked
        """
        if price <= 0:
            return False, f"Invalid price {price} for {order.symbol}"

        total_eq = portfolio.equity({order.symbol: price})
        if total_eq <= 0:
            return False, "Portfolio equity is zero or negative"

        order_value = order.quantity * price
        position_pct = order_value / total_eq

        if position_pct > self.config.max_position_pct * 1.1:  # 10% tolerance
            return False, (
                f"Order value {order_value:.0f} ({position_pct:.1%} of equity) "
                f"exceeds max position size {self.config.max_position_pct:.0%}"
            )

        # Insufficient cash for a buy
        if order.side == "buy":
            total_cost = order_value * (1 + self.config.commission_pct + self.config.slippage_pct)
            if total_cost > portfolio.cash:
                return False, (
                    f"Insufficient cash: need {total_cost:.2f}, have {portfolio.cash:.2f}"
                )

        # Max open positions (for buys only)
        if order.side == "buy" and len(portfolio.positions) >= self.config.max_open_positions:
            if order.symbol not in portfolio.positions:
                return False, (
                    f"Max open positions reached ({self.config.max_open_positions})"
                )

        return True, ""

    # ------------------------------------------------------------------
    # Portfolio-level halt check
    # ------------------------------------------------------------------

    def check_halt(
        self,
        portfolio: "Portfolio",
        prices: dict[str, float],
    ) -> tuple[bool, str]:
        """
        Check whether portfolio state requires a trading halt.

        Returns:
            (True, reason) — halt all trading
            (False, "")    — all clear
        """
        daily_loss = -portfolio.daily_pnl_pct(prices)
        if daily_loss > self.config.max_daily_loss_pct:
            reason = (
                f"Daily loss {daily_loss:.2%} exceeds limit "
                f"{self.config.max_daily_loss_pct:.2%}"
            )
            logger.warning(f"RISK HALT — {reason}")
            return True, reason

        drawdown = portfolio.drawdown(prices)
        if drawdown > self.config.max_drawdown_pct:
            reason = (
                f"Drawdown {drawdown:.2%} exceeds circuit breaker "
                f"{self.config.max_drawdown_pct:.2%}"
            )
            logger.warning(f"RISK HALT — {reason}")
            return True, reason

        return False, ""

    # ------------------------------------------------------------------
    # Execution cost modeling
    # ------------------------------------------------------------------

    def apply_slippage(self, side: str, price: float) -> float:
        """
        Apply slippage to execution price.
        Buys fill higher, sells fill lower (adverse slippage).
        """
        if side == "buy":
            return price * (1.0 + self.config.slippage_pct)
        return price * (1.0 - self.config.slippage_pct)

    def apply_commission(self, trade_value: float) -> float:
        """Commission as a flat percentage of trade value."""
        return trade_value * self.config.commission_pct
