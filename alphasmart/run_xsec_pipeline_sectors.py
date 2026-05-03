"""
Cross-sectional momentum on sector ETFs — Tier A #4 (different universe).

Hypothesis: the 15-tech-mega-cap universe was structurally homogeneous
(ρ ~0.7 between assets), so all cross-sectional strategies converged to
the same edge. Sector ETFs span 11 distinct industries with much lower
inter-asset correlation, breaking that homogeneity.

Universe: 11 sector SPDRs — XLK XLF XLV XLE XLI XLP XLY XLU XLB XLRE XLC.
"""
from __future__ import annotations

import sys, time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.data.database import Database
from run_xsec_pipeline import run_xsec_momentum, compute_metrics, synchronised_block_bootstrap, StageResult, PERIODS_PER_YEAR, TIMEFRAME, DB_URL
from run_xsec_pipeline_v2 import vol_target_overlay


SECTOR_SYMBOLS = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC"]


def run_sector_momentum(closes, lookback_days, skip_days, top_k, rebal_days):
    rets, rebs = run_xsec_momentum(closes, lookback_days, skip_days, top_k, rebal_days)
    return vol_target_overlay(rets), rebs


def stage_1(closes, p):
    t0 = time.time()
    rets, rebs = run_sector_momentum(closes, **p); m = compute_metrics(rets, rebs)
    return StageResult("1_smoke", time.time()-t0, {"params": p, "metrics": m,
        "kill_pass": m["sharpe"] > 0 and m["max_drawdown"] < 0.30 and m["trade_count"] >= 30})


def stage_2(closes, p, orig, n_sims=50):
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=n_sims, block_size=20, seed=42)
    sh = []
    for sc in sims:
        full = pd.concat([closes.iloc[0:1], sc]).iloc[: len(closes)]; full.index = closes.index
        rets, rebs = run_sector_momentum(full, **p); sh.append(compute_metrics(rets, rebs)["sharpe"])
    arr = np.array([s for s in sh if not np.isnan(s)])
    p25, med, p75 = (np.percentile(arr,[25,50,75]) if len(arr) else (np.nan,)*3)
    ratio = float(med)/orig if orig > 0 else 0.0
    return StageResult("2_fast_bootstrap", time.time()-t0, {"n_sims": len(arr),
        "sim_sharpe_p25": float(p25), "sim_sharpe_p50": float(med), "sim_sharpe_p75": float(p75),
        "ratio": float(ratio), "kill_pass": float(ratio) >= 0.4})


def stage_3(closes, grid):
    t0 = time.time(); rows = []
    for combo in product(*grid.values()):
        params = dict(zip(grid.keys(), combo))
        rets, rebs = run_sector_momentum(closes, **params); m = compute_metrics(rets, rebs)
        rows.append({"params": params, **m})
    rows.sort(key=lambda r: -r["sharpe"])
    return StageResult("3_grid", time.time()-t0, {"n_combos": len(rows), "top5": rows[:5],
        "best": rows[0] if rows else None, "best_kill_pass": rows[0]["sharpe"] >= 1.0 if rows else False})


def stage_3b(closes, best_p):
    is_b = 2*PERIODS_PER_YEAR; oos_b = PERIODS_PER_YEAR; step = PERIODS_PER_YEAR // 2
    n = len(closes); folds = []; start = 0
    while start + is_b + oos_b <= n:
        is_c = closes.iloc[start: start+is_b]; oos_c = closes.iloc[start+is_b: start+is_b+oos_b]
        is_r,_ = run_sector_momentum(is_c, **best_p); oos_r,_ = run_sector_momentum(oos_c, **best_p)
        folds.append({"is_sharpe": compute_metrics(is_r,0)["sharpe"], "oos_sharpe": compute_metrics(oos_r,0)["sharpe"]})
        start += step
    valid = [f for f in folds if f["is_sharpe"] > 0]
    ofr = float(np.mean([max(0.0,f["oos_sharpe"])/f["is_sharpe"] for f in valid])) if valid else float("nan")
    return {"folds": folds, "ofr": ofr, "gate2_pass": ofr >= 0.70}


def stage_4(closes, best_p, orig, n_sims=200):
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=n_sims, block_size=20, seed=7)
    sh = []
    for sc in sims:
        full = pd.concat([closes.iloc[0:1], sc]).iloc[: len(closes)]; full.index = closes.index
        rets, rebs = run_sector_momentum(full, **best_p); sh.append(compute_metrics(rets, rebs)["sharpe"])
    arr = np.array([s for s in sh if not np.isnan(s)])
    p5,p25,med,p75,p95 = (np.percentile(arr,[5,25,50,75,95]) if len(arr) else (np.nan,)*5)
    ratio = float(med)/orig if orig > 0 else 0.0
    return StageResult("4_confirm_bootstrap", time.time()-t0, {"n_sims": len(arr),
        "sim_sharpe_p5": float(p5), "sim_sharpe_p25": float(p25), "sim_sharpe_p50": float(med),
        "sim_sharpe_p75": float(p75), "sim_sharpe_p95": float(p95), "ratio": float(ratio),
        "verdict": "ROBUST" if float(ratio) >= 0.65 else "FRAGILE"})


