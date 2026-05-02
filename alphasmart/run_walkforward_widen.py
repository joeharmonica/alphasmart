"""
Widening sweep — second pass after the top-4 +stop sweep returned 0 ROBUST
passers under bootstrap (lessons.md #33).

Strategies (all `+stop` variants — ATR(14) * 2.0 trailing stop):
  momentum_long+stop      — 6-month rate-of-change momentum (different from cci's CCI signal)
  donchian_bo+stop        — channel breakout, less narrative-dependent than cci_trend
  alpha_composite+stop    — proprietary multi-signal composite (trimmed grid)
  bb_reversion+stop       — Bollinger mean reversion (newly registered in optimizer/api)

Same harness as run_walkforward_top4.py:
  IS=2y / OOS=1y / step=6mo → ~4 folds on 5-yr daily data
  Gate 1: Sharpe > 1.2, MaxDD < 25%, trades >= 30, +ve return
  Gate 2: avg(OOS_sharpe / IS_sharpe) >= 0.70 across folds (OFR)

Outputs:
  reports/walkforward_widen_<UTC date>.csv  — every (strategy, symbol) row
  reports/walkforward_widen_<UTC date>_passers.json — Gate1+Gate2 passers
  optimized_params.json — auto-saved passers

After this finishes, the bootstrap step (lessons.md #33) is the binding gate —
any passer must clear BOTH OFR ≥ 0.70 AND bootstrap ratio ≥ 0.65 to be
considered tradable. Run:
  ./venv/bin/python run_bootstrap_passers.py reports/walkforward_widen_<date>_passers.json
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

# Tighten walk-forward windows BEFORE importing optimizer so we get
# 4 folds on 5yr daily data instead of the default's single fold.
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
    "momentum_long+stop",
    "donchian_bo+stop",
    "alpha_composite+stop",
    "bb_reversion+stop",
)

# Trimmed grids:
#   momentum_long+stop  — default (27 combos)
#   donchian_bo+stop    — default (7 combos)
#   bb_reversion+stop   — default (12 combos)
#   alpha_composite+stop — full grid is 1458; trim aggressively to ~36 by
#                          fixing the weight axes at midpoints (lessons #11
#                          says weights must sum to 1.0; the constructor and
#                          combo generator both validate this) and varying
#                          only the EMA periods, RSI threshold, and entry sensitivity.
TRIMMED_GRIDS: dict[str, dict[str, list]] = {
    "alpha_composite+stop": {
        "fast_ema":        [10, 13],
        "slow_ema":        [25, 40],
        "rsi_period":      [14],
        "rsi_oversold":    [40.0, 45.0, 50.0],
        "trend_weight":    [0.45],
        "rsi_weight":      [0.35],
        "entry_threshold": [0.45, 0.50, 0.55],
    },
}


def _all_symbols_1d() -> list[str]:
    db = Database(DB_URL)
    rows = db.fetch_status()
    return sorted({r["symbol"] for r in rows if r["timeframe"] == "1d"})


def _row_from_result(strategy: str, symbol: str, opt: dict) -> dict:
    if "error" in opt:
        return {
            "strategy": strategy, "symbol": symbol, "timeframe": "1d",
            "error": opt["error"], "valid_combos": 0,
            "best_sharpe": None, "best_cagr": None, "best_max_drawdown": None,
            "best_trade_count": 0, "gate1_pass": False,
            "wf_folds": 0, "overfitting_score": None, "gate2_pass": False,
            "best_params": "",
        }

    best = opt.get("best_params", {})
    sharpe = opt.get("best_sharpe")
    cagr = opt.get("best_cagr")
    mdd = opt.get("best_max_drawdown")
    tc = opt.get("best_trade_count", 0)

    gate1 = bool(
        sharpe is not None and sharpe > 1.2
        and mdd is not None and mdd < 0.25
        and tc >= 30
        and (cagr is not None and cagr > 0)
    )

    return {
        "strategy": strategy, "symbol": symbol, "timeframe": "1d",
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
                    strategy=strategy, symbol=sym, timeframe="1d",
                    objective="sharpe", params=params,
                    sharpe=float(row["best_sharpe"]),
                    cagr=float(row["best_cagr"]),
                    max_drawdown=float(row["best_max_drawdown"]),
                    gate2_pass=True,
                )
                passers.append({
                    "strategy": strategy, "symbol": sym, "timeframe": "1d",
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
    csv_path = reports_dir / f"walkforward_widen_{date_tag}.csv"

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

    passers_path = reports_dir / f"walkforward_widen_{date_tag}_passers.json"
    passers_path.write_text(json.dumps(passers, indent=2))
    print(f"JSON → {passers_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
