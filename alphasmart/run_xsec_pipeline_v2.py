"""
Cross-sectional momentum v2 — addresses the Stage 1 kill from v1.

Two changes vs v1:
  1. Drop PLTR (IPO 2020) + CRWD (IPO 2019) — they gated the cross-section
     to 5.5 yr of overlapping data. Using 15 symbols × ~10 yr instead.
  2. Add a vol-targeting overlay on the portfolio's daily returns.
     Scale = min(target_vol / max(realized_vol, vol_floor), max_leverage)
     Realized vol from trailing 60-day window of portfolio returns.

Same 5-stage fail-fast pipeline as v1.
"""
from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.data.database import Database
from run_xsec_pipeline import (  # reuse infra
    run_xsec_momentum, compute_metrics, synchronised_block_bootstrap, StageResult,
    PERIODS_PER_YEAR, TIMEFRAME, DB_URL,
)

VOL_TARGET_ANNUAL = 0.15
VOL_PERIOD = 60          # bars
VOL_FLOOR = 0.05         # 5% annualised floor in denominator
MAX_LEVERAGE = 1.5
EXCLUDE_SYMBOLS = {"PLTR", "CRWD"}


def vol_target_overlay(returns: pd.Series) -> pd.Series:
    """Apply vol-targeting to a daily portfolio-return series.
    For each bar t, scale return[t] by min(target/realized, max_leverage)
    where realized is the std of the prior VOL_PERIOD bars (annualised)."""
    out = returns.copy()
    n = len(returns)
    for i in range(VOL_PERIOD, n):
        window = returns.iloc[i - VOL_PERIOD: i]
        std = float(window.std(ddof=1))
        realised = std * math.sqrt(PERIODS_PER_YEAR)
        denom = max(realised, VOL_FLOOR)
        scale = min(VOL_TARGET_ANNUAL / denom, MAX_LEVERAGE)
        out.iloc[i] = float(returns.iloc[i]) * scale
    # Pre-window: keep raw (no vol estimate yet). Reasonable default.
    return out


def run_xsec_momentum_voltarget(
    closes: pd.DataFrame,
    lookback_days: int, skip_days: int, top_k: int, rebal_days: int,
) -> tuple[pd.Series, int]:
    rets, rebs = run_xsec_momentum(closes, lookback_days, skip_days, top_k, rebal_days)
    return vol_target_overlay(rets), rebs


# ---- Stage helpers (reuse v1 with the new strategy fn) -----------------------

def _run_default(closes, params):
    rets, rebs = run_xsec_momentum_voltarget(closes, **params)
    return rets, rebs


def stage_1_smoke(closes, default_params):
    t0 = time.time()
    rets, rebs = _run_default(closes, default_params)
    m = compute_metrics(rets, rebs)
    return StageResult("1_smoke", time.time() - t0, {
        "params": default_params, "metrics": m,
        "kill_pass": m["sharpe"] > 0 and m["max_drawdown"] < 0.30 and m["trade_count"] >= 30,
    })


def stage_2_fast_bootstrap(closes, default_params, original_sharpe, n_sims=50):
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=n_sims, block_size=20, seed=42)
    sim_sharpes = []
    for sim_close in sims:
        full = pd.concat([closes.iloc[0:1], sim_close]).iloc[: len(closes)]
        full.index = closes.index
        rets, rebs = _run_default(full, default_params)
        m = compute_metrics(rets, rebs)
        sim_sharpes.append(m["sharpe"])
    arr = np.array([s for s in sim_sharpes if not np.isnan(s)])
    p25, med, p75 = (np.percentile(arr, [25, 50, 75]) if len(arr) else (np.nan, np.nan, np.nan))
    ratio = float(med) / original_sharpe if original_sharpe > 0 else 0.0
    return StageResult("2_fast_bootstrap", time.time() - t0, {
        "n_sims": len(arr),
        "sim_sharpe_p25": float(p25), "sim_sharpe_p50": float(med), "sim_sharpe_p75": float(p75),
        "ratio": float(ratio), "kill_pass": float(ratio) >= 0.4,
    })


