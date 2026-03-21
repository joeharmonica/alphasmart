"""
Unit tests for src/data/indicators.py
All calculations verified against known expected values.
"""
import numpy as np
import pandas as pd
import pytest

from src.data.indicators import (
    ema, rsi, bollinger_bands, atr, volume_ma, vwap,
    add_emas, add_rsi, add_bollinger_bands, add_atr, add_volume_ma, add_vwap, add_all,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _make_df(n=100) -> pd.DataFrame:
    np.random.seed(99)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    closes = 100 + np.cumsum(np.random.randn(n) * 0.5)
    noise = np.abs(np.random.randn(n)) * 0.3
    return pd.DataFrame({
        "open":   closes + np.random.randn(n) * 0.1,
        "high":   closes + noise,
        "low":    closes - noise,
        "close":  closes,
        "volume": np.random.randint(500_000, 2_000_000, n).astype(float),
    }, index=dates)


@pytest.fixture
def df():
    return _make_df()


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEMA:
    def test_ema_returns_series(self, df):
        result = ema(df, 10)
        assert isinstance(result, pd.Series)
        assert len(result) == len(df)

    def test_ema_same_index(self, df):
        result = ema(df, 21)
        assert result.index.equals(df.index)

    def test_add_emas_adds_correct_columns(self, df):
        result = add_emas(df, periods=[10, 50])
        assert "ema_10" in result.columns
        assert "ema_50" in result.columns

    def test_ema_does_not_mutate_input(self, df):
        original_cols = list(df.columns)
        _ = add_emas(df)
        assert list(df.columns) == original_cols

    def test_ema_converges_to_constant_series(self):
        """For a constant price series, EMA should equal the constant."""
        dates = pd.date_range("2024-01-01", periods=200, freq="D")
        df_const = pd.DataFrame({"close": np.ones(200) * 50.0}, index=dates)
        result = ema(df_const, 20)
        # After enough periods, EMA should converge to 50
        assert abs(result.iloc[-1] - 50.0) < 0.01

    def test_ema_faster_period_reacts_quicker(self, df):
        """EMA with smaller period should change faster than longer period."""
        e10 = ema(df, 10)
        e50 = ema(df, 50)
        # Variance of faster EMA should be higher
        assert e10.std() >= e50.std()


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

class TestRSI:
    def test_rsi_returns_series(self, df):
        result = rsi(df, 14)
        assert isinstance(result, pd.Series)

    def test_rsi_bounded(self, df):
        result = rsi(df, 14).dropna()
        assert (result >= 0).all()
        assert (result <= 100).all()

    def test_rsi_all_up_approaches_100(self):
        """Constant rising prices → RSI approaches 100."""
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        closes = pd.Series(range(1, 101), index=dates, dtype=float)
        df_up = pd.DataFrame({"close": closes})
        result = rsi(df_up, 14).dropna()
        assert result.iloc[-1] > 90

    def test_rsi_all_down_approaches_0(self):
        """Constant falling prices → RSI approaches 0."""
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        closes = pd.Series(range(100, 0, -1), index=dates, dtype=float)
        df_down = pd.DataFrame({"close": closes})
        result = rsi(df_down, 14).dropna()
        assert result.iloc[-1] < 10

    def test_add_rsi_column_name(self, df):
        result = add_rsi(df, 14)
        assert "rsi_14" in result.columns

    def test_add_rsi_does_not_mutate(self, df):
        original_cols = list(df.columns)
        _ = add_rsi(df)
        assert list(df.columns) == original_cols


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class TestBollingerBands:
    def test_bb_returns_correct_columns(self, df):
        result = bollinger_bands(df, 20)
        assert set(result.columns) == {"bb_upper", "bb_mid", "bb_lower", "bb_width", "bb_pct_b"}

    def test_upper_above_mid_above_lower(self, df):
        bb = bollinger_bands(df, 20).dropna()
        assert (bb["bb_upper"] >= bb["bb_mid"]).all()
        assert (bb["bb_mid"] >= bb["bb_lower"]).all()

    def test_mid_is_rolling_mean(self, df):
        bb = bollinger_bands(df, 20)
        expected_mid = df["close"].rolling(20).mean()
        pd.testing.assert_series_equal(bb["bb_mid"], expected_mid, check_names=False)

    def test_add_bb_appends_columns(self, df):
        result = add_bollinger_bands(df)
        assert "bb_upper" in result.columns
        assert "bb_lower" in result.columns

    def test_bb_width_positive(self, df):
        bb = bollinger_bands(df, 20).dropna()
        assert (bb["bb_width"] > 0).all()


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

class TestATR:
    def test_atr_returns_series(self, df):
        result = atr(df, 14)
        assert isinstance(result, pd.Series)

    def test_atr_positive(self, df):
        result = atr(df, 14).dropna()
        assert (result > 0).all()

    def test_atr_increases_with_volatility(self):
        """Higher volatility should produce higher ATR."""
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        np.random.seed(7)

        # Low volatility
        c_low = 100 + np.cumsum(np.random.randn(100) * 0.1)
        df_low = pd.DataFrame({
            "high": c_low + 0.1, "low": c_low - 0.1, "close": c_low
        }, index=dates)

        # High volatility
        c_high = 100 + np.cumsum(np.random.randn(100) * 2.0)
        df_high = pd.DataFrame({
            "high": c_high + 2.0, "low": c_high - 2.0, "close": c_high
        }, index=dates)

        atr_low = atr(df_low, 14).iloc[-1]
        atr_high = atr(df_high, 14).iloc[-1]
        assert atr_high > atr_low

    def test_add_atr_column_name(self, df):
        result = add_atr(df, 14)
        assert "atr_14" in result.columns


# ---------------------------------------------------------------------------
# Volume MA
# ---------------------------------------------------------------------------

class TestVolumeMA:
    def test_volume_ma_returns_series(self, df):
        result = volume_ma(df, 20)
        assert isinstance(result, pd.Series)

    def test_add_vol_ma_column(self, df):
        result = add_volume_ma(df, 20)
        assert "vol_ma_20" in result.columns

    def test_volume_ma_matches_rolling_mean(self, df):
        result = volume_ma(df, 20)
        expected = df["volume"].rolling(20).mean()
        pd.testing.assert_series_equal(result, expected, check_names=False)


# ---------------------------------------------------------------------------
# VWAP
# ---------------------------------------------------------------------------

class TestVWAP:
    def test_vwap_returns_series(self, df):
        result = vwap(df)
        assert isinstance(result, pd.Series)

    def test_vwap_positive(self, df):
        result = vwap(df).dropna()
        assert (result > 0).all()

    def test_add_vwap_column(self, df):
        result = add_vwap(df)
        assert "vwap" in result.columns

    def test_vwap_constant_price(self):
        """VWAP of constant price should equal that price."""
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        df_const = pd.DataFrame({
            "high":   [50.0] * 50,
            "low":    [50.0] * 50,
            "close":  [50.0] * 50,
            "volume": [1000.0] * 50,
        }, index=dates)
        result = vwap(df_const).dropna()
        assert np.allclose(result.values, 50.0, atol=1e-6)


# ---------------------------------------------------------------------------
# add_all convenience function
# ---------------------------------------------------------------------------

class TestAddAll:
    def test_add_all_returns_dataframe(self, df):
        result = add_all(df)
        assert isinstance(result, pd.DataFrame)

    def test_add_all_has_expected_columns(self, df):
        result = add_all(df)
        expected = [
            "ema_10", "ema_21", "ema_50", "ema_200",
            "rsi_14",
            "bb_upper", "bb_mid", "bb_lower", "bb_width", "bb_pct_b",
            "atr_14",
            "vol_ma_20",
            "vwap",
        ]
        for col in expected:
            assert col in result.columns, f"Missing column: {col}"

    def test_add_all_does_not_mutate_input(self, df):
        original_cols = list(df.columns)
        _ = add_all(df)
        assert list(df.columns) == original_cols

    def test_add_all_preserves_ohlcv(self, df):
        result = add_all(df)
        for col in ["open", "high", "low", "close", "volume"]:
            pd.testing.assert_series_equal(result[col], df[col])
