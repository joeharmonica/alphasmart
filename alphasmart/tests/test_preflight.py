"""Tests for pre-flight checks."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.execution.broker.alpaca_paper import AlpacaPaperBroker, AlpacaOrderRequest
from src.execution.shadow_log import ShadowLog
from src.execution.preflight import (
    check_data_freshness, check_universe_completeness,
    check_filter_input_available, check_broker_connectivity,
    check_cash_buffer, check_position_concentration,
    run_all_checks,
)


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def closes():
    n = 250
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.005, n)
    return pd.DataFrame({
        "AAPL": 100 * np.exp(np.cumsum(rets)),
        "MSFT": 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.005, n))),
        "SPY":  100 * np.exp(np.cumsum(rng.normal(0.0003, 0.005, n))),
    }, index=idx)


@pytest.fixture
def broker(tmp_root):
    log = ShadowLog(channel="alpaca_pf", root=tmp_root)
    return AlpacaPaperBroker(mock=True, log=log)


# data_freshness ------------------------------------------------------------

def test_freshness_ok_when_recent(closes):
    last = closes.index[-1].to_pydatetime()
    now = last + timedelta(hours=1)
    r = check_data_freshness(closes, stale_after_hours=36, now_utc=now)
    assert r.ok


def test_freshness_fail_when_stale(closes):
    last = closes.index[-1].to_pydatetime()
    now = last + timedelta(hours=72)
    r = check_data_freshness(closes, stale_after_hours=36, now_utc=now)
    assert not r.ok
    assert "age" in r.reason


def test_freshness_fail_on_empty():
    r = check_data_freshness(pd.DataFrame())
    assert not r.ok


# universe_completeness -----------------------------------------------------

def test_universe_complete(closes):
    r = check_universe_completeness(closes, ["AAPL", "MSFT"])
    assert r.ok


def test_universe_missing_column(closes):
    r = check_universe_completeness(closes, ["AAPL", "GOOG"])
    assert not r.ok
    assert "GOOG" in r.reason


def test_universe_nan_at_latest(closes):
    closes = closes.copy()
    closes.loc[closes.index[-1], "AAPL"] = float("nan")
    r = check_universe_completeness(closes, ["AAPL", "MSFT"])
    assert not r.ok


# filter_input --------------------------------------------------------------

def test_filter_present(closes):
    r = check_filter_input_available(closes, "SPY", min_bars=200)
    assert r.ok


def test_filter_missing(closes):
    r = check_filter_input_available(closes, "VIX", min_bars=200)
    assert not r.ok


def test_filter_too_few_bars(closes):
    short = closes.iloc[:100]
    r = check_filter_input_available(short, "SPY", min_bars=200)
    assert not r.ok


def test_filter_skipped_when_none(closes):
    r = check_filter_input_available(closes, None)
    assert r.ok


# broker_connectivity -------------------------------------------------------

def test_broker_ok(broker):
    r = check_broker_connectivity(broker)
    assert r.ok


def test_broker_trading_blocked(broker):
    broker._mock_account.trading_blocked = True
    r = check_broker_connectivity(broker)
    assert not r.ok
    assert "trading_blocked" in r.reason


def test_broker_status_not_active(broker):
    broker._mock_account.status = "ACCOUNT_DISABLED"
    r = check_broker_connectivity(broker)
    assert not r.ok


# cash_buffer ---------------------------------------------------------------

def test_cash_buffer_ok(broker):
    r = check_cash_buffer(broker, min_cash_buffer_pct=0.01)
    assert r.ok


def test_cash_buffer_below_threshold(broker):
    broker._mock_account.cash = 100.0  # 0.1% of 100k
    r = check_cash_buffer(broker, min_cash_buffer_pct=0.01)
    assert not r.ok


# position_concentration ----------------------------------------------------

def test_concentration_empty_portfolio(broker):
    r = check_position_concentration(broker, max_position_pct=0.25)
    assert r.ok


def test_concentration_within_limit(broker):
    # Buy small position via the mock: 100 shares × $100 = $10k = 10% of $100k
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=100.0, side="buy"))
    r = check_position_concentration(broker, max_position_pct=0.25)
    assert r.ok


def test_concentration_over_limit(broker):
    # 600 shares × $100 = $60k = 60% of $100k → over 25% threshold
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=600.0, side="buy"))
    r = check_position_concentration(broker, max_position_pct=0.25)
    assert not r.ok
    assert "AAPL" in r.reason


# run_all_checks (smoke) ----------------------------------------------------

def test_run_all_returns_six_results(closes, broker):
    last = closes.index[-1].to_pydatetime()
    now = last + timedelta(hours=1)
    results = run_all_checks(
        closes=closes, universe=["AAPL", "MSFT"], filter_symbol="SPY",
        broker=broker, now_utc=now,
    )
    assert len(results) == 6
    assert all(r.ok for r in results)


# ---------------------------------------------------------------------------
# A6 (lessons.md #56) — preflight retry on transient broker network failures
# ---------------------------------------------------------------------------

class _FlakyBroker:
    """Broker stub whose method `fn_name` fails the first N calls with the
    given exception, then succeeds. Used to test the retry helper without
    monkeypatching the real Alpaca SDK."""
    def __init__(self, real, fn_name, exc, n_fails):
        self._real = real
        self._fn_name = fn_name
        self._exc = exc
        self._n_fails = n_fails
        self._calls = 0

    def __getattr__(self, name):
        target = getattr(self._real, name)
        if name != self._fn_name:
            return target
        def wrapped(*a, **kw):
            self._calls += 1
            if self._calls <= self._n_fails:
                raise self._exc
            return target(*a, **kw)
        return wrapped


def test_a6_retry_rescues_single_transient_failure(broker, monkeypatch):
    monkeypatch.setattr("src.execution.preflight.time.sleep", lambda _: None)
    """One transient RemoteDisconnected → retry succeeds."""
    from http.client import RemoteDisconnected
    flaky = _FlakyBroker(broker, "get_account", RemoteDisconnected("Remote end closed"), n_fails=1)
    result = check_broker_connectivity(flaky)
    assert result.ok is True, f"retry should rescue first transient: {result.reason}"
    assert flaky._calls == 2  # one failure + one success


def test_a6_retry_propagates_after_second_failure(broker, monkeypatch):
    """Two consecutive transient failures → final exception caught as preflight fail."""
    monkeypatch.setattr("src.execution.preflight.time.sleep", lambda _: None)
    from http.client import RemoteDisconnected
    flaky = _FlakyBroker(broker, "get_account", RemoteDisconnected("Remote end closed"), n_fails=2)
    result = check_broker_connectivity(flaky)
    assert result.ok is False
    assert "get_account failed" in (result.reason or "")
    assert flaky._calls == 2  # only retries ONCE (not infinitely)


def test_a6_retry_does_not_fire_on_auth_error(broker):
    """Non-transient errors (auth, 4xx, value) propagate on first attempt — no retry."""
    flaky = _FlakyBroker(broker, "get_account", ValueError("invalid api key"), n_fails=10)
    result = check_broker_connectivity(flaky)
    assert result.ok is False
    assert "invalid api key" in (result.reason or "")
    assert flaky._calls == 1  # did NOT retry — would have called more


def test_a6_retry_applies_to_position_concentration(broker, monkeypatch):
    """position_concentration calls get_account AND get_positions; both wrapped."""
    monkeypatch.setattr("src.execution.preflight.time.sleep", lambda _: None)
    from urllib3.exceptions import ProtocolError
    # First get_account call fails transiently, second succeeds; get_positions OK.
    flaky = _FlakyBroker(broker, "get_account", ProtocolError("Connection aborted"), n_fails=1)
    result = check_position_concentration(flaky)
    assert result.ok is True, f"retry should rescue: {result.reason}"


def test_a6_transient_classifier_recognises_known_patterns():
    """The _is_transient_broker_error helper covers the patterns we've seen in prod."""
    from src.execution.preflight import _is_transient_broker_error
    from http.client import RemoteDisconnected
    assert _is_transient_broker_error(RemoteDisconnected("anything"))
    assert _is_transient_broker_error(ConnectionResetError("reset"))
    assert _is_transient_broker_error(TimeoutError("timed out"))
    assert _is_transient_broker_error(Exception("('Connection aborted.', ...)"))
    assert _is_transient_broker_error(Exception("Max retries exceeded"))
    # Real config bugs should NOT be classified as transient
    assert not _is_transient_broker_error(ValueError("missing API key"))
    assert not _is_transient_broker_error(KeyError("ALPACA_SECRET"))
    assert not _is_transient_broker_error(PermissionError("forbidden"))
