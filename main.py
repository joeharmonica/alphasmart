"""
AlphaSMART CLI — Phase 2 entrypoint.

Commands:
  fetch       Fetch and store OHLCV data for a symbol
  indicators  Compute and display indicators for a stored symbol
  db-status   Show what data is currently stored
  backtest    Run a strategy backtest on stored data

Usage:
  python main.py fetch AAPL --period 1y --timeframe 1d
  python main.py fetch BTC/USDT --timeframe 1d --limit 365
  python main.py indicators AAPL
  python main.py db-status
  python main.py backtest AAPL --strategy ema
  python main.py backtest AAPL --strategy rsi --capital 50000
  python main.py backtest AAPL --strategy donchian
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
from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.runner import BatchRunner, DEFAULT_STOCKS, DEFAULT_CRYPTOS
from src.strategy.risk_manager import RiskConfig
from src.strategy.trend import EMACrossoverStrategy
from src.strategy.mean_reversion import RSIMeanReversionStrategy
from src.strategy.breakout import DonchianBreakoutStrategy
from src.strategy.macd_momentum import MACDMomentumStrategy
from src.strategy.bollinger_reversion import BollingerReversionStrategy
from src.reporting.report import generate_report


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


def cmd_backtest(args: argparse.Namespace) -> None:
    db = Database(DB_URL)
    symbol = args.symbol
    timeframe = getattr(args, "timeframe", "1d")

    df = db.query_ohlcv(symbol, timeframe=timeframe)
    if df.empty:
        print(f"No data for {symbol}. Run: python main.py fetch {symbol}")
        sys.exit(1)

    strategy_map = {
        "ema":          lambda: EMACrossoverStrategy(symbol),
        "rsi":          lambda: RSIMeanReversionStrategy(symbol),
        "donchian":     lambda: DonchianBreakoutStrategy(symbol),
        "macd":         lambda: MACDMomentumStrategy(symbol),
        "bb_reversion": lambda: BollingerReversionStrategy(symbol),
    }
    strategy_key = args.strategy.lower()
    if strategy_key not in strategy_map:
        print(f"Unknown strategy '{args.strategy}'. Choose from: {', '.join(strategy_map)}")
        sys.exit(1)

    strategy = strategy_map[strategy_key]()
    config = BacktestConfig(
        initial_capital=args.capital,
        risk_config=RiskConfig(max_position_pct=1.0),
    )

    print(f"\nRunning backtest: {strategy.name} on {symbol} [{timeframe}] "
          f"({len(df)} bars, capital={args.capital:,.0f})")

    engine = BacktestEngine()
    result = engine.run(strategy, df, config)
    result.print_summary(strategy_name=f"{strategy.name} / {symbol}")


def cmd_backtest_all(args: argparse.Namespace) -> None:
    """Run all 5 strategies across all symbols and timeframes, then print ranked report."""
    symbols = args.symbols if args.symbols else (DEFAULT_STOCKS + DEFAULT_CRYPTOS)
    stocks  = [s for s in symbols if "/" not in s]
    cryptos = [s for s in symbols if "/" in s]

    strategy_factories = {
        "ema_crossover":  lambda sym: EMACrossoverStrategy(sym),
        "rsi_reversion":  lambda sym: RSIMeanReversionStrategy(sym),
        "donchian_bo":    lambda sym: DonchianBreakoutStrategy(sym),
        "macd_momentum":  lambda sym: MACDMomentumStrategy(sym),
        "bb_reversion":   lambda sym: BollingerReversionStrategy(sym),
    }

    runner = BatchRunner(
        db_url=DB_URL,
        initial_capital=args.capital,
        stocks=stocks,
        cryptos=cryptos,
    )

    print(f"\nStarting batch backtest: {len(strategy_factories)} strategies × {len(symbols)} symbols")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Capital: ${args.capital:,.0f}\n")

    results_df = runner.run_all(strategy_factories, fetch_if_missing=True)

    if results_df.empty:
        print("No results produced — check data availability and logs.")
        sys.exit(1)

    generate_report(results_df, output_csv=args.output, initial_capital=args.capital)


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

    # backtest
    p_bt = sub.add_parser("backtest", help="Run a strategy backtest")
    p_bt.add_argument("symbol", help="Symbol to backtest (must be fetched first)")
    p_bt.add_argument("--strategy", default="ema",
                      choices=["ema", "rsi", "donchian", "macd", "bb_reversion"],
                      help="Strategy to run (default: ema)")
    p_bt.add_argument("--capital", type=float, default=100_000,
                      help="Initial capital (default: 100000)")
    p_bt.add_argument("--timeframe", default="1d", help="Timeframe (default: 1d)")

    # backtest-all
    p_bta = sub.add_parser("backtest-all", help="Run all 5 strategies across all symbols")
    p_bta.add_argument("--symbols", nargs="+", default=None,
                       metavar="SYMBOL",
                       help="Symbols to test (default: AAPL MSFT SPY BTC/USDT ETH/USDT)")
    p_bta.add_argument("--capital", type=float, default=100_000,
                       help="Initial capital per run (default: 100000)")
    p_bta.add_argument("--output", default=None, metavar="FILE",
                       help="CSV output path (default: reports/backtest_report_TIMESTAMP.csv)")

    args = parser.parse_args()

    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "indicators":
        cmd_indicators(args)
    elif args.command == "db-status":
        cmd_db_status(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "backtest-all":
        cmd_backtest_all(args)


if __name__ == "__main__":
    main()
