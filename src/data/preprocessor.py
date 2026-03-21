"""
OHLCV data preprocessor.
Validates, cleans, and normalises raw market data before it enters the engine.
"""
from __future__ import annotations

import pandas as pd

from src.monitoring.logger import logger

REQUIRED_COLS = {"open", "high", "low", "close", "volume"}


class PreprocessError(Exception):
    """Raised when data cannot be cleaned to a usable state."""


def preprocess(df: pd.DataFrame, symbol: str = "", ffill_limit: int = 3) -> pd.DataFrame:
    """
    Clean and validate an OHLCV DataFrame.

    Steps:
    1. Validate required columns exist
    2. Normalise column names to lowercase
    3. Cast columns to float
    4. Remove duplicate timestamps (keep last)
    5. Sort by timestamp ascending
    6. Forward-fill small gaps (up to ffill_limit consecutive bars)
    7. Drop remaining NaN rows
    8. Validate OHLCV integrity (high >= low, all prices > 0)

    Args:
        df:          Raw OHLCV DataFrame with DatetimeIndex
        symbol:      Symbol name for log context
        ffill_limit: Max consecutive NaN bars to forward-fill before dropping

    Returns:
        Clean pd.DataFrame with columns [open, high, low, close, volume]

    Raises:
        PreprocessError: If the DataFrame is empty or has missing required columns.
    """
    label = symbol or "unknown"

    if df is None or df.empty:
        raise PreprocessError(f"[{label}] Empty DataFrame received")

    # Normalise columns
    df = df.copy()
    df.columns = [c.lower().strip() for c in df.columns]

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise PreprocessError(f"[{label}] Missing required columns: {missing}")

    df = df[list(REQUIRED_COLS)].copy()

    # Cast to float
    for col in REQUIRED_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Remove duplicate timestamps (keep last)
    before = len(df)
    df = df[~df.index.duplicated(keep="last")]
    dupes = before - len(df)
    if dupes:
        logger.warning(f"[{label}] Dropped {dupes} duplicate timestamps")

    # Sort ascending
    df = df.sort_index()

    # Forward-fill small gaps (skip if limit is 0 or negative)
    if ffill_limit > 0:
        df = df.ffill(limit=ffill_limit)

    # Drop remaining NaN rows
    before = len(df)
    df = df.dropna()
    dropped = before - len(df)
    if dropped:
        logger.warning(f"[{label}] Dropped {dropped} rows with NaN values")

    if df.empty:
        raise PreprocessError(f"[{label}] No data remaining after cleaning")

    # Validate OHLCV integrity
    bad_prices = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if bad_prices.any():
        count = bad_prices.sum()
        logger.warning(f"[{label}] Dropping {count} rows with non-positive prices")
        df = df[~bad_prices]

    bad_hl = df["high"] < df["low"]
    if bad_hl.any():
        count = bad_hl.sum()
        logger.warning(f"[{label}] Dropping {count} rows where high < low")
        df = df[~bad_hl]

    if df.empty:
        raise PreprocessError(f"[{label}] No data remaining after integrity checks")

    logger.debug(f"[{label}] Preprocessed: {len(df)} bars, "
                 f"{df.index[0]} → {df.index[-1]}")
    return df
