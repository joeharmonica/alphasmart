"""
Incremental live-data poller (paper_trade_design.md step 3).

Wraps the existing StockDataFetcher to keep the local DB up-to-date for
the universe of symbols the strategy_runner will rebalance against. Calls
yfinance for the last `lookback_days` of bars per symbol; the DB's
upsert_ohlcv method is idempotent (skips bars that already exist) so calls
can be made every day without duplicating data.

Failure semantics: per-symbol exceptions are caught and logged; the poll
returns a PollResult with per-symbol status. The caller (runner_main)
decides whether to abort the rebalance based on coverage thresholds
(e.g. "abort if < 14 of 15 symbols have a bar from the last 36h").

Why a separate poller (not just calling fetch in runner_main): for live
deployment we want to:
  - log fetch elapsed time + new-bars-count per symbol (drift signal)
  - distinguish "no new bars because weekend" from "yfinance error"
  - keep the runner_main logic broker-side and the data-fetching here
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from src.data.database import Database
from src.data.fetcher import StockDataFetcher
from src.execution.shadow_log import ShadowLog


@dataclass
class SymbolFetchResult:
    symbol: str
    timeframe: str
    bars_fetched: int          # bars returned by yfinance
    bars_inserted: int         # new bars actually written to DB (after dedupe)
    latest_bar_utc: Optional[str]
    elapsed_ms: int
    error: Optional[str] = None


@dataclass
class PollResult:
    timestamp_utc: str
    timeframe: str
    universe_size: int
    symbols_ok: int
    symbols_error: int
    total_bars_inserted: int
    elapsed_total_ms: int
    per_symbol: list[SymbolFetchResult] = field(default_factory=list)
    coverage_ok: bool = False    # all symbols had a bar within stale_after_hours

    def errors(self) -> list[SymbolFetchResult]:
        return [r for r in self.per_symbol if r.error]


class LiveDataPoller:
    """
    Per-call incremental fetch. Construct once per process, call poll()
    each rebalance day.
    """

    def __init__(
        self,
        db_url: str,
        log: Optional[ShadowLog] = None,
        fetcher: Optional[StockDataFetcher] = None,
    ) -> None:
        self.db = Database(db_url)
        self.fetcher = fetcher or StockDataFetcher()
        self.log = log or ShadowLog(channel="live_data")

    def poll(
        self,
        universe: list[str],
        timeframe: str = "1d",
        lookback_period: str = "5d",
        stale_after_hours: float = 36.0,
        skip_if_fresh: bool = True,
    ) -> PollResult:
        """
        Fetch the last `lookback_period` of bars for each symbol in
        `universe`. If `skip_if_fresh=True`, skip symbols whose latest
        DB bar is already within `stale_after_hours` of now.
        """
        t0_total = time.time()
        ts_iso = datetime.now(timezone.utc).isoformat()
        now = datetime.now(timezone.utc)

        per_symbol: list[SymbolFetchResult] = []
        total_inserted = 0
        n_ok = 0
        n_err = 0

        self.log.event(
            "poll_start",
            {
                "universe_size": len(universe), "timeframe": timeframe,
                "lookback_period": lookback_period,
                "skip_if_fresh": skip_if_fresh,
                "stale_after_hours": stale_after_hours,
            },
        )

        for sym in universe:
            t0 = time.time()
            # Skip-if-fresh check
            if skip_if_fresh:
                latest_db = self._latest_bar(sym, timeframe)
                if latest_db is not None:
                    age_hours = (now - latest_db).total_seconds() / 3600.0
                    if age_hours <= stale_after_hours:
                        per_symbol.append(SymbolFetchResult(
                            symbol=sym, timeframe=timeframe,
                            bars_fetched=0, bars_inserted=0,
                            latest_bar_utc=latest_db.isoformat(),
                            elapsed_ms=int((time.time() - t0) * 1000),
                            error=None,
                        ))
                        n_ok += 1
                        self.log.event(
                            "poll_symbol_fresh_skip",
                            {"symbol": sym, "age_hours": age_hours},
                        )
                        continue

            # Actual fetch
            try:
                df = self.fetcher.get_ohlcv(sym, period=lookback_period, interval=timeframe)
                fetched = len(df)
                if fetched == 0:
                    raise RuntimeError("yfinance returned 0 bars")
                inserted = self.db.upsert_ohlcv(df, symbol=sym, timeframe=timeframe, source="live_poll")
                latest_bar = df.index[-1]
                if latest_bar.tzinfo is None:
                    latest_bar = latest_bar.tz_localize("UTC")
                per_symbol.append(SymbolFetchResult(
                    symbol=sym, timeframe=timeframe,
                    bars_fetched=fetched, bars_inserted=inserted,
                    latest_bar_utc=latest_bar.isoformat(),
                    elapsed_ms=int((time.time() - t0) * 1000),
                ))
                total_inserted += inserted
                n_ok += 1
                self.log.event(
                    "poll_symbol_ok",
                    {"symbol": sym, "bars_fetched": fetched, "bars_inserted": inserted,
                     "latest_bar_utc": latest_bar.isoformat()},
                )
            except Exception as exc:
                per_symbol.append(SymbolFetchResult(
                    symbol=sym, timeframe=timeframe,
                    bars_fetched=0, bars_inserted=0, latest_bar_utc=None,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    error=f"{type(exc).__name__}: {exc}",
                ))
                n_err += 1
                self.log.event(
                    "poll_symbol_error",
                    {"symbol": sym, "error": f"{type(exc).__name__}: {exc}"},
                    level="error",
                )

        # Coverage check: all symbols must have some recent bar (whether
        # newly fetched or already-fresh-from-skip)
        coverage_ok = self._coverage_ok(universe, timeframe, stale_after_hours)
        elapsed_total = int((time.time() - t0_total) * 1000)
        result = PollResult(
            timestamp_utc=ts_iso, timeframe=timeframe,
            universe_size=len(universe),
            symbols_ok=n_ok, symbols_error=n_err,
            total_bars_inserted=total_inserted,
            elapsed_total_ms=elapsed_total,
            per_symbol=per_symbol,
            coverage_ok=coverage_ok,
        )
        self.log.event(
            "poll_end",
            {
                "n_ok": n_ok, "n_err": n_err,
                "total_bars_inserted": total_inserted,
                "elapsed_total_ms": elapsed_total,
                "coverage_ok": coverage_ok,
            },
            level="info" if coverage_ok else "warn",
        )
        return result

    # -----------------------------------------------------------------

    def _latest_bar(self, symbol: str, timeframe: str) -> Optional[datetime]:
        df = self.db.query_ohlcv(symbol, timeframe=timeframe)
        if df is None or df.empty:
            return None
        last = df.index[-1]
        if last.tzinfo is None:
            last = last.tz_localize("UTC")
        return last.to_pydatetime()

    def _coverage_ok(
        self,
        universe: list[str],
        timeframe: str,
        stale_after_hours: float,
    ) -> bool:
        now = datetime.now(timezone.utc)
        for sym in universe:
            latest = self._latest_bar(sym, timeframe)
            if latest is None:
                return False
            age_hours = (now - latest).total_seconds() / 3600.0
            if age_hours > stale_after_hours:
                return False
        return True
