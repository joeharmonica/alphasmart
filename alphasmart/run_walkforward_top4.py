"""
Walk-forward optimization across the top 4 trend candidates × full symbol universe.

Strategies (all `+stop` variants — ATR(14) * 2.0 trailing stop):
  cci_trend+stop, hull_ma_crossover+stop, keltner_breakout+stop, rsi_vwap+stop

For each (strategy, symbol, 1d):
  1. Grid search across all valid params (full 5yr history)
  2. Walk-forward validation (IS=2yr / OOS=1yr / step=6mo → ~3 folds)
  3. Gate 1: best-params backtest meets Sharpe>1.2, MaxDD<25%, trades>=30, +ve return
  4. Gate 2: avg(OOS_sharpe / IS_sharpe) >= 0.70 across folds

Outputs:
  reports/walkforward_top4_<UTC date>.csv  — every (strategy, symbol) row
  optimized_params.json                    — Gate 1+Gate 2 passers persisted
  reports/walkforward_top4_<UTC date>_passers.json — passer summary
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make src/ importable
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

# Tighten walk-forward windows BEFORE importing optimizer so we get
# 3+ folds on 5yr daily data instead of the default's single fold.
import src.backtest.optimizer as _opt_mod
_opt_mod._IS_YEARS = 2
_opt_mod._OOS_YEARS = 1
_opt_mod._STEP_YEARS = 0.5

from src.backtest.optimizer import run_optimization
from src.data.database import Database
from api import _save_opt_params

DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
INITIAL_CAPITAL = 100_000.0

STRATEGIES = (
    "cci_trend+stop",
    "hull_ma_crossover+stop",
    "keltner_breakout+stop",
    "rsi_vwap+stop",
)

# Per-strategy grid trims so heavy strategies don't dominate wall-clock.
# Target ~18-27 combos each — same ballpark as cci_trend+stop (~36) and
# hull_ma_crossover+stop (~27 after fast<slow). Strategies absent from this
# dict use their default PARAM_GRIDS entry.
TRIMMED_GRIDS: dict[str, dict[str, list]] = {
    "keltner_breakout+stop": {
        "period":       [15, 30],
        "atr_period":   [10, 14],
        "atr_mult":     [1.5, 2.0, 2.5],
        "trend_period": [100, 200],
    },
    "rsi_vwap+stop": {
        "vwap_period": [12, 24],
        "rsi_period":  [10, 14],
        "oversold":    [25.0, 30.0, 35.0],
        "overbought":  [60.0, 70.0],
    },
}


def _all_symbols_1d() -> list[str]:
    """All distinct symbols that have 1d bars in the database."""
    db = Database(DB_URL)
    rows = db.fetch_status()
    symbols = sorted({r["symbol"] for r in rows if r["timeframe"] == "1d"})
    return symbols


def _row_from_result(strategy: str, symbol: str, opt: dict) -> dict:
    """Flatten run_optimization() output into a single CSV row."""
    if "error" in opt:
        return {
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": "1d",
            "error": opt["error"],
            "valid_combos": 0,
            "best_sharpe": None,
            "best_cagr": None,
            "best_max_drawdown": None,
            "best_trade_count": 0,
            "gate1_pass": False,
            "wf_folds": 0,
            "overfitting_score": None,
            "gate2_pass": False,
            "best_params": "",
        }

    best = opt.get("best_params", {})
    sharpe = opt.get("best_sharpe")
    cagr = opt.get("best_cagr")
    mdd = opt.get("best_max_drawdown")
    tc = opt.get("best_trade_count", 0)

    gate1 = bool(
        sharpe is not None
        and sharpe > 1.2
        and mdd is not None
        and mdd < 0.25
        and tc >= 30
        and (cagr is not None and cagr > 0)
    )

    return {
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": "1d",
        "error": "",
        "valid_combos": opt.get("valid_combos", 0),
        "best_sharpe": sharpe,
        "best_cagr": cagr,
        "best_max_drawdown": mdd,
        "best_trade_count": tc,
        "gate1_pass": gate1,
        "wf_folds": len(opt.get("walk_forward", [])),
        "overfitting_score": opt.get("overfitting_score"),
        "gate2_pass": bool(opt.get("gate2_pass", False)),
        "best_params": json.dumps(best, sort_keys=True),
    }


def main() -> int:
    symbols = _all_symbols_1d()
    if not symbols:
        print("No 1d symbols in DB — run main.py fetch first.")
        return 1

    print(f"Universe: {len(symbols)} symbols × {len(STRATEGIES)} strategies = "
          f"{len(symbols) * len(STRATEGIES)} optimization runs")
    print(f"Symbols: {symbols}")
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
                    timeframe="1d",
                    db_url=DB_URL,
                    capital=INITIAL_CAPITAL,
                    objective="sharpe",
                    custom_param_grid=TRIMMED_GRIDS.get(strategy),
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
            if row["gate1_pass"]:
                tag.append("G1")
            if row["gate2_pass"]:
                tag.append("G2")
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

            # Persist Gate1+Gate2 passers for use by All Results / live
            if row["gate1_pass"] and row["gate2_pass"]:
                params = opt["best_params"]
                _save_opt_params(
                    strategy=strategy,
                    symbol=sym,
                    timeframe="1d",
                    objective="sharpe",
                    params=params,
                    sharpe=float(row["best_sharpe"]),
                    cagr=float(row["best_cagr"]),
                    max_drawdown=float(row["best_max_drawdown"]),
                    gate2_pass=True,
                )
                passers.append({
                    "strategy": strategy,
                    "symbol": sym,
                    "timeframe": "1d",
                    "params": params,
                    "sharpe": row["best_sharpe"],
                    "cagr": row["best_cagr"],
                    "max_drawdown": row["best_max_drawdown"],
                    "trade_count": row["best_trade_count"],
                    "overfitting_score": row["overfitting_score"],
                })

    elapsed_total = time.time() - t_start
    print(f"\nDone — {len(rows)} runs in {elapsed_total:.1f}s "
          f"({len(passers)} Gate1+Gate2 passers)")

    # Write CSV
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    reports_dir = _ROOT.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    csv_path = reports_dir / f"walkforward_top4_{date_tag}.csv"

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

    passers_path = reports_dir / f"walkforward_top4_{date_tag}_passers.json"
    passers_path.write_text(json.dumps(passers, indent=2))
    print(f"JSON → {passers_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
