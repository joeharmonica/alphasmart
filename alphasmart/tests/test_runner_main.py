"""End-to-end tests for the runner_main orchestrator."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.execution.broker.alpaca_paper import AlpacaPaperBroker, AlpacaOrderRequest
from src.execution.shadow_log import ShadowLog
from src.execution.runner_main import (
    orchestrate_rebalance, build_equity_spec, EQUITY_UNIVERSE,
    write_halt, read_halt, clear_halt,
)
from src.execution.strategy_runner import (
    StrategySpec, xsec_momentum_target_weights, binary_200ma_filter,
)


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def closes_and_now():
    """Synthetic closes for a 5-symbol mini-universe + SPY, deterministic ranking."""
    n = 250
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    drifts = {"sym_A": 0.0001, "sym_B": 0.0005, "sym_C": 0.0010,
              "sym_D": 0.0015, "sym_E": 0.0020, "SPY": 0.0006}
    t = np.arange(n)
    closes = pd.DataFrame({s: 100.0 * np.exp(mu * t) for s, mu in drifts.items()}, index=idx)
    now = closes.index[-1].to_pydatetime() + timedelta(hours=2)
    return closes, now


@pytest.fixture
def mini_spec():
    return StrategySpec(
        name="test_mini_xsec",
        signal_fn=xsec_momentum_target_weights,
        signal_params={"lookback_days": 60, "skip_days": 0, "top_k": 3},
        filter_fn=binary_200ma_filter,
        filter_input_symbol="SPY",
        universe=["sym_A", "sym_B", "sym_C", "sym_D", "sym_E"],
    )


@pytest.fixture
def broker(tmp_root, closes_and_now):
    closes, _now = closes_and_now
    latest = closes.iloc[-1].to_dict()
    log = ShadowLog(channel="alpaca", root=tmp_root / "logs")
    return AlpacaPaperBroker(
        mock=True, log=log,
        mock_price_provider=lambda sym: float(latest.get(sym, 100.0)),
    )


# ---------------------------------------------------------------------------
# Halt-state helpers
# ---------------------------------------------------------------------------

def test_halt_round_trip(tmp_root):
    state_root = tmp_root / "state"
    assert read_halt(state_root, "ch") is None
    write_halt(state_root, "ch", reason="test")
    halt = read_halt(state_root, "ch")
    assert halt is not None
    assert halt.reason == "test"
    assert clear_halt(state_root, "ch") is True
    assert read_halt(state_root, "ch") is None


# ---------------------------------------------------------------------------
# Orchestration: shadow mode
# ---------------------------------------------------------------------------

def test_orchestrate_shadow_mode_succeeds(mini_spec, broker, closes_and_now, tmp_root, monkeypatch):
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    log = ShadowLog(channel="orch", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="shadow", state_root=state_root, log=log,
    )
    assert result.pre_flight_ok is True
    assert result.rebalance_executed is True
    assert result.equivalence_check_passed is True
    assert result.orders_submitted == 0   # shadow mode never submits
    assert result.new_halt_written is False


def test_orchestrate_paper_mode_submits_and_reconciles(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    log = ShadowLog(channel="orch", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.pre_flight_ok is True
    assert result.equivalence_check_passed is True
    assert result.orders_submitted == 3   # top-K of mini_spec
    # Reconciliation should run in paper mode and pass (broker filled exactly what state expected)
    assert result.reconciliation_should_halt is False
    assert result.new_halt_written is False


def test_orchestrate_aborts_on_pre_flight_failure(mini_spec, broker, closes_and_now, tmp_root, monkeypatch):
    """Stale data → freshness check fails → rebalance aborted."""
    closes, _now = closes_and_now
    fake_now = closes.index[-1].to_pydatetime() + timedelta(days=10)
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(fake_now))
    state_root = tmp_root / "state"
    log = ShadowLog(channel="orch", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.pre_flight_ok is False
    assert result.rebalance_executed is False
    failed = [r for r in result.pre_flight_results if not r["ok"]]
    assert any(r["name"] == "data_freshness" for r in failed)


def test_orchestrate_skips_when_halt_active(mini_spec, broker, closes_and_now, tmp_root, monkeypatch):
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    write_halt(state_root, mini_spec.name, reason="prior incident")
    log = ShadowLog(channel="orch", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.halt_state is not None
    assert result.halt_state["reason"] == "prior incident"
    assert result.rebalance_executed is False
    assert result.orders_submitted == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Now:
    """Patcher for datetime.now() in preflight; preserves classmethods."""
    def __init__(self, fixed: datetime):
        self.fixed = fixed if fixed.tzinfo else fixed.replace(tzinfo=timezone.utc)
        # Defer to the real datetime for attributes other than now()
        from datetime import datetime as real_dt
        self._real = real_dt
    def now(self, tz=None):
        if tz is None:
            return self.fixed
        return self.fixed.astimezone(tz)
    def __getattr__(self, name):
        return getattr(self._real, name)
