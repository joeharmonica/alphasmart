"""
Cross-sectional low-volatility — Tier A #2 from implementation_plan_v2.

Long top-K assets by *lowest* trailing 60-day vol (i.e. inverse vol). Equal-
weighted, rebalance monthly. The "betting against beta" / quality factor
(Frazzini & Pedersen 2014).

Same 5-stage pipeline as v2; same universe (15 syms, 10 yr) and vol-target
overlay. If this also clears all 5 stages and is uncorrelated with the
momentum strategy from v2, that's 2 of the 3 needed for paper-tradable.
"""
from __future__ import annotations

import math
import sys
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.data.database import Database
from run_xsec_pipeline import (
    compute_metrics, synchronised_block_bootstrap, StageResult,
    PERIODS_PER_YEAR, TIMEFRAME, DB_URL,
)
from run_xsec_pipeline_v2 import vol_target_overlay, EXCLUDE_SYMBOLS


def run_xsec_lowvol(
    closes: pd.DataFrame,
    vol_window: int,
    skip_days: int,
    top_k: int,
    rebal_days: int,
) -> tuple[pd.Series, int]:
    """Long top-K by *lowest* trailing vol_window-day realized vol."""
    n_bars, n_assets = closes.shape
    if n_bars <= vol_window + skip_days:
        return pd.Series(dtype=float), 0

    returns = closes.pct_change()
    portfolio_returns = pd.Series(0.0, index=closes.index)
    held: list[str] = []
    rebalances = 0

    start = vol_window + skip_days
    for i in range(start, n_bars):
        if (i - start) % rebal_days == 0 or not held:
            window = returns.iloc[i - skip_days - vol_window: i - skip_days].dropna(how="all")
            if len(window) >= max(20, vol_window // 3):
                vol = window.std(ddof=1) * math.sqrt(PERIODS_PER_YEAR)
                # Lowest vol = best score
                valid = vol.dropna()
                if len(valid) >= top_k:
                    held = valid.nsmallest(top_k).index.tolist()
                    rebalances += 1
        if held:
            day_rets = returns.iloc[i][held].dropna()
            if len(day_rets) > 0:
                portfolio_returns.iloc[i] = float(day_rets.mean())

    return vol_target_overlay(portfolio_returns), rebalances


def stage_1_smoke(closes, p):
    t0 = time.time()
    rets, rebs = run_xsec_lowvol(closes, **p)
    m = compute_metrics(rets, rebs)
    return StageResult("1_smoke", time.time()-t0, {"params": p, "metrics": m,
        "kill_pass": m["sharpe"] > 0 and m["max_drawdown"] < 0.30 and m["trade_count"] >= 30})


def stage_2_fast_bootstrap(closes, p, orig_sharpe, n_sims=50):
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=n_sims, block_size=20, seed=42)
    sim_sh = []
    for sc in sims:
        full = pd.concat([closes.iloc[0:1], sc]).iloc[: len(closes)]; full.index = closes.index
        rets, rebs = run_xsec_lowvol(full, **p)
        sim_sh.append(compute_metrics(rets, rebs)["sharpe"])
    arr = np.array([s for s in sim_sh if not np.isnan(s)])
    p25, med, p75 = (np.percentile(arr,[25,50,75]) if len(arr) else (np.nan,)*3)
    ratio = float(med)/orig_sharpe if orig_sharpe > 0 else 0.0
    return StageResult("2_fast_bootstrap", time.time()-t0, {"n_sims": len(arr),
        "sim_sharpe_p25": float(p25), "sim_sharpe_p50": float(med), "sim_sharpe_p75": float(p75),
        "ratio": float(ratio), "kill_pass": float(ratio) >= 0.4})


def stage_3_grid(closes, grid):
    t0 = time.time()
    keys = list(grid); rows = []
    for combo in product(*grid.values()):
        params = dict(zip(keys, combo))
        rets, rebs = run_xsec_lowvol(closes, **params)
        m = compute_metrics(rets, rebs)
        rows.append({"params": params, **m})
    rows.sort(key=lambda r: -r["sharpe"])
    return StageResult("3_grid", time.time()-t0, {"n_combos": len(rows), "top5": rows[:5],
        "best": rows[0] if rows else None, "best_kill_pass": rows[0]["sharpe"] >= 1.0 if rows else False})


def stage_3b_walkforward(closes, best_p, is_years=2, oos_years=1, step_years=0.5):
    is_b = int(is_years*PERIODS_PER_YEAR); oos_b = int(oos_years*PERIODS_PER_YEAR); step = int(step_years*PERIODS_PER_YEAR)
    n = len(closes); folds = []; start = 0
    while start + is_b + oos_b <= n:
        is_c = closes.iloc[start: start+is_b]; oos_c = closes.iloc[start+is_b: start+is_b+oos_b]
        is_r, _ = run_xsec_lowvol(is_c, **best_p); oos_r, _ = run_xsec_lowvol(oos_c, **best_p)
        folds.append({"is_sharpe": compute_metrics(is_r,0)["sharpe"], "oos_sharpe": compute_metrics(oos_r,0)["sharpe"]})
        start += step
    valid = [f for f in folds if f["is_sharpe"] > 0]
    ofr = float(np.mean([max(0.0,f["oos_sharpe"])/f["is_sharpe"] for f in valid])) if valid else float("nan")
    return {"folds": folds, "ofr": ofr, "gate2_pass": ofr >= 0.70}


