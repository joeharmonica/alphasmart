"""
Backtest candidate tickers against the live paper-trade strategy
(equity_xsec_momentum_B): xsec 126d momentum, top-5, monthly rebal,
binary SPY 200d-MA regime filter. Mirrors build_equity_spec() in
src/execution/runner_main.py:75-83 exactly.

Default behavior (no args): tests TQQQ + UPRO individually and combined.

Custom usage:
    python run_xsec_leveraged_etfs.py SOXL TECL          # test each + combined
    python run_xsec_leveraged_etfs.py --combo NVDL TQQQ  # only test combined add

For each candidate universe it reports:
  - Sharpe / CAGR / MaxDD vs the baseline universe
  - How often each new ticker would have been picked into the top-K
  - Whether the new ticker bumps an existing name out of the top-5 most-held

Pre-req: each new ticker must have ≥ (lookback + warmup) bars of 1d data
already in the DB. Fetch first:
    python main.py fetch <SYMBOL> --period 10y --timeframe 1d
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.data.database import Database
from run_xsec_pipeline import run_xsec_momentum, synchronised_block_bootstrap
from run_regime_filter_v2 import binary_signal, metrics


BASELINE_UNIVERSE = sorted([
    "AAPL", "AMD", "AMZN", "ASML", "AVGO", "GOOG", "LLY", "MA", "META",
    "MSFT", "NOW", "NVDA", "NVO", "QQQ", "SPY", "TSLA", "V",
])
DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
LOOKBACK, SKIP, TOP_K, REBAL = 126, 0, 5, 21


def load_closes(db: Database, symbols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame({s: db.query_ohlcv(s, "1d")["close"] for s in symbols})
    return df.dropna()


def run_xsec_with_holdings(
    closes: pd.DataFrame,
    lookback_days: int,
    skip_days: int,
    top_k: int,
    rebal_days: int,
) -> tuple[pd.Series, pd.DataFrame]:
    """Same as run_xsec_momentum but also returns a holdings frame (date × sym)."""
    n_bars = len(closes)
    rets = closes.pct_change()
    portfolio = pd.Series(0.0, index=closes.index)
    holdings = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    held: list[str] = []

    start = lookback_days + skip_days
    for i in range(start, n_bars):
        if (i - start) % rebal_days == 0 or not held:
            past = closes.iloc[i - skip_days - lookback_days : i - skip_days]
            anchor = past.iloc[0]
            tip = closes.iloc[i - skip_days] if skip_days > 0 else closes.iloc[i]
            valid = anchor.notna() & tip.notna() & (anchor > 0)
            if int(valid.sum()) >= top_k:
                trailing = (tip[valid] / anchor[valid]) - 1.0
                held = trailing.nlargest(top_k).index.tolist()
        if held:
            day_rets = rets.iloc[i][held].dropna()
            if len(day_rets) > 0:
                portfolio.iloc[i] = float(day_rets.mean())
            for sym in held:
                if sym in holdings.columns:
                    holdings.iloc[i, holdings.columns.get_loc(sym)] = 1.0 / top_k
    return portfolio, holdings


def run_one_universe(db: Database, name: str, symbols: list[str]) -> dict:
    closes = load_closes(db, symbols)
    spy = db.query_ohlcv("SPY", "1d")["close"]

    mom, holdings = run_xsec_with_holdings(closes, LOOKBACK, SKIP, TOP_K, REBAL)
    filt = binary_signal(spy).reindex(closes.index).ffill().fillna(0)
    filtered = mom * filt

    base = metrics(mom, 252)
    filtered_m = metrics(filtered, 252)

    # Holdings stats per ticker
    sel_freq = {}
    for sym in closes.columns:
        days_held = float((holdings[sym] > 0).sum())
        sel_freq[sym] = {
            "days_in_top_k": int(days_held),
            "pct_of_days": float(days_held / len(holdings)) if len(holdings) else 0.0,
        }

    return {
        "name": name,
        "n_symbols": len(symbols),
        "symbols": symbols,
        "date_range": [str(closes.index[0].date()), str(closes.index[-1].date())],
        "n_bars": len(closes),
        "unfiltered": base,
        "filtered_B": filtered_m,
        "in_market_pct": filtered_m["in_market_pct"],
        "selection_frequency": sel_freq,
    }


def print_universe(r: dict) -> None:
    print(f"\n{'='*92}")
    print(f"  Universe: {r['name']}  ({r['n_symbols']} symbols, "
          f"{r['n_bars']} bars, {r['date_range'][0]} → {r['date_range'][1]})")
    print('='*92)
    print(f"  {'Variant':<22} {'Sharpe':>8} {'CAGR':>8} {'MaxDD':>8} {'InMkt%':>8}")
    print(f"  {'A_unfiltered':<22} {r['unfiltered']['sharpe']:>8.3f} "
          f"{r['unfiltered']['cagr']:>8.3f} {r['unfiltered']['max_drawdown']:>8.3f} "
          f"{r['unfiltered'].get('in_market_pct',1.0)*100:>7.1f}%")
    print(f"  {'B_binary_SPY200':<22} {r['filtered_B']['sharpe']:>8.3f} "
          f"{r['filtered_B']['cagr']:>8.3f} {r['filtered_B']['max_drawdown']:>8.3f} "
          f"{r['filtered_B']['in_market_pct']*100:>7.1f}%")

    # Show how often any non-baseline tickers get picked
    relevant = [s for s in r["symbols"] if s not in BASELINE_UNIVERSE]
    if relevant:
        print(f"\n  Selection frequency for new tickers:")
        for s in relevant:
            sf = r["selection_frequency"][s]
            print(f"    {s:6} held on {sf['days_in_top_k']:>5} of {r['n_bars']} bars "
                  f"({sf['pct_of_days']*100:.1f}% of days)")
    # Also show top-3 most-held in this universe
    top = sorted(r["selection_frequency"].items(),
                 key=lambda kv: -kv[1]["days_in_top_k"])[:5]
    print(f"\n  Most-held symbols (top 5):")
    for sym, sf in top:
        print(f"    {sym:6}  {sf['pct_of_days']*100:5.1f}%")


def build_universes(candidates: list[str], combined_only: bool) -> dict[str, list[str]]:
    """Always include baseline + the all-candidates-added universe.
    Per-candidate individual universes are added unless combined_only."""
    universes: dict[str, list[str]] = {"baseline": BASELINE_UNIVERSE}
    if not combined_only:
        for c in candidates:
            universes[f"+{c}"] = sorted(BASELINE_UNIVERSE + [c])
    if len(candidates) >= 2 or combined_only:
        label = "+" + "+".join(candidates)
        universes[label] = sorted(BASELINE_UNIVERSE + list(candidates))
    return universes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tickers", nargs="*", default=["TQQQ", "UPRO"],
                        help="Tickers to test against the paper-trade strategy "
                             "(default: TQQQ UPRO)")
    parser.add_argument("--combo", action="store_true",
                        help="Skip per-ticker universes; only test all candidates combined.")
    args = parser.parse_args()

    db = Database(DB_URL)
    universes = build_universes(args.tickers, combined_only=args.combo)

    results = {}
    for name, syms in universes.items():
        results[name] = run_one_universe(db, name, syms)
        print_universe(results[name])

    # Comparison table
    print(f"\n{'='*92}")
    print("  COMPARISON (binary SPY 200d-MA filtered — paper-trade variant)")
    print('='*92)
    print(f"  {'Universe':<14} {'Symbols':>8} {'Sharpe':>8} {'CAGR':>8} "
          f"{'MaxDD':>8} {'InMkt%':>8}  Δ vs baseline")
    base = results["baseline"]["filtered_B"]
    for name, r in results.items():
        m = r["filtered_B"]
        d = (f"ΔSh={m['sharpe']-base['sharpe']:+.3f}  "
             f"ΔCAGR={m['cagr']-base['cagr']:+.3f}  "
             f"ΔMaxDD={m['max_drawdown']-base['max_drawdown']:+.3f}")
        print(f"  {name:<14} {r['n_symbols']:>8} "
              f"{m['sharpe']:>8.3f} {m['cagr']:>8.3f} "
              f"{m['max_drawdown']:>8.3f} {m['in_market_pct']*100:>7.1f}%  {d}")

    # Persist
    tag = "_".join(args.tickers) if args.tickers else "default"
    out = _ROOT.parent / "reports" / (
        f"xsec_addticker_{tag}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": "equity_xsec_momentum_B (paper-trade variant)",
        "params": {"lookback_days": LOOKBACK, "skip_days": SKIP,
                   "top_k": TOP_K, "rebal_days": REBAL,
                   "filter": "binary_200ma_filter on SPY"},
        "universes": results,
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
