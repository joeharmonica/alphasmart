"""
AlphaSMART CLI — Phase 1 entrypoint.

Commands:
  fetch       Fetch and store OHLCV data for a symbol
  indicators  Compute and display indicators for a stored symbol
  db-status   Show what data is currently stored

Usage:
  python main.py fetch AAPL --period 1y --timeframe 1d
  python main.py fetch BTC/USDT --timeframe 1d --limit 365
  python main.py indicators AAPL
  python main.py db-status
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from src.data.database import Database
from src.data.fetcher import DataFetcher
from src.data.preprocessor import preprocess, PreprocessError
from src.data.indicators import add_all
from src.monitoring.logger import logger


DB_URL = "sqlite:///alphasmart_dev.db"


def cmd_fetch(args: argparse.Namespace) -> None:
    db = Database(DB_URL)
    fetcher = DataFetcher()

    symbol = args.symbol
    timeframe = args.timeframe

    logger.info(f"Fetching {symbol} [{timeframe}]...")
    raw = fetcher.get_ohlcv(
        symbol,
        timeframe=timeframe,
        period=args.period,
        limit=args.limit,
    )

    try:
        clean = preprocess(raw, symbol=symbol)
    except PreprocessError as exc:
        logger.error(f"Preprocess failed: {exc}")
        sys.exit(1)

    source = "binance" if fetcher.is_crypto(symbol) else "yfinance"
    inserted = db.upsert_ohlcv(clean, symbol=symbol, timeframe=timeframe, source=source)

    print(f"\n✓ {symbol} [{timeframe}]")
    print(f"  Bars fetched:  {len(clean)}")
    print(f"  New bars saved: {inserted}")
    print(f"  Date range:    {clean.index[0].date()} → {clean.index[-1].date()}")
    print(f"  Latest close:  {clean['close'].iloc[-1]:.4f}")


def cmd_indicators(args: argparse.Namespace) -> None:
    db = Database(DB_URL)
    symbol = args.symbol
    timeframe = args.timeframe

    df = db.query_ohlcv(symbol, timeframe=timeframe)
    if df.empty:
        print(f"No data for {symbol}. Run: python main.py fetch {symbol}")
        sys.exit(1)

    df = add_all(df)
    print(f"\n{symbol} [{timeframe}] — Latest bar with indicators:")
    print(f"  Date:       {df.index[-1].date()}")
    print(f"  Close:      {df['close'].iloc[-1]:.4f}")
    print(f"  EMA 10/21:  {df['ema_10'].iloc[-1]:.4f} / {df['ema_21'].iloc[-1]:.4f}")
    print(f"  EMA 50/200: {df['ema_50'].iloc[-1]:.4f} / {df['ema_200'].iloc[-1]:.4f}")
    print(f"  RSI 14:     {df['rsi_14'].iloc[-1]:.2f}")
    print(f"  BB upper:   {df['bb_upper'].iloc[-1]:.4f}")
    print(f"  BB lower:   {df['bb_lower'].iloc[-1]:.4f}")
    print(f"  ATR 14:     {df['atr_14'].iloc[-1]:.4f}")
    print(f"  Vol MA 20:  {df['vol_ma_20'].iloc[-1]:.0f}")


def cmd_db_status(_args: argparse.Namespace) -> None:
    db = Database(DB_URL)
    rows = db.fetch_status()

    if not rows:
        print("Database is empty. Run: python main.py fetch <SYMBOL>")
        return

    print(f"\n{'Symbol':<15} {'Timeframe':<10} {'Bars':<8} {'Last Fetched'}")
    print("-" * 55)
    for r in rows:
        print(f"{r['symbol']:<15} {r['timeframe']:<10} {r['record_count']:<8} {r['last_fetched_at']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="alphasmart",
        description="AlphaSMART — algorithmic trading platform CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch and store OHLCV data")
    p_fetch.add_argument("symbol", help="Symbol to fetch (e.g. AAPL, BTC/USDT)")
    p_fetch.add_argument("--period", default="1y", help="Period for stock data (default: 1y)")
    p_fetch.add_argument("--timeframe", default="1d", help="Bar interval (default: 1d)")
    p_fetch.add_argument("--limit", type=int, default=365, help="Bar limit for crypto (default: 365)")

    # indicators
    p_ind = sub.add_parser("indicators", help="Show indicators for a stored symbol")
    p_ind.add_argument("symbol", help="Symbol to analyse")
    p_ind.add_argument("--timeframe", default="1d", help="Timeframe (default: 1d)")

    # db-status
    sub.add_parser("db-status", help="Show stored data summary")

    args = parser.parse_args()

    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "indicators":
        cmd_indicators(args)
    elif args.command == "db-status":
        cmd_db_status(args)


if __name__ == "__main__":
    main()
