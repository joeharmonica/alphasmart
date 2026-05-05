"""
Pre-flight checks for the paper-trade rebalance pipeline (design §4).

Each check returns CheckResult{ok: bool, name, reason}. The orchestrator
runs all checks before invoking StrategyRunner; any single ok=False aborts
the rebalance with the failing check's reason logged.

Six checks from the design:
  1. Data freshness — latest bar close ≤ stale_after_hours old
  2. Universe completeness — all expected symbols return non-NaN closes
  3. Filter input — bellwether (e.g. SPY) has enough bars for its MA
  4. Broker connectivity — get_account succeeds
  5. Cash buffer — free cash ≥ min_cash_buffer_pct of portfolio
  6. Position concentration — no symbol > max_position_pct of portfolio
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from src.execution.broker.alpaca_paper import AlpacaPaperBroker


@dataclass
class CheckResult:
    name: str
    ok: bool
    reason: Optional[str] = None
    detail: Optional[dict] = None


def check_data_freshness(
    closes: pd.DataFrame,
    stale_after_hours: float = 36.0,
    now_utc: Optional[datetime] = None,
) -> CheckResult:
    """Latest bar close must be within `stale_after_hours` of now."""
    if closes.empty:
        return CheckResult("data_freshness", False, "closes is empty")
    last_idx = closes.index[-1]
    if last_idx.tzinfo is None:
        last_idx = last_idx.tz_localize("UTC")
    now = now_utc or datetime.now(timezone.utc)
    age_hours = (now - last_idx.to_pydatetime()).total_seconds() / 3600.0
    if age_hours > stale_after_hours:
        return CheckResult(
            "data_freshness", False,
            f"latest bar age {age_hours:.1f}h > {stale_after_hours}h",
            detail={"age_hours": age_hours, "last_bar": str(last_idx)},
        )
    return CheckResult("data_freshness", True, detail={"age_hours": age_hours})


def check_universe_completeness(
    closes: pd.DataFrame,
    universe: list[str],
) -> CheckResult:
    """All universe symbols must be present and have non-NaN latest close."""
    missing = [s for s in universe if s not in closes.columns]
    if missing:
        return CheckResult(
            "universe_completeness", False,
            f"missing columns: {missing}",
            detail={"missing": missing},
        )
    nan_syms = [s for s in universe if pd.isna(closes[s].iloc[-1])]
    if nan_syms:
        return CheckResult(
            "universe_completeness", False,
            f"NaN at latest bar: {nan_syms}",
            detail={"nan_symbols": nan_syms},
        )
    return CheckResult("universe_completeness", True)


def check_filter_input_available(
    closes: pd.DataFrame,
    filter_symbol: Optional[str],
    min_bars: int = 200,
) -> CheckResult:
    """Filter bellwether (e.g. SPY) must have ≥ min_bars history."""
    if filter_symbol is None:
        return CheckResult("filter_input", True, detail={"skipped": "no filter"})
    if filter_symbol not in closes.columns:
        return CheckResult(
            "filter_input", False,
            f"filter symbol '{filter_symbol}' not in closes",
        )
    valid = closes[filter_symbol].dropna()
    if len(valid) < min_bars:
        return CheckResult(
            "filter_input", False,
            f"only {len(valid)} bars for {filter_symbol}, need ≥ {min_bars}",
            detail={"bars_available": len(valid), "min_bars": min_bars},
        )
    return CheckResult("filter_input", True, detail={"bars_available": len(valid)})


def check_broker_connectivity(broker: AlpacaPaperBroker) -> CheckResult:
    """get_account succeeds and account is in good standing."""
    try:
        acc = broker.get_account()
    except Exception as exc:
        return CheckResult("broker_connectivity", False, f"get_account failed: {exc}")
    if acc.trading_blocked:
        return CheckResult("broker_connectivity", False, "trading_blocked=true")
    if acc.status != "ACTIVE":
        return CheckResult(
            "broker_connectivity", False,
            f"status={acc.status} (not ACTIVE)",
            detail={"status": acc.status},
        )
    return CheckResult(
        "broker_connectivity", True,
        detail={"buying_power": acc.buying_power, "status": acc.status},
    )


def check_cash_buffer(
    broker: AlpacaPaperBroker,
    min_cash_buffer_pct: float = 0.01,
) -> CheckResult:
    """Free cash ≥ min_cash_buffer_pct of portfolio_value (covers cmsn + slippage)."""
    try:
        acc = broker.get_account()
    except Exception as exc:
        return CheckResult("cash_buffer", False, f"get_account failed: {exc}")
    if acc.portfolio_value <= 0:
        return CheckResult("cash_buffer", False, "portfolio_value <= 0")
    pct = acc.cash / acc.portfolio_value
    if pct < min_cash_buffer_pct:
        return CheckResult(
            "cash_buffer", False,
            f"cash buffer {pct:.4f} < {min_cash_buffer_pct}",
            detail={"cash": acc.cash, "portfolio_value": acc.portfolio_value, "pct": pct},
        )
    return CheckResult("cash_buffer", True, detail={"pct": pct})


def check_position_concentration(
    broker: AlpacaPaperBroker,
    max_position_pct: float = 0.25,
) -> CheckResult:
    """No single position should exceed max_position_pct of portfolio."""
    try:
        acc = broker.get_account()
        positions = broker.get_positions()
    except Exception as exc:
        return CheckResult("position_concentration", False, f"broker call failed: {exc}")
    if acc.portfolio_value <= 0:
        return CheckResult("position_concentration", True, detail={"empty_portfolio": True})
    over = []
    for p in positions:
        pct = abs(p.market_value) / acc.portfolio_value
        if pct > max_position_pct:
            over.append({"symbol": p.symbol, "pct": pct})
    if over:
        return CheckResult(
            "position_concentration", False,
            f"positions exceeding {max_position_pct}: {over}",
            detail={"over_threshold": over},
        )
    return CheckResult("position_concentration", True)


def run_all_checks(
    closes: pd.DataFrame,
    universe: list[str],
    filter_symbol: Optional[str],
    broker: AlpacaPaperBroker,
    stale_after_hours: float = 36.0,
    min_filter_bars: int = 200,
    min_cash_buffer_pct: float = 0.01,
    max_position_pct: float = 0.25,
    now_utc: Optional[datetime] = None,
) -> list[CheckResult]:
    return [
        check_data_freshness(closes, stale_after_hours, now_utc),
        check_universe_completeness(closes, universe),
        check_filter_input_available(closes, filter_symbol, min_filter_bars),
        check_broker_connectivity(broker),
        check_cash_buffer(broker, min_cash_buffer_pct),
        check_position_concentration(broker, max_position_pct),
    ]
