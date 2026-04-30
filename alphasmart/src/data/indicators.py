"""
Technical indicators for AlphaSMART.
Pure functions — take a DataFrame, return a DataFrame with indicator columns appended.
No side effects. All calculations verified against standard formulas.
"""
from __future__ import annotations

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

def ema(df: pd.DataFrame, period: int, col: str = "close") -> pd.Series:
    """Exponential Moving Average."""
    return df[col].ewm(span=period, adjust=False).mean()


def add_emas(df: pd.DataFrame, periods: list[int] = (10, 21, 50, 200)) -> pd.DataFrame:
    """Add EMA columns for each period: ema_10, ema_21, ema_50, ema_200."""
    df = df.copy()
    for p in periods:
        df[f"ema_{p}"] = ema(df, p)
    return df


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(df: pd.DataFrame, period: int = 14, col: str = "close") -> pd.Series:
    """
    Relative Strength Index (Wilder's smoothing method).
    Returns values between 0–100.
    """
    delta = df[col].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    # When avg_loss is 0 and avg_gain > 0: RSI = 100 (perfectly rising series)
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi_series = 100 - (100 / (1 + rs))
    # Fill spots where avg_loss was 0: 100 if gaining, 50 if flat
    rsi_series = rsi_series.where(avg_loss != 0, other=avg_gain.apply(lambda g: 100.0 if g > 0 else 50.0))
    return rsi_series


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add rsi_{period} column."""
    df = df.copy()
    df[f"rsi_{period}"] = rsi(df, period)
    return df


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    col: str = "close",
) -> pd.DataFrame:
    """
    Bollinger Bands.
    Returns DataFrame with columns: bb_upper, bb_mid, bb_lower, bb_width, bb_pct_b
    """
    mid = df[col].rolling(period).mean()
    std = df[col].rolling(period).std(ddof=0)

    upper = mid + std_dev * std
    lower = mid - std_dev * std
    width = (upper - lower) / mid.replace(0, float("nan"))
    pct_b = (df[col] - lower) / (upper - lower).replace(0, float("nan"))

    return pd.DataFrame({
        "bb_upper": upper,
        "bb_mid": mid,
        "bb_lower": lower,
        "bb_width": width,
        "bb_pct_b": pct_b,
    }, index=df.index)


def add_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Add bb_upper, bb_mid, bb_lower, bb_width, bb_pct_b columns."""
    df = df.copy()
    bb = bollinger_bands(df, period=period, std_dev=std_dev)
    return pd.concat([df, bb], axis=1)


# ---------------------------------------------------------------------------
# ATR — Average True Range
# ---------------------------------------------------------------------------

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (Wilder's smoothing).
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(alpha=1 / period, adjust=False).mean()


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add atr_{period} column."""
    df = df.copy()
    df[f"atr_{period}"] = atr(df, period)
    return df


# ---------------------------------------------------------------------------
# MACD — Moving Average Convergence/Divergence
# ---------------------------------------------------------------------------

def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    col: str = "close",
) -> pd.DataFrame:
    """
    MACD indicator.
    Returns DataFrame with columns: macd, macd_signal, macd_hist
      macd       = EMA(fast) - EMA(slow)
      macd_signal = EMA(signal) of macd
      macd_hist  = macd - macd_signal
    """
    ema_fast = df[col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[col].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "macd_signal": signal_line, "macd_hist": histogram},
        index=df.index,
    )


def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Add macd, macd_signal, macd_hist columns."""
    df = df.copy()
    m = macd(df, fast=fast, slow=slow, signal=signal)
    return pd.concat([df, m], axis=1)


# ---------------------------------------------------------------------------
# Volume MA
# ---------------------------------------------------------------------------

def volume_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Simple moving average of volume."""
    return df["volume"].rolling(period).mean()


def add_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Add vol_ma_{period} column."""
    df = df.copy()
    df[f"vol_ma_{period}"] = volume_ma(df, period)
    return df


# ---------------------------------------------------------------------------
# VWAP — Volume-Weighted Average Price
# ---------------------------------------------------------------------------

def vwap(df: pd.DataFrame) -> pd.Series:
    """
    VWAP calculated cumulatively.
    Note: meaningful for intraday data. On daily data, this is a cumulative VWAP
    which can be used as a trend reference.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
    cumulative_vol = df["volume"].cumsum()
    return cumulative_tp_vol / cumulative_vol.replace(0, float("nan"))


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Add vwap column."""
    df = df.copy()
    df["vwap"] = vwap(df)
    return df


# ---------------------------------------------------------------------------
# CCI — Commodity Channel Index
# ---------------------------------------------------------------------------

def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Commodity Channel Index.
    CCI = (Typical Price - SMA(TP, n)) / (0.015 * MAD(TP, n))
    MAD = mean absolute deviation (more outlier-robust than std dev).
    Typical range: ±100 is neutral. >+100 = strong uptrend. <-100 = strong downtrend.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma_tp) / (0.015 * mad.replace(0, float("nan")))


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------