def main():
    db = Database(DB_URL)
    closes = pd.DataFrame({s: db.query_ohlcv(s, TIMEFRAME)["close"] for s in SECTOR_SYMBOLS}).dropna()
    print(f"Universe: {SECTOR_SYMBOLS}")
    print(f"Aligned closes: {len(closes)} bars × {len(closes.columns)} sectors  range {closes.index[0].date()} → {closes.index[-1].date()}\n")

    DEFAULT = dict(lookback_days=126, skip_days=0, top_k=3, rebal_days=21)

    print("="*78); print("STAGE 1 — Smoke (sector rotation, voltarget overlay)"); print("="*78)
    s1 = stage_1(closes, DEFAULT); m = s1.payload["metrics"]
    print(f"  Sharpe={m['sharpe']:.3f}  CAGR={m['cagr']:.3f}  MaxDD={m['max_drawdown']:.3f}  rebs={m['trade_count']}  kill_pass={s1.payload['kill_pass']}  ({s1.elapsed_s:.1f}s)\n")
    if not s1.payload["kill_pass"]:
        print("KILLED at Stage 1."); return 0

    print("="*78); print("STAGE 2 — Fast bootstrap (n=50)"); print("="*78)
    s2 = stage_2(closes, DEFAULT, m["sharpe"]); p = s2.payload
    print(f"  p25/p50/p75={p['sim_sharpe_p25']:.3f}/{p['sim_sharpe_p50']:.3f}/{p['sim_sharpe_p75']:.3f}  ratio={p['ratio']:.3f}  kill_pass={p['kill_pass']}  ({s2.elapsed_s:.1f}s)\n")
    if not p["kill_pass"]:
        print("KILLED at Stage 2."); return 0

    print("="*78); print("STAGE 3 — Grid"); print("="*78)
    GRID = {"lookback_days": [63, 126, 189, 252], "skip_days": [0, 21], "top_k": [2, 3, 4], "rebal_days": [21, 63]}
    s3 = stage_3(closes, GRID)
    print(f"  combos={s3.payload['n_combos']}  ({s3.elapsed_s:.1f}s)")
    for r in s3.payload["top5"]:
        print(f"    Sh={r['sharpe']:.3f} CAGR={r['cagr']:.3f} DD={r['max_drawdown']:.3f} reb={r['trade_count']}  {r['params']}")
    best = s3.payload["best"]; print()
    if not s3.payload["best_kill_pass"]:
        print(f"KILLED at Stage 3 — best Sharpe {best['sharpe']:.3f} < 1.0."); return 0

    print("  Walk-forward OFR:")
    wf = stage_3b(closes, best["params"])
    print(f"    folds={len(wf['folds'])}  OFR={wf['ofr']:.3f}  Gate2={'Y' if wf['gate2_pass'] else 'N'}\n")

    print("="*78); print("STAGE 4 — Confirmation bootstrap (n=200)"); print("="*78)
    s4 = stage_4(closes, best["params"], best["sharpe"]); p = s4.payload
    print(f"  p5/p25/p50/p75/p95={p['sim_sharpe_p5']:.3f}/{p['sim_sharpe_p25']:.3f}/{p['sim_sharpe_p50']:.3f}/{p['sim_sharpe_p75']:.3f}/{p['sim_sharpe_p95']:.3f}")
    print(f"  ratio={p['ratio']:.3f}  verdict: {p['verdict']}  ({s4.elapsed_s:.1f}s)\n")

    print("="*78); print("STAGE 5 — Portfolio decision"); print("="*78)
    if p["verdict"] == "ROBUST" and wf["gate2_pass"]:
        print(f"  PORTFOLIO_READY ✅  Sharpe={best['sharpe']:.3f}  CAGR={best['cagr']:.3f}  MaxDD={best['max_drawdown']:.3f}  OFR={wf['ofr']:.3f}  ratio={p['ratio']:.3f}")
    else:
        reasons = []
        if not wf["gate2_pass"]: reasons.append(f"OFR={wf['ofr']:.3f} < 0.70")
        if p["verdict"] != "ROBUST": reasons.append(f"ratio={p['ratio']:.3f} < 0.65")
        print(f"  CONCENTRATION/NONE — {'; '.join(reasons)}")

    import json
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = _ROOT.parent / "reports" / f"xsec_sectors_pipeline_{date_tag}.json"
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "variant": "xsec_momentum_on_11_sector_ETFs",
        "universe": SECTOR_SYMBOLS, "default_params": DEFAULT, "grid": {k: list(v) for k,v in GRID.items()},
        "stages": {"1_smoke": s1.payload, "2_fast_bootstrap": s2.payload,
                   "3_grid_top5": s3.payload["top5"], "3_grid_best": best,
                   "3b_walkforward": wf, "4_confirm_bootstrap": s4.payload},
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
