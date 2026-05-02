"""
Build synthetic pair-spread OHLCV series and store as new symbols in the DB.

Why: per lessons.md #33, every single-asset backtest cleared OFR but failed
block bootstrap because the edge fits the asset's macro arc. Pair spreads
(ratio of two correlated assets) are a structurally different mechanic —
the edge is sector-relative mispricing, not absolute price trend, so it's
not tied to any single macro arc.

Spread construction (ratio):
    close_ratio  = close_A  / close_B
    open_ratio   = open_A   / open_B
    high_ratio   = high_A   / low_B    # max ratio over the bar
    low_ratio    = low_A    / high_B   # min ratio over the bar
    volume       = volume_A + volume_B

Storage: each pair is registered as a new "symbol" in the existing
`ohlcv_records` table with timeframe "1d". Downstream tooling (optimizer,
backtester, dashboard) sees it identically to any other 1d asset.

Usage:
  python build_pairs_synthetic.py
  python build_pairs_synthetic.py --pairs V-MA NVDA-AVGO MSFT-GOOG
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.data.database import Database

DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
TIMEFRAME = "1d"

# Pairs we'll synthesise. Each pair is "A-B" — A is the numerator. Tickers
# chosen by sector cohabitation so the cointegration assumption (similar
# macro exposure) is at least plausible.
DEFAULT_PAIRS = [
    "V-MA",         # Payments — Visa vs Mastercard
    "NVDA-AVGO",    # Semis — NVIDIA vs Broadcom
    "MSFT-GOOG",    # Mega-cap cloud — Microsoft vs Alphabet
    "AAPL-MSFT",    # Mega-cap tech
    "ASML-AVGO",    # Semi-equipment vs semi-product
]


def build_spread(db: Database, pair: str, timeframe: str) -> pd.DataFrame | None:
    if "-" not in pair:
        print(f"  ✗ Invalid pair format (need A-B): {pair}")
        return None

    a, b = pair.split("-", 1)
    da = db.query_ohlcv(a, timeframe=timeframe)
    dbf = db.query_ohlcv(b, timeframe=timeframe)
    if da.empty:
        print(f"  ✗ No {timeframe} data for {a}")
        return None
    if dbf.empty:
        print(f"  ✗ No {timeframe} data for {b}")
        return None

    # Inner-join on timestamps so spread is only defined when both legs exist.
    merged = da.join(dbf, lsuffix="_a", rsuffix="_b", how="inner")
    if merged.empty:
        print(f"  ✗ {a} and {b} have no overlapping bars")
        return None

    # Guard against zero/negative B prices (shouldn't happen for equities).
    bad = (merged["close_b"] <= 0) | (merged["low_b"] <= 0) | (merged["high_b"] <= 0)
    if bad.any():
        merged = merged[~bad]

    spread = pd.DataFrame(index=merged.index)
    spread["open"]   = merged["open_a"]  / merged["open_b"]
    spread["high"]   = merged["high_a"]  / merged["low_b"]    # tightest upper bound
    spread["low"]    = merged["low_a"]   / merged["high_b"]   # tightest lower bound
    spread["close"]  = merged["close_a"] / merged["close_b"]
    spread["volume"] = merged["volume_a"] + merged["volume_b"]

    # Sanity: high >= max(open, close) and low <= min(open, close)
    spread["high"] = spread[["high", "open", "close"]].max(axis=1)
    spread["low"]  = spread[["low",  "open", "close"]].min(axis=1)

    return spread


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS,
                    help="Pair symbols of form A-B (default: 5 pre-selected pairs)")
    ap.add_argument("--timeframe", default=TIMEFRAME, help="Bar interval (default 1d)")
    args = ap.parse_args(argv[1:])

    db = Database(DB_URL)

    for pair in args.pairs:
        print(f"Building spread for {pair} on {args.timeframe}...")
        spread = build_spread(db, pair, args.timeframe)
        if spread is None or spread.empty:
            continue
        n = db.upsert_ohlcv(spread, symbol=pair, timeframe=args.timeframe,
                            source="synthetic_pair")
        print(f"  ✓ {pair}: {len(spread)} bars built, {n} new bars saved.")
        print(f"    range: {spread.index[0].date()} → {spread.index[-1].date()}")
        print(f"    close stats: min={spread['close'].min():.4f}  "
              f"med={spread['close'].median():.4f}  max={spread['close'].max():.4f}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
