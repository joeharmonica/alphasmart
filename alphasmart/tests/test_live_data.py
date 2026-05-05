"""
Tests for LiveDataPoller.

Uses an in-memory SQLite DB and a stub fetcher (no network calls).
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.execution.live_data import LiveDataPoller, PollResult
from src.execution.shadow_log import ShadowLog


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def db_url(tmp_root):
    return f"sqlite:///{tmp_root}/test.db"


@pytest.fixture
def log(tmp_root):
    return ShadowLog(channel="livedata", root=tmp_root)


def _bars_df(n: int, last_day: datetime, freq: str = "D") -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame ending at `last_day`."""
    idx = pd.date_range(end=last_day, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open":   np.linspace(100, 110, n),
        "high":   np.linspace(101, 111, n),
        "low":    np.linspace(99, 109, n),
        "close":  np.linspace(100, 110, n),
        "volume": np.full(n, 1_000_000.0),
    }, index=idx)


# ---------------------------------------------------------------------------
# Stub fetcher
# ---------------------------------------------------------------------------

class _StubFetcher:
    """Drop-in replacement for StockDataFetcher; returns canned data."""
    def __init__(self, response_by_symbol=None, raise_for=None):
        self.response_by_symbol = response_by_symbol or {}
        self.raise_for = raise_for or set()
        self.calls = []
    def get_ohlcv(self, symbol, period="1y", interval="1d"):
        self.calls.append((symbol, period, interval))
        if symbol in self.raise_for:
            raise RuntimeError(f"stub fetch failure for {symbol}")
        return self.response_by_symbol.get(symbol, pd.DataFrame())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_poll_inserts_new_bars_when_db_empty(db_url, log):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fetcher = _StubFetcher(response_by_symbol={
        "AAPL": _bars_df(5, today),
        "MSFT": _bars_df(5, today),
    })
    poller = LiveDataPoller(db_url=db_url, log=log, fetcher=fetcher)
    res = poller.poll(["AAPL", "MSFT"], lookback_period="5d", stale_after_hours=36)
    assert res.symbols_ok == 2
    assert res.symbols_error == 0
    assert res.total_bars_inserted == 10
    assert res.coverage_ok is True
    assert all(p.bars_inserted == 5 for p in res.per_symbol)


def test_poll_dedupes_existing_bars(db_url, log):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    df = _bars_df(5, today)
    fetcher = _StubFetcher(response_by_symbol={"AAPL": df})
    poller = LiveDataPoller(db_url=db_url, log=log, fetcher=fetcher)
    # First call: 5 inserts
    r1 = poller.poll(["AAPL"], stale_after_hours=36, skip_if_fresh=False)
    assert r1.total_bars_inserted == 5
    # Second call: 0 new inserts (same bars), but still ok
    r2 = poller.poll(["AAPL"], stale_after_hours=36, skip_if_fresh=False)
    assert r2.total_bars_inserted == 0
    assert r2.symbols_ok == 1


def test_poll_skip_if_fresh_avoids_redundant_fetch(db_url, log):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    df = _bars_df(5, today)
    fetcher = _StubFetcher(response_by_symbol={"AAPL": df})
    poller = LiveDataPoller(db_url=db_url, log=log, fetcher=fetcher)
    # Prime the DB
    poller.poll(["AAPL"], stale_after_hours=36, skip_if_fresh=False)
    n_calls_before = len(fetcher.calls)
    # Second call with skip_if_fresh=True: the bar is < 36h old → no fetch
    res = poller.poll(["AAPL"], stale_after_hours=36, skip_if_fresh=True)
    assert len(fetcher.calls) == n_calls_before  # no new yfinance call
    assert res.symbols_ok == 1
    assert res.coverage_ok is True


def test_poll_records_per_symbol_errors_and_continues(db_url, log):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fetcher = _StubFetcher(
        response_by_symbol={"AAPL": _bars_df(5, today)},  # ok
        raise_for={"BAD"},                                 # raises
    )
    poller = LiveDataPoller(db_url=db_url, log=log, fetcher=fetcher)
    res = poller.poll(["AAPL", "BAD"], skip_if_fresh=False, stale_after_hours=36)
    assert res.symbols_ok == 1
    assert res.symbols_error == 1
    assert res.coverage_ok is False  # BAD has no DB bar
    bad = next(p for p in res.per_symbol if p.symbol == "BAD")
    assert bad.error and "BAD" in bad.error


def test_poll_empty_response_treated_as_error(db_url, log):
    fetcher = _StubFetcher(response_by_symbol={"AAPL": pd.DataFrame()})
    poller = LiveDataPoller(db_url=db_url, log=log, fetcher=fetcher)
    res = poller.poll(["AAPL"], skip_if_fresh=False)
    assert res.symbols_error == 1
    assert any("0 bars" in (p.error or "") for p in res.per_symbol)


def test_poll_coverage_false_when_data_too_old(db_url, log):
    """If the latest bar is too old, coverage_ok=False even if fetch succeeded."""
    old_day = datetime.now(timezone.utc) - timedelta(days=10)
    fetcher = _StubFetcher(response_by_symbol={"AAPL": _bars_df(5, old_day)})
    poller = LiveDataPoller(db_url=db_url, log=log, fetcher=fetcher)
    res = poller.poll(["AAPL"], stale_after_hours=24, skip_if_fresh=False)
    assert res.symbols_ok == 1
    assert res.coverage_ok is False


def test_poll_logs_lifecycle_events(db_url, log, tmp_root):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fetcher = _StubFetcher(response_by_symbol={"AAPL": _bars_df(3, today)})
    poller = LiveDataPoller(db_url=db_url, log=log, fetcher=fetcher)
    poller.poll(["AAPL"], skip_if_fresh=False)
    log_files = list(tmp_root.rglob("livedata.jsonl"))
    assert log_files
    import json
    events = [json.loads(line) for line in log_files[0].read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert "poll_start" in types
    assert "poll_symbol_ok" in types
    assert "poll_end" in types
