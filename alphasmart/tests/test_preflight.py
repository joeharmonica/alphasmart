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
