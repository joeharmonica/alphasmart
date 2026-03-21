"""
Unit tests for src/data/preprocessor.py
All tests use synthetic data — no network calls.
"""
import numpy as np
import pandas as pd
import pytest

from src.data.preprocessor import preprocess, PreprocessError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n=50, seed=0) -> pd.DataFrame:
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    closes = 100 + np.cumsum(np.random.randn(n))
    noise = np.abs(np.random.randn(n)) * 0.5
    return pd.DataFrame({
        "open":   closes + np.random.randn(n) * 0.2,
        "high":   closes + noise,
        "low":    closes - noise,
        "close":  closes,
        "volume": np.random.randint(100_000, 500_000, n).astype(float),
    }, index=dates)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPreprocessHappyPath:
    def test_returns_dataframe(self):
        df = _make_df()
        result = preprocess(df)
        assert isinstance(result, pd.DataFrame)

    def test_required_columns_present(self):
        df = _make_df()
        result = preprocess(df)
        assert set(result.columns) == {"open", "high", "low", "close", "volume"}

    def test_no_nans_in_output(self):
        df = _make_df()
        result = preprocess(df)
        assert not result.isnull().any().any()

    def test_sorted_ascending(self):
        df = _make_df().iloc[::-1]  # reverse order
        result = preprocess(df)
        assert result.index.is_monotonic_increasing

    def test_uppercase_columns_normalised(self):
        df = _make_df()
        df.columns = [c.upper() for c in df.columns]
        result = preprocess(df)
        assert all(c == c.lower() for c in result.columns)


class TestPreprocessEdgeCases:
    def test_empty_dataframe_raises(self):
        with pytest.raises(PreprocessError):
            preprocess(pd.DataFrame())

    def test_none_raises(self):
        with pytest.raises(PreprocessError):
            preprocess(None)

    def test_missing_column_raises(self):
        df = _make_df().drop(columns=["volume"])
        with pytest.raises(PreprocessError, match="Missing required columns"):
            preprocess(df)

    def test_duplicate_timestamps_removed(self):
        df = _make_df(20)
        df_duped = pd.concat([df, df.iloc[:5]])  # add 5 duplicate rows
        result = preprocess(df_duped)
        assert not result.index.duplicated().any()
        assert len(result) == 20

    def test_nan_rows_dropped(self):
        df = _make_df(50)
        df.iloc[10:13, df.columns.get_loc("close")] = np.nan
        result = preprocess(df, ffill_limit=0)
        assert not result.isnull().any().any()

    def test_ffill_fills_small_gaps(self):
        df = _make_df(50)
        df.iloc[20, df.columns.get_loc("close")] = np.nan
        result = preprocess(df, ffill_limit=3)
        # With ffill, the NaN should be filled
        assert not result.isnull().any().any()

    def test_negative_prices_dropped(self):
        df = _make_df(50)
        df.iloc[5, df.columns.get_loc("close")] = -1.0
        df.iloc[5, df.columns.get_loc("open")] = -1.0
        result = preprocess(df)
        assert (result[["open", "high", "low", "close"]] > 0).all().all()

    def test_high_less_than_low_dropped(self):
        df = _make_df(50)
        df.iloc[5, df.columns.get_loc("high")] = 1.0
        df.iloc[5, df.columns.get_loc("low")] = 999.0
        result = preprocess(df)
        assert (result["high"] >= result["low"]).all()

    def test_all_nan_raises(self):
        df = _make_df(10)
        df["close"] = np.nan
        with pytest.raises(PreprocessError):
            preprocess(df, ffill_limit=0)
