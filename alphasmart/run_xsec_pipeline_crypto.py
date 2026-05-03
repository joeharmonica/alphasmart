"""
Cross-sectional momentum on 9 crypto pairs — Phase 9 multi-universe.

Universe: BTC ETH SOL BNB XRP ADA AVAX DOGE LINK (vs USD), 1d, 5y (~1826 bars).

Crypto trades 7 days/week, but yfinance reports daily bars including weekends.
PERIODS_PER_YEAR = 365 (vs 252 for equities). Sharpe and CAGR scale accordingly.

Hypothesis: crypto has zero structural correlation to equities (the assets are
non-overlapping). Cross-sectional momentum across crypto sub-classes (BTC vs
ETH vs alt-L1s vs meme-coins) should produce a signal genuinely uncorrelated
with the equity strategies.

Caveat: crypto has higher autocorrelation (longer trends, sharper crashes) so
block-bootstrap block_size scaled to 30 (vs 20 for equities).
"""
from __future__ import annotations

import math, sys, time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.data.database import Database
from run_xsec_pipeline import run_xsec_momentum, synchronised_block_bootstrap, StageResult, DB_URL

CRYPTO_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
                  "ADA-USD", "AVAX-USD", "DOGE-USD", "LINK-USD"]
PERIODS_PER_YEAR = 365   # crypto = 7-day market
VOL_TARGET_ANNUAL = 0.20  # higher target for higher-vol asset class
VOL_PERIOD = 30
VOL_FLOOR = 0.10
MAX_LEVERAGE = 1.5


def vol_overlay_crypto(returns):
    out = returns.copy(); n = len(returns)
    for i in range(VOL_PERIOD, n):
        window = returns.iloc[i - VOL_PERIOD: i]
        std = float(window.std(ddof=1))
        realised = std * math.sqrt(PERIODS_PER_YEAR)
        denom = max(realised, VOL_FLOOR)
        scale = min(VOL_TARGET_ANNUAL / denom, MAX_LEVERAGE)
        out.iloc[i] = float(returns.iloc[i]) * scale
    return out


def metrics_crypto(returns, rebs):
    if returns.empty:
        return {"sharpe":0.0,"cagr":0.0,"max_drawdown":0.0,"trade_count":0}
    active = returns[returns != 0]
    if len(active) < 5:
        return {"sharpe":0.0,"cagr":0.0,"max_drawdown":0.0,"trade_count":rebs}
    mean = float(returns.mean()); std = float(returns.std(ddof=1))
    sharpe = (mean*PERIODS_PER_YEAR)/(std*math.sqrt(PERIODS_PER_YEAR)) if std > 0 else 0.0
    eq = (1+returns.fillna(0)).cumprod(); n = len(returns)
    cagr = float(eq.iloc[-1])**(PERIODS_PER_YEAR/n) - 1 if n > 0 and eq.iloc[-1] > 0 else 0.0
    dd = (eq/eq.cummax() - 1)
    return {"sharpe":float(sharpe),"cagr":float(cagr),"max_drawdown":float(abs(dd.min())),"trade_count":int(rebs)}


def run_crypto_momentum(closes, lookback_days, skip_days, top_k, rebal_days):
    rets, rebs = run_xsec_momentum(closes, lookback_days, skip_days, top_k, rebal_days)
    return vol_overlay_crypto(rets), rebs


def stage_3b_corrected(closes, best_p, is_years=2, oos_years=1, step_years=0.5):
    is_b, oos_b, step = int(is_years*PERIODS_PER_YEAR), int(oos_years*PERIODS_PER_YEAR), int(step_years*PERIODS_PER_YEAR)
    n = len(closes); folds = []; start = 0
    while start + is_b + oos_b <= n:
        combined = closes.iloc[start: start + is_b + oos_b]
        rets, _ = run_crypto_momentum(combined, **best_p)
        is_r = rets.iloc[:is_b]; oos_r = rets.iloc[is_b:]
        folds.append({"is_sharpe": metrics_crypto(is_r,0)["sharpe"], "oos_sharpe": metrics_crypto(oos_r,0)["sharpe"]})
        start += step
    valid = [f for f in folds if f["is_sharpe"] > 0]
    ofr = float(np.mean([max(0.0,f["oos_sharpe"])/f["is_sharpe"] for f in valid])) if valid else float("nan")
    return {"folds": folds, "ofr": ofr, "gate2_pass": ofr >= 0.70}