def stage_4_confirm(closes, best_p, orig_sh, n_sims=200):
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=n_sims, block_size=20, seed=7)
    sim_sh = []
    for sc in sims:
        full = pd.concat([closes.iloc[0:1], sc]).iloc[: len(closes)]; full.index = closes.index
        rets, rebs = run_xsec_lowvol(full, **best_p)
        sim_sh.append(compute_metrics(rets, rebs)["sharpe"])
    arr = np.array([s for s in sim_sh if not np.isnan(s)])
    p5,p25,med,p75,p95 = (np.percentile(arr,[5,25,50,75,95]) if len(arr) else (np.nan,)*5)
    ratio = float(med)/orig_sh if orig_sh > 0 else 0.0
    return StageResult("4_confirm_bootstrap", time.time()-t0, {"n_sims": len(arr),
        "sim_sharpe_p5": float(p5), "sim_sharpe_p25": float(p25), "sim_sharpe_p50": float(med),
        "sim_sharpe_p75": float(p75), "sim_sharpe_p95": float(p95), "ratio": float(ratio),
        "verdict": "ROBUST" if float(ratio) >= 0.65 else "FRAGILE"})


def main():
    db = Database(DB_URL)
    rows = db.fetch_status()
    syms = sorted(set(r["symbol"] for r in rows if r["timeframe"]==TIMEFRAME and "-" not in r["symbol"]) - EXCLUDE_SYMBOLS)
    closes = pd.DataFrame({s: db.query_ohlcv(s, TIMEFRAME)["close"] for s in syms}).dropna()
    print(f"Universe: {len(syms)} symbols, {len(closes)} bars, range {closes.index[0].date()} → {closes.index[-1].date()}\n")

    DEFAULT = dict(vol_window=60, skip_days=0, top_k=3, rebal_days=21)

    print("="*78); print("STAGE 1 — Smoke (xsec LOW-VOL, voltarget overlay)"); print("="*78)
    s1 = stage_1_smoke(closes, DEFAULT)
    m = s1.payload["metrics"]
    print(f"  Sharpe={m['sharpe']:.3f}  CAGR={m['cagr']:.3f}  MaxDD={m['max_drawdown']:.3f}  rebs={m['trade_count']}  kill_pass={s1.payload['kill_pass']}  ({s1.elapsed_s:.1f}s)\n")
    if not s1.payload["kill_pass"]:
        print("KILLED at Stage 1."); return 0

    print("="*78); print("STAGE 2 — Fast bootstrap (n=50)"); print("="*78)
    s2 = stage_2_fast_bootstrap(closes, DEFAULT, m["sharpe"])
    p = s2.payload
    print(f"  p25/p50/p75={p['sim_sharpe_p25']:.3f}/{p['sim_sharpe_p50']:.3f}/{p['sim_sharpe_p75']:.3f}  ratio={p['ratio']:.3f}  kill_pass={p['kill_pass']}  ({s2.elapsed_s:.1f}s)\n")
    if not p["kill_pass"]:
        print("KILLED at Stage 2."); return 0

    print("="*78); print("STAGE 3 — Grid"); print("="*78)
    GRID = {"vol_window": [30, 60, 90], "skip_days": [0, 21], "top_k": [2, 3, 5], "rebal_days": [21, 63]}
    s3 = stage_3_grid(closes, GRID)
    print(f"  combos={s3.payload['n_combos']}  ({s3.elapsed_s:.1f}s)")
    for r in s3.payload["top5"]:
        print(f"    Sh={r['sharpe']:.3f} CAGR={r['cagr']:.3f} DD={r['max_drawdown']:.3f} reb={r['trade_count']}  {r['params']}")
    best = s3.payload["best"]; print()
    if not s3.payload["best_kill_pass"]:
        print(f"KILLED at Stage 3 — best Sharpe {best['sharpe']:.3f} < 1.0."); return 0

    print("  Walk-forward OFR:")
    wf = stage_3b_walkforward(closes, best["params"])
    print(f"    folds={len(wf['folds'])}  OFR={wf['ofr']:.3f}  Gate2={'Y' if wf['gate2_pass'] else 'N'}\n")

    print("="*78); print("STAGE 4 — Confirmation bootstrap (n=200)"); print("="*78)
    s4 = stage_4_confirm(closes, best["params"], best["sharpe"])
    p = s4.payload
    print(f"  p5/p25/p50/p75/p95={p['sim_sharpe_p5']:.3f}/{p['sim_sharpe_p25']:.3f}/{p['sim_sharpe_p50']:.3f}/{p['sim_sharpe_p75']:.3f}/{p['sim_sharpe_p95']:.3f}")
    print(f"  ratio={p['ratio']:.3f}  verdict: {p['verdict']}  ({s4.elapsed_s:.1f}s)\n")

    print("="*78); print("STAGE 5 — Portfolio decision"); print("="*78)
    if p["verdict"] == "ROBUST" and wf["gate2_pass"]:
        print(f"  PORTFOLIO_READY (single-strategy) ✅")
        print(f"    Sharpe={best['sharpe']:.3f}  CAGR={best['cagr']:.3f}  MaxDD={best['max_drawdown']:.3f}  OFR={wf['ofr']:.3f}  ratio={p['ratio']:.3f}")
    else:
        reasons = []
        if not wf["gate2_pass"]: reasons.append(f"OFR={wf['ofr']:.3f} < 0.70")
        if p["verdict"] != "ROBUST": reasons.append(f"ratio={p['ratio']:.3f} < 0.65")
        print(f"  CONCENTRATION/NONE — {'; '.join(reasons)}")

    import json
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = _ROOT.parent / "reports" / f"xsec_lowvol_pipeline_{date_tag}.json"
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "variant": "xsec_lowvol",
        "universe": syms, "default_params": DEFAULT, "grid": {k: list(v) for k,v in GRID.items()},
        "stages": {"1_smoke": s1.payload, "2_fast_bootstrap": s2.payload,
                   "3_grid_top5": s3.payload["top5"], "3_grid_best": best,
                   "3b_walkforward": wf, "4_confirm_bootstrap": s4.payload},
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
