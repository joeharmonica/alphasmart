"""
Tests for StrategyRunner — the rebalance orchestrator.

Covers:
  - target weight computation (xsec momentum at the latest bar)
  - regime filter applied as multiplier (binary on/off)
  - current weight computation from broker positions
  - order generation respects rebalance_threshold_pct
  - shadow mode does NOT submit; paper mode DOES submit
  - signal-equivalence check passes when consistent, FAILS when sabotaged
  - halt-on-trading-blocked short-circuits without submitting
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.execution.broker.alpaca_paper import AlpacaPaperBroker, AlpacaOrderRequest
from src.execution.shadow_log import ShadowLog
from src.execution.strategy_runner import (
    StrategyRunner, StrategySpec,
    xsec_momentum_target_weights, binary_200ma_filter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log_root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def synthetic_closes():
    """
    Build deterministic close prices for 5 symbols + SPY over 300 bars.
    Pure exponential drift (no noise) so cross-sectional momentum ranking
    is deterministic — sym_E fastest, sym_A slowest.
    """
    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    drift = {"sym_A": 0.0001, "sym_B": 0.0005, "sym_C": 0.0010,
             "sym_D": 0.0015, "sym_E": 0.0020, "SPY": 0.0004}
    t = np.arange(n)
    closes = {sym: 100.0 * np.exp(mu * t) for sym, mu in drift.items()}
    return pd.DataFrame(closes, index=idx)


@pytest.fixture
def spec():
    return StrategySpec(
        name="test_xsec_mom_top3",
        signal_fn=xsec_momentum_target_weights,
        signal_params={"lookback_days": 60, "skip_days": 0, "top_k": 3},
        filter_fn=binary_200ma_filter,
        filter_input_symbol="SPY",
        universe=["sym_A", "sym_B", "sym_C", "sym_D", "sym_E"],
    )


@pytest.fixture
def broker(tmp_log_root, synthetic_closes):
    """Mock broker with prices wired to synthetic_closes' latest bar.
    This way order quantities computed by the runner produce realistic
    market_value tracking — sym_E filled at ~$181, not $100."""
    log = ShadowLog(channel="alpaca_test", root=tmp_log_root)
    latest = synthetic_closes.iloc[-1].to_dict()
    return AlpacaPaperBroker(mock=True, log=log,
                              mock_price_provider=lambda sym: float(latest.get(sym, 100.0)))


@pytest.fixture
def runner(spec, broker, tmp_log_root):
    log = ShadowLog(channel="runner_test", root=tmp_log_root)
    return StrategyRunner(spec=spec, broker=broker, mode="shadow", log=log)


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------

def test_xsec_momentum_picks_topk(synthetic_closes):
    closes = synthetic_closes[["sym_A", "sym_B", "sym_C", "sym_D", "sym_E"]]
    weights = xsec_momentum_target_weights(closes, lookback_days=60, skip_days=0, top_k=3)
    assert len(weights) == 3
    assert sum(weights.values()) == pytest.approx(1.0)
    # Highest growth rates win
    assert "sym_E" in weights
    assert "sym_D" in weights
    assert "sym_A" not in weights


def test_xsec_momentum_returns_empty_when_too_few_bars(synthetic_closes):
    short = synthetic_closes.iloc[:30]
    weights = xsec_momentum_target_weights(short, lookback_days=60, skip_days=0, top_k=3)
    assert weights == {}


def test_binary_filter_on_when_above(synthetic_closes):
    spy_uptrend = synthetic_closes["SPY"]
    val = binary_200ma_filter(spy_uptrend, ma_period=200)
    assert val in (0.0, 1.0)
    # Uptrending series ends above its MA
    assert val == 1.0


def test_binary_filter_off_when_below():
    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    # First 200 bars at 100, then crash to 50
    close = pd.Series([100.0] * 200 + [50.0] * 100, index=idx)
    val = binary_200ma_filter(close, ma_period=200)
    assert val == 0.0


# ---------------------------------------------------------------------------
# Runner integration tests
# ---------------------------------------------------------------------------

def test_rebalance_in_shadow_mode_does_not_submit(runner, broker, synthetic_closes):
    result = runner.rebalance(synthetic_closes)
    assert result.mode == "shadow"
    assert result.orders_submitted == 0
    # But it should have computed target weights
    assert len(result.target_weights) == 3
    # Equivalence check passes
    assert result.equivalence_check_passed
    assert result.equivalence_max_drift < 1e-6
    # No actual broker positions changed
    assert broker.get_positions() == []


def test_rebalance_in_paper_mode_submits(spec, broker, tmp_log_root, synthetic_closes):
    log = ShadowLog(channel="runner_paper", root=tmp_log_root)
    runner = StrategyRunner(spec=spec, broker=broker, mode="paper", log=log)
    result = runner.rebalance(synthetic_closes)
    assert result.mode == "paper"
    assert result.orders_submitted == 3   # exactly top-K
    assert len(result.target_weights) == 3
    # Broker now has those positions
    syms = sorted(p.symbol for p in broker.get_positions())
    assert syms == sorted(result.target_weights.keys())


def test_rebalance_threshold_skips_dust_trades(spec, broker, tmp_log_root, synthetic_closes):
    """If we already hold the targets, a tiny rebalance request should be skipped."""
    # First rebalance: establish positions
    log = ShadowLog(channel="runner_threshold", root=tmp_log_root)
    runner = StrategyRunner(spec=spec, broker=broker, mode="paper", log=log,
                             rebalance_threshold_pct=0.005)
    runner.rebalance(synthetic_closes)
    n_after_first = len(broker.get_positions())
    # Second rebalance immediately on the same data — targets identical →
    # all per-symbol deltas should be sub-threshold and skipped
    result = runner.rebalance(synthetic_closes)
    # mock fill price is constant 100 so positions exactly match — zero new orders
    assert result.orders_submitted == 0
    assert result.orders_skipped_threshold > 0


def test_rebalance_zero_filter_produces_zero_weights(spec, broker, tmp_log_root):
    """When the regime filter says cash, target_weights should sum to 0."""
    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(0)
    closes_dict = {}
    for sym in ["sym_A", "sym_B", "sym_C", "sym_D", "sym_E"]:
        closes_dict[sym] = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.005, n)))
    # Force SPY below its 200d MA at the end: high then crash
    closes_dict["SPY"] = np.array([100.0] * 200 + [50.0] * 100)
    closes = pd.DataFrame(closes_dict, index=idx)
    log = ShadowLog(channel="runner_zerofilt", root=tmp_log_root)
    runner = StrategyRunner(spec=spec, broker=broker, mode="paper", log=log)
    result = runner.rebalance(closes)
    assert result.target_weights == {}
    assert result.orders_submitted == 0   # no positions to take


def test_signal_equivalence_check_catches_divergence(spec, broker, tmp_log_root, synthetic_closes):
    """
    Pass deliberately-wrong weights to _signal_equivalence_check directly.
    This tests the gate's logic without needing to monkey-patch a method that
    the gate itself calls.
    """
    log = ShadowLog(channel="runner_eqcheck", root=tmp_log_root)
    runner = StrategyRunner(spec=spec, broker=broker, mode="shadow", log=log)
    # Compute the *correct* weights first
    correct, _ = runner._compute_target_weights(synthetic_closes)
    assert correct, "fixture should produce a non-empty weight set"
    # Build a sabotaged version with one symbol drift > 1e-6
    sabotaged = dict(correct)
    first = next(iter(sabotaged))
    sabotaged[first] += 0.2
    passed, max_drift, drifts = runner._signal_equivalence_check(synthetic_closes, sabotaged)
    assert passed is False
    assert max_drift > 1e-6
    assert drifts[first] >= 0.2 - 1e-9
    # Also sanity-check the happy path: passing the correct weights should pass
    passed_ok, max_drift_ok, _ = runner._signal_equivalence_check(synthetic_closes, correct)
    assert passed_ok is True
    assert max_drift_ok < 1e-6


def test_trading_blocked_short_circuits(spec, broker, tmp_log_root, synthetic_closes):
    """If broker reports trading_blocked, runner halts before any computation."""
    broker._mock_account.trading_blocked = True
    log = ShadowLog(channel="runner_halt", root=tmp_log_root)
    runner = StrategyRunner(spec=spec, broker=broker, mode="paper", log=log)
    result = runner.rebalance(synthetic_closes)
    assert "trading_blocked" in result.halts
    assert result.orders_submitted == 0
    # No positions touched
    assert broker.get_positions() == []


def test_log_records_rebalance_lifecycle(runner, synthetic_closes, tmp_log_root):
    runner.rebalance(synthetic_closes)
    log_files = list(tmp_log_root.rglob("runner_test.jsonl"))
    assert len(log_files) == 1
    events = [json.loads(line) for line in log_files[0].read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    # Mandatory events
    for t in ("rebalance_start", "target_weights", "current_weights",
              "orders_planned", "shadow_skip_submit",
              "signal_equivalence_check", "rebalance_end"):
        assert t in types, f"missing event type: {t}"