def stage_3_grid(closes, grid):
    t0 = time.time()
    keys = list(grid.keys()); vals = list(grid.values())
    rows = []
    for combo in product(*vals):
        params = dict(zip(keys, combo))
        rets, rebs = _run_default(closes, params)
        m = compute_metrics(rets, rebs)
        rows.append({"params": params, **m})
    rows.sort(key=lambda r: -r["sharpe"])
    return StageResult("3_grid", time.time() - t0, {
        "n_combos": len(rows), "top5": rows[:5], "best": rows[0] if rows else None,
        "best_kill_pass": rows[0]["sharpe"] >= 1.0 if rows else False,
    })


def stage_3b_walkforward(closes, best_params, is_years=2, oos_years=1, step_years=0.5):
    is_bars = int(is_years * PERIODS_PER_YEAR)
    oos_bars = int(oos_years * PERIODS_PER_YEAR)
    step = int(step_years * PERIODS_PER_YEAR)
    n = len(closes)
    folds = []
    start = 0
    while start + is_bars + oos_bars <= n:
        is_close = closes.iloc[start: start + is_bars]
        oos_close = closes.iloc[start + is_bars: start + is_bars + oos_bars]
        is_rets, _ = _run_default(is_close, best_params)
        oos_rets, _ = _run_default(oos_close, best_params)
        is_m = compute_metrics(is_rets, 0)
        oos_m = compute_metrics(oos_rets, 0)
        folds.append({"is_sharpe": is_m["sharpe"], "oos_sharpe": oos_m["sharpe"]})
        start += step
    valid = [f for f in folds if f["is_sharpe"] > 0]
    ofr = float(np.mean([max(0.0, f["oos_sharpe"]) / f["is_sharpe"] for f in valid])) if valid else float("nan")
    return {"folds": folds, "ofr": ofr, "gate2_pass": ofr >= 0.70}


def stage_4_confirm_bootstrap(closes, best_params, original_sharpe, n_sims=200):
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=n_sims, block_size=20, seed=7)
    sim_sharpes = []
    for sim_close in sims:
        full = pd.concat([closes.iloc[0:1], sim_close]).iloc[: len(closes)]
        full.index = closes.index
        rets, rebs = _run_default(full, best_params)
        m = compute_metrics(rets, rebs)
        sim_sharpes.append(m["sharpe"])
    arr = np.array([s for s in sim_sharpes if not np.isnan(s)])
    p5, p25, med, p75, p95 = (np.percentile(arr, [5, 25, 50, 75, 95]) if len(arr) else (np.nan,)*5)
    ratio = float(med) / original_sharpe if original_sharpe > 0 else 0.0
    return StageResult("4_confirm_bootstrap", time.time() - t0, {
        "n_sims": len(arr),
        "sim_sharpe_p5": float(p5), "sim_sharpe_p25": float(p25), "sim_sharpe_p50": float(med),
        "sim_sharpe_p75": float(p75), "sim_sharpe_p95": float(p95),
        "ratio": float(ratio),
        "verdict": "ROBUST" if float(ratio) >= 0.65 else "FRAGILE",
    })


