"""
Event-driven backtest engine for AlphaSMART.

Design:
  - Processes one bar at a time (event-driven = live parity)
  - Signal at bar T → execute at bar T+1 open (no lookahead)
  - Risk engine validates every order before queuing
  - Slippage and commission applied at fill time
  - Risk halt terminates simulation early

Bar processing order per step:
  1. Execute pending orders at current bar's OPEN (with slippage)
  2. Record equity snapshot at current bar's CLOSE
  3. Check risk halt conditions
  4. Generate signal for current bar (using data[0:i+1])
  5. Size position → validate with risk engine → queue for next bar
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from src.strategy.base import Fill, Order, Strategy
from src.strategy.portfolio import Portfolio
from src.strategy.risk_manager import RiskConfig, RiskEngine
from src.backtest.metrics import BacktestMetrics, bars_per_day_for, bars_per_year_for, compute_metrics
from src.monitoring.logger import logger


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    timeframe: str = "1d"  # used for correct annualisation of Sharpe/CAGR/Sortino


@dataclass
class BacktestResult:
    metrics: BacktestMetrics
    equity_df: pd.DataFrame      # DatetimeIndex, column='equity'
    fills: list[Fill]
    halted: bool = False
    halt_reason: str = ""
    n_bars_run: int = 0

    def print_summary(self, strategy_name: str = "") -> None:
        label = f"  Strategy: {strategy_name}" if strategy_name else ""
        print(f"\n{'='*50}")
        print(f"  BACKTEST RESULTS{label}")
        print(f"{'='*50}")
        for k, v in self.metrics.summary_dict().items():
            print(f"  {k:<18} {v}")
        if self.halted:
            print(f"\n  ⚠️  Halted early: {self.halt_reason}")
        print(f"{'='*50}\n")


class BacktestEngine:
    """
    Event-driven single-asset backtester.

    Usage:
        engine = BacktestEngine()
        result = engine.run(strategy, data, config)
    """

    def run(
        self,
        strategy: Strategy,
        data: pd.DataFrame,
        config: Optional[BacktestConfig] = None,
    ) -> BacktestResult:
        """
        Run a backtest of `strategy` against `data`.

        Args:
            strategy: Strategy instance (must implement generate_signals + size_position)
            data:     OHLCV DataFrame with DatetimeIndex, sorted ascending.
                      Must have columns: open, high, low, close, volume
            config:   BacktestConfig (defaults if None)

        Returns:
            BacktestResult
        """
        if config is None:
            config = BacktestConfig()

        if data.empty or len(data) < 2:
            logger.warning("BacktestEngine: data has fewer than 2 bars — nothing to run")
            return BacktestResult(
                metrics=compute_metrics(pd.DataFrame(columns=["equity"]), [], config.initial_capital),
                equity_df=pd.DataFrame(columns=["equity"]),
                fills=[],
            )

        required_cols = {"open", "high", "low", "close", "volume"}
        missing = required_cols - set(data.columns)
        if missing:
            raise ValueError(f"Data missing required columns: {missing}")

        portfolio = Portfolio(config.initial_capital)

        # Scale the daily loss limit for intraday timeframes so that normal
        # single-bar volatility (e.g. a 3-6% 4h BTC candle) doesn't trip the
        # circuit breaker that was calibrated for daily equity bars.
        bpd = bars_per_day_for(config.timeframe)
        effective_rc = (
            dataclasses.replace(
                config.risk_config,
                max_daily_loss_pct=config.risk_config.max_daily_loss_pct * bpd,
            )
            if bpd > 1.0 else config.risk_config
        )
        risk = RiskEngine(effective_rc)

        pending_order: Optional[Order] = None
        halted = False
        halt_reason = ""

        # Record initial equity
        portfolio.record_equity(data.index[0], {"__init__": 0})

        for i in range(1, len(data)):
            current_bar = data.iloc[i]
            timestamp = data.index[i]
            symbol = getattr(strategy, "symbol", None)

            current_open = float(current_bar["open"])
            current_close = float(current_bar["close"])
            prices = {symbol: current_close} if symbol else {}

            # ----------------------------------------------------------
            # 1. Execute pending order at current bar OPEN (+ slippage)
            # ----------------------------------------------------------
            if pending_order is not None:
                fill = self._execute_order(pending_order, current_open, timestamp, risk)
                if fill:
                    portfolio.apply_fill(fill)
                pending_order = None

            # ----------------------------------------------------------
            # 2. Record equity at current bar CLOSE
            # ----------------------------------------------------------
            portfolio.record_equity(timestamp, prices)

            # ----------------------------------------------------------
            # 3. Check risk halt
            # ----------------------------------------------------------
            halt, reason = risk.check_halt(portfolio, prices)
            if halt:
                halted = True
                halt_reason = reason
                logger.warning(f"Backtest halted at bar {i} ({timestamp}): {reason}")
                # Liquidate all positions at close
                self._liquidate(portfolio, prices, timestamp, risk)
                break

            # ----------------------------------------------------------
            # 4. Generate signal using data up to bar i (inclusive)
            # ----------------------------------------------------------
            history = data.iloc[: i + 1]
            signal = strategy.generate_signals(history)

            # ----------------------------------------------------------
            # 5. Size position, risk-check, queue for next bar
            # ----------------------------------------------------------
            order = strategy.size_position(signal, portfolio, current_close)
            if order is not None:
                allowed, block_reason = risk.check_order(order, portfolio, current_close)
                if allowed:
                    pending_order = order
                    logger.debug(
                        f"[{timestamp.date()}] Order queued: "
                        f"{order.side.upper()} {order.quantity:.4f} {order.symbol}"
                    )
                else:
                    logger.debug(f"[{timestamp.date()}] Order blocked: {block_reason}")

        # ------------------------------------------------------------------
        # End of data: liquidate any remaining open positions at last close
        # ------------------------------------------------------------------
        if not halted and symbol and portfolio.has_position(symbol):
            last_close = float(data["close"].iloc[-1])
            last_ts = data.index[-1]
            last_prices = {symbol: last_close}
            self._liquidate(portfolio, last_prices, last_ts, risk)
            # Record final equity after liquidation
            portfolio.record_equity(last_ts, last_prices)

        equity_df = portfolio.to_equity_df()
        bpy = bars_per_year_for(config.timeframe)
        metrics = compute_metrics(equity_df, portfolio.fills, config.initial_capital, bpy)

        logger.info(
            f"Backtest complete: {len(data)} bars, {len(portfolio.fills)} fills, "
            f"Sharpe={metrics.sharpe:.3f}, MaxDD={metrics.max_drawdown:.2%}"
        )

        return BacktestResult(
            metrics=metrics,
            equity_df=equity_df,
            fills=portfolio.fills,
            halted=halted,
            halt_reason=halt_reason,
            n_bars_run=i,
        )

    def _execute_order(
        self,
        order: Order,
        open_price: float,
        timestamp: datetime,
        risk: RiskEngine,
    ) -> Optional[Fill]:
        """Execute an order at open_price with slippage and commission."""
        if open_price <= 0:
            logger.warning(f"Cannot execute order at invalid price {open_price}")
            return None

        fill_price = risk.apply_slippage(order.side, open_price)
        trade_value = fill_price * order.quantity
        commission = risk.apply_commission(trade_value)
        slippage_cost = abs(fill_price - open_price) * order.quantity

        return Fill(
            order=order,
            fill_price=fill_price,
            commission=commission,
            slippage_cost=slippage_cost,
            timestamp=timestamp,
        )

    def _liquidate(
        self,
        portfolio: Portfolio,
        prices: dict[str, float],
        timestamp: datetime,
        risk: RiskEngine,
    ) -> None:
        """Force-close all open positions (end of backtest or risk halt)."""
        for sym, qty in list(portfolio.positions.items()):
            if qty > 0 and sym in prices:
                exit_order = Order(
                    symbol=sym,
                    side="sell",
                    quantity=qty,
                    strategy_name="__liquidation__",
                    timestamp=timestamp,
                )
                fill = self._execute_order(exit_order, prices[sym], timestamp, risk)
                if fill:
                    portfolio.apply_fill(fill)
                    logger.info(f"Liquidated {qty:.4f} {sym} @ {prices[sym]:.4f}")