def main():
    db = Database(DB_URL)
    closes = pd.DataFrame({s: db.query_ohlcv(s, "1d")["close"] for s in CRYPTO_SYMBOLS}).dropna()
    print(f"Universe: {CRYPTO_SYMBOLS}")
    print(f"Aligned closes: {len(closes)} bars × {len(closes.columns)}, range {closes.index[0].date()} → {closes.index[-1].date()}\n")

    DEFAULT = dict(lookback_days=90, skip_days=0, top_k=3, rebal_days=14)

    print("="*78); print("STAGE 1 — Smoke (xsec crypto momentum)"); print("="*78)
    t0 = time.time()
    rets, rebs = run_crypto_momentum(closes, **DEFAULT); m = metrics_crypto(rets, rebs)
    kp = m["sharpe"] > 0 and m["max_drawdown"] < 0.40 and m["trade_count"] >= 30   # crypto MaxDD threshold relaxed to 40%
    print(f"  Sharpe={m['sharpe']:.3f}  CAGR={m['cagr']:.3f}  MaxDD={m['max_drawdown']:.3f}  rebs={m['trade_count']}  kill_pass={kp}  ({time.time()-t0:.1f}s)\n")
    if not kp: print("KILLED at Stage 1."); return 0

    print("="*78); print("STAGE 2 — Fast bootstrap (n=50, block_size=30)"); print("="*78)
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=50, block_size=30, seed=42)
    sh = []
    for sc in sims:
        full = pd.concat([closes.iloc[0:1], sc]).iloc[: len(closes)]; full.index = closes.index
        rr, rb = run_crypto_momentum(full, **DEFAULT); sh.append(metrics_crypto(rr, rb)["sharpe"])
    arr = np.array([s for s in sh if not np.isnan(s)])
    p25, med, p75 = np.percentile(arr, [25,50,75])
    ratio = float(med)/m["sharpe"] if m["sharpe"] > 0 else 0.0
    s2 = float(ratio) >= 0.4
    print(f"  p25/p50/p75={p25:.3f}/{med:.3f}/{p75:.3f}  ratio={ratio:.3f}  kill_pass={s2}  ({time.time()-t0:.1f}s)\n")
    if not s2: print("KILLED at Stage 2."); return 0

    print("="*78); print("STAGE 3 — Grid"); print("="*78)
    t0 = time.time()
    GRID = {"lookback_days": [30, 60, 90, 180], "skip_days": [0, 7], "top_k": [2, 3, 4], "rebal_days": [7, 14, 30]}
    rows = []
    for combo in product(*GRID.values()):
        params = dict(zip(GRID.keys(), combo))
        rr, rb = run_crypto_momentum(closes, **params); mm = metrics_crypto(rr, rb)
        rows.append({"params": params, **mm})
    rows.sort(key=lambda r: -r["sharpe"])
    print(f"  combos={len(rows)}  ({time.time()-t0:.1f}s)")
    for r in rows[:5]:
        print(f"    Sh={r['sharpe']:.3f} CAGR={r['cagr']:.3f} DD={r['max_drawdown']:.3f} reb={r['trade_count']}  {r['params']}")
    best = rows[0]; print()
    if best["sharpe"] < 1.0: print(f"KILLED at Stage 3 — best Sharpe {best['sharpe']:.3f} < 1.0."); return 0

    print("  Walk-forward OFR (corrected with IS+OOS warm-up):")
    wf = stage_3b_corrected(closes, best["params"])
    print(f"    folds={len(wf['folds'])}  OFR={wf['ofr']:.3f}  Gate2={'Y' if wf['gate2_pass'] else 'N'}")
    for i, f in enumerate(wf["folds"], 1):
        print(f"    fold{i}: IS={f['is_sharpe']:+.3f}  OOS={f['oos_sharpe']:+.3f}")
    print()

    print("="*78); print("STAGE 4 — Confirmation bootstrap (n=200)"); print("="*78)
    t0 = time.time()
    sims = synchronised_block_bootstrap(closes, n_sims=200, block_size=30, seed=7)
    sh = []
    for sc in sims:
        full = pd.concat([closes.iloc[0:1], sc]).iloc[: len(closes)]; full.index = closes.index
        rr, rb = run_crypto_momentum(full, **best["params"]); sh.append(metrics_crypto(rr, rb)["sharpe"])
    arr = np.array([s for s in sh if not np.isnan(s)])
    p5,p25,med,p75,p95 = np.percentile(arr, [5,25,50,75,95])
    ratio = float(med)/best["sharpe"] if best["sharpe"] > 0 else 0.0
    verdict = "ROBUST" if float(ratio) >= 0.65 else "FRAGILE"
    print(f"  p5/p25/p50/p75/p95={p5:.3f}/{p25:.3f}/{med:.3f}/{p75:.3f}/{p95:.3f}")
    print(f"  ratio={ratio:.3f}  verdict: {verdict}  ({time.time()-t0:.1f}s)\n")

    print("="*78); print("STAGE 5 — Portfolio decision"); print("="*78)
    if verdict == "ROBUST" and wf["gate2_pass"]:
        print(f"  PORTFOLIO_READY ✅  Sharpe={best['sharpe']:.3f}  CAGR={best['cagr']:.3f}  MaxDD={best['max_drawdown']:.3f}  OFR={wf['ofr']:.3f}  ratio={ratio:.3f}")
    else:
        reasons = []
        if not wf["gate2_pass"]: reasons.append(f"OFR={wf['ofr']:.3f} < 0.70")
        if verdict != "ROBUST": reasons.append(f"ratio={ratio:.3f} < 0.65")
        print(f"  CONCENTRATION/NONE — {'; '.join(reasons)}")

    import json
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = _ROOT.parent / "reports" / f"xsec_crypto_pipeline_{date_tag}.json"
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "variant": "xsec_momentum_crypto_9pairs",
        "universe": CRYPTO_SYMBOLS, "default_params": DEFAULT, "grid": {k: list(v) for k,v in GRID.items()},
        "stages": {
            "1_smoke": {"params": DEFAULT, "metrics": m, "kill_pass": kp},
            "2_fast_bootstrap": {"sim_p25": float(p25), "sim_p50": float(med), "sim_p75": float(p75), "ratio": float(ratio)},
            "3_grid_top5": rows[:5], "3_grid_best": best,
            "3b_walkforward": wf,
            "4_confirm_bootstrap": {"sim_p5": float(p5), "sim_p25": float(p25), "sim_p50": float(med),
                                     "sim_p75": float(p75), "sim_p95": float(p95), "ratio": float(ratio), "verdict": verdict},
        },
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
