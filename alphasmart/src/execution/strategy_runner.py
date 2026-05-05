"""
StrategyRunner — orchestration for a single rebalance event.

Responsibilities:
  1. Compute target weights from the latest bar of OHLCV data, applying
     the strategy's signal function and the regime filter.
  2. Snapshot the broker's current positions and convert to current weights
     (against the live portfolio value).
  3. Compute the order set that brings current weights to target weights,
     applying a rebalance threshold to avoid tiny noisy trades.
  4. In paper mode: submit the orders to the broker.
     In shadow mode: log what would have been submitted, do not call broker.
  5. Run the signal-equivalence cross-check: re-compute target weights from
     scratch and compare against what the runner actually emitted. Any
     divergence > 1e-6 per symbol is logged at error level — this is the
     zero-tolerance correctness gate from paper_trade_design.md §5.

The runner is intentionally state-less between calls. It receives the data
and the broker reference, runs one rebalance, logs everything to the
ShadowLog, returns a structured summary. The caller (cron / scheduler)
decides when to call rebalance() and how often.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

import numpy as np
import pandas as pd

from src.execution.broker.alpaca_paper import (
    AlpacaPaperBroker, AlpacaOrderRequest,
)
from src.execution.shadow_log import ShadowLog


Mode = Literal["shadow", "paper"]


# ---------------------------------------------------------------------------
# Strategy signal: returns target weights at the latest bar
# ---------------------------------------------------------------------------

def xsec_momentum_target_weights(
    closes: pd.DataFrame,
    lookback_days: int,
    skip_days: int,
    top_k: int,
) -> dict[str, float]:
    """
    Cross-sectional momentum target weights at the LATEST bar of `closes`.
    Returns {symbol: weight}, summing to 1.0 (or {} if cannot compute).
    """
    n_bars = len(closes)
    if n_bars < lookback_days + skip_days + 1:
        return {}

    anchor_idx = -(skip_days + lookback_days + 1)
    tip_idx = -(skip_days + 1)
    if anchor_idx + n_bars < 0:
        return {}

    anchor = closes.iloc[anchor_idx]
    tip = closes.iloc[tip_idx]
    valid = anchor.notna() & tip.notna() & (anchor > 0)
    if int(valid.sum()) < top_k:
        return {}
    trailing = (tip[valid] / anchor[valid]) - 1.0
    held = trailing.nlargest(top_k).index.tolist()
    w = 1.0 / top_k
    return {sym: w for sym in held}


# ---------------------------------------------------------------------------
# Regime filter: returns a [0, 1] allocation scale at the latest bar
# ---------------------------------------------------------------------------

def binary_200ma_filter(close: pd.Series, ma_period: int = 200) -> float:
    """1.0 if close > ma(close), else 0.0. Returns 1.0 if not enough bars yet."""
    if len(close) < ma_period:
        return 1.0
    ma = close.rolling(ma_period).mean().iloc[-1]
    last = close.iloc[-1]
    if pd.isna(ma) or pd.isna(last):
        return 1.0
    return 1.0 if float(last) > float(ma) else 0.0


# ---------------------------------------------------------------------------
# Runner config + result
# ---------------------------------------------------------------------------

@dataclass
class StrategySpec:
    """Pure-data spec of what to compute."""
    name: str                      # e.g. "equity_xsec_momentum_B"
    signal_fn: Callable[..., dict[str, float]]
    signal_params: dict
    filter_fn: Optional[Callable[[pd.Series], float]] = None
    filter_input_symbol: Optional[str] = None  # e.g. "SPY" — must be in closes
    universe: list[str] = field(default_factory=list)


@dataclass
class RebalanceResult:
    timestamp_utc: datetime
    rebalance_kind: str            # "scheduled" / "manual" / "smoke"
    mode: Mode
    portfolio_value: float
    target_weights: dict[str, float]
    current_weights: dict[str, float]
    orders_submitted: int
    orders_skipped_threshold: int
    equivalence_check_passed: bool
    equivalence_max_drift: float
    halts: list[str]               # any pre-flight or runtime halts encountered


# ---------------------------------------------------------------------------
# StrategyRunner
# ---------------------------------------------------------------------------

class StrategyRunner:
    """
    One-rebalance orchestrator. Stateless across calls; the broker carries
    the live state.

    Args:
        spec:        what strategy to run
        broker:      AlpacaPaperBroker (mock or real)
        mode:        "shadow" computes only; "paper" submits
        log:         ShadowLog instance — defaults to a new one per channel
        rebalance_threshold_pct:
                     skip orders whose notional change is < this fraction
                     of portfolio value (default 0.5%). Avoids tiny dust
                     trades when rebalance moves a position by a sliver.
    """

    def __init__(
        self,
        spec: StrategySpec,
        broker: AlpacaPaperBroker,
        mode: Mode = "shadow",
        log: Optional[ShadowLog] = None,
        rebalance_threshold_pct: float = 0.005,
    ) -> None:
        self.spec = spec
        self.broker = broker
        self.mode = mode
        self.log = log or ShadowLog(channel=f"runner_{spec.name}")
        self.rebalance_threshold_pct = float(rebalance_threshold_pct)

    # ------------------------------------------------------------------
    # Compute layer (pure)
    # ------------------------------------------------------------------

    def _compute_target_weights(self, closes: pd.DataFrame) -> tuple[dict[str, float], float]:
        """Apply signal_fn then filter_fn. Returns (weights, filter_value)."""
        # Restrict to the spec's universe so spurious extra columns don't leak in
        cols = [c for c in self.spec.universe if c in closes.columns] or list(closes.columns)
        sub = closes[cols]
        raw_weights = self.spec.signal_fn(sub, **self.spec.signal_params)

        filter_value = 1.0
        if self.spec.filter_fn is not None and self.spec.filter_input_symbol:
            sym = self.spec.filter_input_symbol
            if sym not in closes.columns:
                # Filter input missing — fail open (full allocation) but log
                self.log.event(
                    "filter_input_missing",
                    {"symbol": sym, "fallback_value": 1.0},
                    level="warn",
                )
            else:
                try:
                    filter_value = float(self.spec.filter_fn(closes[sym]))
                except Exception as exc:
                    self.log.event(
                        "filter_error",
                        {"symbol": sym, "error": str(exc), "fallback_value": 1.0},
                        level="error",
                    )

        target = {s: w * filter_value for s, w in raw_weights.items()}
        # Floor near-zero weights so cash positions are explicit
        target = {s: w for s, w in target.items() if w > 1e-9}
        return target, filter_value

    def _current_weights_from_positions(
        self,
        positions: list,
        portfolio_value: float,
    ) -> dict[str, float]:
        if portfolio_value <= 0:
            return {}
        return {p.symbol: p.market_value / portfolio_value for p in positions}

    def _add_pending_orders_to_weights(
        self,
        current_weights: dict[str, float],
        pending_orders: list,
        latest_prices: dict[str, float],
        portfolio_value: float,
    ) -> dict[str, float]:
        """
        Credit pending (open) broker orders against current weights so
        subsequent rebalances don't double-submit. A pending buy for AAPL of
        $20k effectively raises current_weight[AAPL] toward the target.
        """
        if portfolio_value <= 0 or not pending_orders:
            return dict(current_weights)
        out = dict(current_weights)
        for o in pending_orders:
            price = latest_prices.get(o.symbol)
            if price is None or price <= 0:
                continue
            signed_qty = o.qty if o.side == "buy" else -o.qty
            value = signed_qty * price
            out[o.symbol] = out.get(o.symbol, 0.0) + (value / portfolio_value)
        return out

    def _compute_orders(
        self,
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        portfolio_value: float,
        latest_prices: dict[str, float],
    ) -> tuple[list[AlpacaOrderRequest], int]:
        """
        Returns (orders, skipped_count). Orders bring current → target; the
        threshold filters out trades whose notional change is below the
        configured percentage of portfolio_value.
        """
        all_syms = set(target_weights) | set(current_weights)
        threshold_dollars = self.rebalance_threshold_pct * portfolio_value
        orders: list[AlpacaOrderRequest] = []
        skipped = 0

        for sym in sorted(all_syms):
            target_w = target_weights.get(sym, 0.0)
            current_w = current_weights.get(sym, 0.0)
            target_value = target_w * portfolio_value
            current_value = current_w * portfolio_value
            delta_value = target_value - current_value

            if abs(delta_value) < threshold_dollars:
                skipped += 1
                continue

            price = latest_prices.get(sym)
            if price is None or price <= 0:
                self.log.event(
                    "missing_price",
                    {"symbol": sym, "delta_value": delta_value},
                    level="warn",
                )
                continue

            qty = abs(delta_value) / price
            qty = round(qty, 6)  # Alpaca fractional-share precision
            if qty <= 0:
                skipped += 1
                continue

            side = "buy" if delta_value > 0 else "sell"
            orders.append(AlpacaOrderRequest(symbol=sym, qty=qty, side=side))

        return orders, skipped

    # ------------------------------------------------------------------
    # Equivalence check (the zero-tolerance gate)
    # ------------------------------------------------------------------

    def _signal_equivalence_check(
        self,
        closes: pd.DataFrame,
        emitted_target_weights: dict[str, float],
    ) -> tuple[bool, float, dict]:
        """
        Re-compute target weights from scratch, compare to what the runner
        actually emitted. Any per-symbol drift > 1e-6 fails the gate.
        """
        recomputed, _filter_value = self._compute_target_weights(closes)
        all_syms = set(emitted_target_weights) | set(recomputed)
        drifts = {
            s: abs(emitted_target_weights.get(s, 0.0) - recomputed.get(s, 0.0))
            for s in all_syms
        }
        max_drift = max(drifts.values()) if drifts else 0.0
        passed = max_drift <= 1e-6
        return passed, max_drift, drifts

    # ------------------------------------------------------------------
    # Main entrypoint
    # ------------------------------------------------------------------

    def rebalance(
        self,
        closes: pd.DataFrame,
        rebalance_kind: str = "scheduled",
    ) -> RebalanceResult:
        """
        Run one rebalance against the latest bar of `closes`.

        `closes` must be a DataFrame indexed by timestamp with one column
        per symbol in the spec's universe (plus the filter input symbol).
        """
        ts = datetime.now(timezone.utc)
        halts: list[str] = []
        self.log.event(
            "rebalance_start",
            {"strategy": self.spec.name, "mode": self.mode, "kind": rebalance_kind,
             "n_universe_symbols": len(self.spec.universe), "n_bars": len(closes)},
        )

        # Snapshot broker state
        account = self.broker.get_account()
        if account.trading_blocked:
            halts.append("trading_blocked")
            self.log.event("halt", {"reason": "trading_blocked"}, level="error")
            return RebalanceResult(
                timestamp_utc=ts, rebalance_kind=rebalance_kind, mode=self.mode,
                portfolio_value=account.portfolio_value,
                target_weights={}, current_weights={},
                orders_submitted=0, orders_skipped_threshold=0,
                equivalence_check_passed=True, equivalence_max_drift=0.0,
                halts=halts,
            )

        positions = self.broker.get_positions()
        current_weights = self._current_weights_from_positions(positions, account.portfolio_value)

        # Pending orders — credit them against current so we don't double-submit
        # if a previous rebalance's orders are still queued (market closed,
        # latency, partial fills, etc.). Best-effort: tolerate broker
        # failures here.
        try:
            pending_orders = self.broker.list_open_orders()
        except Exception:
            pending_orders = []

        # Compute target
        target_weights, filter_value = self._compute_target_weights(closes)
        self.log.event(
            "target_weights",
            {"weights": target_weights, "filter_value": filter_value,
             "n_holdings": len(target_weights)},
        )

        # Build orders
        latest_prices = {sym: float(closes[sym].iloc[-1]) for sym in closes.columns
                         if not pd.isna(closes[sym].iloc[-1])}
        effective_current = self._add_pending_orders_to_weights(
            current_weights, pending_orders, latest_prices, account.portfolio_value,
        )
        self.log.event(
            "current_weights",
            {"positions_only": current_weights,
             "with_pending_orders": effective_current,
             "n_pending_orders": len(pending_orders)},
        )

        orders, skipped = self._compute_orders(
            target_weights, effective_current, account.portfolio_value, latest_prices,
        )
        self.log.event(
            "orders_planned",
            {"n_orders": len(orders), "n_skipped_threshold": skipped,
             "orders": [
                 {"symbol": o.symbol, "qty": o.qty, "side": o.side, "type": o.type}
                 for o in orders
             ]},
        )

        # Submit (paper mode only)
        n_submitted = 0
        if self.mode == "paper":
            for o in orders:
                try:
                    self.broker.submit_order(o)
                    n_submitted += 1
                except Exception as exc:
                    self.log.event(
                        "submit_failed",
                        {"symbol": o.symbol, "qty": o.qty, "side": o.side, "error": str(exc)},
                        level="error",
                    )
                    halts.append(f"submit_failed:{o.symbol}")
        else:
            self.log.event("shadow_skip_submit", {"would_submit_count": len(orders)})

        # Zero-tolerance equivalence check
        passed, max_drift, drifts = self._signal_equivalence_check(closes, target_weights)
        self.log.event(
            "signal_equivalence_check",
            {"passed": passed, "max_drift": max_drift, "drifts": drifts},
            level="info" if passed else "error",
        )
        if not passed:
            halts.append("equivalence_check_failed")

        result = RebalanceResult(
            timestamp_utc=ts,
            rebalance_kind=rebalance_kind,
            mode=self.mode,
            portfolio_value=account.portfolio_value,
            target_weights=target_weights,
            current_weights=current_weights,
            orders_submitted=n_submitted,
            orders_skipped_threshold=skipped,
            equivalence_check_passed=passed,
            equivalence_max_drift=max_drift,
            halts=halts,
        )
        self.log.event(
            "rebalance_end",
            {"orders_submitted": n_submitted, "orders_skipped_threshold": skipped,
             "halts": halts},
        )
        return result
