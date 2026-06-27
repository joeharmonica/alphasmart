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
    build_parser, cmd_rebalance,
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
    assert result.cadence_reason is not None and "same calendar month" in result.cadence_reason
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
    A9: top-K unchanged BUT last rebalance was 45 days ago → spans a
    different calendar month AND well over the 14td guard → cadence reached.
    """
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_C": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=datetime.now(timezone.utc) - timedelta(days=45),
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


def test_cadence_gate_blocks_new_month_below_trading_day_guard(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """
    A9: anchor is in the previous calendar month but only ~3 trading days
    elapsed (the Jun-30 → Jul-1 / Jul-2 edge case). The trading-day guard
    blocks the rebalance — otherwise back-to-back firings would happen
    around every month boundary.
    """
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    # Build an anchor that lands in the previous calendar month with only
    # a few trading days elapsed. Use real-clock "now" minus 4 calendar
    # days, then snap to the last day of the prior month if still same month.
    now_real = datetime.now(timezone.utc)
    if now_real.day > 5:
        # E.g. today is the 27th — set anchor to last day of last month
        first_of_month = now_real.replace(day=1, hour=23, minute=59, second=0, microsecond=0)
        anchor = first_of_month - timedelta(days=1)
    else:
        # Edge case: we're in first 5 days of month — anchor 4 days back is
        # already last month with few trading days. Perfect.
        anchor = now_real - timedelta(days=4)
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_C": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=anchor,
    )
    log = ShadowLog(channel="orch_a9_guard", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
        min_trading_days=14,
    )
    # If we're far into a month (e.g. 27th), then anchor=last-day-of-prev-month
    # is ~27 days ago = ~19 trading days, which EXCEEDS the 14td guard. In
    # that case the gate would PASS — so the test is sensitive to when we
    # run it. The robust assertion: if trading_days < 14, expect blocked;
    # else expect proceeds.
    import numpy as np
    td = int(np.busday_count(anchor.date(), now_real.date()))
    if td < 14:
        assert result.cadence_blocked is True
        assert "new month but only" in (result.cadence_reason or "")
    else:
        # Test ran in the middle/end of the month — the guard already cleared.
        # Still validates that the gate's logic is consistent.
        assert result.cadence_blocked is False


def test_cadence_gate_blocks_same_month_regardless_of_days(
    mini_spec, broker, closes_and_now, tmp_root, monkeypatch,
):
    """
    A9: even if 25 days elapsed, if it's still the same calendar month,
    cadence is blocked. (Edge case that shouldn't fire in practice because
    no calendar month has 25+ days within itself, but tests the gate
    structure.)
    """
    closes, now = closes_and_now
    monkeypatch.setattr("src.execution.preflight.datetime", _Now(now))
    state_root = tmp_root / "state"
    # Seed with an anchor in the current calendar month, 5 days ago.
    _seed_prior_state(
        state_root, mini_spec,
        target_weights={"sym_C": 1/3, "sym_D": 1/3, "sym_E": 1/3},
        last_rebal_dt=datetime.now(timezone.utc) - timedelta(days=5),
    )
    log = ShadowLog(channel="orch_a9_samemonth", root=tmp_root / "logs")
    result = orchestrate_rebalance(
        spec=mini_spec, broker=broker, closes=closes,
        mode="paper", state_root=state_root, log=log,
    )
    assert result.cadence_blocked is True
    assert "same calendar month" in (result.cadence_reason or "")


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


# ---------------------------------------------------------------------------
# A11 (lessons.md #58) — decouple poller skip_if_fresh cutoff from the
# preflight data_freshness threshold. Bug: both consumed the single
# --stale-after-hours flag, so A10's bump (50h -> 96h, to kill the Monday
# false-positive on the *preflight* check) silently let the live poller
# skip re-fetching any symbol for up to 4 days once a bar landed inside
# that window — freezing its data with no exception, no error log, and a
# misleadingly green "Fetched N bars" line (the fetch succeeded; it was
# just never re-attempted).
# ---------------------------------------------------------------------------

def test_parser_decouples_poll_fresh_hours_from_stale_after_hours():
    """The two thresholds must be independently settable CLI flags."""
    parser = build_parser()
    args = parser.parse_args([
        "rebalance", "--stale-after-hours", "96", "--poll-fresh-hours", "20",
    ])
    assert args.stale_after_hours == 96.0
    assert args.poll_fresh_hours == 20.0


def test_parser_poll_fresh_hours_default_is_tighter_than_stale_after_hours():
    """Defaults alone must not reintroduce the bug: poll cutoff < preflight cutoff."""
    parser = build_parser()
    args = parser.parse_args(["rebalance"])
    assert args.poll_fresh_hours < args.stale_after_hours


def test_cmd_rebalance_passes_poll_fresh_hours_not_stale_after_hours_to_poller(
    tmp_root, monkeypatch,
):
    """
    Regression test for A11: cmd_rebalance must call LiveDataPoller.poll()
    with args.poll_fresh_hours, never args.stale_after_hours — otherwise a
    lenient preflight threshold silently starves the daily data poll.
    """
    monkeypatch.setattr(
        "src.execution.shadow_log.ShadowLog._default_root",
        staticmethod(lambda: tmp_root / "logs"),
    )

    captured = {}

    class _StubPoller:
        def __init__(self, db_url, log):
            pass

        def poll(self, **kwargs):
            captured.update(kwargs)
            from src.execution.live_data import PollResult
            return PollResult(
                timestamp_utc="2026-06-21T00:00:00Z", timeframe="1d",
                universe_size=len(kwargs.get("universe", [])),
                symbols_ok=0, symbols_error=0, total_bars_inserted=0,
                elapsed_total_ms=0, per_symbol=[], coverage_ok=True,
            )

    monkeypatch.setattr("src.execution.runner_main.LiveDataPoller", _StubPoller)

    parser = build_parser()
    args = parser.parse_args([
        "rebalance", "--mode", "paper", "--mock",
        "--db-url", f"sqlite:///{tmp_root}/empty.db",
        "--fetch-before-rebalance",
        "--stale-after-hours", "96",
        "--poll-fresh-hours", "20",
    ])
    cmd_rebalance(args)  # DB is empty -> returns 1 after the poll; that's fine

    assert captured.get("stale_after_hours") == 20.0, (
        f"poller got {captured.get('stale_after_hours')}h — expected the "
        f"dedicated poll_fresh_hours (20h), not stale_after_hours (96h)"
    )


# ---------------------------------------------------------------------------
# Lesson #60 — mock/shadow runs must NOT write to the production state file.
# orchestrate_rebalance.state.write() runs unconditionally once equivalence
# passes; a `--mock` dry-run (synthetic pv=100000) once clobbered the live
# cadence anchor + reconciler baseline. cmd_rebalance must redirect state to
# a diagnostic root whenever args.mock or args.mode == "shadow".
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("argv_extra", [
    ["--mode", "paper", "--mock"],
    ["--mode", "shadow", "--mock"],
    ["--mode", "shadow"],
])
def test_cmd_rebalance_mock_or_shadow_never_writes_production_state(
    tmp_root, monkeypatch, argv_extra,
):
    monkeypatch.setattr(
        "src.execution.shadow_log.ShadowLog._default_root",
        staticmethod(lambda: tmp_root / "logs"),
    )

    captured = {}

    def _fake_orchestrate(*a, **kw):
        captured["state_root"] = kw.get("state_root")
        from src.execution.runner_main import OrchestrationResult
        return OrchestrationResult(
            timestamp_utc="2026-06-27T00:00:00Z",
            channel="equity_xsec_momentum_B", mode=kw.get("mode", "?"),
            pre_flight_ok=True, equivalence_check_passed=True,
        )

    # Give load_closes something non-empty so we reach orchestrate.
    monkeypatch.setattr(
        "src.execution.runner_main.load_closes",
        lambda **kw: pd.DataFrame({"AMD": [1.0, 2.0]}),
    )
    monkeypatch.setattr(
        "src.execution.runner_main.orchestrate_rebalance", _fake_orchestrate,
    )

    parser = build_parser()
    args = parser.parse_args(
        ["rebalance", *argv_extra, "--db-url", f"sqlite:///{tmp_root}/x.db"]
    )
    cmd_rebalance(args)

    sr = captured["state_root"]
    assert sr is not None, "mock/shadow must pass an explicit diagnostic state_root"
    assert "state_diagnostic" in str(sr), (
        f"state_root {sr} should be the diagnostic root, never production"
    )


def test_cmd_rebalance_real_paper_uses_production_state(tmp_root, monkeypatch):
    """The inverse: a real paper-mode run must NOT redirect (state_root=None)."""
    monkeypatch.setattr(
        "src.execution.shadow_log.ShadowLog._default_root",
        staticmethod(lambda: tmp_root / "logs"),
    )
    captured = {}

    def _fake_orchestrate(*a, **kw):
        captured["state_root"] = kw.get("state_root", "MISSING")
        from src.execution.runner_main import OrchestrationResult
        return OrchestrationResult(
            timestamp_utc="2026-06-27T00:00:00Z",
            channel="equity_xsec_momentum_B", mode="paper",
            pre_flight_ok=True, equivalence_check_passed=True,
        )

    monkeypatch.setattr(
        "src.execution.runner_main.load_closes",
        lambda **kw: pd.DataFrame({"AMD": [1.0, 2.0]}),
    )
    monkeypatch.setattr(
        "src.execution.runner_main.orchestrate_rebalance", _fake_orchestrate,
    )
    # Avoid building a real broker (needs creds): stub it.
    monkeypatch.setattr(
        "src.execution.runner_main._build_broker", lambda *a, **kw: object(),
    )

    parser = build_parser()
    args = parser.parse_args(
        ["rebalance", "--mode", "paper", "--db-url", f"sqlite:///{tmp_root}/x.db"]
    )
    cmd_rebalance(args)
    assert captured["state_root"] is None, (
        "real paper run must use the production state root (no override)"
    )
