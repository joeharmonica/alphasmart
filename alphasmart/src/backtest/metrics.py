"""
Performance metrics for AlphaSMART backtests.
All metrics computed from the equity curve and fill log.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from src.strategy.base import Fill

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.0  # annualised, set to 0 for simplicity

# Bars per year for each supported timeframe — used for annualising Sharpe/CAGR
BARS_PER_YEAR: dict[str, int] = {
    "1m":  int(252 * 6.5 * 60),   # ~98280
    "5m":  int(252 * 6.5 * 12),   # ~19656
    "15m": int(252 * 6.5 * 4),    # ~6552
    "30m": int(252 * 6.5 * 2),    # ~3276
    "1h":  int(252 * 6.5),        # ~1638
    "60m": int(252 * 6.5),        # ~1638 (alias)
    "4h":  int(252 * 6.5 / 4),    # ~410
    "1d":  252,
    "5d":  52,
    "1wk": 52,
    "1mo": 12,
}


def bars_per_year_for(timeframe: str) -> int:
    """Return the annualisation factor for a given timeframe string."""
    return BARS_PER_YEAR.get(timeframe.lower(), TRADING_DAYS_PER_YEAR)


@dataclass
class BacktestMetrics:
    """All performance metrics for a single backtest run."""
    sharpe: float
    sortino: float
    cagr: float
    max_drawdown: float       # as fraction, e.g. 0.15 = 15%
    win_rate: float           # fraction of profitable round-trips
    profit_factor: float      # gross profit / gross loss
    total_return: float       # fraction, e.g. 0.20 = 20%
    trade_count: int          # number of completed round-trips (buy+sell pairs)
    exposure: float           # fraction of bars with open position
    avg_trade_return: float   # average return per round-trip
    best_trade: float         # best single round-trip return
    worst_trade: float        # worst single round-trip return
    n_bars: int               # total bars in backtest

    def passes_gate_1(self) -> bool:
        """Gate 1 criteria: Sharpe > 1.2, MaxDD < 25%, trades ≥ 100, positive return."""
        return (
            self.sharpe > 1.2
            and self.max_drawdown < 0.25
            and self.trade_count >= 100
            and self.total_return > 0
        )

    def summary_dict(self) -> dict:
        return {
            "Sharpe":         f"{self.sharpe:.3f}",
            "Sortino":        f"{self.sortino:.3f}",
            "CAGR":           f"{self.cagr:.2%}",
            "Max Drawdown":   f"{self.max_drawdown:.2%}",
            "Win Rate":       f"{self.win_rate:.2%}",
            "Profit Factor":  f"{self.profit_factor:.2f}",
            "Total Return":   f"{self.total_return:.2%}",
            "Trades":         str(self.trade_count),
            "Exposure":       f"{self.exposure:.2%}",
            "Avg Trade":      f"{self.avg_trade_return:.2%}",
            "Best Trade":     f"{self.best_trade:.2%}",
            "Worst Trade":    f"{self.worst_trade:.2%}",
            "Gate 1":         "✅ PASS" if self.passes_gate_1() else "❌ FAIL",
        }


def compute_metrics(
    equity_df: pd.DataFrame,
    fills: list["Fill"],
    initial_capital: float,
    bars_per_year: int = TRADING_DAYS_PER_YEAR,
) -> BacktestMetrics:
    """
    Compute all performance metrics from the equity curve and fill list.

    Args:
        equity_df:       DataFrame with 'equity' column and DatetimeIndex
        fills:           List of Fill objects from the backtest
        initial_capital: Starting portfolio value

    Returns:
        BacktestMetrics
    """
    if equity_df.empty or len(equity_df) < 2:
        return _empty_metrics()

    equity = equity_df["equity"]
    n_bars = len(equity)

    # ------------------------------------------------------------------
    # Daily returns
    # ------------------------------------------------------------------
    daily_returns = equity.pct_change().dropna()

    # ------------------------------------------------------------------
    # Total return
    # ------------------------------------------------------------------
    final_equity = equity.iloc[-1]
    total_return = (final_equity / initial_capital) - 1.0

    # ------------------------------------------------------------------
    # CAGR
    # ------------------------------------------------------------------
    n_trading_bars = max(n_bars - 1, 1)
    years = n_trading_bars / bars_per_year
    if total_return > -1 and years > 0:
        cagr = (final_equity / initial_capital) ** (1.0 / years) - 1.0
    else:
        cagr = -1.0

    # ------------------------------------------------------------------
    # Sharpe ratio (annualised)
    # ------------------------------------------------------------------
    bar_rf = RISK_FREE_RATE / bars_per_year
    excess_returns = daily_returns - bar_rf
    std = excess_returns.std()
    if std > 0 and len(excess_returns) > 1:
        sharpe = (excess_returns.mean() / std) * np.sqrt(bars_per_year)
    else:
        sharpe = 0.0

    # ------------------------------------------------------------------
    # Sortino ratio (annualised) — uses downside deviation
    # ------------------------------------------------------------------
    downside = excess_returns[excess_returns < 0]
    downside_std = np.sqrt((downside ** 2).mean()) if len(downside) > 0 else 0.0
    if downside_std > 0:
        sortino = (excess_returns.mean() / downside_std) * np.sqrt(bars_per_year)
    else:
        sortino = sharpe  # no downside → perfect, use Sharpe as proxy

    # ------------------------------------------------------------------
    # Max drawdown
    # ------------------------------------------------------------------
    rolling_peak = equity.cummax()
    drawdown_series = (rolling_peak - equity) / rolling_peak.replace(0, float("nan"))
    max_drawdown = float(drawdown_series.max()) if not drawdown_series.isna().all() else 0.0

    # ------------------------------------------------------------------
    # Exposure — fraction of bars with a non-zero position
    # ------------------------------------------------------------------
    # Count bars where equity changed due to position (approximation: equity != cash-only curve)
    # Better: count bars where portfolio had at least one position
    # Since we don't track this directly, we use: bars where equity != starting value
    # This is an approximation — Phase 3 will track per-bar position state
    if len(fills) >= 2:
        # Rough exposure: time between first buy and last sell / total bars
        buy_fills = [f for f in fills if f.order.side == "buy"]
        sell_fills = [f for f in fills if f.order.side == "sell"]
        if buy_fills and sell_fills:
            in_market_bars = 0
            # Count bars between each buy-sell pair
            buys = sorted(buy_fills, key=lambda f: f.timestamp)
            sells = sorted(sell_fills, key=lambda f: f.timestamp)
            # Match pairs
            all_times = equity_df.index
            for buy in buys:
                # Find next sell after this buy
                next_sells = [s for s in sells if s.timestamp > buy.timestamp]
                if next_sells:
                    exit_time = next_sells[0].timestamp
                    in_market_bars += ((all_times >= buy.timestamp) & (all_times <= exit_time)).sum()
            exposure = min(1.0, in_market_bars / n_bars)
        else:
            exposure = 0.0
    else:
        exposure = 0.0

    # ------------------------------------------------------------------
    # Trade-level statistics (round-trips: buy→sell pairs)
    # ------------------------------------------------------------------
    trade_returns = _compute_trade_returns(fills)
    trade_count = len(trade_returns)

    if trade_returns:
        profitable = [r for r in trade_returns if r > 0]
        losing = [r for r in trade_returns if r <= 0]
        win_rate = len(profitable) / trade_count
        gross_profit = sum(profitable)
        gross_loss = abs(sum(losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.9
        avg_trade_return = float(np.mean(trade_returns))
        best_trade = float(max(trade_returns))
        worst_trade = float(min(trade_returns))
    else:
        win_rate = 0.0
        profit_factor = 0.0
        avg_trade_return = 0.0
        best_trade = 0.0
        worst_trade = 0.0

    return BacktestMetrics(
        sharpe=round(sharpe, 4),
        sortino=round(sortino, 4),
        cagr=round(cagr, 4),
        max_drawdown=round(max_drawdown, 4),
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4),
        total_return=round(total_return, 4),
        trade_count=trade_count,
        exposure=round(exposure, 4),
        avg_trade_return=round(avg_trade_return, 4),
        best_trade=round(best_trade, 4),
        worst_trade=round(worst_trade, 4),
        n_bars=n_bars,
    )


def _compute_trade_returns(fills: list["Fill"]) -> list[float]:
    """
    Pair buy fills with subsequent sell fills to compute round-trip returns.
    Returns list of (sell_value - buy_cost) / buy_cost for each completed round-trip.
    """
    if not fills:
        return []

    # Group by symbol
    by_symbol: dict[str, list] = {}
    for f in fills:
        sym = f.order.symbol
        by_symbol.setdefault(sym, []).append(f)

    round_trips = []
    for sym, sym_fills in by_symbol.items():
        open_buys: list = []
        for f in sorted(sym_fills, key=lambda x: x.timestamp):
            if f.order.side == "buy":
                open_buys.append(f)
            elif f.order.side == "sell" and open_buys:
                buy = open_buys.pop(0)  # FIFO
                # Return = (sell_net - buy_cost) / buy_cost
                buy_cost = buy.fill_price * buy.order.quantity + buy.commission
                sell_net = f.fill_price * f.order.quantity - f.commission
                if buy_cost > 0:
                    round_trips.append((sell_net - buy_cost) / buy_cost)

    return round_trips


def _empty_metrics() -> BacktestMetrics:
    return BacktestMetrics(
        sharpe=0.0, sortino=0.0, cagr=0.0, max_drawdown=0.0,
        win_rate=0.0, profit_factor=0.0, total_return=0.0,
        trade_count=0, exposure=0.0, avg_trade_return=0.0,
        best_trade=0.0, worst_trade=0.0, n_bars=0,
    )
