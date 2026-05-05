"""
Persistent state for the paper-trade pipeline.

Tracks what the strategy *intends* to hold (the "expected positions" record)
so the reconciler can compare against the broker's reality. Written by
StrategyRunner after each successful rebalance, read by Reconciler.

Format: a single JSON file per channel, atomically updated. History is
preserved as line-delimited JSON in a sibling file so cumulative drift
can be computed across rebalances.

Schema:
    {
      "last_updated_utc": "<iso>",
      "git_sha": "<12-char>",
      "strategy": "<spec.name>",
      "rebalance_id": "<unique-per-rebalance>",
      "positions": {"<symbol>": {"qty": <float>, "weight": <float>}},
      "cash_weight": <float>,
      "portfolio_value": <float>
    }
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()[:12]
    except Exception:
        return "unknown"


@dataclass
class ExpectedPosition:
    qty: float
    weight: float


@dataclass
class StateRecord:
    last_updated_utc: str
    git_sha: str
    strategy: str
    rebalance_id: str
    positions: dict[str, ExpectedPosition]
    cash_weight: float
    portfolio_value: float


class StateStore:
    """
    Per-channel state store. Writes are atomic (write-temp-then-rename).
    History append is best-effort (failure to append history doesn't
    invalidate the live state).
    """

    def __init__(self, channel: str, root: Optional[Path] = None) -> None:
        self.channel = channel
        self._root = Path(root) if root else self._default_root()
        self._root.mkdir(parents=True, exist_ok=True)
        self._state_path = self._root / f"{channel}.json"
        self._history_path = self._root / f"{channel}.history.jsonl"

    @staticmethod
    def _default_root() -> Path:
        # alphasmart/src/execution/state_store.py → ../../reports/paper_trade/state
        return Path(__file__).resolve().parents[2].parent / "reports" / "paper_trade" / "state"

    @property
    def state_path(self) -> Path:
        return self._state_path

    @property
    def history_path(self) -> Path:
        return self._history_path

    def write(
        self,
        strategy: str,
        rebalance_id: str,
        target_weights: dict[str, float],
        portfolio_value: float,
        latest_prices: dict[str, float],
    ) -> StateRecord:
        positions: dict[str, ExpectedPosition] = {}
        for sym, w in target_weights.items():
            price = latest_prices.get(sym)
            if price is None or price <= 0 or w <= 0:
                continue
            qty = round((w * portfolio_value) / price, 6)
            positions[sym] = ExpectedPosition(qty=qty, weight=float(w))

        cash_weight = max(0.0, 1.0 - sum(target_weights.values()))
        rec = StateRecord(
            last_updated_utc=datetime.now(timezone.utc).isoformat(),
            git_sha=_git_sha(),
            strategy=strategy,
            rebalance_id=rebalance_id,
            positions=positions,
            cash_weight=cash_weight,
            portfolio_value=float(portfolio_value),
        )
        self._atomic_write(rec)
        self._append_history(rec)
        return rec

    def read(self) -> Optional[StateRecord]:
        if not self._state_path.exists():
            return None
        try:
            data = json.loads(self._state_path.read_text())
            positions = {
                sym: ExpectedPosition(qty=float(d["qty"]), weight=float(d["weight"]))
                for sym, d in data.get("positions", {}).items()
            }
            return StateRecord(
                last_updated_utc=data["last_updated_utc"],
                git_sha=data["git_sha"],
                strategy=data["strategy"],
                rebalance_id=data["rebalance_id"],
                positions=positions,
                cash_weight=float(data["cash_weight"]),
                portfolio_value=float(data["portfolio_value"]),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def history(self):
        if not self._history_path.exists():
            return
        with self._history_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _atomic_write(self, rec: StateRecord) -> None:
        tmp = self._state_path.with_suffix(".tmp")
        payload = {
            **asdict(rec),
            "positions": {sym: asdict(p) for sym, p in rec.positions.items()},
        }
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, self._state_path)

    def _append_history(self, rec: StateRecord) -> None:
        try:
            payload = {
                **asdict(rec),
                "positions": {sym: asdict(p) for sym, p in rec.positions.items()},
            }
            with self._history_path.open("a") as fh:
                fh.write(json.dumps(payload) + "\n")
        except OSError:
            pass  # history is best-effort
