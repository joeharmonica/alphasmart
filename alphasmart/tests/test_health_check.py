"""
Tests for the runner_main `health-check` subcommand (A3, lessons.md #42).

The check returns distinct exit codes per failure class so a wrapping cron
can route each to a different alert severity.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.execution.runner_main import (
    _run_health_check, build_equity_spec, write_halt,
    HEALTH_OK, HEALTH_HALT_ACTIVE, HEALTH_STATE_STALE,
    HEALTH_BROKER_UNREACHABLE, HEALTH_STATE_MISSING,
)
from src.execution.state_store import StateStore


@pytest.fixture
def tmp_state_root(monkeypatch):
    """Redirect StateStore's default root to an isolated tmp dir per test."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "state"
        root.mkdir()
        monkeypatch.setattr(StateStore, "_default_root", staticmethod(lambda: root))
        yield root


@pytest.fixture
def spec():
    return build_equity_spec()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_health_check_ok_when_state_fresh_and_no_halt(tmp_state_root, spec):
    state = StateStore(channel=spec.name)
    state.write(spec.name, "rb-fresh",
                target_weights={"AAPL": 1.0},
                portfolio_value=100_000.0,
                latest_prices={"AAPL": 200.0})
    code, payload = _run_health_check(
        spec, max_state_age_hours=80.0,
        check_broker=False, allow_no_state=False,
    )
    assert code == HEALTH_OK
    assert payload["issues"] == []
    assert payload["halt"]["active"] is False
    assert payload["state"]["present"] is True


# ---------------------------------------------------------------------------
# Halt active (lessons #42 silent halt)
# ---------------------------------------------------------------------------

def test_health_check_flags_halt_active(tmp_state_root, spec):
    write_halt(tmp_state_root, spec.name, reason="cash_buffer -0.0160 < 0.01")
    state = StateStore(channel=spec.name)
    state.write(spec.name, "rb-fresh", {"AAPL": 1.0}, 100_000.0, {"AAPL": 200.0})
    code, payload = _run_health_check(
        spec, max_state_age_hours=80.0,
        check_broker=False, allow_no_state=False,
    )
    assert code == HEALTH_HALT_ACTIVE
    assert payload["halt"]["active"] is True
    issues = {i["code"] for i in payload["issues"]}
    assert "halt_active" in issues


# ---------------------------------------------------------------------------
# Stale state (the lesson #42 root scenario: cron silently halted 4 days)
# ---------------------------------------------------------------------------

def test_health_check_flags_state_stale(tmp_state_root, spec):
    state = StateStore(channel=spec.name)
    # Write a state record with last_updated_utc 100h in the past — beyond 80h default
    rec = state.write(spec.name, "rb-old",
                      target_weights={"AAPL": 1.0}, portfolio_value=100_000.0,
                      latest_prices={"AAPL": 200.0})
    # Patch the persisted timestamp to be old
    raw = json.loads(state.state_path.read_text())
    raw["last_updated_utc"] = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
    state.state_path.write_text(json.dumps(raw))
    code, payload = _run_health_check(
        spec, max_state_age_hours=80.0,
        check_broker=False, allow_no_state=False,
    )
    assert code == HEALTH_STATE_STALE
    assert payload["state"]["age_hours"] > 80.0
    assert any(i["code"] == "state_stale" for i in payload["issues"])


def test_health_check_state_within_threshold_is_ok(tmp_state_root, spec):
    state = StateStore(channel=spec.name)
    rec = state.write(spec.name, "rb-recent",
                      target_weights={"AAPL": 1.0}, portfolio_value=100_000.0,
                      latest_prices={"AAPL": 200.0})
    # 60h old — under default 80h
    raw = json.loads(state.state_path.read_text())
    raw["last_updated_utc"] = (datetime.now(timezone.utc) - timedelta(hours=60)).isoformat()
    state.state_path.write_text(json.dumps(raw))
    code, _ = _run_health_check(
        spec, max_state_age_hours=80.0,
        check_broker=False, allow_no_state=False,
    )
    assert code == HEALTH_OK


# ---------------------------------------------------------------------------
# Missing state (first-run case; configurable severity)
# ---------------------------------------------------------------------------

def test_health_check_state_missing_warns_by_default(tmp_state_root, spec):
    code, payload = _run_health_check(
        spec, max_state_age_hours=80.0,
        check_broker=False, allow_no_state=False,
    )
    assert code == HEALTH_STATE_MISSING
    assert payload["state"]["present"] is False


def test_health_check_state_missing_ok_when_allowed(tmp_state_root, spec):
    code, _ = _run_health_check(
        spec, max_state_age_hours=80.0,
        check_broker=False, allow_no_state=True,
    )
    assert code == HEALTH_OK


# ---------------------------------------------------------------------------
# Halt + stale combination — halt takes precedence (most-actionable)
# ---------------------------------------------------------------------------

def test_health_check_halt_precedence_over_stale(tmp_state_root, spec):
    write_halt(tmp_state_root, spec.name, reason="reconciliation:phantom")
    state = StateStore(channel=spec.name)
    rec = state.write(spec.name, "rb", {"AAPL": 1.0}, 100_000.0, {"AAPL": 200.0})
    raw = json.loads(state.state_path.read_text())
    raw["last_updated_utc"] = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
    state.state_path.write_text(json.dumps(raw))
    code, payload = _run_health_check(
        spec, max_state_age_hours=80.0,
        check_broker=False, allow_no_state=False,
    )
    assert code == HEALTH_HALT_ACTIVE
    # Both issues are logged in payload but exit code is the most actionable one
    codes = {i["code"] for i in payload["issues"]}
    assert "halt_active" in codes
    assert "state_stale" in codes


# ---------------------------------------------------------------------------
# Broker reachability — covered indirectly (real network not used in unit tests)
# ---------------------------------------------------------------------------

def test_health_check_broker_unreachable_when_creds_missing(monkeypatch, tmp_state_root, spec):
    """If --check-broker is on but env vars are absent, AlpacaConfig.from_env raises → 12."""
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    state = StateStore(channel=spec.name)
    state.write(spec.name, "rb", {"AAPL": 1.0}, 100_000.0, {"AAPL": 200.0})
    code, payload = _run_health_check(
        spec, max_state_age_hours=80.0,
        check_broker=True, allow_no_state=False,
    )
    assert code == HEALTH_BROKER_UNREACHABLE
    assert payload["broker"]["checked"] is True
    assert "error" in payload["broker"]
