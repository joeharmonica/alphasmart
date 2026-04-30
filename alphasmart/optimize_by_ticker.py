"""
Per-ticker optimization sweep.

Optimizes each strategy on each available symbol/timeframe, saves best params,
then prints a summary table of the best strategy per ticker.

Usage:
    python optimize_by_ticker.py [--timeframe 1h|1d|all]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

# Redirect loguru to stderr before any imports trigger it
import src.monitoring.logger  # noqa: F401

from loguru import logger as _logger
_logger.remove()
_logger.add(sys.stderr, level="WARNING")

from src.data.database import Database
from src.backtest.optimizer import run_optimization, PARAM_GRIDS

DB_URL = "sqlite:///alphasmart_dev.db"
OPT_FILE = Path("optimized_params.json")

# Strategy sets per timeframe (only include strategies with param grids)
STRATEGIES_1H = [
    "rsi_vwap",
    "keltner_breakout",
    "hull_ma_crossover",
    "vwap_reversion",
    "zscore_reversion",
    "bb_reversion",
    "stoch_rsi",
    "squeeze_momentum",
]

STRATEGIES_1D = [
    "donchian_bo",
    "bb_reversion",
    "cci_trend",
    "atr_breakout",
    "triple_screen",
    "macd_momentum",
    "ema_crossover",
    "rsi_reversion",
    "momentum_long",
    "zscore_reversion",
    "vwap_reversion",
    "stoch_rsi",
    "williams_r",
    "alpha_composite",
    "rsi_vwap",
    "keltner_breakout",
    "hull_ma_crossover",
]


def load_opt_store() -> dict:
    if OPT_FILE.exists():
        with open(OPT_FILE) as f:
            return json.load(f)
    return {}


def save_opt_store(store: dict) -> None:
    with open(OPT_FILE, "w") as f:
        json.dump(store, f, indent=2)


def opt_key(strategy: str, symbol: str, timeframe: str) -> str:
    return f"{strategy}::{symbol}::{timeframe}"


def run_all_optimizations(timeframe_filter: str = "all") -> None:
    db = Database(DB_URL)
    status = db.fetch_status()

    # Group symbols by timeframe
    by_tf: dict[str, list[str]] = {}
    for r in status:
        tf = r["timeframe"]
        sym = r["symbol"]
        by_tf.setdefault(tf, []).append(sym)

    store = load_opt_store()
    results: list[dict] = []

    for tf, symbols in sorted(by_tf.items()):
        if timeframe_filter != "all" and tf != timeframe_filter:
            continue

        strat_list = STRATEGIES_1H if tf != "1d" else STRATEGIES_1D

        for sym in sorted(symbols):
            for strat in strat_list:
                if strat not in PARAM_GRIDS:
                    continue

                key = opt_key(strat, sym, tf)
                t0 = time.time()
                print(f"  Optimizing {strat:22s} {sym:6s} [{tf}] ...", end=" ", flush=True)

                try:
                    res = run_optimization(strat, sym, tf, DB_URL, objective="sharpe")
                    elapsed = time.time() - t0

                    if "error" in res:
                        print(f"SKIP ({res['error'][:50]})")
                        continue

                    sharpe = res["best_sharpe"]
                    cagr   = res["best_cagr"]
                    dd     = res["best_max_drawdown"]
                    trades = res["best_trade_count"]
                    g2     = res["gate2_pass"]
                    combos = res["total_combos"]

                    print(f"Sharpe={sharpe:5.2f}  CAGR={cagr:6.1%}  DD={dd:5.1%}  "
                          f"Trades={trades:4d}  Gate2={'Y' if g2 else 'n'}  "
                          f"({combos} combos, {elapsed:.0f}s)")

                    # Save to store
                    store[key] = {
                        "strategy": strat,
                        "symbol": sym,
                        "timeframe": tf,
                        "params": res["best_params"],
                        "sharpe": sharpe,
                        "cagr": cagr,
                        "max_drawdown": dd,
                        "trade_count": trades,
                        "gate2_pass": g2,
                        "overfitting_score": res.get("overfitting_score"),
                    }
                    save_opt_store(store)  # incremental save

                    results.append({
                        "strategy": strat,
                        "symbol": sym,
                        "timeframe": tf,
                        "sharpe": sharpe,
                        "cagr": cagr,
                        "max_drawdown": dd,
                        "trade_count": trades,
                        "gate2_pass": g2,
                    })

                except Exception as exc:
                    print(f"ERROR: {exc}")

    # ---- Summary: best strategy per ticker ----
    print("\n" + "=" * 80)
    print("BEST STRATEGY PER TICKER (optimised Sharpe)")
    print("=" * 80)
    print(f"{'Ticker':<8} {'TF':<5} {'Best Strategy':<22} {'Sharpe':>6} {'CAGR':>7} {'MaxDD':>6} {'Trades':>7}  Gate2")
    print("-" * 75)

    by_ticker: dict[str, list[dict]] = {}
    for r in results:
        k = f"{r['symbol']}[{r['timeframe']}]"
        by_ticker.setdefault(k, []).append(r)

    for ticker_tf in sorted(by_ticker.keys()):
        runs = by_ticker[ticker_tf]
        best = max(runs, key=lambda x: x["sharpe"])
        sym, tf_label = ticker_tf.rstrip("]").split("[")
        g2 = "Y" if best["gate2_pass"] else "n"
        print(
            f"{sym:<8} {tf_label:<5} {best['strategy']:<22} "
            f"{best['sharpe']:>6.2f} {best['cagr']:>7.1%} {best['max_drawdown']:>6.1%} "
            f"{best['trade_count']:>7}  {g2}"
        )


if __name__ == "__main__":
    tf = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(f"\nPer-ticker optimization sweep — timeframe filter: {tf}")
    print("Saving optimized params incrementally to optimized_params.json\n")
    run_all_optimizations(tf)
