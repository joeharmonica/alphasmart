"""
Cross-sectional momentum — 5-stage fail-fast pipeline (implementation_plan_v2 §3).

This is the first execution of the v2 plan. It tests Tier A #1
(cross-sectional 12-1 momentum, long top-K, monthly rebalance) on the
17-symbol 10-yr daily universe, running all 5 stages sequentially with
explicit kill gates.

Stage 0 — Compatibility check (instant)
Stage 1 — Coarse smoke screen: 1 backtest at default params
Stage 2 — Fast bootstrap (n=50) at default params
Stage 3 — Grid optimization across (lookback, skip, top_k, rebal_freq)
Stage 4 — Confirmation bootstrap (n=200) on best params
Stage 5 — Portfolio decision (degenerate for a single strategy class — verdict is binary)

Pre-registered kill criteria (per implementation_plan_v2 §6.2):
  Hypothesis: cross-sectional 12-1 momentum on 17-sym 10-yr 1d will produce
              ≥ 1 ROBUST passer (bootstrap ratio ≥ 0.65).
  Stage 1 kill: original Sharpe < 0 OR MaxDD > 30% OR rebal_count < 30
  Stage 2 kill: bootstrap ratio < 0.4 (vs final cutoff 0.65)
  Stage 3 kill: best Sharpe < 1.0 OR best OFR < 0.5 (relaxed)
  Success: best params clear Stage 4 with ratio ≥ 0.65
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

DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
TIMEFRAME = "1d"
PERIODS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Strategy: cross-sectional momentum
# ---------------------------------------------------------------------------

def run_xsec_momentum(
    closes: pd.DataFrame,
    lookback_days: int,
    skip_days: int,
    top_k: int,
    rebal_days: int,
) -> tuple[pd.Series, int]:
    """
    Long top-K assets by trailing (close[t-skip] / close[t-skip-lookback] - 1).
    Equal-weighted, rebalance every rebal_days.

    Returns: (daily_portfolio_returns_series, rebalance_count)
    """
    n_bars, n_assets = closes.shape
    if n_bars <= lookback_days + skip_days:
        return pd.Series(dtype=float), 0

    returns = closes.pct_change()
    portfolio_returns = pd.Series(0.0, index=closes.index)
    held: list[str] = []
    rebalances = 0

    start = lookback_days + skip_days
    for i in range(start, n_bars):
        if (i - start) % rebal_days == 0 or not held:
            past_window = closes.iloc[i - skip_days - lookback_days : i - skip_days]
            anchor = past_window.iloc[0]
            tip = closes.iloc[i - skip_days] if skip_days > 0 else closes.iloc[i]
            valid = anchor.notna() & tip.notna() & (anchor > 0)
            if valid.sum() >= top_k:
                trailing = (tip[valid] / anchor[valid]) - 1.0
                held = trailing.nlargest(top_k).index.tolist()
                rebalances += 1
            # else: keep prior `held`

        if held:
            day_rets = returns.iloc[i][held].dropna()
            if len(day_rets) > 0:
                portfolio_returns.iloc[i] = float(day_rets.mean())

    return portfolio_returns, rebalances


def compute_metrics(returns: pd.Series, rebalances: int) -> dict:
    """Subset of the standard metrics, sufficient for the pipeline gates."""
    if returns.empty:
        return {"sharpe": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "trade_count": 0}

    active = returns[returns != 0]
    if len(active) < 5:
        return {"sharpe": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "trade_count": rebalances}

    mean = float(returns.mean())
    std = float(returns.std(ddof=1))
    sharpe = (mean * PERIODS_PER_YEAR) / (std * math.sqrt(PERIODS_PER_YEAR)) if std > 0 else 0.0

    eq = (1 + returns.fillna(0)).cumprod()
    n = len(returns)
    cagr = float(eq.iloc[-1]) ** (PERIODS_PER_YEAR / n) - 1 if n > 0 and eq.iloc[-1] > 0 else 0.0
    drawdown = (eq / eq.cummax() - 1)
    max_dd = float(abs(drawdown.min()))

    return {
        "sharpe": float(sharpe),
        "cagr": float(cagr),
        "max_drawdown": max_dd,
        "trade_count": int(rebalances),
    }


# ---------------------------------------------------------------------------
# Synchronised block bootstrap (cross-asset correlation preserved)
# ---------------------------------------------------------------------------

def synchronised_block_bootstrap(
    closes: pd.DataFrame,
    n_sims: int,
    block_size: int = 20,
    seed: Optional[int] = None,
) -> list[pd.DataFrame]:
    rng = np.random.default_rng(seed)
    log_returns = np.log(closes / closes.shift(1)).dropna(how="all")
    n = len(log_returns)
    if n < block_size * 2:
        block_size = max(1, n // 10)
    n_blocks = math.ceil(n / block_size)

    sims = []
    for _ in range(n_sims):
        starts = rng.integers(0, n, size=n_blocks)
        rows = []
        for s in starts:
            e = s + block_size
            if e <= n:
                rows.append(log_returns.iloc[s:e].values)
            else:
                rows.append(np.vstack([log_returns.iloc[s:].values,
                                       log_returns.iloc[: e - n].values]))
        arr = np.vstack(rows)[:n]
        sim_log = pd.DataFrame(arr, columns=closes.columns, index=log_returns.index)
        sim_close = closes.iloc[0:1].values * np.exp(sim_log.cumsum())
        sim_close = pd.DataFrame(sim_close, columns=closes.columns, index=log_returns.index)
        sims.append(sim_close)
    return sims


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    stage: str
    elapsed_s: float
    payload: dict


def stage_0_compat(symbols: list[str], data_by_symbol: dict) -> StageResult:
    t0 = time.time()
    bar_counts = {s: len(df) for s, df in data_by_symbol.items()}
    short = [s for s, n in bar_counts.items() if n < 252 * 3]  # need ≥ 3 yr
    return StageResult("0_compat", time.time() - t0, {
        "n_symbols": len(symbols),
        "bar_counts": bar_counts,
        "dropped_too_short": short,
    })


def stage_1_smoke(closes: pd.DataFrame, default_params: dict) -> StageResult:
    t0 = time.time()
    rets, rebs = run_xsec_momentum(closes, **default_params)
    m = compute_metrics(rets, rebs)
    return StageResult("1_smoke", time.time() - t0, {
        "params": default_params,
        "metrics": m,
        "kill_pass": m["sharpe"] > 0 and m["max_drawdown"] < 0.30 and m["trade_count"] >= 30,
    })


def stage_2_fast_bootstrap(closes: pd.DataFrame, default_params: dict, original_sharpe: float, n_sims: int = 50) -> StageResult:
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=n_sims, block_size=20, seed=42)
    sim_sharpes = []
    for sim_close in sims:
        # synthetic close needs the dropped first row reattached for run_xsec
        full = pd.concat([closes.iloc[0:1], sim_close]).iloc[: len(closes)]
        full.index = closes.index
        rets, rebs = run_xsec_momentum(full, **default_params)
        m = compute_metrics(rets, rebs)
        sim_sharpes.append(m["sharpe"])
    arr = np.array([s for s in sim_sharpes if not np.isnan(s)])
    p25, med, p75 = (np.percentile(arr, [25, 50, 75]) if len(arr) else (np.nan, np.nan, np.nan))
    ratio = float(med) / original_sharpe if original_sharpe > 0 else 0.0
    return StageResult("2_fast_bootstrap", time.time() - t0, {
        "n_sims": len(arr),
        "sim_sharpe_p25": float(p25), "sim_sharpe_p50": float(med), "sim_sharpe_p75": float(p75),
        "ratio": float(ratio),
        "kill_pass": float(ratio) >= 0.4,
    })


def stage_3_grid(closes: pd.DataFrame, grid: dict) -> StageResult:
    t0 = time.time()
    keys = list(grid.keys()); vals = list(grid.values())
    rows = []
    for combo in product(*vals):
        params = dict(zip(keys, combo))
        rets, rebs = run_xsec_momentum(closes, **params)
        m = compute_metrics(rets, rebs)
        rows.append({"params": params, **m})
    rows.sort(key=lambda r: -r["sharpe"])
    return StageResult("3_grid", time.time() - t0, {
        "n_combos": len(rows),
        "top5": rows[:5],
        "best": rows[0] if rows else None,
        "best_kill_pass": rows[0]["sharpe"] >= 1.0 if rows else False,
    })


def stage_3b_walkforward(closes: pd.DataFrame, best_params: dict, is_years=2, oos_years=1, step_years=0.5) -> dict:
    """Quick walk-forward OFR for the chosen params (skip the full grid per fold for speed —
    we already optimized; this measures stability of *fixed* params across folds)."""
    is_bars = int(is_years * PERIODS_PER_YEAR)
    oos_bars = int(oos_years * PERIODS_PER_YEAR)
    step = int(step_years * PERIODS_PER_YEAR)
    n = len(closes)
    folds = []
    start = 0
    while start + is_bars + oos_bars <= n:
        is_close = closes.iloc[start: start + is_bars]
        oos_close = closes.iloc[start + is_bars: start + is_bars + oos_bars]
        is_rets, _ = run_xsec_momentum(is_close, **best_params)
        oos_rets, _ = run_xsec_momentum(oos_close, **best_params)
        is_m = compute_metrics(is_rets, 0)
        oos_m = compute_metrics(oos_rets, 0)
        folds.append({"is_sharpe": is_m["sharpe"], "oos_sharpe": oos_m["sharpe"]})
        start += step
    valid = [f for f in folds if f["is_sharpe"] > 0]
    if valid:
        ratios = [max(0.0, f["oos_sharpe"]) / f["is_sharpe"] for f in valid]
        ofr = float(np.mean(ratios))
    else:
        ofr = float("nan")
    return {"folds": folds, "ofr": ofr, "gate2_pass": ofr >= 0.70}


def stage_4_confirm_bootstrap(closes: pd.DataFrame, best_params: dict, original_sharpe: float, n_sims: int = 200) -> StageResult:
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=n_sims, block_size=20, seed=7)
    sim_sharpes = []
    for sim_close in sims:
        full = pd.concat([closes.iloc[0:1], sim_close]).iloc[: len(closes)]
        full.index = closes.index
        rets, rebs = run_xsec_momentum(full, **best_params)
        m = compute_metrics(rets, rebs)
        sim_sharpes.append(m["sharpe"])
    arr = np.array([s for s in sim_sharpes if not np.isnan(s)])
    p5, p25, med, p75, p95 = np.percentile(arr, [5, 25, 50, 75, 95]) if len(arr) else (np.nan,)*5
    ratio = float(med) / original_sharpe if original_sharpe > 0 else 0.0
    return StageResult("4_confirm_bootstrap", time.time() - t0, {
        "n_sims": len(arr),
        "sim_sharpe_p5": float(p5), "sim_sharpe_p25": float(p25), "sim_sharpe_p50": float(med),
        "sim_sharpe_p75": float(p75), "sim_sharpe_p95": float(p95),
        "ratio": float(ratio),
        "verdict": "ROBUST" if float(ratio) >= 0.65 else "FRAGILE",
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    db = Database(DB_URL)
    rows = db.fetch_status()
    symbols = sorted({r["symbol"] for r in rows if r["timeframe"] == TIMEFRAME and "-" not in r["symbol"]})  # exclude pair synthetics
    data_by_symbol = {s: db.query_ohlcv(s, TIMEFRAME) for s in symbols}
    print(f"Universe: {len(symbols)} symbols on {TIMEFRAME}")
    for s in symbols:
        print(f"  {s:6} bars={len(data_by_symbol[s]):>5}  range={data_by_symbol[s].index[0].date()} → {data_by_symbol[s].index[-1].date()}")
    print()

    # Align on common date range (intersection of all symbols)
    closes = pd.DataFrame({s: df["close"] for s, df in data_by_symbol.items()})
    closes = closes.dropna()  # only dates where ALL assets have data
    print(f"Aligned closes: {len(closes)} bars × {len(closes.columns)} assets, "
          f"range {closes.index[0].date()} → {closes.index[-1].date()}\n")

    # Default params: classic 12-1 momentum, top-3, monthly rebalance
    DEFAULT = dict(lookback_days=252, skip_days=21, top_k=3, rebal_days=21)

    print("="*78); print("STAGE 0 — Compatibility"); print("="*78)
    s0 = stage_0_compat(symbols, data_by_symbol)
    print(f"  symbols: {s0.payload['n_symbols']}, dropped: {s0.payload['dropped_too_short'] or 'none'}  ({s0.elapsed_s:.1f}s)\n")

    print("="*78); print("STAGE 1 — Smoke screen (default params)"); print("="*78)
    s1 = stage_1_smoke(closes, DEFAULT)
    m = s1.payload["metrics"]
    print(f"  params: {DEFAULT}")
    print(f"  Sharpe={m['sharpe']:.3f}  CAGR={m['cagr']:.3f}  MaxDD={m['max_drawdown']:.3f}  rebalances={m['trade_count']}")
    print(f"  kill_pass: {s1.payload['kill_pass']}  ({s1.elapsed_s:.1f}s)\n")
    if not s1.payload["kill_pass"]:
        print("KILLED at Stage 1 — strategy fails smoke screen.")
        return 0

    print("="*78); print("STAGE 2 — Fast bootstrap (n=50, default params)"); print("="*78)
    s2 = stage_2_fast_bootstrap(closes, DEFAULT, m["sharpe"], n_sims=50)
    p = s2.payload
    print(f"  sims={p['n_sims']}  sim_p25/p50/p75={p['sim_sharpe_p25']:.3f}/{p['sim_sharpe_p50']:.3f}/{p['sim_sharpe_p75']:.3f}")
    print(f"  ratio={p['ratio']:.3f}  kill_pass(≥0.4): {p['kill_pass']}  ({s2.elapsed_s:.1f}s)\n")
    if not p["kill_pass"]:
        print("KILLED at Stage 2 — bootstrap-fragile at default params.")
        return 0

    print("="*78); print("STAGE 3 — Grid optimization"); print("="*78)
    GRID = {
        "lookback_days": [126, 189, 252],   # 6m, 9m, 12m
        "skip_days":     [0, 21],            # 0m, 1m
        "top_k":         [2, 3, 5],
        "rebal_days":    [21, 63],           # monthly, quarterly
    }
    s3 = stage_3_grid(closes, GRID)
    print(f"  combos={s3.payload['n_combos']}  ({s3.elapsed_s:.1f}s)")
    print(f"  Top 5:")
    for r in s3.payload["top5"]:
        print(f"    Sh={r['sharpe']:.3f} CAGR={r['cagr']:.3f} DD={r['max_drawdown']:.3f} reb={r['trade_count']}  params={r['params']}")
    best = s3.payload["best"]
    print()
    if not s3.payload["best_kill_pass"]:
        print(f"KILLED at Stage 3 — best Sharpe {best['sharpe']:.3f} < 1.0.")
        return 0

    # Walk-forward stability check on best params
    print("  Walk-forward OFR on best params:")
    wf = stage_3b_walkforward(closes, best["params"])
    print(f"    folds={len(wf['folds'])}  OFR={wf['ofr']:.3f}  Gate2={'Y' if wf['gate2_pass'] else 'N'}")
    for i, f in enumerate(wf["folds"], 1):
        print(f"    fold{i}: IS={f['is_sharpe']:+.3f}  OOS={f['oos_sharpe']:+.3f}")
    print()

    print("="*78); print("STAGE 4 — Confirmation bootstrap (n=200)"); print("="*78)
    s4 = stage_4_confirm_bootstrap(closes, best["params"], best["sharpe"], n_sims=200)
    p = s4.payload
    print(f"  sims={p['n_sims']}  p5/p25/p50/p75/p95={p['sim_sharpe_p5']:.3f}/{p['sim_sharpe_p25']:.3f}/{p['sim_sharpe_p50']:.3f}/{p['sim_sharpe_p75']:.3f}/{p['sim_sharpe_p95']:.3f}")
    print(f"  ratio={p['ratio']:.3f}  verdict: {p['verdict']}  ({s4.elapsed_s:.1f}s)\n")

    print("="*78); print("STAGE 5 — Portfolio decision"); print("="*78)
    if p["verdict"] == "ROBUST" and wf["gate2_pass"]:
        print(f"  PORTFOLIO_READY (single-strategy): cross-sectional momentum")
        print(f"    Sharpe={best['sharpe']:.3f}  CAGR={best['cagr']:.3f}  MaxDD={best['max_drawdown']:.3f}")
        print(f"    OFR={wf['ofr']:.3f}  bootstrap_ratio={p['ratio']:.3f}")
    else:
        reasons = []
        if not wf["gate2_pass"]: reasons.append(f"OFR={wf['ofr']:.3f} < 0.70")
        if p["verdict"] != "ROBUST": reasons.append(f"bootstrap ratio={p['ratio']:.3f} < 0.65")
        print(f"  CONCENTRATION/NONE — {'; '.join(reasons)}")

    # Persist results for record
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = _ROOT.parent / "reports" / f"xsec_momentum_pipeline_{date_tag}.json"
    import json
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "universe": symbols,
        "default_params": DEFAULT,
        "grid": {k: list(v) for k, v in GRID.items()},
        "stages": {
            "0_compat": s0.payload,
            "1_smoke": s1.payload,
            "2_fast_bootstrap": s2.payload,
            "3_grid_top5": s3.payload["top5"],
            "3_grid_best": best,
            "3b_walkforward": wf,
            "4_confirm_bootstrap": s4.payload,
        },
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
