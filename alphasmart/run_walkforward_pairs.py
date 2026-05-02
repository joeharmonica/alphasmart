"""
Pairs / spread strategy sweep — final architectural pivot after lessons #33
showed every single-asset backtest failed bootstrap (cross-timeframe
replication included).

Mechanic shift: instead of testing strategies on absolute prices (which embed
each asset's macro arc), we test them on *spread ratios* between two
correlated assets. The spread's edge — sector-relative mispricing — is
structurally less tied to any single macro narrative.

Synthetic pair symbols (built by build_pairs_synthetic.py, stored as 1d):
  V-MA, NVDA-AVGO, MSFT-GOOG, AAPL-MSFT, ASML-AVGO

Strategies (mean-reversion mechanics that fit ratio dynamics):
  zscore_reversion+stop  — long when spread is N std below rolling mean
  bb_reversion+stop      — long at lower band, exit at midline

Walk-forward: IS=2y / OOS=1y / step=6mo (4 folds on 5-yr daily).

After this finishes, bootstrap is the binding gate:
  ./venv/bin/python run_bootstrap_passers.py reports/walkforward_pairs_<date>_passers.json
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
TIMEFRAME = "1d"

PAIRS = (
    "V-MA",
    "NVDA-AVGO",
    "MSFT-GOOG",
    "AAPL-MSFT",
    "ASML-AVGO",
)

STRATEGIES = (
    "zscore_reversion+stop",
    "bb_reversion+stop",
)

# Default grids work fine for pairs; both strategies are scale-invariant via
# z-score / std-dev normalisation. No trimming needed at these combo counts:
#   zscore_reversion: 4 × 3 × 3 = 36 combos
#   bb_reversion:     4 × 3     = 12 combos
TRIMMED_GRIDS: dict[str, dict[str, list]] = {}


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
    db = Database(DB_URL)
    avail = {r["symbol"] for r in db.fetch_status() if r["timeframe"] == TIMEFRAME}
    missing = [p for p in PAIRS if p not in avail]
    if missing:
        print(f"ERROR: pair symbols not in DB: {missing}")
        print("Run: ./venv/bin/python build_pairs_synthetic.py")
        return 1

    print(f"Universe: {len(PAIRS)} pairs × {len(STRATEGIES)} strategies = "
          f"{len(PAIRS) * len(STRATEGIES)} optimization runs")
    print(f"Pairs: {list(PAIRS)}")
    print(f"Walk-forward: IS={_opt_mod._IS_YEARS}y / OOS={_opt_mod._OOS_YEARS}y / "
          f"step={_opt_mod._STEP_YEARS}y")
    print()

    rows: list[dict] = []
    passers: list[dict] = []
    t_start = time.time()

    for strategy in STRATEGIES:
        for sym in PAIRS:
            t0 = time.time()
            try:
                opt = run_optimization(
                    strategy_key=strategy,
                    symbol=sym,
                    timeframe=TIMEFRAME,
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
                print(f"  ✗ {strategy:24} {sym:12}  ERROR: {row['error']}  ({elapsed:.1f}s)")
                continue

            tag = []
            if row["gate1_pass"]: tag.append("G1")
            if row["gate2_pass"]: tag.append("G2")
            tag_str = "+".join(tag) if tag else "-"

            print(
                f"  {strategy:24} {sym:12}  "
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
    csv_path = reports_dir / f"walkforward_pairs_{date_tag}.csv"

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

    passers_path = reports_dir / f"walkforward_pairs_{date_tag}_passers.json"
    passers_path.write_text(json.dumps(passers, indent=2))
    print(f"JSON → {passers_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
