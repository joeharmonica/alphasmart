"""
Block-bootstrap robustness check for Gate1+Gate2 walk-forward passers.

For each passer in `reports/walkforward_top4_<date>_passers.json`:
  1. Pull historical OHLCV for (symbol, 1d) from the local DB.
  2. Run `block_bootstrap` (n=200) via src.backtest.simulation.run_simulation.
  3. Verdict ROBUST if median sim Sharpe >= 65% of original Sharpe; else FRAGILE.

Outputs:
  reports/bootstrap_passers_<UTC date>.json — full per-passer record incl.
      original_sharpe, sim_sharpe percentiles, ratio, verdict.

Usage:
  python run_bootstrap_passers.py                        # latest passers JSON
  python run_bootstrap_passers.py path/to/passers.json   # explicit input
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.backtest.simulation import run_simulation
from src.data.database import Database

DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
INITIAL_CAPITAL = 100_000.0
N_SIMULATIONS = 200
ROBUST_RATIO = 0.65   # median sim Sharpe must be >= 65% of original


def _latest_passers_json() -> Path | None:
    reports_dir = _ROOT.parent / "reports"
    if not reports_dir.exists():
        return None
    candidates = sorted(
        reports_dir.glob("walkforward_top4_*_passers.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _bootstrap_one(passer: dict) -> dict:
    strategy = passer["strategy"]
    symbol = passer["symbol"]
    timeframe = passer.get("timeframe", "1d")
    params = passer["params"]
    original_sharpe = float(passer["sharpe"])

    db = Database(DB_URL)
    data = db.query_ohlcv(symbol, timeframe=timeframe)
    if data.empty:
        return {
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "error": f"No data for {symbol}/{timeframe}",
            "verdict": "ERROR",
        }

    t0 = time.time()
    result = run_simulation(
        strategy_key=strategy,
        symbol=symbol,
        data=data,
        simulation_type="block_bootstrap",
        n_simulations=N_SIMULATIONS,
        params=params,
        capital=INITIAL_CAPITAL,
        timeframe=timeframe,
    )
    elapsed = time.time() - t0

    sims = [s for s in result.sim_sharpes if s is not None and not np.isnan(s)]
    if not sims:
        return {
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "error": "All simulations failed",
            "verdict": "ERROR",
            "elapsed_s": round(elapsed, 1),
        }

    arr = np.array(sims)
    sim_median = float(np.median(arr))
    sim_p25 = float(np.percentile(arr, 25))
    sim_p75 = float(np.percentile(arr, 75))
    sim_p5 = float(np.percentile(arr, 5))
    sim_p95 = float(np.percentile(arr, 95))
    sim_mean = float(np.mean(arr))

    ratio = sim_median / original_sharpe if original_sharpe > 0 else 0.0
    verdict = "ROBUST" if ratio >= ROBUST_RATIO else "FRAGILE"

    return {
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "params": params,
        "original_sharpe": original_sharpe,
        "original_cagr": passer.get("cagr"),
        "original_max_drawdown": passer.get("max_drawdown"),
        "original_trade_count": passer.get("trade_count"),
        "n_simulations": len(sims),
        "sim_sharpe_p5": round(sim_p5, 4),
        "sim_sharpe_p25": round(sim_p25, 4),
        "sim_sharpe_median": round(sim_median, 4),
        "sim_sharpe_p75": round(sim_p75, 4),
        "sim_sharpe_p95": round(sim_p95, 4),
        "sim_sharpe_mean": round(sim_mean, 4),
        "ratio_median_to_original": round(ratio, 4),
        "robust_threshold": ROBUST_RATIO,
        "verdict": verdict,
        "elapsed_s": round(elapsed, 1),
    }


def main(argv: list[str]) -> int:
    if len(argv) >= 2:
        passers_path = Path(argv[1])
    else:
        latest = _latest_passers_json()
        if latest is None:
            print("ERROR: no passers JSON found in reports/. Run "
                  "run_walkforward_top4.py first or pass a path explicitly.")
            return 1
        passers_path = latest

    if not passers_path.exists():
        print(f"ERROR: passers file does not exist: {passers_path}")
        return 1

    passers = json.loads(passers_path.read_text())
    if not passers:
        print(f"No passers in {passers_path} — nothing to bootstrap.")
        return 0

    print(f"Loaded {len(passers)} passers from {passers_path}")
    print(f"Block-bootstrap: n={N_SIMULATIONS} sims, ROBUST threshold = "
          f"median_sim_sharpe / original_sharpe >= {ROBUST_RATIO}")
    print()

    records: list[dict] = []
    for i, passer in enumerate(passers, 1):
        tag = f"{passer['strategy']}::{passer['symbol']}::{passer.get('timeframe', '1d')}"
        print(f"[{i}/{len(passers)}] bootstrapping {tag} ...", flush=True)
        try:
            rec = _bootstrap_one(passer)
        except Exception as exc:
            rec = {
                "strategy": passer["strategy"],
                "symbol": passer["symbol"],
                "timeframe": passer.get("timeframe", "1d"),
                "error": f"{type(exc).__name__}: {exc}",
                "verdict": "ERROR",
            }
        records.append(rec)

        if rec.get("verdict") == "ERROR":
            print(f"    ERROR: {rec.get('error')}")
        else:
            print(
                f"    orig Sharpe={rec['original_sharpe']:.3f}  "
                f"sim p25/p50/p75={rec['sim_sharpe_p25']:.3f}/"
                f"{rec['sim_sharpe_median']:.3f}/{rec['sim_sharpe_p75']:.3f}  "
                f"ratio={rec['ratio_median_to_original']:.2f}  "
                f"[{rec['verdict']}]  ({rec['elapsed_s']}s)"
            )

    n_robust = sum(1 for r in records if r.get("verdict") == "ROBUST")
    n_fragile = sum(1 for r in records if r.get("verdict") == "FRAGILE")
    n_error = sum(1 for r in records if r.get("verdict") == "ERROR")
    print()
    print(f"Verdicts: ROBUST={n_robust}  FRAGILE={n_fragile}  ERROR={n_error}")

    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    reports_dir = _ROOT.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    out_path = reports_dir / f"bootstrap_passers_{date_tag}.json"
    out_path.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_passers": str(passers_path),
        "n_simulations": N_SIMULATIONS,
        "robust_threshold": ROBUST_RATIO,
        "summary": {"robust": n_robust, "fragile": n_fragile, "error": n_error},
        "records": records,
    }, indent=2))
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
