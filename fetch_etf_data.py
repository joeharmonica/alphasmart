"""
Fetch 10 years of daily OHLCV data for leveraged ETF study.
Symbols: QQQ, QLD, TQQQ, SPY, UPRO

Modes:
  python fetch_etf_data.py            -- fetch from Yahoo Finance (requires network)
  python fetch_etf_data.py --check    -- show current DB status only
  python fetch_etf_data.py --csv DIR  -- import CSV files from a directory
                                         (expects files named QQQ.csv, SPY.csv, etc.)

CSV format expected (yfinance / most brokers export):
  Date,Open,High,Low,Close,Volume
  2016-01-04,108.76,109.26,107.84,108.27,34000000
  ...
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from src.data.fetcher import StockDataFetcher
from src.data.database import Database
import pandas as pd

SYMBOLS = ["QQQ", "QLD", "TQQQ", "SPY", "UPRO"]
PERIOD = "10y"
INTERVAL = "1d"
DB_PATH = "sqlite:///alphasmart_dev.db"


def print_status(db: Database) -> None:
    status = db.fetch_status()
    etf_status = [s for s in status if s["symbol"] in SYMBOLS]

    if not etf_status:
        print("No ETF data in database yet.")
        return

    print(f"\n{'Symbol':<8} {'Bars':>6} {'Last Fetched':<22} {'Timeframe'}")
    print("-" * 55)
    for s in sorted(etf_status, key=lambda x: x["symbol"]):
        fetched = s["last_fetched_at"].strftime("%Y-%m-%d %H:%M") if s["last_fetched_at"] else "N/A"
        print(f"{s['symbol']:<8} {s['record_count']:>6}  {fetched:<22} {s['timeframe']}")

    missing = [sym for sym in SYMBOLS if sym not in {s["symbol"] for s in etf_status}]
    if missing:
        print(f"\nMissing data for: {', '.join(missing)}")


def fetch_from_web(db: Database) -> None:
    fetcher = StockDataFetcher()
    print(f"\nFetching {PERIOD} daily data for: {', '.join(SYMBOLS)}\n")
    print(f"{'Symbol':<8} {'Bars':>6} {'Start':<12} {'End':<12} {'Status'}")
    print("-" * 55)

    for symbol in SYMBOLS:
        try:
            df = fetcher.get_ohlcv(symbol, period=PERIOD, interval=INTERVAL)
            if df.empty:
                print(f"{symbol:<8} {'0':>6}  {'N/A':<12} {'N/A':<12} EMPTY")
                continue

            inserted = db.upsert_ohlcv(df, symbol=symbol, timeframe=INTERVAL, source="yfinance")
            total = db.count_bars(symbol, INTERVAL)
            start = df.index[0].strftime("%Y-%m-%d")
            end = df.index[-1].strftime("%Y-%m-%d")
            print(f"{symbol:<8} {total:>6}  {start:<12} {end:<12} OK (+{inserted} new)")

        except Exception as exc:
            print(f"{symbol:<8} {'ERR':>6}  {'':<12} {'':<12} FAILED: {exc}")


def import_from_csv(db: Database, csv_dir: str) -> None:
    """
    Import CSV files from a directory.
    Expects files like: QQQ.csv, SPY.csv, etc.
    Supported column names (case-insensitive): Date/date, Open, High, Low, Close, Volume
    """
    print(f"\nImporting CSV files from: {csv_dir}\n")
    print(f"{'Symbol':<8} {'Bars':>6} {'Start':<12} {'End':<12} {'Status'}")
    print("-" * 55)

    for symbol in SYMBOLS:
        csv_path = os.path.join(csv_dir, f"{symbol}.csv")
        if not os.path.exists(csv_path):
            print(f"{symbol:<8} {'N/A':>6}  {'N/A':<12} {'N/A':<12} SKIP (no {symbol}.csv found)")
            continue

        try:
            df = pd.read_csv(csv_path, parse_dates=True)
            df.columns = [c.lower() for c in df.columns]

            # Find and set date column as index
            date_col = next((c for c in df.columns if c in ("date", "datetime", "timestamp")), None)
            if date_col is None:
                print(f"{symbol:<8} {'ERR':>6}  {'':<12} {'':<12} FAILED: no date column found")
                continue

            df[date_col] = pd.to_datetime(df[date_col])
            df = df.set_index(date_col).sort_index()
            df.index.name = "timestamp"

            required = ["open", "high", "low", "close", "volume"]
            missing = [c for c in required if c not in df.columns]
            if missing:
                print(f"{symbol:<8} {'ERR':>6}  {'':<12} {'':<12} FAILED: missing columns {missing}")
                continue

            df = df[required].dropna()
            # Filter to last 10 years
            cutoff = pd.Timestamp.now() - pd.DateOffset(years=10)
            df = df[df.index >= cutoff]

            if df.empty:
                print(f"{symbol:<8} {'0':>6}  {'N/A':<12} {'N/A':<12} EMPTY after filtering")
                continue

            inserted = db.upsert_ohlcv(df, symbol=symbol, timeframe=INTERVAL, source="csv_import")
            total = db.count_bars(symbol, INTERVAL)
            start = df.index[0].strftime("%Y-%m-%d")
            end = df.index[-1].strftime("%Y-%m-%d")
            print(f"{symbol:<8} {total:>6}  {start:<12} {end:<12} OK (+{inserted} imported)")

        except Exception as exc:
            print(f"{symbol:<8} {'ERR':>6}  {'':<12} {'':<12} FAILED: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ETF data fetcher for AlphaSMART")
    parser.add_argument("--check", action="store_true", help="Show current DB status only")
    parser.add_argument("--csv", metavar="DIR", help="Import CSV files from this directory")
    args = parser.parse_args()

    db = Database(DB_PATH)

    if args.check:
        print_status(db)
        return

    if args.csv:
        import_from_csv(db, args.csv)
    else:
        fetch_from_web(db)

    print("\n--- Database Status ---")
    print_status(db)
    print(f"\nDatabase: alphasmart_dev.db")


if __name__ == "__main__":
    main()
