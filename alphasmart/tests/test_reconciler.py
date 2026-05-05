"""
Tests for Reconciler + StateStore.

Covers:
  - StateStore round-trip (write → read produces identical record)
  - History append works
  - Reconciler "no state yet" — empty broker → ok; broker has positions → phantom halt
  - Reconciler "all match" — broker positions exactly match expected → no halt
  - Reconciler "sub-threshold drift" — small diff classified ok, no halt
  - Reconciler "above per-symbol threshold" — large diff → halt with halt_reason
  - Reconciler "missing symbol" — expected position not at broker → halt
  - Reconciler "phantom symbol" — broker has unexpected position → halt
  - Reconciler "cumulative drift" — many small drifts adding up → halt
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.execution.broker.alpaca_paper import AlpacaPaperBroker, AlpacaOrderRequest
from src.execution.shadow_log import ShadowLog
from src.execution.state_store import StateStore, ExpectedPosition
from src.execution.reconciler import Reconciler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def state(tmp_root):
    return StateStore(channel="test", root=tmp_root / "state")


@pytest.fixture
def broker(tmp_root):
    log = ShadowLog(channel="alpaca_test", root=tmp_root / "logs")
    # Mock broker with prices wired so positions track meaningful market_value
    return AlpacaPaperBroker(
        mock=True, log=log,
        mock_price_provider=lambda sym: 100.0,
    )


@pytest.fixture
def reconciler(broker, state, tmp_root):
    log = ShadowLog(channel="reconciler_test", root=tmp_root / "logs")
    return Reconciler(broker=broker, state=state, log=log)


# ---------------------------------------------------------------------------
# StateStore tests
# ---------------------------------------------------------------------------

def test_state_store_round_trip(state):
    rec = state.write(
        strategy="equity_xsec_momentum_B",
        rebalance_id="rb-001",
        target_weights={"AAPL": 0.2, "MSFT": 0.2, "NVDA": 0.2, "GOOG": 0.2, "META": 0.2},
        portfolio_value=100_000.0,
        latest_prices={"AAPL": 200.0, "MSFT": 400.0, "NVDA": 800.0, "GOOG": 150.0, "META": 500.0},
    )
    assert rec.strategy == "equity_xsec_momentum_B"
    assert rec.rebalance_id == "rb-001"
    assert len(rec.positions) == 5
    assert rec.positions["AAPL"].qty == pytest.approx(100.0)  # 0.2 * 100k / 200
    assert rec.positions["NVDA"].qty == pytest.approx(25.0)   # 0.2 * 100k / 800

    read = state.read()
    assert read is not None
    assert read.strategy == rec.strategy
    assert read.rebalance_id == rec.rebalance_id
    for sym in rec.positions:
        assert read.positions[sym].qty == pytest.approx(rec.positions[sym].qty)
        assert read.positions[sym].weight == pytest.approx(rec.positions[sym].weight)


def test_state_store_history_appends(state):
    state.write("s", "rb-1", {"AAPL": 0.5}, 100_000.0, {"AAPL": 100.0})
    state.write("s", "rb-2", {"MSFT": 0.5}, 100_000.0, {"MSFT": 200.0})
    history = list(state.history())
    assert len(history) == 2
    assert history[0]["rebalance_id"] == "rb-1"
    assert history[1]["rebalance_id"] == "rb-2"


def test_state_store_read_returns_none_when_no_state(state):
    assert state.read() is None


def test_state_store_skips_zero_weight_or_missing_price(state):
    rec = state.write(
        strategy="s", rebalance_id="rb",
        target_weights={"AAPL": 0.5, "MSFT": 0.0, "NVDA": 0.5},
        portfolio_value=100_000.0,
        latest_prices={"AAPL": 100.0, "NVDA": 200.0},  # MSFT missing
    )
    assert "AAPL" in rec.positions
    assert "MSFT" not in rec.positions  # zero weight excluded
    assert "NVDA" in rec.positions


# ---------------------------------------------------------------------------
# Reconciler — happy path / no state
# ---------------------------------------------------------------------------

def test_reconciler_no_state_empty_broker_is_ok(reconciler):
    result = reconciler.reconcile()
    assert result.expected_positions_count == 0
    assert result.broker_positions_count == 0
    assert result.should_halt is False


def test_reconciler_no_state_with_broker_positions_halts(reconciler, broker):
    broker.submit_order(AlpacaOrderRequest(symbol="STALE", qty=10, side="buy"))
    result = reconciler.reconcile()
    assert result.should_halt is True
    assert "STALE" in result.phantom_symbols
    assert "first_run_with_phantoms" in result.halt_reason


def test_reconciler_perfect_match_no_halt(reconciler, broker, state):
    # Strategy intends to hold AAPL=10, MSFT=10
    state.write("s", "rb-1",
                target_weights={"AAPL": 0.5, "MSFT": 0.5},
                portfolio_value=2_000.0,
                latest_prices={"AAPL": 100.0, "MSFT": 100.0})
    # Broker fills exactly that
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=10.0, side="buy"))
    broker.submit_order(AlpacaOrderRequest(symbol="MSFT", qty=10.0, side="buy"))
    result = reconciler.reconcile()
    assert result.should_halt is False
    assert result.max_drift_pct == 0.0
    assert all(s.classification == "ok" for s in result.symbols)


# ---------------------------------------------------------------------------
# Reconciler — drift / missing / phantom
# ---------------------------------------------------------------------------

def test_reconciler_subthreshold_drift_classified_ok(reconciler, broker, state):
    """0.5% drift is below the 1% per-symbol halt threshold → ok."""
    state.write("s", "rb",
                target_weights={"AAPL": 1.0},
                portfolio_value=1000.0, latest_prices={"AAPL": 100.0})
    # State expects qty=10. Broker actually has 9.95 (-0.5%)
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=9.95, side="buy"))
    result = reconciler.reconcile()
    assert result.should_halt is False
    assert all(s.classification == "ok" for s in result.symbols)


def test_reconciler_per_symbol_drift_above_threshold_halts(reconciler, broker, state):
    """5% drift on a symbol → above 1% threshold → halt."""
    state.write("s", "rb",
                target_weights={"AAPL": 1.0},
                portfolio_value=1000.0, latest_prices={"AAPL": 100.0})
    # State expects qty=10. Broker has 9.5 (-5%)
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=9.5, side="buy"))
    result = reconciler.reconcile()
    assert result.should_halt is True
    assert result.max_drift_pct >= 0.04
    assert "per_symbol_drift" in result.halt_reason
    assert any(s.symbol == "AAPL" and s.classification == "drift" for s in result.symbols)


def test_reconciler_missing_symbol_halts(reconciler, broker, state):
    """State expects MSFT but broker has none → halt."""
    state.write("s", "rb",
                target_weights={"AAPL": 0.5, "MSFT": 0.5},
                portfolio_value=2000.0,
                latest_prices={"AAPL": 100.0, "MSFT": 100.0})
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=10.0, side="buy"))
    # MSFT was never bought → missing
    result = reconciler.reconcile()
    assert result.should_halt is True
    assert "MSFT" in result.missing_symbols
    assert "missing_symbols" in result.halt_reason


def test_reconciler_phantom_symbol_halts_when_configured(reconciler, broker, state):
    """Broker has a position not in expected state → halt."""
    state.write("s", "rb",
                target_weights={"AAPL": 1.0},
                portfolio_value=1000.0, latest_prices={"AAPL": 100.0})
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=10.0, side="buy"))
    broker.submit_order(AlpacaOrderRequest(symbol="GHOST", qty=5.0, side="buy"))
    result = reconciler.reconcile()
    assert result.should_halt is True
    assert "GHOST" in result.phantom_symbols


def test_reconciler_phantom_symbol_no_halt_when_disabled(broker, state, tmp_root):
    """If phantom_halt=False, phantoms surface but don't trigger halt by themselves."""
    state.write("s", "rb",
                target_weights={"AAPL": 1.0},
                portfolio_value=1000.0, latest_prices={"AAPL": 100.0})
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=10.0, side="buy"))
    broker.submit_order(AlpacaOrderRequest(symbol="GHOST", qty=5.0, side="buy"))
    log = ShadowLog(channel="recon_no_halt", root=tmp_root / "logs")
    reconciler = Reconciler(broker=broker, state=state, log=log, phantom_halt=False)
    result = reconciler.reconcile()
    assert "GHOST" in result.phantom_symbols
    # Phantom alone shouldn't halt; no other halt source either
    assert result.should_halt is False


