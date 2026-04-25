"""
Shared pytest fixtures for AlphaSMART tests.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


def make_ohlcv(n: int = 100, start_price: float = 100.0) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")

    # Random walk close prices
    returns = np.random.normal(0.001, 0.02, n)
    closes = start_price * np.exp(np.cumsum(returns))

    # Generate OHLCV from closes
    noise = np.abs(np.random.normal(0, 0.01, n))
    highs = closes * (1 + noise)
    lows = closes * (1 - noise)
    opens = closes * (1 + np.random.normal(0, 0.005, n))
    volumes = np.random.randint(100_000, 1_000_000, n).astype(float)

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=dates)


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    return make_ohlcv(200)


@pytest.fixture
def small_ohlcv() -> pd.DataFrame:
    return make_ohlcv(30)