def main():
    db = Database(DB_URL)
    rows = db.fetch_status()
    all_syms = sorted({r["symbol"] for r in rows if r["timeframe"] == TIMEFRAME and "-" not in r["symbol"]})
    symbols = [s for s in all_syms if s not in EXCLUDE_SYMBOLS]
    data_by_symbol = {s: db.query_ohlcv(s, TIMEFRAME) for s in symbols}
    print(f"Universe (excluding {EXCLUDE_SYMBOLS}): {len(symbols)} symbols")
    closes = pd.DataFrame({s: df["close"] for s, df in data_by_symbol.items()}).dropna()
    print(f"Aligned closes: {len(closes)} bars × {len(closes.columns)} assets, "
          f"range {closes.index[0].date()} → {closes.index[-1].date()}\n")

    DEFAULT = dict(lookback_days=252, skip_days=21, top_k=3, rebal_days=21)

    print("="*78); print("STAGE 1 — Smoke screen (vol-targeted, 15-sym 10-yr)"); print("="*78)
    s1 = stage_1_smoke(closes, DEFAULT)
    m = s1.payload["metrics"]
    print(f"  Sharpe={m['sharpe']:.3f}  CAGR={m['cagr']:.3f}  MaxDD={m['max_drawdown']:.3f}  rebalances={m['trade_count']}")
    print(f"  kill_pass: {s1.payload['kill_pass']}  ({s1.elapsed_s:.1f}s)\n")
    if not s1.payload["kill_pass"]:
        print("KILLED at Stage 1.")
        return 0

    print("="*78); print("STAGE 2 — Fast bootstrap (n=50)"); print("="*78)
    s2 = stage_2_fast_bootstrap(closes, DEFAULT, m["sharpe"], n_sims=50)
    p = s2.payload
    print(f"  sims={p['n_sims']}  p25/p50/p75={p['sim_sharpe_p25']:.3f}/{p['sim_sharpe_p50']:.3f}/{p['sim_sharpe_p75']:.3f}")
    print(f"  ratio={p['ratio']:.3f}  kill_pass(≥0.4): {p['kill_pass']}  ({s2.elapsed_s:.1f}s)\n")
    if not p["kill_pass"]:
        print("KILLED at Stage 2.")
        return 0

    print("="*78); print("STAGE 3 — Grid optimization"); print("="*78)
    GRID = {
        "lookback_days": [126, 189, 252],
        "skip_days":     [0, 21],
        "top_k":         [2, 3, 5],
        "rebal_days":    [21, 63],
    }
    s3 = stage_3_grid(closes, GRID)
    print(f"  combos={s3.payload['n_combos']}  ({s3.elapsed_s:.1f}s)")
    for r in s3.payload["top5"]:
        print(f"    Sh={r['sharpe']:.3f} CAGR={r['cagr']:.3f} DD={r['max_drawdown']:.3f} reb={r['trade_count']}  {r['params']}")
    best = s3.payload["best"]
    print()
    if not s3.payload["best_kill_pass"]:
        print(f"KILLED at Stage 3 — best Sharpe {best['sharpe']:.3f} < 1.0.")
        return 0

    print("  Walk-forward OFR on best params:")
    wf = stage_3b_walkforward(closes, best["params"])
    print(f"    folds={len(wf['folds'])}  OFR={wf['ofr']:.3f}  Gate2={'Y' if wf['gate2_pass'] else 'N'}")
    for i, f in enumerate(wf["folds"], 1):
        print(f"    fold{i}: IS={f['is_sharpe']:+.3f}  OOS={f['oos_sharpe']:+.3f}")
    print()

    print("="*78); print("STAGE 4 — Confirmation bootstrap (n=200)"); print("="*78)
    s4 = stage_4_confirm_bootstrap(closes, best["params"], best["sharpe"], n_sims=200)
    p = s4.payload
    print(f"  p5/p25/p50/p75/p95={p['sim_sharpe_p5']:.3f}/{p['sim_sharpe_p25']:.3f}/{p['sim_sharpe_p50']:.3f}/{p['sim_sharpe_p75']:.3f}/{p['sim_sharpe_p95']:.3f}")
    print(f"  ratio={p['ratio']:.3f}  verdict: {p['verdict']}  ({s4.elapsed_s:.1f}s)\n")

    print("="*78); print("STAGE 5 — Portfolio decision"); print("="*78)
    if p["verdict"] == "ROBUST" and wf["gate2_pass"]:
        print(f"  PORTFOLIO_READY (single-strategy) ✅")
        print(f"    Sharpe={best['sharpe']:.3f}  CAGR={best['cagr']:.3f}  MaxDD={best['max_drawdown']:.3f}")
        print(f"    OFR={wf['ofr']:.3f}  bootstrap_ratio={p['ratio']:.3f}")
    else:
        reasons = []
        if not wf["gate2_pass"]: reasons.append(f"OFR={wf['ofr']:.3f} < 0.70")
        if p["verdict"] != "ROBUST": reasons.append(f"bootstrap ratio={p['ratio']:.3f} < 0.65")
        print(f"  CONCENTRATION/NONE — {'; '.join(reasons)}")

    import json
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = _ROOT.parent / "reports" / f"xsec_momentum_pipeline_v2_{date_tag}.json"
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "variant": "v2: voltarget + drop PLTR/CRWD",
        "universe": symbols,
        "default_params": DEFAULT,
        "grid": {k: list(v) for k, v in GRID.items()},
        "stages": {
            "1_smoke": s1.payload, "2_fast_bootstrap": s2.payload,
            "3_grid_top5": s3.payload["top5"], "3_grid_best": best,
            "3b_walkforward": wf, "4_confirm_bootstrap": s4.payload,
        },
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
