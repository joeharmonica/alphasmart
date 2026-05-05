"""
Reconciler — post-rebalance integrity check (paper_trade_design.md §2(d)).

Compares broker-reported positions against the StrategyRunner's persisted
expected positions. Flags drift beyond per-symbol and cumulative thresholds.

Drift sources we expect to see:
  - Fractional-share rounding (~0.01% per symbol, expected, ignored)
  - Slippage at fill (avg_entry_price differs but qty matches; not a drift)

Drift sources that should halt:
  - Missing fill (broker qty < expected by > threshold)
  - Phantom position (broker has a symbol the strategy never asked for)
  - Unknown corporate action (broker reports drastically different qty)

Failure escalation per design:
  drift > 1% per-symbol → halt new orders, leave existing positions alone,
  emit one notification event. The reconciler returns should_halt=True;
  the orchestrator (runner_main, step 6) is responsible for actually
  halting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.execution.broker.alpaca_paper import AlpacaPaperBroker, AlpacaPosition
from src.execution.shadow_log import ShadowLog
from src.execution.state_store import StateStore, StateRecord


# Defaults from paper_trade_design.md §2 / §6
DEFAULT_PER_SYMBOL_DRIFT_HALT_PCT = 0.01     # 1% qty drift on any one symbol
DEFAULT_CUMULATIVE_30D_HALT_PCT = 0.005      # 0.5% across all symbols, 30 days
PHANTOM_POSITION_HALT = True                  # broker has a symbol we didn't expect


@dataclass
class SymbolDrift:
    symbol: str
    expected_qty: float
    broker_qty: float
    drift_qty: float
    drift_pct: float                 # broker_qty - expected_qty / expected_qty (when expected > 0)
    classification: str              # "ok" | "drift" | "missing" | "phantom" | "pending_fill"
    pending_open_qty: float = 0.0    # qty currently in unfilled broker orders


@dataclass
class ReconciliationResult:
    timestamp_utc: datetime
    state_age_seconds: Optional[float]
    expected_positions_count: int
    broker_positions_count: int
    symbols: list[SymbolDrift]
    max_drift_pct: float
    cumulative_drift_pct: float       # sum of |drift_pct| for symbols with classification "drift"
    phantom_symbols: list[str]
    missing_symbols: list[str]
    should_halt: bool
    halt_reason: Optional[str] = None


class Reconciler:
    def __init__(
        self,
        broker: AlpacaPaperBroker,
        state: StateStore,
        log: Optional[ShadowLog] = None,
        per_symbol_drift_halt_pct: float = DEFAULT_PER_SYMBOL_DRIFT_HALT_PCT,
        cumulative_30d_halt_pct: float = DEFAULT_CUMULATIVE_30D_HALT_PCT,
        phantom_halt: bool = PHANTOM_POSITION_HALT,
    ) -> None:
        self.broker = broker
        self.state = state
        self.log = log or ShadowLog(channel=f"reconciler_{state.channel}")
        self.per_symbol_threshold = float(per_symbol_drift_halt_pct)
        self.cumulative_threshold = float(cumulative_30d_halt_pct)
        self.phantom_halt = bool(phantom_halt)

    def reconcile(self) -> ReconciliationResult:
        """
        Read state, snapshot broker, classify each symbol, decide halt.
        Logs the full result; halt decisions surface in `should_halt`.
        """
        ts = datetime.now(timezone.utc)
        record = self.state.read()
        broker_positions = self.broker.get_positions()
        broker_by_sym = {p.symbol: p for p in broker_positions}

        if record is None:
            # No expected state yet → first run; just confirm broker is empty.
            return self._handle_no_state(ts, broker_by_sym)

        # Also pull broker open orders so we can credit "pending fills"
        # toward expected positions. Without this, the reconciler at the
        # moment of submission (orders queued but not yet filled — e.g. when
        # market is closed) would always halt with missing_symbols=[...].
        try:
            open_orders = self.broker.list_open_orders()
        except Exception:
            open_orders = []
        pending_by_sym: dict[str, float] = {}
        for o in open_orders:
            signed = o.qty if o.side == "buy" else -o.qty
            pending_by_sym[o.symbol] = pending_by_sym.get(o.symbol, 0.0) + signed

        expected = record.positions
        all_syms = set(expected) | set(broker_by_sym) | set(pending_by_sym)
        symbols: list[SymbolDrift] = []
        for sym in sorted(all_syms):
            pending_qty = pending_by_sym.get(sym, 0.0)
            if sym in expected and sym in broker_by_sym:
                drift = self._classify_match(sym, expected[sym].qty, broker_by_sym[sym])
                drift.pending_open_qty = pending_qty
                symbols.append(drift)
            elif sym in expected:
                # Expected but not yet at broker. If a pending buy exists
                # that closes the gap, treat as pending_fill (no halt).
                expected_qty = expected[sym].qty
                effective_broker = pending_qty   # what broker WILL show after fill
                drift_qty = effective_broker - expected_qty
                drift_pct = drift_qty / expected_qty if expected_qty != 0 else float("inf")
                if abs(drift_pct) <= self.per_symbol_threshold and pending_qty != 0:
                    classification = "pending_fill"
                else:
                    classification = "missing"
                symbols.append(SymbolDrift(
                    symbol=sym,
                    expected_qty=expected_qty,
                    broker_qty=0.0,
                    drift_qty=-expected_qty,
                    drift_pct=-1.0,
                    classification=classification,
                    pending_open_qty=pending_qty,
                ))
            else:
                pos = broker_by_sym[sym]
                symbols.append(SymbolDrift(
                    symbol=sym,
                    expected_qty=0.0, broker_qty=pos.qty,
                    drift_qty=pos.qty,
                    drift_pct=float("inf"),
                    classification="phantom",
                    pending_open_qty=pending_qty,
                ))

        max_drift = max((abs(s.drift_pct) for s in symbols
                         if s.classification == "drift"), default=0.0)
        cumulative = sum(abs(s.drift_pct) for s in symbols if s.classification == "drift")
        phantom_syms = [s.symbol for s in symbols if s.classification == "phantom"]
        missing_syms = [s.symbol for s in symbols if s.classification == "missing"]
        pending_syms = [s.symbol for s in symbols if s.classification == "pending_fill"]

        # Halt logic (escalation matches design §6 default 4)
        halt_reasons = []
        if max_drift > self.per_symbol_threshold:
            halt_reasons.append(f"per_symbol_drift={max_drift:.4f}>{self.per_symbol_threshold}")
        if cumulative > self.cumulative_threshold:
            halt_reasons.append(f"cumulative_drift={cumulative:.4f}>{self.cumulative_threshold}")
        if missing_syms:
            halt_reasons.append(f"missing_symbols={missing_syms}")
        if phantom_syms and self.phantom_halt:
            halt_reasons.append(f"phantom_symbols={phantom_syms}")

        should_halt = bool(halt_reasons)
        halt_reason = "; ".join(halt_reasons) if halt_reasons else None

        try:
            state_dt = datetime.fromisoformat(record.last_updated_utc)
            state_age = (ts - state_dt).total_seconds()
        except Exception:
            state_age = None

        result = ReconciliationResult(
            timestamp_utc=ts,
            state_age_seconds=state_age,
            expected_positions_count=len(expected),
            broker_positions_count=len(broker_by_sym),
            symbols=symbols,
            max_drift_pct=max_drift,
            cumulative_drift_pct=cumulative,
            phantom_symbols=phantom_syms,
            missing_symbols=missing_syms,
            should_halt=should_halt,
            halt_reason=halt_reason,
        )

        self.log.event(
            "reconciliation",
            {
                "max_drift_pct": max_drift,
                "cumulative_drift_pct": cumulative,
                "phantom_symbols": phantom_syms,
                "missing_symbols": missing_syms,
                "pending_fill_symbols": pending_syms,
                "should_halt": should_halt,
                "halt_reason": halt_reason,
                "state_age_seconds": state_age,
                "n_expected": len(expected),
                "n_broker": len(broker_by_sym),
                "n_open_orders": len(open_orders),
                "symbols": [vars(s) for s in symbols],
            },
            level="error" if should_halt else "info",
        )
        return result

    # -----------------------------------------------------------------

    def _classify_match(self, sym: str, expected_qty: float, broker_pos: AlpacaPosition) -> SymbolDrift:
        broker_qty = broker_pos.qty
        drift_qty = broker_qty - expected_qty
        if expected_qty != 0:
            drift_pct = drift_qty / expected_qty
        else:
            drift_pct = 0.0 if broker_qty == 0 else float("inf")

        # Treat drift below the per-symbol threshold as "ok" (sub-threshold rounding)
        classification = "ok" if abs(drift_pct) <= self.per_symbol_threshold else "drift"
        return SymbolDrift(
            symbol=sym,
            expected_qty=expected_qty,
            broker_qty=broker_qty,
            drift_qty=drift_qty,
            drift_pct=drift_pct,
            classification=classification,
        )

    def _handle_no_state(self, ts: datetime, broker_by_sym: dict[str, AlpacaPosition]) -> ReconciliationResult:
        # First-ever reconciliation — there is no expected state to compare.
        # If broker has positions anyway, those are phantoms (or stale from a
        # prior run). Either way: log loudly and halt if so configured.
        phantom_syms = sorted(broker_by_sym.keys())
        symbols = [
            SymbolDrift(symbol=s, expected_qty=0.0, broker_qty=broker_by_sym[s].qty,
                        drift_qty=broker_by_sym[s].qty, drift_pct=float("inf"),
                        classification="phantom")
            for s in phantom_syms
        ]
        should_halt = bool(phantom_syms) and self.phantom_halt
        halt_reason = (f"first_run_with_phantoms={phantom_syms}"
                       if should_halt else None)
        result = ReconciliationResult(
            timestamp_utc=ts,
            state_age_seconds=None,
            expected_positions_count=0,
            broker_positions_count=len(broker_by_sym),
            symbols=symbols,
            max_drift_pct=0.0,
            cumulative_drift_pct=0.0,
            phantom_symbols=phantom_syms,
            missing_symbols=[],
            should_halt=should_halt,
            halt_reason=halt_reason,
        )
        self.log.event(
            "reconciliation_no_state",
            {"phantom_symbols": phantom_syms, "should_halt": should_halt,
             "halt_reason": halt_reason},
            level="warn" if phantom_syms else "info",
        )
        return result
