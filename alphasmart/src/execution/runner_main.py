"""
runner_main — paper-trade orchestrator + CLI entrypoint.

Wires together:
  pre-flight checks (preflight.py)
  → strategy compute + signal-equivalence gate (strategy_runner.py)
  → broker submit (alpaca_paper.py, mock or real)
  → state persist (state_store.py)
  → reconciliation drift check (reconciler.py)
  → halt-state file (paper_trade_design.md §6.4 escalation)

CLI:
    # One-shot rebalance against the equity strategy in shadow mode
    python -m src.execution.runner_main rebalance --mode shadow

    # Same in paper mode (actually submits to the paper broker)
    python -m src.execution.runner_main rebalance --mode paper

    # Status: print current state, halt flag, last reconciliation
    python -m src.execution.runner_main status

    # Clear a halt (after operator review)
    python -m src.execution.runner_main clear-halt

Persistent state lives under reports/paper_trade/state/. The halt file
(`halt.<channel>.json`) is the kill-switch: if present, rebalance refuses
to run until manually cleared.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

# Load .env if present — same pattern as api.py / main.py
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
except ImportError:
    pass

from src.data.database import Database
from src.execution.broker.alpaca_paper import (
    AlpacaPaperBroker, AlpacaConfig,
)
from src.execution.live_data import LiveDataPoller
from src.execution.preflight import run_all_checks, CheckResult
from src.execution.reconciler import Reconciler
from src.execution.shadow_log import ShadowLog
from src.execution.state_store import StateStore
from src.execution.strategy_runner import (
    StrategyRunner, StrategySpec,
    xsec_momentum_target_weights, binary_200ma_filter,
)


# ---------------------------------------------------------------------------
# Built-in strategy: equity xsec momentum + B (binary SPY 200d-MA) filter
# ---------------------------------------------------------------------------

EQUITY_UNIVERSE = sorted([
    "AAPL", "AMZN", "ASML", "AVGO", "GOOG", "MA", "META", "MSFT", "NOW",
    "NVDA", "NVO", "QQQ", "SPY", "TSLA", "V",
])


def build_equity_spec() -> StrategySpec:
    return StrategySpec(
        name="equity_xsec_momentum_B",
        signal_fn=xsec_momentum_target_weights,
        signal_params={"lookback_days": 126, "skip_days": 0, "top_k": 5},
        filter_fn=binary_200ma_filter,
        filter_input_symbol="SPY",
        universe=EQUITY_UNIVERSE,
    )


# ---------------------------------------------------------------------------
# Halt state
# ---------------------------------------------------------------------------

@dataclass
class HaltState:
    halted_at_utc: str
    reason: str
    git_sha: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "HaltState":
        return cls(
            halted_at_utc=d.get("halted_at_utc", ""),
            reason=d.get("reason", ""),
            git_sha=d.get("git_sha", ""),
        )


def _halt_path(state_root: Path, channel: str) -> Path:
    return state_root / f"halt.{channel}.json"


def read_halt(state_root: Path, channel: str) -> Optional[HaltState]:
    path = _halt_path(state_root, channel)
    if not path.exists():
        return None
    try:
        return HaltState.from_dict(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


def write_halt(state_root: Path, channel: str, reason: str, git_sha: str = "") -> Path:
    state_root.mkdir(parents=True, exist_ok=True)
    path = _halt_path(state_root, channel)
    payload = HaltState(
        halted_at_utc=datetime.now(timezone.utc).isoformat(),
        reason=reason,
        git_sha=git_sha,
    )
    path.write_text(json.dumps(asdict(payload), indent=2))
    return path


def clear_halt(state_root: Path, channel: str) -> bool:
    path = _halt_path(state_root, channel)
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Rebalance orchestration
# ---------------------------------------------------------------------------

@dataclass
class OrchestrationResult:
    timestamp_utc: str
    channel: str
    mode: str
    pre_flight_ok: bool
    pre_flight_results: list[dict] = field(default_factory=list)
    halt_state: Optional[dict] = None
    rebalance_kind: str = "scheduled"
    rebalance_executed: bool = False
    orders_submitted: int = 0
    equivalence_check_passed: bool = True
    reconciliation_should_halt: bool = False
    reconciliation_reason: Optional[str] = None
    new_halt_written: bool = False
    rebalance_result: Optional[dict] = None
    reconciliation_result: Optional[dict] = None


def load_closes(
    db_url: str,
    universe: list[str],
    filter_symbol: Optional[str] = None,
) -> pd.DataFrame:
    """Read latest 1d closes from the DB for the universe (+ filter symbol)."""
    syms = list(universe)
    if filter_symbol and filter_symbol not in syms:
        syms.append(filter_symbol)
    db = Database(db_url)
    cols = {}
    for s in syms:
        df = db.query_ohlcv(s, "1d")
        if df is None or df.empty:
            continue
        cols[s] = df["close"]
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def orchestrate_rebalance(
    spec: StrategySpec,
    broker: AlpacaPaperBroker,
    closes: pd.DataFrame,
    *,
    mode: str = "shadow",
    rebalance_kind: str = "scheduled",
    state_root: Optional[Path] = None,
    log: Optional[ShadowLog] = None,
    rebalance_threshold_pct: float = 0.005,
    stale_after_hours: float = 36.0,
    min_cash_buffer_pct: float = 0.01,
    max_position_pct: float = 0.25,
) -> OrchestrationResult:
    """One-rebalance orchestration. Idempotent given the same inputs."""
    channel = spec.name
    log = log or ShadowLog(channel=channel)
    state_root = Path(state_root) if state_root else None
    state = StateStore(channel=channel, root=state_root)
    state_root_actual = state._root  # already-resolved root

    ts_iso = datetime.now(timezone.utc).isoformat()
    out = OrchestrationResult(timestamp_utc=ts_iso, channel=channel, mode=mode,
                               pre_flight_ok=False, rebalance_kind=rebalance_kind)

    # Halt-state guard: if a halt file is present, refuse to run.
    halt = read_halt(state_root_actual, channel)
    if halt is not None:
        out.halt_state = asdict(halt)
        log.event("halt_active_skip_rebalance", asdict(halt), level="warn")
        return out

    # Pre-flights
    checks = run_all_checks(
        closes=closes, universe=spec.universe,
        filter_symbol=spec.filter_input_symbol, broker=broker,
        stale_after_hours=stale_after_hours,
        min_cash_buffer_pct=min_cash_buffer_pct,
        max_position_pct=max_position_pct,
    )
    out.pre_flight_results = [
        {"name": c.name, "ok": c.ok, "reason": c.reason, "detail": c.detail}
        for c in checks
    ]
    out.pre_flight_ok = all(c.ok for c in checks)
    log.event("pre_flight", {"ok": out.pre_flight_ok, "results": out.pre_flight_results})

    if not out.pre_flight_ok:
        log.event("rebalance_aborted", {"reason": "pre_flight_failed"}, level="error")
        return out

    # Strategy run
    runner = StrategyRunner(
        spec=spec, broker=broker, mode=mode, log=log,
        rebalance_threshold_pct=rebalance_threshold_pct,
    )
    rb_result = runner.rebalance(closes, rebalance_kind=rebalance_kind)
    out.rebalance_executed = True
    out.orders_submitted = rb_result.orders_submitted
    out.equivalence_check_passed = rb_result.equivalence_check_passed
    out.rebalance_result = asdict(rb_result)

    # Halt on equivalence failure (zero-tolerance gate)
    if not rb_result.equivalence_check_passed:
        write_halt(state_root_actual, channel,
                   reason=f"equivalence_check_failed:max_drift={rb_result.equivalence_max_drift}")
        out.new_halt_written = True
        log.event("halt_written", {"reason": "equivalence_check_failed"}, level="error")
        return out

    # Persist intent state — only after the equivalence gate passes
    rebalance_id = f"rb-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    latest_prices = {sym: float(closes[sym].iloc[-1]) for sym in closes.columns
                     if not pd.isna(closes[sym].iloc[-1])}
    state.write(
        strategy=spec.name,
        rebalance_id=rebalance_id,
        target_weights=rb_result.target_weights,
        portfolio_value=rb_result.portfolio_value,
        latest_prices=latest_prices,
    )

    # Reconcile (paper mode only; in shadow mode there's no submit so the
    # broker won't have moved → reconciliation is meaningless against fresh
    # state, would always show "missing" for every target).
    if mode == "paper":
        reconciler = Reconciler(broker=broker, state=state, log=log)
        rc_result = reconciler.reconcile()
        out.reconciliation_should_halt = rc_result.should_halt
        out.reconciliation_reason = rc_result.halt_reason
        out.reconciliation_result = {
            "max_drift_pct": rc_result.max_drift_pct,
            "cumulative_drift_pct": rc_result.cumulative_drift_pct,
            "phantom_symbols": rc_result.phantom_symbols,
            "missing_symbols": rc_result.missing_symbols,
            "should_halt": rc_result.should_halt,
            "halt_reason": rc_result.halt_reason,
        }
        if rc_result.should_halt:
            write_halt(state_root_actual, channel, reason=f"reconciliation:{rc_result.halt_reason}")
            out.new_halt_written = True
            log.event("halt_written", {"reason": rc_result.halt_reason}, level="error")

    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_broker(mode: str, log: ShadowLog, mock: bool = False) -> AlpacaPaperBroker:
    if mock:
        return AlpacaPaperBroker(mock=True, log=log)
    # Real mode (mode=paper, mock=False) — credentials must be in env
    cfg = AlpacaConfig.from_env()
    return AlpacaPaperBroker(config=cfg, mock=False, log=log)


def cmd_rebalance(args: argparse.Namespace) -> int:
    spec = build_equity_spec()
    log = ShadowLog(channel=spec.name, also_stdout=args.verbose)
    broker = _build_broker(args.mode, log, mock=args.mock)
    db_url = args.db_url or f"sqlite:///{Path(__file__).resolve().parents[2] / 'alphasmart_dev.db'}"

    # Optional pre-rebalance live-data fetch
    if args.fetch_before_rebalance:
        poller = LiveDataPoller(db_url=db_url, log=log)
        # Need both universe + filter input symbol
        full_universe = list(spec.universe)
        if spec.filter_input_symbol and spec.filter_input_symbol not in full_universe:
            full_universe.append(spec.filter_input_symbol)
        poll_result = poller.poll(
            universe=full_universe,
            timeframe="1d",
            lookback_period=args.fetch_lookback,
            stale_after_hours=args.stale_after_hours,
            skip_if_fresh=not args.force_fetch,
        )
        if not poll_result.coverage_ok:
            errors = poll_result.errors()
            print(f"WARN: live data poll did not achieve full coverage. "
                  f"Errors: {len(errors)}. Continuing — rebalance pre-flight will validate.",
                  file=sys.stderr)

    closes = load_closes(db_url=db_url, universe=spec.universe,
                          filter_symbol=spec.filter_input_symbol)
    if closes.empty:
        print("ERROR: no closes loaded from DB.", file=sys.stderr)
        return 1
    result = orchestrate_rebalance(
        spec=spec, broker=broker, closes=closes, mode=args.mode,
        rebalance_kind=args.kind, log=log,
        stale_after_hours=args.stale_after_hours,
    )
    print(json.dumps(asdict(result), indent=2, default=str))
    if not result.pre_flight_ok:
        return 2
    if not result.equivalence_check_passed:
        return 3
    if result.reconciliation_should_halt:
        return 4
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """Standalone live-data fetch — populate DB with latest bars."""
    spec = build_equity_spec()
    log = ShadowLog(channel="live_data", also_stdout=args.verbose)
    db_url = args.db_url or f"sqlite:///{Path(__file__).resolve().parents[2] / 'alphasmart_dev.db'}"
    poller = LiveDataPoller(db_url=db_url, log=log)
    full_universe = list(spec.universe)
    if spec.filter_input_symbol and spec.filter_input_symbol not in full_universe:
        full_universe.append(spec.filter_input_symbol)
    result = poller.poll(
        universe=full_universe,
        timeframe="1d",
        lookback_period=args.lookback,
        stale_after_hours=args.stale_after_hours,
        skip_if_fresh=not args.force,
    )
    print(json.dumps({
        "timestamp_utc": result.timestamp_utc,
        "universe_size": result.universe_size,
        "symbols_ok": result.symbols_ok,
        "symbols_error": result.symbols_error,
        "total_bars_inserted": result.total_bars_inserted,
        "elapsed_total_ms": result.elapsed_total_ms,
        "coverage_ok": result.coverage_ok,
        "errors": [{"symbol": e.symbol, "error": e.error} for e in result.errors()],
    }, indent=2, default=str))
    return 0 if result.coverage_ok else 5


def cmd_status(args: argparse.Namespace) -> int:
    spec = build_equity_spec()
    state = StateStore(channel=spec.name)
    state_root = state._root
    halt = read_halt(state_root, spec.name)
    record = state.read()
    payload = {
        "channel": spec.name,
        "halt_active": halt is not None,
        "halt": asdict(halt) if halt else None,
        "last_state": (
            {
                "rebalance_id": record.rebalance_id,
                "last_updated_utc": record.last_updated_utc,
                "n_positions": len(record.positions),
                "portfolio_value": record.portfolio_value,
                "positions": {sym: asdict(p) for sym, p in record.positions.items()},
            } if record else None
        ),
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


def cmd_clear_halt(args: argparse.Namespace) -> int:
    spec = build_equity_spec()
    state = StateStore(channel=spec.name)
    cleared = clear_halt(state._root, spec.name)
    print(json.dumps({"cleared": cleared, "channel": spec.name}, indent=2))
    return 0 if cleared else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="runner_main", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    p_reb = sub.add_parser("rebalance", help="Run one rebalance.")
    p_reb.add_argument("--mode", choices=("shadow", "paper"), default="shadow")
    p_reb.add_argument("--mock", action="store_true",
                       help="Use mock broker (no API calls). Default in shadow mode is mock=true.")
    p_reb.add_argument("--kind", default="scheduled",
                       choices=("scheduled", "manual", "smoke"))
    p_reb.add_argument("--db-url", default=None,
                       help="SQLAlchemy DB URL. Default: alphasmart_dev.db.")
    p_reb.add_argument("--stale-after-hours", type=float, default=36.0,
                       help="Pre-flight data-freshness threshold in hours.")
    p_reb.add_argument("--fetch-before-rebalance", action="store_true",
                       help="Run a LiveDataPoller fetch before rebalancing.")
    p_reb.add_argument("--fetch-lookback", default="5d",
                       help="yfinance period string for the fetch (default 5d).")
    p_reb.add_argument("--force-fetch", action="store_true",
                       help="Fetch even if DB bars are within stale_after_hours.")
    p_reb.add_argument("--verbose", action="store_true",
                       help="Tee log events to stdout.")
    p_reb.set_defaults(func=cmd_rebalance)

    p_fe = sub.add_parser("fetch", help="Standalone live-data fetch (populate DB).")
    p_fe.add_argument("--lookback", default="5d",
                      help="yfinance period string (default 5d).")
    p_fe.add_argument("--stale-after-hours", type=float, default=36.0)
    p_fe.add_argument("--force", action="store_true",
                      help="Fetch even if DB bars are fresh.")
    p_fe.add_argument("--db-url", default=None)
    p_fe.add_argument("--verbose", action="store_true")
    p_fe.set_defaults(func=cmd_fetch)

    p_st = sub.add_parser("status", help="Print current state and halt flag.")
    p_st.set_defaults(func=cmd_status)

    p_ch = sub.add_parser("clear-halt", help="Remove the halt file (after operator review).")
    p_ch.set_defaults(func=cmd_clear_halt)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
