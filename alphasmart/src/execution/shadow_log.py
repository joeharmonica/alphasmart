"""
Structured JSON-line event log for paper-trade execution.

Each event is one line of valid JSON with a fixed schema, written to a
date-stamped file under reports/paper_trade/<UTC date>/. Designed to be
forensically auditable: every broker call, every signal computation, every
reconciliation result, every halt is recorded with timestamps + git SHA.

Usage:
    log = ShadowLog(channel="alpaca_paper")
    log.event("get_account", {"buying_power": 100_000.0, "status": "ACTIVE"})
    log.event("submit_order", {...}, level="info")
    log.event("reconciliation_drift", {...}, level="warn")

Read back later:
    for ev in ShadowLog.read("2026-05-05"):
        if ev["type"] == "submit_order": ...
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _git_sha() -> str:
    """Best-effort git SHA capture; returns 'unknown' if not in a repo."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        return sha[:12]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"


def _serialise(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _serialise(v) for k, v in asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialise(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # Fallback for unknown types (e.g. pandas Timestamp)
    return str(obj)


class ShadowLog:
    """
    JSON-line event log. One file per (channel, UTC date) under
    reports/paper_trade/<date>/<channel>.jsonl.
    """

    def __init__(
        self,
        channel: str,
        root: Path | str | None = None,
        also_stdout: bool = False,
    ) -> None:
        self.channel = channel
        self.also_stdout = also_stdout
        self.git_sha = _git_sha()
        self._root = Path(root) if root else self._default_root()
        self._date = datetime.now(timezone.utc).strftime("%Y%m%d")
        self._dir = self._root / self._date
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{channel}.jsonl"

    @staticmethod
    def _default_root() -> Path:
        # alphasmart/src/execution/shadow_log.py → ../../reports/paper_trade
        return Path(__file__).resolve().parents[2].parent / "reports" / "paper_trade"

    @property
    def path(self) -> Path:
        return self._path

    def event(
        self,
        event_type: str,
        payload: Any = None,
        level: str = "info",
    ) -> dict:
        rec = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "channel": self.channel,
            "level": level,
            "type": event_type,
            "git_sha": self.git_sha,
            "pid": os.getpid(),
            "payload": _serialise(payload) if payload is not None else None,
        }
        line = json.dumps(rec, default=str)
        with self._path.open("a") as fh:
            fh.write(line + "\n")
        if self.also_stdout:
            print(line, file=sys.stdout, flush=True)
        return rec

    @classmethod
    def read(
        cls,
        date_tag: str,
        channel: str | None = None,
        root: Path | str | None = None,
    ) -> Iterator[dict]:
        """Iterate events from a given UTC date. Optionally filter by channel."""
        base = Path(root) if root else cls._default_root()
        day = base / date_tag
        if not day.exists():
            return
        files = sorted(day.glob("*.jsonl"))
        if channel:
            files = [f for f in files if f.stem == channel]
        for f in files:
            with f.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
