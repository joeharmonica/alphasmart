"""
Unit tests for src/data/database.py
All tests use in-memory SQLite — no files written, no network calls.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.database import Database


IN_MEMORY = "sqlite:///:memory:"


@pytest.fixture
def db():
    return Database(IN_MEMORY)


def _make_ohlcv(n=50, start="2024-01-01") -> pd.DataFrame:
    np.random.seed(1)
    dates = pd.date_range(start, periods=n, freq="D")
    closes = 100 + np.cumsum(np.random.randn(n))
    noise = np.abs(np.random.randn(n)) * 0.5
    return pd.DataFrame({
        "open":   closes + np.random.randn(n) * 0.2,
        "high":   closes + noise,
        "low":    closes - noise,
        "close":  closes,
        "volume": np.random.randint(100_000, 500_000, n).astype(float),
    }, index=pd.DatetimeIndex(dates))


# ---------------------------------------------------------------------------
# Schema & init
# ---------------------------------------------------------------------------

class TestDatabaseInit:
    def test_creates_without_error(self):
        db = Database(IN_MEMORY)
        assert db is not None

    def test_tables_created(self):
        db = Database(IN_MEMORY)
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        assert "ohlcv" in tables
        assert "fetch_metadata" in tables


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

class TestUpsertOHLCV:
    def test_insert_new_rows(self, db):
        df = _make_ohlcv(50)
        inserted = db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        assert inserted == 50

    def test_no_duplicates_on_second_upsert(self, db):
        df = _make_ohlcv(50)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        inserted_again = db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        assert inserted_again == 0

    def test_partial_overlap_inserts_only_new(self, db):
        df1 = _make_ohlcv(50)
        db.upsert_ohlcv(df1, symbol="AAPL", timeframe="1d")

        # 25 overlap + 25 new
        df2 = _make_ohlcv(75)
        inserted = db.upsert_ohlcv(df2, symbol="AAPL", timeframe="1d")
        assert inserted == 25

    def test_empty_dataframe_returns_zero(self, db):
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        inserted = db.upsert_ohlcv(empty, symbol="AAPL", timeframe="1d")
        assert inserted == 0

    def test_different_symbols_independent(self, db):
        df = _make_ohlcv(50)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        inserted = db.upsert_ohlcv(df, symbol="MSFT", timeframe="1d")
        assert inserted == 50


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

class TestQueryOHLCV:
    def test_query_returns_dataframe(self, db):
        df = _make_ohlcv(50)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        result = db.query_ohlcv("AAPL", "1d")
        assert isinstance(result, pd.DataFrame)

    def test_query_returns_correct_columns(self, db):
        df = _make_ohlcv(50)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        result = db.query_ohlcv("AAPL", "1d")
        assert set(result.columns) == {"open", "high", "low", "close", "volume"}

    def test_query_returns_correct_count(self, db):
        df = _make_ohlcv(50)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        result = db.query_ohlcv("AAPL", "1d")
        assert len(result) == 50

    def test_query_missing_symbol_returns_empty(self, db):
        result = db.query_ohlcv("NONEXISTENT", "1d")
        assert result.empty

    def test_query_date_range_filter(self, db):
        df = _make_ohlcv(100)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")

        start = datetime(2024, 2, 1)
        end = datetime(2024, 2, 28)
        result = db.query_ohlcv("AAPL", "1d", start=start, end=end)

        assert len(result) > 0
        assert all(ts >= start for ts in result.index)
        assert all(ts <= end for ts in result.index)

    def test_query_sorted_ascending(self, db):
        df = _make_ohlcv(50)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        result = db.query_ohlcv("AAPL", "1d")
        assert result.index.is_monotonic_increasing

    def test_query_values_match_inserted(self, db):
        df = _make_ohlcv(10)
        db.upsert_ohlcv(df, symbol="TEST", timeframe="1d")
        result = db.query_ohlcv("TEST", "1d")
        # Closes should match (within float precision)
        assert np.allclose(result["close"].values, df["close"].values, atol=1e-6)


# ---------------------------------------------------------------------------
# Count + status
# ---------------------------------------------------------------------------

class TestCountAndStatus:
    def test_count_bars(self, db):
        df = _make_ohlcv(50)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        assert db.count_bars("AAPL", "1d") == 50

    def test_list_symbols(self, db):
        df = _make_ohlcv(10)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d")
        db.upsert_ohlcv(df, symbol="BTC/USDT", timeframe="1d")
        symbols = db.list_symbols()
        assert "AAPL" in symbols
        assert "BTC/USDT" in symbols

    def test_fetch_status_updated(self, db):
        df = _make_ohlcv(20)
        db.upsert_ohlcv(df, symbol="AAPL", timeframe="1d", source="yfinance")
        status = db.fetch_status()
        assert len(status) == 1
        assert status[0]["symbol"] == "AAPL"
        assert status[0]["record_count"] == 20

    def test_fetch_status_empty_db(self, db):
        status = db.fetch_status()
        assert status == []