def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Williams %R.
    %R = -100 * (Highest High(n) - Close) / (Highest High(n) - Lowest Low(n))
    Range: 0 to -100. Oversold: < -80. Overbought: > -20.
    """
    highest_high = df["high"].rolling(period).max()
    lowest_low = df["low"].rolling(period).min()
    denom = (highest_high - lowest_low).replace(0, float("nan"))
    return -100.0 * (highest_high - df["close"]) / denom


# ---------------------------------------------------------------------------
# Stochastic RSI
# ---------------------------------------------------------------------------

def stoch_rsi(
    df: pd.DataFrame,
    rsi_period: int = 14,
    stoch_period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> pd.DataFrame:
    """
    Stochastic RSI.
    Applies the Stochastic formula to RSI values instead of price.
    Returns DataFrame with columns: stochrsi_k, stochrsi_d (both 0–100).
    More sensitive than plain RSI; useful for detecting momentum exhaustion.
    """
    rsi_vals = rsi(df, period=rsi_period)
    rsi_min = rsi_vals.rolling(stoch_period).min()
    rsi_max = rsi_vals.rolling(stoch_period).max()
    denom = (rsi_max - rsi_min).replace(0, float("nan"))
    raw_k = 100.0 * (rsi_vals - rsi_min) / denom
    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return pd.DataFrame({"stochrsi_k": k, "stochrsi_d": d}, index=df.index)


# ---------------------------------------------------------------------------
# Keltner Channel
# ---------------------------------------------------------------------------

def keltner_channel(
    df: pd.DataFrame,
    period: int = 20,
    atr_period: int = 14,
    atr_mult: float = 1.5,
) -> pd.DataFrame:
    """
    Keltner Channel.
    Mid = EMA(close, period). Bands = Mid ± atr_mult * ATR(atr_period).
    Returns DataFrame with columns: kc_upper, kc_mid, kc_lower.
    """
    mid = df["close"].ewm(span=period, adjust=False).mean()
    atr_vals = atr(df, period=atr_period)
    return pd.DataFrame({
        "kc_upper": mid + atr_mult * atr_vals,
        "kc_mid":   mid,
        "kc_lower": mid - atr_mult * atr_vals,
    }, index=df.index)


# ---------------------------------------------------------------------------
# Convenience: add all indicators at once
# ---------------------------------------------------------------------------

def add_all(
    df: pd.DataFrame,
    ema_periods: list[int] = (10, 21, 50, 200),
    rsi_period: int = 14,
    bb_period: int = 20,
    atr_period: int = 14,
    vol_ma_period: int = 20,
) -> pd.DataFrame:
    """Add full indicator set to DataFrame."""
    df = add_emas(df, periods=ema_periods)
    df = add_rsi(df, period=rsi_period)
    df = add_bollinger_bands(df, period=bb_period)
    df = add_atr(df, period=atr_period)
    df = add_volume_ma(df, period=vol_ma_period)
    df = add_vwap(df)
    df = add_macd(df)
    return df
