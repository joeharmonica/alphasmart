"""
Tests for the Alpaca paper-trading adapter (mock mode).

These exercise the adapter's contract without hitting Alpaca's API:
  - account / position / order shapes
  - mock state mutation on submit_order (positions update, cash decrements)
  - structured shadow-log entries get written
  - idempotency via client_order_id
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.execution.broker.alpaca_paper import (
    AlpacaPaperBroker, AlpacaConfig,
    AlpacaOrderRequest,
)
from src.execution.shadow_log import ShadowLog


@pytest.fixture
def tmp_log_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def broker(tmp_log_root):
    log = ShadowLog(channel="alpaca_paper_test", root=tmp_log_root)
    return AlpacaPaperBroker(mock=True, log=log)


def test_get_account_initial_state(broker):
    acc = broker.get_account()
    assert acc.account_number == "MOCK000001"
    assert acc.status == "ACTIVE"
    assert acc.buying_power == 100_000.0
    assert acc.cash == 100_000.0
    assert acc.pattern_day_trader is False
    assert acc.trading_blocked is False


def test_no_positions_initially(broker):
    assert broker.get_positions() == []
    assert broker.get_position("AAPL") is None


def test_submit_buy_creates_position(broker):
    req = AlpacaOrderRequest(symbol="AAPL", qty=10.0, side="buy")
    res = broker.submit_order(req)
    assert res.status == "filled"
    assert res.symbol == "AAPL"
    assert res.qty == 10.0
    assert res.side == "buy"
    assert res.filled_qty == 10.0
    assert res.filled_avg_price == 100.0  # mock fill price
    assert res.client_order_id  # auto-generated if not provided
    assert res.id

    pos = broker.get_position("AAPL")
    assert pos is not None
    assert pos.symbol == "AAPL"
    assert pos.qty == 10.0
    assert pos.avg_entry_price == 100.0
    assert pos.side == "long"

    # Cash decremented by 10 × 100
    assert broker.get_account().cash == 100_000.0 - 1_000.0


def test_submit_sell_reduces_position(broker):
    broker.submit_order(AlpacaOrderRequest(symbol="MSFT", qty=20.0, side="buy"))
    broker.submit_order(AlpacaOrderRequest(symbol="MSFT", qty=5.0, side="sell"))
    pos = broker.get_position("MSFT")
    assert pos is not None
    assert pos.qty == 15.0


def test_full_close_removes_position(broker):
    broker.submit_order(AlpacaOrderRequest(symbol="NVDA", qty=8.0, side="buy"))
    broker.submit_order(AlpacaOrderRequest(symbol="NVDA", qty=8.0, side="sell"))
    assert broker.get_position("NVDA") is None
    # Cash returns to baseline
    assert broker.get_account().cash == 100_000.0


def test_get_positions_lists_all(broker):
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=1.0, side="buy"))
    broker.submit_order(AlpacaOrderRequest(symbol="MSFT", qty=2.0, side="buy"))
    broker.submit_order(AlpacaOrderRequest(symbol="GOOG", qty=3.0, side="buy"))
    syms = sorted(p.symbol for p in broker.get_positions())
    assert syms == ["AAPL", "GOOG", "MSFT"]


def test_explicit_client_order_id_preserved(broker):
    req = AlpacaOrderRequest(symbol="V", qty=1.0, side="buy", client_order_id="custom-123")
    res = broker.submit_order(req)
    assert res.client_order_id == "custom-123"


def test_clock_in_mock_is_open(broker):
    clock = broker.get_clock()
    assert clock.is_open is True


def test_shadow_log_records_each_call(broker, tmp_log_root):
    broker.get_account()
    broker.get_positions()
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=5.0, side="buy"))
    # Read the log file directly
    log_files = list(tmp_log_root.rglob("*.jsonl"))
    assert len(log_files) == 1
    events = [json.loads(line) for line in log_files[0].read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert "get_account" in types
    assert "get_positions" in types
    assert "submit_order" in types
    # Every event must have a git_sha (even if 'unknown')
    assert all("git_sha" in e for e in events)


def test_submit_order_log_includes_implementation_gap_fields(broker, tmp_log_root):
    """
    The headline metric for paper-trade validation: every submit_order log
    entry must carry intent_ts_utc, submitted_ts_utc, elapsed_ms — the three
    fields used to derive the 'intent-to-fill' implementation-gap signal.
    """
    broker.submit_order(AlpacaOrderRequest(symbol="QQQ", qty=2.0, side="buy"))
    log_path = next(tmp_log_root.rglob("*.jsonl"))
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    submit_events = [e for e in events if e["type"] == "submit_order"]
    assert submit_events
    payload = submit_events[0]["payload"]
    assert "intent_ts_utc" in payload
    assert "submitted_ts_utc" in payload
    assert "elapsed_ms" in payload
    assert isinstance(payload["elapsed_ms"], int)
    assert payload["request"]["symbol"] == "QQQ"
    assert payload["result"]["status"] == "filled"


def test_real_mode_requires_credentials():
    """In real mode, missing creds must raise at construction, not later."""
    import os
    saved = {k: os.environ.pop(k, None) for k in ("ALPACA_API_KEY", "ALPACA_API_SECRET")}
    try:
        with pytest.raises(RuntimeError, match="ALPACA_API_KEY"):
            AlpacaConfig.from_env()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_shadow_log_round_trip(tmp_log_root):
    log = ShadowLog(channel="t1", root=tmp_log_root)
    log.event("hello", {"x": 1})
    log.event("world", {"y": [1, 2, 3]})
    date_tag = log.path.parent.name
    events = list(ShadowLog.read(date_tag, channel="t1", root=tmp_log_root))
    assert len(events) == 2
    assert events[0]["type"] == "hello"
    assert events[1]["payload"]["y"] == [1, 2, 3]
