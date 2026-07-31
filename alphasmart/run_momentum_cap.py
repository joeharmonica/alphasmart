"""
Backtest a "momentum cap" filter against the live paper-trade universe
(equity_xsec_momentum_B, 21 symbols): exclude any name whose trailing
126d momentum exceeds a cap threshold from top-K selection, on the
hypothesis that extreme trailing momentum (e.g. MU +265%, pre-crash CRWD)
is more likely to be overextended / due for mean reversion than a name
that continues compounding.

Mirrors build_equity_spec() in src/execution/runner_main.py exactly
(126d lookback, top-5, binary SPY 200d-MA filter), and the matched-window
methodology from lessons.md #59: all variants clipped to CRWD's 2019-06-12
IPO date so cap thresholds aren't compared across different-length windows.

Usage:
    python run_momentum_cap.py                       # default cap grid
    python run_momentum_cap.py --caps 100 150 200     # custom caps (%)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.data.database import Database
from run_regime_filter_v2 import binary_signal, metrics

UNIVERSE = sorted([
    "AAPL", "AMD", "AMZN", "ANET", "ASML", "AVGO", "CRWD", "GOOG", "LLY",
    "MA", "META", "MSFT", "MU", "NOW", "NVDA", "NVO", "PANW", "QQQ",
    "SPY", "TSLA", "V",
])
DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
LOOKBACK, SKIP, TOP_K, REBAL = 126, 0, 5, 21
MATCH_START = "2019-06-12"  # CRWD IPO — the binding constraint (lesson #59)


def load_closes(db: Database, symbols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame({s: db.query_ohlcv(s, "1d")["close"] for s in symbols})
    return df.dropna()


def run_with_cap(
    closes: pd.DataFrame,
    lookback_days: int,
    skip_days: int,
    top_k: int,
    rebal_days: int,
    cap_pct: float | None,
) -> tuple[pd.Series, pd.DataFrame, dict]:
    """
    Same rebalance-every-N-days xsec momentum as run_xsec_momentum, but at
    each rebalance point any symbol with trailing momentum > cap_pct is
    excluded from selection entirely (not just deprioritized). If fewer
    than top_k names survive the cap, the portfolio holds only the
    survivors (equal-weighted among them) rather than backfilling with
    over-cap names — the point of the cap is to refuse exposure to
    "overextended" names outright.

    cap_pct=None reproduces the uncapped baseline exactly.
    """
    n_bars = len(closes)
    rets = closes.pct_change()
    portfolio = pd.Series(0.0, index=closes.index)
    holdings = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    held: list[str] = []
    excluded_log: dict[str, int] = {s: 0 for s in closes.columns}
    rebalances = 0

    start = lookback_days + skip_days
    for i in range(start, n_bars):
        if (i - start) % rebal_days == 0 or not held:
            past = closes.iloc[i - skip_days - lookback_days : i - skip_days]
            anchor = past.iloc[0]
            tip = closes.iloc[i - skip_days] if skip_days > 0 else closes.iloc[i]
            valid = anchor.notna() & tip.notna() & (anchor > 0)
            if int(valid.sum()) >= 1:
                trailing = (tip[valid] / anchor[valid]) - 1.0
                if cap_pct is not None:
                    over_cap = trailing[trailing * 100 > cap_pct].index
                    for s in over_cap:
                        excluded_log[s] += 1
                    trailing = trailing[trailing * 100 <= cap_pct]
                if len(trailing) > 0:
                    held = trailing.nlargest(top_k).index.tolist()
                    rebalances += 1
                # else: keep prior `held` (nothing qualifies this period)
        if held:
            day_rets = rets.iloc[i][held].dropna()
            if len(day_rets) > 0:
                portfolio.iloc[i] = float(day_rets.mean())
            w = 1.0 / len(held)
            for sym in held:
                holdings.iloc[i, holdings.columns.get_loc(sym)] = w

    return portfolio, holdings, {"rebalances": rebalances, "excluded_counts": excluded_log}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--caps", nargs="*", type=float, default=[75, 100, 150, 200, 250],
                         help="Momentum cap thresholds to test, in percent (default: 75 100 150 200 250)")
    args = parser.parse_args()

    db = Database(DB_URL)
    closes_full = load_closes(db, UNIVERSE)
    closes = closes_full[closes_full.index >= MATCH_START]
    spy = db.query_ohlcv("SPY", "1d")["close"]
    filt = binary_signal(spy).reindex(closes.index).ffill().fillna(0)

    print(f"Matched window: {closes.index[0].date()} -> {closes.index[-1].date()} "
          f"({len(closes)} bars, clipped to CRWD IPO per lesson #59)\n")

    variants = {"uncapped_baseline": None}
    for c in args.caps:
        variants[f"cap_{int(c)}pct"] = c

    results = {}
    print(f"{'Variant':<20} {'Sharpe':>8} {'CAGR':>8} {'MaxDD':>8} {'InMkt%':>8} {'Rebals':>7}")
    print("-" * 68)
    for name, cap in variants.items():
        mom, holdings, meta = run_with_cap(closes, LOOKBACK, SKIP, TOP_K, REBAL, cap)
        filtered = mom * filt
        m = metrics(filtered, 252)
        sel_freq = {
            s: {
                "days_in_top_k": int((holdings[s] > 0).sum()),
                "pct_of_days": float((holdings[s] > 0).sum() / len(holdings)),
                "days_excluded_by_cap": meta["excluded_counts"][s],
            }
            for s in closes.columns
        }
        results[name] = {
            "cap_pct": cap,
            "metrics": m,
            "rebalances": meta["rebalances"],
            "selection_frequency": sel_freq,
        }
        print(f"{name:<20} {m['sharpe']:>8.3f} {m['cagr']:>8.3f} "
              f"{m['max_drawdown']:>8.3f} {m['in_market_pct']*100:>7.1f}% {meta['rebalances']:>7}")

    # Delta table vs baseline
    base = results["uncapped_baseline"]["metrics"]
    print(f"\n{'Variant':<20} {'ΔSharpe':>9} {'ΔCAGR':>9} {'ΔMaxDD':>9}")
    print("-" * 50)
    for name, r in results.items():
        m = r["metrics"]
        print(f"{name:<20} {m['sharpe']-base['sharpe']:>+9.3f} "
              f"{m['cagr']-base['cagr']:>+9.3f} {m['max_drawdown']-base['max_drawdown']:>+9.3f}")

    # Focus: MU and CRWD selection frequency + exclusion counts across caps
    print(f"\n{'='*68}\nMU / CRWD selection frequency by variant (the two names implicated\nin the live 6/29 rotation drag):")
    print(f"{'Variant':<20} {'MU days':>10} {'MU excl':>10} {'CRWD days':>10} {'CRWD excl':>10}")
    for name, r in results.items():
        mu = r["selection_frequency"]["MU"]
        crwd = r["selection_frequency"]["CRWD"]
        print(f"{name:<20} {mu['days_in_top_k']:>10} {mu['days_excluded_by_cap']:>10} "
              f"{crwd['days_in_top_k']:>10} {crwd['days_excluded_by_cap']:>10}")

    # Would the cap have excluded MU/CRWD/PANW/ANET specifically on the live
    # rotation date (2026-06-29)?
    if "2026-06-29" in [d.strftime("%Y-%m-%d") for d in closes.index]:
        idx = closes.index.get_loc(pd.Timestamp("2026-06-29"))
        anchor = closes.iloc[idx - LOOKBACK]
        tip = closes.iloc[idx]
        trailing_629 = ((tip / anchor) - 1) * 100
        print(f"\n{'='*68}\nActual trailing 126d momentum on 2026-06-29 (the live v3 rotation date):")
        for s in trailing_629.sort_values(ascending=False).index[:8]:
            print(f"  {s:6} {trailing_629[s]:+8.1f}%")

    out = _ROOT.parent / "reports" / (
        f"momentum_cap_backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": "equity_xsec_momentum_B (momentum-cap variant study)",
        "params": {"lookback_days": LOOKBACK, "skip_days": SKIP, "top_k": TOP_K,
                    "rebal_days": REBAL, "match_start": MATCH_START,
                    "filter": "binary_200ma_filter on SPY"},
        "universe": UNIVERSE,
        "variants": results,
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
