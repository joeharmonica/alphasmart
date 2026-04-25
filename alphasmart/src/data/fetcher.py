"""
Market data fetchers for AlphaSMART.
StockDataFetcher  — yfinance (free) or Polygon.io (prod)
CryptoDataFetcher — ccxt / Binance
DataFetcher       — unified interface
"""
from __future__ import annotations

import os
from typing import Optional

import ccxt
import pandas as pd
import yfinance as yf

from src.monitoring.logger import logger


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

class StockDataFetcher:
    """Fetch OHLCV data for equities via Yahoo Finance."""

    def get_ohlcv(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch OHLCV for a single stock symbol.

        Args:
            symbol:   Ticker symbol, e.g. "AAPL", "SPY"
            period:   yfinance period string — "1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max"
            interval: Bar interval — "1m","2m","5m","15m","30m","60m","90m","1h","1d","5d","1wk","1mo","3mo"

        Returns:
            pd.DataFrame with columns [open, high, low, close, volume]
            Index: pd.DatetimeIndex (UTC-normalised for daily, tz-aware for intraday)
        """
        logger.info(f"Fetching stock OHLCV: {symbol} period={period} interval={interval}")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval, auto_adjust=True)

            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

            df.columns = [c.lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index.name = "timestamp"

            logger.info(f"Fetched {len(df)} bars for {symbol}")
            return df

        except Exception as exc:
            logger.error(f"StockDataFetcher failed for {symbol}: {exc}")
            raise

    def get_multiple(
        self,
        symbols: list[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        return {s: self.get_ohlcv(s, period=period, interval=interval) for s in symbols}


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------

class CryptoDataFetcher:
    """Fetch OHLCV data for crypto via CCXT (100+ exchanges)."""

    TIMEFRAME_MAP = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
    }

    def __init__(self, exchange_id: str = "binance") -> None:
        exchange_class = getattr(ccxt, exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"Unknown exchange: {exchange_id}")

        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_SECRET")

        config: dict = {"enableRateLimit": True}
        if api_key and api_secret:
            config["apiKey"] = api_key
            config["secret"] = api_secret

        self.exchange = exchange_class(config)
        self.exchange_id = exchange_id
        logger.info(f"CryptoDataFetcher initialised: exchange={exchange_id}")

    def get_ohlcv(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1d",
        limit: int = 365,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV for a crypto pair.

        Args:
            symbol:    CCXT unified symbol, e.g. "BTC/USDT", "ETH/USDT"
            timeframe: Bar interval — "1m","5m","15m","30m","1h","4h","1d","1w"
            limit:     Number of bars to fetch (max varies by exchange)

        Returns:
            pd.DataFrame with columns [open, high, low, close, volume]
            Index: pd.DatetimeIndex (UTC)
        """
        logger.info(f"Fetching crypto OHLCV: {symbol} tf={timeframe} limit={limit} from {self.exchange_id}")
        try:
            raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            if not raw:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

            df = pd.DataFrame(
                raw,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp").sort_index()

            logger.info(f"Fetched {len(df)} bars for {symbol}")
            return df

        except ccxt.NetworkError as exc:
            logger.error(f"Network error fetching {symbol}: {exc}")
            raise
        except ccxt.ExchangeError as exc:
            logger.error(f"Exchange error fetching {symbol}: {exc}")
            raise
        except Exception as exc:
            logger.error(f"CryptoDataFetcher failed for {symbol}: {exc}")
            raise


# ---------------------------------------------------------------------------
# Unified interface
# ---------------------------------------------------------------------------

class DataFetcher:
    """
    Unified data fetcher.
    Automatically routes to StockDataFetcher or CryptoDataFetcher based on symbol format.
    Crypto symbols contain '/': "BTC/USDT". Stock symbols do not: "AAPL".
    """

    def __init__(self, crypto_exchange: str = "binance") -> None:
        self._stock = StockDataFetcher()
        self._crypto = CryptoDataFetcher(exchange_id=crypto_exchange)

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        period: str = "1y",
        limit: int = 365,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV for any symbol.
        Routes crypto (symbol contains '/') to CryptoDataFetcher, stocks to StockDataFetcher.
        """
        if "/" in symbol:
            return self._crypto.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return self._stock.get_ohlcv(symbol, period=period, interval=timeframe)

    def is_crypto(self, symbol: str) -> bool:
        return "/" in symbol
