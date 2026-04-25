"""
End-to-end pipeline test: preprocess → indicators → database → query.
No network calls — uses synthetic data throughout.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.preprocessor import preprocess
from src.data.indicators import add_all
from src.data.database import Database

IN_MEMORY = "sqlite:///:memory:"


def _make_raw_ohlcv(n=150) -> pd.DataFrame:
    """Simulates raw data as it arrives from a fetcher (some noise/NaN possible)."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    closes = 200 + np.cumsum(np.random.randn(n) * 1.5)
    noise = np.abs(np.random.randn(n)) * 1.0
    df = pd.DataFrame({
        "Open":   closes + np.random.randn(n) * 0.5,
        "High":   closes + noise,
        "Low":    closes - noise,
        "Close":  closes,
        "Volume": np.random.randint(500_000, 5_000_000, n).astype(float),
    }, index=pd.DatetimeIndex(dates))
    # Introduce a couple of NaN values as realistic noise
    df.iloc[5, df.columns.get_loc("Close")] = np.nan
    df.iloc[20, df.columns.get_loc("Volume")] = np.nan
    return df


class TestFullPipeline:
    def test_preprocess_cleans_raw_data(self):
        raw = _make_raw_ohlcv()
        clean = preprocess(raw, symbol="SPY")
        assert not clean.isnull().any().any()
        assert set(clean.columns) == {"open", "high", "low", "close", "volume"}

    def test_indicators_applied_to_clean_data(self):
        raw = _make_raw_ohlcv()
        clean = preprocess(raw, symbol="SPY")
        with_indicators = add_all(clean)
        expected_cols = ["ema_10", "ema_21", "rsi_14", "bb_upper", "atr_14", "vwap"]
        for col in expected_cols:
            assert col in with_indicators.columns

    def test_store_and_retrieve_preserves_values(self):
        raw = _make_raw_ohlcv(100)
        clean = preprocess(raw, symbol="SPY")

        db = Database(IN_MEMORY)
        db.upsert_ohlcv(clean, symbol="SPY", timeframe="1d", source="test")

        retrieved = db.query_ohlcv("SPY", "1d")
        assert len(retrieved) == len(clean)
        assert np.allclose(retrieved["close"].values, clean["close"].values, atol=1e-5)

    def test_full_pipeline_multi_symbol(self):
        db = Database(IN_MEMORY)
        symbols = ["AAPL", "MSFT", "BTC/USDT"]

        for sym in symbols:
            raw = _make_raw_ohlcv(100)
            clean = preprocess(raw, symbol=sym)
            db.upsert_ohlcv(clean, symbol=sym, timeframe="1d")

        stored = db.list_symbols()
        for sym in symbols:
            assert sym in stored

        status = db.fetch_status()
        assert len(status) == 3
        for row in status:
            assert row["record_count"] > 0

    def test_indicators_on_retrieved_data(self):
        db = Database(IN_MEMORY)
        raw = _make_raw_ohlcv(200)
        clean = preprocess(raw, symbol="TSLA")
        db.upsert_ohlcv(clean, symbol="TSLA", timeframe="1d")

        retrieved = db.query_ohlcv("TSLA", "1d")
        result = add_all(retrieved)

        # After 200 days we should have non-NaN EMA-200
        assert not result["ema_200"].iloc[-1:].isna().any()
        assert not result["rsi_14"].iloc[-1:].isna().any()

    def test_no_lookahead_in_indicators(self):
        """
        Verify that indicators at time T only use data up to T.
        Test: compute EMA on the full series vs. compute on truncated series.
        The last value of the truncated series should match the full series at that point.
        """
        raw = _make_raw_ohlcv(150)
        clean = preprocess(raw, symbol="TEST")

        full = add_all(clean)
        trunc = add_all(clean.iloc[:100])

        # EMA value at index 99 should match between full and truncated
        assert abs(full["ema_21"].iloc[99] - trunc["ema_21"].iloc[99]) < 1e-8
