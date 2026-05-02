"""
Cross-timeframe replication sweep — same 8 strategies that have been swept on
1d (top-4 + widening), now on 1wk. Tests whether daily edges survive at a
fundamentally different sampling rate (lessons.md #33: independence from a
specific macro arc is the actual robustness signal).

Strategies (all `+stop`):
  cci_trend, hull_ma_crossover, keltner_breakout, rsi_vwap   — top-4
  momentum_long, donchian_bo, alpha_composite, bb_reversion — widening

Universe: 17 symbols on 1wk (same set that has 1d data). Walk-forward windows
scale automatically via `bars_per_year_for("1wk") = 52`, giving ~4 folds on
~5 yr weekly data (260 bars).

**Critical:** 1d parameter grids are bar-count-based and don't translate to
1wk (lessons.md #10). E.g. `period=20` on 1d ≈ 1 month, but on 1wk ≈ 5
months. WEEKLY_GRIDS below scales bar-count params by ~1/5 to preserve the
economic time-window. Threshold / level / multiplier params are unchanged
(they're unitless w.r.t. timeframe).

After this finishes, bootstrap is the binding gate (lessons #33). Run:
  ./venv/bin/python run_bootstrap_passers.py reports/walkforward_weekly_<date>_passers.json
  ./venv/bin/python decide_portfolio.py
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

# Tighten walk-forward windows BEFORE importing optimizer.
import src.backtest.optimizer as _opt_mod
_opt_mod._IS_YEARS = 2
_opt_mod._OOS_YEARS = 1
_opt_mod._STEP_YEARS = 0.5

from src.backtest.optimizer import run_optimization
from src.data.database import Database
from api import _save_opt_params

DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
INITIAL_CAPITAL = 100_000.0
TIMEFRAME = "1wk"

STRATEGIES = (
    # Top-4 (sweep run 2026-04-30)
    "cci_trend+stop",
    "hull_ma_crossover+stop",
    "keltner_breakout+stop",
    "rsi_vwap+stop",
    # Widening (sweep run 2026-05-02)
    "momentum_long+stop",
    "donchian_bo+stop",
    "alpha_composite+stop",
    "bb_reversion+stop",
)

# Weekly-scaled grids: bar-count params (period, atr_period, fast/slow EMA,
# lookback_period, trend_period, vwap_period, rsi_period) divided by ~5 from
# the 1d grids; threshold / level / multiplier params unchanged.
WEEKLY_GRIDS: dict[str, dict[str, list]] = {
    "cci_trend+stop": {
        # 1d period=20 → 1wk period=4 (~1mo). vol_period default 20 → 4 weeks internally.
        "period":        [4, 8],            # ~1m, ~2m
        "entry_level":   [75.0, 100.0, 125.0],
        "exit_level":    [0.0, 50.0],
        "vol_threshold": [0.8, 1.0, 1.2],
    },
    "hull_ma_crossover+stop": {
        # 1d fast [13,21,34] → 1wk [3,5]; slow [50,89,144] → [13,26]; trend [50,100,200] → [26,52]
        "fast_period":  [3, 5],             # ~3, ~5 weeks
        "slow_period":  [13, 26],           # ~3, ~6 months
        "trend_period": [26, 52],           # ~6 months, ~1 year
    },
    "keltner_breakout+stop": {
        "period":       [4, 8],             # ~1m, ~2m
        "atr_period":   [4, 6],             # ~1m, ~1.5m
        "atr_mult":     [1.5, 2.0, 2.5],
        "trend_period": [26, 52],           # ~6m, ~1y
    },
    "rsi_vwap+stop": {
        "vwap_period": [4, 8],              # ~1m, ~2m
        "rsi_period":  [4, 6],              # ~1m, ~1.5m
        "oversold":    [25.0, 30.0, 35.0],
        "overbought":  [60.0, 70.0],
    },
    "momentum_long+stop": {
        # 1d lookback [63, 126, 189] (3, 6, 9 months) → 1wk [13, 26, 39]
        "lookback_period": [13, 26, 39],    # 3m, 6m, 9m
        "entry_threshold": [0.03, 0.05, 0.08],
        "exit_threshold":  [-0.05, -0.02, 0.0],
    },
    "donchian_bo+stop": {
        # 1d period [10..50] → 1wk [4..20] (~1m to ~5m)
        "period": [4, 6, 8, 10, 13, 20],
    },
    "alpha_composite+stop": {
        # 1d fast_ema [8,10,13] → 1wk [3, 5]; slow_ema [25,30,40] → [10, 20]
        "fast_ema":        [3, 5],
        "slow_ema":        [10, 20],
        "rsi_period":      [6],             # 1d 14 → 1wk ~3; using 6 to give RSI more room
        "rsi_oversold":    [40.0, 45.0, 50.0],
        "trend_weight":    [0.45],
        "rsi_weight":      [0.35],
        "entry_threshold": [0.45, 0.50, 0.55],
    },
    "bb_reversion+stop": {
        # 1d period [15,20,25,30] → 1wk [4, 6, 8]
        "period":  [4, 6, 8],
        "std_dev": [1.5, 2.0, 2.5],
    },
}


def _all_symbols_with_1wk() -> list[str]:
    """Symbols that have 1wk bars in the DB."""
    db = Database(DB_URL)
    rows = db.fetch_status()
    return sorted({r["symbol"] for r in rows if r["timeframe"] == TIMEFRAME})


def _row_from_result(strategy: str, symbol: str, opt: dict) -> dict:
    if "error" in opt:
        return {
            "strategy": strategy, "symbol": symbol, "timeframe": TIMEFRAME,
            "error": opt["error"], "valid_combos": 0,
            "best_sharpe": None, "best_cagr": None, "best_max_drawdown": None,
            "best_trade_count": 0, "gate1_pass": False,
            "wf_folds": 0, "overfitting_score": None, "gate2_pass": False,
            "best_params": "",
        }
    best = opt.get("best_params", {})
    sharpe = opt.get("best_sharpe")
    cagr   = opt.get("best_cagr")
    mdd    = opt.get("best_max_drawdown")
    tc     = opt.get("best_trade_count", 0)

    # Gate 1 unchanged. Note: weekly trade counts will be lower than daily
    # by definition (~5x fewer bars per year). Trade count ≥ 30 may be
    # binding for slower-cycling configs; lessons #31 relaxation framework
    # applies natively here.
    gate1 = bool(
        sharpe is not None and sharpe > 1.2
        and mdd is not None and mdd < 0.25
        and tc >= 30
        and (cagr is not None and cagr > 0)
    )

    return {
        "strategy": strategy, "symbol": symbol, "timeframe": TIMEFRAME,
        "error": "", "valid_combos": opt.get("valid_combos", 0),
        "best_sharpe": sharpe, "best_cagr": cagr,
        "best_max_drawdown": mdd, "best_trade_count": tc,
        "gate1_pass": gate1,
        "wf_folds": len(opt.get("walk_forward", [])),
        "overfitting_score": opt.get("overfitting_score"),
        "gate2_pass": bool(opt.get("gate2_pass", False)),
        "best_params": json.dumps(best, sort_keys=True),
    }


def main() -> int:
    symbols = _all_symbols_with_1wk()
    if not symbols:
        print(f"No {TIMEFRAME} symbols in DB — fetch first.")
        return 1

    print(f"Universe: {len(symbols)} symbols × {len(STRATEGIES)} strategies = "
          f"{len(symbols) * len(STRATEGIES)} optimization runs")
    print(f"Symbols: {symbols}")
    print(f"Timeframe: {TIMEFRAME}")
    print(f"Walk-forward: IS={_opt_mod._IS_YEARS}y / OOS={_opt_mod._OOS_YEARS}y / "
          f"step={_opt_mod._STEP_YEARS}y")
    print()

    rows: list[dict] = []
    passers: list[dict] = []
    t_start = time.time()

    for strategy in STRATEGIES:
        for sym in symbols:
            t0 = time.time()
            try:
                opt = run_optimization(
                    strategy_key=strategy,
                    symbol=sym,
                    timeframe=TIMEFRAME,
                    db_url=DB_URL,
                    capital=INITIAL_CAPITAL,
                    objective="sharpe",
                    custom_param_grid=WEEKLY_GRIDS.get(strategy),
                )
            except Exception as exc:
                opt = {"error": f"{type(exc).__name__}: {exc}"}

            row = _row_from_result(strategy, sym, opt)
            rows.append(row)
            elapsed = time.time() - t0

            if row["error"]:
                print(f"  ✗ {strategy:24} {sym:10}  ERROR: {row['error']}  ({elapsed:.1f}s)")
                continue

            tag = []
            if row["gate1_pass"]: tag.append("G1")
            if row["gate2_pass"]: tag.append("G2")
            tag_str = "+".join(tag) if tag else "-"

            print(
                f"  {strategy:24} {sym:10}  "
                f"Sh={row['best_sharpe']:.3f}  "
                f"DD={row['best_max_drawdown']:.3f}  "
                f"trades={row['best_trade_count']:>3}  "
                f"WF folds={row['wf_folds']}  "
                f"OFR={row['overfitting_score'] if row['overfitting_score'] is not None else 'NA'}  "
                f"[{tag_str}]  ({elapsed:.1f}s)"
            )

            if row["gate1_pass"] and row["gate2_pass"]:
                params = opt["best_params"]
                _save_opt_params(
                    strategy=strategy, symbol=sym, timeframe=TIMEFRAME,
                    objective="sharpe", params=params,
                    sharpe=float(row["best_sharpe"]),
                    cagr=float(row["best_cagr"]),
                    max_drawdown=float(row["best_max_drawdown"]),
                    gate2_pass=True,
                )
                passers.append({
                    "strategy": strategy, "symbol": sym, "timeframe": TIMEFRAME,
                    "params": params,
                    "sharpe": row["best_sharpe"], "cagr": row["best_cagr"],
                    "max_drawdown": row["best_max_drawdown"],
                    "trade_count": row["best_trade_count"],
                    "overfitting_score": row["overfitting_score"],
                })

    elapsed_total = time.time() - t_start
    print(f"\nDone — {len(rows)} runs in {elapsed_total:.1f}s "
          f"({len(passers)} Gate1+Gate2 passers)")

    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    reports_dir = _ROOT.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    csv_path = reports_dir / f"walkforward_weekly_{date_tag}.csv"

    fieldnames = [
        "strategy", "symbol", "timeframe", "valid_combos",
        "best_sharpe", "best_cagr", "best_max_drawdown", "best_trade_count",
        "gate1_pass", "wf_folds", "overfitting_score", "gate2_pass",
        "best_params", "error",
    ]
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV  → {csv_path}")

    passers_path = reports_dir / f"walkforward_weekly_{date_tag}_passers.json"
    passers_path.write_text(json.dumps(passers, indent=2))
    print(f"JSON → {passers_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
