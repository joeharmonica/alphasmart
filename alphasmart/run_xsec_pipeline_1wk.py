"""
Cross-sectional momentum on 17-symbol 1wk universe.

We have 17 symbols on 1wk after the previous fetch. Aligned cross-section
should be ~261 weekly bars (5 yr) when all 17 are required, or longer if
we drop the IPO-newcomers (PLTR, CRWD).

Bar-count parameters scaled by 1/5 from the 1d defaults (1 week ≈ 5 trading days):
  lookback_days=126 (1d) → 25 weeks (1wk)
  rebal_days=21 (1d)    → 4 weeks (1wk)
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
from run_xsec_pipeline import run_xsec_momentum, compute_metrics, synchronised_block_bootstrap, StageResult, DB_URL
from run_xsec_pipeline_v2 import vol_target_overlay, EXCLUDE_SYMBOLS

TIMEFRAME = "1wk"
PERIODS_PER_YEAR = 52


def _vol_overlay(returns):
    """vol-target overlay scaled for weekly bars (52 periods/yr instead of 252)."""
    import math
    out = returns.copy()
    n = len(returns)
    VOL_PERIOD_WK = 12   # ~3 months of weekly bars
    VOL_TARGET_ANNUAL = 0.15
    VOL_FLOOR = 0.05
    MAX_LEVERAGE = 1.5
    for i in range(VOL_PERIOD_WK, n):
        window = returns.iloc[i - VOL_PERIOD_WK: i]
        std = float(window.std(ddof=1))
        realised = std * math.sqrt(PERIODS_PER_YEAR)
        denom = max(realised, VOL_FLOOR)
        scale = min(VOL_TARGET_ANNUAL / denom, MAX_LEVERAGE)
        out.iloc[i] = float(returns.iloc[i]) * scale
    return out


def _wk_metrics(returns: pd.Series, rebs: int) -> dict:
    """Weekly-aware metrics — same as compute_metrics but with periods=52."""
    import math
    if returns.empty:
        return {"sharpe": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "trade_count": 0}
    active = returns[returns != 0]
    if len(active) < 5:
        return {"sharpe": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "trade_count": rebs}
    mean = float(returns.mean()); std = float(returns.std(ddof=1))
    sharpe = (mean * PERIODS_PER_YEAR) / (std * math.sqrt(PERIODS_PER_YEAR)) if std > 0 else 0.0
    eq = (1 + returns.fillna(0)).cumprod()
    n = len(returns)
    cagr = float(eq.iloc[-1]) ** (PERIODS_PER_YEAR / n) - 1 if n > 0 and eq.iloc[-1] > 0 else 0.0
    drawdown = (eq / eq.cummax() - 1)
    return {"sharpe": float(sharpe), "cagr": float(cagr),
            "max_drawdown": float(abs(drawdown.min())), "trade_count": int(rebs)}


def run_xsec_momentum_wk(closes, lookback_weeks, skip_weeks, top_k, rebal_weeks):
    """Cross-sectional momentum on weekly bars with weekly vol-target."""
    rets, rebs = run_xsec_momentum(closes, lookback_days=lookback_weeks, skip_days=skip_weeks,
                                    top_k=top_k, rebal_days=rebal_weeks)
    return _vol_overlay(rets), rebs


def main():
    db = Database(DB_URL)
    rows = db.fetch_status()
    all_syms = sorted({r["symbol"] for r in rows if r["timeframe"] == TIMEFRAME and "-" not in r["symbol"]})
    syms = [s for s in all_syms if s not in EXCLUDE_SYMBOLS]
    closes_full = pd.DataFrame({s: db.query_ohlcv(s, TIMEFRAME)["close"] for s in syms}).dropna()
    print(f"Universe: {len(syms)} symbols (excluded {EXCLUDE_SYMBOLS})")
    print(f"Aligned closes: {len(closes_full)} bars × {len(closes_full.columns)} assets, "
          f"range {closes_full.index[0].date()} → {closes_full.index[-1].date()}\n")

    DEFAULT = dict(lookback_weeks=25, skip_weeks=0, top_k=5, rebal_weeks=4)

    # Stage 1
    print("="*78); print("STAGE 1 — Smoke (1wk xsec momentum)"); print("="*78)
    t0 = time.time()
    rets, rebs = run_xsec_momentum_wk(closes_full, **DEFAULT); m = _wk_metrics(rets, rebs)
    kill_pass = m["sharpe"] > 0 and m["max_drawdown"] < 0.30 and m["trade_count"] >= 30
    print(f"  Sharpe={m['sharpe']:.3f}  CAGR={m['cagr']:.3f}  MaxDD={m['max_drawdown']:.3f}  rebs={m['trade_count']}  kill_pass={kill_pass}  ({time.time()-t0:.1f}s)\n")
    if not kill_pass:
        print("KILLED at Stage 1."); return 0

    # Stage 2
    print("="*78); print("STAGE 2 — Fast bootstrap (n=50)"); print("="*78)
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes_full, n_sims=50, block_size=8, seed=42)
    sh = []
    for sc in sims:
        full = pd.concat([closes_full.iloc[0:1], sc]).iloc[: len(closes_full)]; full.index = closes_full.index
        rr, rb = run_xsec_momentum_wk(full, **DEFAULT); sh.append(_wk_metrics(rr, rb)["sharpe"])
    arr = np.array([s for s in sh if not np.isnan(s)])
    p25, med, p75 = np.percentile(arr, [25,50,75])
    ratio = float(med)/m["sharpe"] if m["sharpe"] > 0 else 0.0
    s2_pass = float(ratio) >= 0.4
    print(f"  p25/p50/p75={p25:.3f}/{med:.3f}/{p75:.3f}  ratio={ratio:.3f}  kill_pass={s2_pass}  ({time.time()-t0:.1f}s)\n")
    if not s2_pass:
        print("KILLED at Stage 2."); return 0

    # Stage 3
    print("="*78); print("STAGE 3 — Grid"); print("="*78)
    t0 = time.time()
    GRID = {"lookback_weeks": [13, 25, 39], "skip_weeks": [0, 4], "top_k": [2, 3, 5], "rebal_weeks": [4, 13]}
    rows_out = []
    for combo in product(*GRID.values()):
        params = dict(zip(GRID.keys(), combo))
        rr, rb = run_xsec_momentum_wk(closes_full, **params); mm = _wk_metrics(rr, rb)
        rows_out.append({"params": params, **mm})
    rows_out.sort(key=lambda r: -r["sharpe"])
    print(f"  combos={len(rows_out)}  ({time.time()-t0:.1f}s)")
    for r in rows_out[:5]:
        print(f"    Sh={r['sharpe']:.3f} CAGR={r['cagr']:.3f} DD={r['max_drawdown']:.3f} reb={r['trade_count']}  {r['params']}")
    best = rows_out[0]; print()
    if best["sharpe"] < 1.0:
        print(f"KILLED at Stage 3 — best Sharpe {best['sharpe']:.3f} < 1.0."); return 0

    # Stage 3b walk-forward (3 folds on ~5y weekly)
    print("  Walk-forward OFR:")
    is_b = 2*PERIODS_PER_YEAR; oos_b = PERIODS_PER_YEAR; step = PERIODS_PER_YEAR // 2
    n = len(closes_full); folds = []; start = 0
    while start + is_b + oos_b <= n:
        is_c = closes_full.iloc[start: start+is_b]; oos_c = closes_full.iloc[start+is_b: start+is_b+oos_b]
        is_r,_ = run_xsec_momentum_wk(is_c, **best["params"]); oos_r,_ = run_xsec_momentum_wk(oos_c, **best["params"])
        folds.append({"is_sharpe": _wk_metrics(is_r,0)["sharpe"], "oos_sharpe": _wk_metrics(oos_r,0)["sharpe"]})
        start += step
    valid = [f for f in folds if f["is_sharpe"] > 0]
    ofr = float(np.mean([max(0.0,f["oos_sharpe"])/f["is_sharpe"] for f in valid])) if valid else float("nan")
    g2 = ofr >= 0.70
    print(f"    folds={len(folds)}  OFR={ofr:.3f}  Gate2={'Y' if g2 else 'N'}\n")

    # Stage 4
    print("="*78); print("STAGE 4 — Confirmation bootstrap (n=200)"); print("="*78)
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes_full, n_sims=200, block_size=8, seed=7)
    sh = []
    for sc in sims:
        full = pd.concat([closes_full.iloc[0:1], sc]).iloc[: len(closes_full)]; full.index = closes_full.index
        rr, rb = run_xsec_momentum_wk(full, **best["params"]); sh.append(_wk_metrics(rr, rb)["sharpe"])
    arr = np.array([s for s in sh if not np.isnan(s)])
    p5,p25,med,p75,p95 = np.percentile(arr, [5,25,50,75,95])
    ratio = float(med)/best["sharpe"] if best["sharpe"] > 0 else 0.0
    verdict = "ROBUST" if float(ratio) >= 0.65 else "FRAGILE"
    print(f"  p5/p25/p50/p75/p95={p5:.3f}/{p25:.3f}/{med:.3f}/{p75:.3f}/{p95:.3f}")
    print(f"  ratio={ratio:.3f}  verdict: {verdict}  ({time.time()-t0:.1f}s)\n")

    # Stage 5
    print("="*78); print("STAGE 5 — Portfolio decision"); print("="*78)
    if verdict == "ROBUST" and g2:
        print(f"  PORTFOLIO_READY ✅  Sharpe={best['sharpe']:.3f}  CAGR={best['cagr']:.3f}  MaxDD={best['max_drawdown']:.3f}  OFR={ofr:.3f}  ratio={ratio:.3f}")
    else:
        reasons = []
        if not g2: reasons.append(f"OFR={ofr:.3f} < 0.70")
        if verdict != "ROBUST": reasons.append(f"ratio={ratio:.3f} < 0.65")
        print(f"  CONCENTRATION/NONE — {'; '.join(reasons)}")

    # Persist
    import json
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = _ROOT.parent / "reports" / f"xsec_momentum_pipeline_1wk_{date_tag}.json"
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "variant": "xsec_momentum_1wk_15sym",
        "universe": syms, "default_params": DEFAULT, "grid": {k: list(v) for k,v in GRID.items()},
        "stages": {
            "1_smoke": {"params": DEFAULT, "metrics": m, "kill_pass": kill_pass},
            "2_fast_bootstrap": {"sim_p25": float(p25), "sim_p50": float(med), "sim_p75": float(p75), "ratio": float(ratio)},
            "3_grid_top5": rows_out[:5], "3_grid_best": best,
            "3b_walkforward": {"folds": folds, "ofr": ofr, "gate2_pass": g2},
            "4_confirm_bootstrap": {"sim_p5": float(p5), "sim_p25": float(p25), "sim_p50": float(med),
                                     "sim_p75": float(p75), "sim_p95": float(p95), "ratio": float(ratio), "verdict": verdict},
        },
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