def test_reconciler_cumulative_drift_halts(broker, state, tmp_root):
    """
    Many sub-threshold drifts each below 1% but summing above the
    cumulative_30d_halt_pct → halt.
    """
    # 5 symbols each at qty=10. Halt threshold cumulative = 0.005 (0.5%).
    state.write("s", "rb",
                target_weights={"A": 0.2, "B": 0.2, "C": 0.2, "D": 0.2, "E": 0.2},
                portfolio_value=5000.0,
                latest_prices={"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0, "E": 100.0})
    # Each symbol drifts 1.5% (above the 1% per-symbol threshold to qualify
    # as "drift"; cumulative = 5*1.5% = 7.5%)
    for sym in "ABCDE":
        broker.submit_order(AlpacaOrderRequest(symbol=sym, qty=9.85, side="buy"))
    log = ShadowLog(channel="recon_cum", root=tmp_root / "logs")
    reconciler = Reconciler(broker=broker, state=state, log=log,
                             # Lower per-symbol so each gets classified as drift
                             per_symbol_drift_halt_pct=0.014,
                             cumulative_30d_halt_pct=0.05)
    result = reconciler.reconcile()
    assert result.should_halt is True
    assert "cumulative_drift" in result.halt_reason
    assert result.cumulative_drift_pct > 0.05


def test_reconciler_pending_open_orders_credited_as_pending_fill(reconciler, broker, state):
    """
    After a paper-mode submit when market is closed, orders queue with status
    'new' (not yet filled). Reconciliation should credit those pending orders
    against expected positions and not halt.
    """
    state.write("s", "rb",
                target_weights={"AAPL": 0.5, "MSFT": 0.5},
                portfolio_value=2000.0,
                latest_prices={"AAPL": 100.0, "MSFT": 100.0})
    # Mock broker doesn't queue in real-Alpaca sense; we synthesise pending
    # orders by directly manipulating the mock orders list to a non-filled status.
    from src.execution.broker.alpaca_paper import AlpacaOrderResult
    from datetime import datetime, timezone
    broker._mock_orders.append(AlpacaOrderResult(
        id="pending-1", client_order_id="cid-1", symbol="AAPL",
        qty=10.0, side="buy", submitted_at=datetime.now(timezone.utc),
        status="new", filled_qty=0.0,
    ))
    broker._mock_orders.append(AlpacaOrderResult(
        id="pending-2", client_order_id="cid-2", symbol="MSFT",
        qty=10.0, side="buy", submitted_at=datetime.now(timezone.utc),
        status="new", filled_qty=0.0,
    ))
    # No actual positions yet; broker.get_positions() returns []
    result = reconciler.reconcile()
    assert result.should_halt is False
    pending = [s for s in result.symbols if s.classification == "pending_fill"]
    assert len(pending) == 2
    assert {s.symbol for s in pending} == {"AAPL", "MSFT"}


def test_reconciler_logs_full_per_symbol_breakdown(reconciler, broker, state, tmp_root):
    state.write("s", "rb",
                target_weights={"AAPL": 1.0},
                portfolio_value=1000.0, latest_prices={"AAPL": 100.0})
    broker.submit_order(AlpacaOrderRequest(symbol="AAPL", qty=10.0, side="buy"))
    reconciler.reconcile()
    log_files = list((tmp_root / "logs").rglob("reconciler_test.jsonl"))
    assert log_files
    events = [json.loads(line) for line in log_files[0].read_text().splitlines() if line.strip()]
    recon_events = [e for e in events if e["type"] == "reconciliation"]
    assert recon_events
    payload = recon_events[0]["payload"]
    assert "symbols" in payload
    assert any(s["symbol"] == "AAPL" for s in payload["symbols"])
