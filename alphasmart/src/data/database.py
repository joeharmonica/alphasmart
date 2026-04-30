"""
Database layer for AlphaSMART.
SQLite for dev → PostgreSQL for prod (swap connection string in settings.yaml).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.monitoring.logger import logger


class Base(DeclarativeBase):
    pass


class OHLCVRecord(Base):
    """One row = one OHLCV bar for a given symbol + timeframe."""

    __tablename__ = "ohlcv"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    timeframe = Column(String(8), nullable=False)   # e.g. "1d", "1h"
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    source = Column(String(32), nullable=True)       # e.g. "yfinance", "binance"

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_ohlcv_bar"),
    )

    def __repr__(self) -> str:
        return f"<OHLCV {self.symbol} {self.timeframe} {self.timestamp} close={self.close}>"


class BacktestCacheRecord(Base):
    """One row = one run_all() result for a strategy × symbol × timeframe combo."""

    __tablename__ = "backtest_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    timeframe = Column(String(8), nullable=False)
    run_at = Column(DateTime, nullable=False)

    # Core metrics
    total_return = Column(Float, nullable=True)
    cagr = Column(Float, nullable=True)
    sharpe = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    win_rate = Column(Float, nullable=True)
    trade_count = Column(Integer, nullable=True)
    profit_factor = Column(Float, nullable=True)
    score = Column(Float, nullable=True)
    rank = Column(Integer, nullable=True)

    # Flags
    gate1_pass = Column(Boolean, nullable=True)
    halted = Column(Boolean, nullable=True)
    is_optimized = Column(Boolean, nullable=True)

    __table_args__ = (
        UniqueConstraint("strategy", "symbol", "timeframe", name="uq_cache_run"),
    )


class FetchMetadata(Base):
    """Tracks the last successful fetch per symbol + timeframe."""

    __tablename__ = "fetch_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    timeframe = Column(String(8), nullable=False)
    last_fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    record_count = Column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", name="uq_fetch_meta"),
    )


class Database:
    """Database access object — handles all CRUD for OHLCV data."""

    def __init__(self, connection_string: str = "sqlite:///alphasmart_dev.db") -> None:
        # In-memory SQLite needs StaticPool so all sessions share the same connection
        if "/:memory:" in connection_string:
            self.engine = create_engine(
                connection_string,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )
        else:
            self.engine = create_engine(connection_string, echo=False)
        self._SessionFactory = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        logger.info(f"Database initialised: {connection_string.split('///')[0]}")

    def session(self) -> Session:
        return self._SessionFactory()

    # ------------------------------------------------------------------
    # OHLCV
    # ------------------------------------------------------------------

    def upsert_ohlcv(self, df: pd.DataFrame, symbol: str, timeframe: str, source: str = "") -> int:
        """
        Insert or ignore OHLCV rows.
        Returns count of rows inserted (not updated — existing bars are preserved).
        """
        if df.empty:
            return 0

        inserted = 0

        # Pass 1: insert new bars
        with self.session() as sess:
            for ts, row in df.iterrows():
                existing = sess.execute(
                    select(OHLCVRecord).where(
                        OHLCVRecord.symbol == symbol,
                        OHLCVRecord.timeframe == timeframe,
                        OHLCVRecord.timestamp == ts,
                    )
                ).scalar_one_or_none()

                if existing is None:
                    record = OHLCVRecord(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                        source=source,
                    )
                    sess.add(record)
                    inserted += 1

            sess.commit()

        # Pass 2: update fetch metadata (after commit so count is accurate)
        total = self.count_bars(symbol, timeframe)
        with self.session() as sess:
            meta = sess.execute(
                select(FetchMetadata).where(
                    FetchMetadata.symbol == symbol,
                    FetchMetadata.timeframe == timeframe,
                )
            ).scalar_one_or_none()

            if meta is None:
                meta = FetchMetadata(symbol=symbol, timeframe=timeframe)
                sess.add(meta)

            meta.last_fetched_at = datetime.now(timezone.utc)
            meta.record_count = total
            sess.commit()

        logger.debug(f"Upserted {inserted} new bars for {symbol}/{timeframe}")
        return inserted

    def query_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame for a symbol, optionally filtered by date range."""
        with self.session() as sess:
            stmt = select(OHLCVRecord).where(
                OHLCVRecord.symbol == symbol,
                OHLCVRecord.timeframe == timeframe,
            )
            if start:
                stmt = stmt.where(OHLCVRecord.timestamp >= start)
            if end:
                stmt = stmt.where(OHLCVRecord.timestamp <= end)
            stmt = stmt.order_by(OHLCVRecord.timestamp)

            rows = sess.execute(stmt).scalars().all()

        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        data = {
            "open": [r.open for r in rows],
            "high": [r.high for r in rows],
            "low": [r.low for r in rows],
            "close": [r.close for r in rows],
            "volume": [r.volume for r in rows],
        }
        index = [r.timestamp for r in rows]
        df = pd.DataFrame(data, index=pd.DatetimeIndex(index))
        df.index.name = "timestamp"
        return df

    def count_bars(self, symbol: str, timeframe: str) -> int:
        with self.session() as sess:
            result = sess.execute(
                text(
                    "SELECT COUNT(*) FROM ohlcv WHERE symbol=:s AND timeframe=:t"
                ),
                {"s": symbol, "t": timeframe},
            ).scalar()
        return result or 0

    def list_symbols(self) -> list[str]:
        with self.session() as sess:
            rows = sess.execute(
                text("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol")
            ).fetchall()
        return [r[0] for r in rows]

    def fetch_status(self) -> list[dict]:
        with self.session() as sess:
            rows = sess.execute(select(FetchMetadata)).scalars().all()
        return [
            {
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "last_fetched_at": r.last_fetched_at,
                "record_count": r.record_count,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Backtest cache
    # ------------------------------------------------------------------

    def upsert_cache_results(self, records: list[dict]) -> int:
        """Upsert a list of run_all() result dicts into backtest_cache. Returns count upserted."""
        if not records:
            return 0
        now = datetime.now(timezone.utc)
        upserted = 0
        with self.session() as sess:
            for rec in records:
                existing = sess.execute(
                    select(BacktestCacheRecord).where(
                        BacktestCacheRecord.strategy == rec.get("strategy", ""),
                        BacktestCacheRecord.symbol == rec.get("symbol", ""),
                        BacktestCacheRecord.timeframe == rec.get("timeframe", "1d"),
                    )
                ).scalar_one_or_none()

                if existing is None:
                    existing = BacktestCacheRecord(
                        strategy=rec.get("strategy", ""),
                        symbol=rec.get("symbol", ""),
                        timeframe=rec.get("timeframe", "1d"),
                    )
                    sess.add(existing)

                existing.run_at = now
                existing.total_return = rec.get("total_return")
                existing.cagr = rec.get("cagr")
                existing.sharpe = rec.get("sharpe")
                existing.max_drawdown = rec.get("max_drawdown")
                existing.win_rate = rec.get("win_rate")
                existing.trade_count = rec.get("trade_count")
                existing.profit_factor = rec.get("profit_factor")
                existing.score = rec.get("score")
                existing.rank = rec.get("rank")
                existing.gate1_pass = bool(rec.get("gate1_pass", False))
                existing.halted = bool(rec.get("halted", False))
                existing.is_optimized = bool(rec.get("is_optimized", False))
                upserted += 1

            sess.commit()
        return upserted

    def query_cache_results(self) -> list[dict]:
        """Return all cached backtest results, sorted by score descending."""
        with self.session() as sess:
            rows = sess.execute(
                select(BacktestCacheRecord).order_by(BacktestCacheRecord.score.desc().nulls_last())
            ).scalars().all()
        return [
            {
                "strategy": r.strategy,
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "run_at": r.run_at.isoformat() if r.run_at else None,
                "total_return": r.total_return,
                "cagr": r.cagr,
                "sharpe": r.sharpe,
                "max_drawdown": r.max_drawdown,
                "win_rate": r.win_rate,
                "trade_count": r.trade_count,
                "profit_factor": r.profit_factor,
                "score": r.score,
                "rank": r.rank,
                "gate1_pass": r.gate1_pass,
                "halted": r.halted,
                "is_optimized": r.is_optimized,
            }
            for r in rows
        ]
