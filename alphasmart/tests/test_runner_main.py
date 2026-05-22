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
# A7 cadence gate (lessons.md #53)
# ---------------------------------------------------------------------------

def _seed_prior_state(state_root, mini_spec, target_weights, last_rebal_dt):
    """Helper: write a StateRecord with explicit last_rebalance_utc."""
    from src.execution.state_store import StateStore
    state = StateStore(channel=mini_spec.name, root=state_root)
    state.write(
        strategy=mini_spec.name,
        rebalance_id="rb-prior",
        target_weights=target_weights,
        portfolio_value=100_000.0,
        latest_prices={s: 100.0 for s in target_weights},
        last_rebalance_utc=last_rebal_dt.isoformat(),
    )


def test_cadence_gate_blocks_recent_no_rotation_paper_run(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """
    A7: top-K membership unchanged + last rebalance was 5 days ago + paper mode
    → cadence gate blocks the run. No orders submitted, no halt written, state
    file unchanged.
    """
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    # Seed prior state with the SAME top-K the strategy would compute (sym_C/D/E
    # are the 3 highest-momentum names in the fixture)
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_C": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=datetime.now(timezone.utc) - timedelta(days=5),
    )
    log = ShadowLog(channel="orch_a7_block", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.cadence_blocked is True
    assert result.cadence_reason is not None and "no_rotation" in result.cadence_reason
    assert 4.5 < (result.days_since_last_rebalance or 0) < 5.5
    assert result.is_rotation is False
    assert result.rebalance_executed is False  # gate fired BEFORE runner.rebalance()
    assert result.orders_submitted == 0
    assert result.new_halt_written is False


def test_cadence_gate_allows_when_rotation(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """
    A7: top-K membership changed (B in prior state, not in new target) AND
    last rebalance was 1 day ago → rotation overrides cadence, runner proceeds.
    """
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    # Seed with a basket that includes sym_B (the strategy's new target won't
    # include it because B has lower 60d momentum than C/D/E)
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_B": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=datetime.now(timezone.utc) - timedelta(days=1),
    )
    log = ShadowLog(channel="orch_a7_rotate", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.cadence_blocked is False
    assert result.is_rotation is True
    assert result.rebalance_executed is True


def test_cadence_gate_allows_when_period_elapsed(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """
    A7: top-K unchanged BUT last rebalance was 25 days ago (> 21d default) →
    cadence reached, runner proceeds.
    """
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_C": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=datetime.now(timezone.utc) - timedelta(days=25),
    )
    log = ShadowLog(channel="orch_a7_period", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.cadence_blocked is False
    assert result.is_rotation is False
    assert result.days_since_last_rebalance is not None and result.days_since_last_rebalance >= 21
    assert result.rebalance_executed is True


def test_cadence_gate_allows_when_force_rebalance(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """A7: force_rebalance=True bypasses cadence (operator override)."""
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_C": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=datetime.now(timezone.utc) - timedelta(days=3),
    )
    log = ShadowLog(channel="orch_a7_force", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
        force_rebalance=True,
    )
    assert result.cadence_blocked is False
    assert result.rebalance_executed is True


def test_cadence_gate_allows_first_run_no_prior_state(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """A7: no prior state file → first run, gate always permits."""
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    log = ShadowLog(channel="orch_a7_first", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.cadence_blocked is False
    assert result.rebalance_executed is True
    # First run also writes state with last_rebalance_utc = now
    from src.execution.state_store import StateStore
    state = StateStore(channel=mini_spec.name, root=state_root).read()
    assert state is not None and state.last_rebalance_utc is not None


def test_cadence_gate_advances_anchor_only_on_pass(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """
    A7: a cadence-blocked run must NOT update last_rebalance_utc. Otherwise
    the gate would reset itself and become useless.
    """
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    anchor_dt = datetime.now(timezone.utc) - timedelta(days=5)
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_C": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=anchor_dt,
    )
    log = ShadowLog(channel="orch_a7_anchor", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.cadence_blocked is True
    # State file must still have the original anchor
    from src.execution.state_store import StateStore
    state = StateStore(channel=mini_spec.name, root=state_root).read()
    assert state.last_rebalance_utc == anchor_dt.isoformat()


def test_cadence_gate_bypassed_in_shadow_mode(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """
    A7: shadow mode is for diagnostics and should always run (bypassing the
    gate) so operators get a fresh signal-equivalence + state preview.
    """
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_C": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=datetime.now(timezone.utc) - timedelta(days=2),
    )
    log = ShadowLog(channel="orch_a7_shadow", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="shadow", state_root=state_root, log=log,
    )
    assert result.cadence_blocked is False  # gate bypassed in shadow
    assert result.rebalance_executed is True
    assert result.orders_submitted == 0  # shadow still doesn't submit


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
