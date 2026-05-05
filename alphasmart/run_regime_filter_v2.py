"""
Regime filter v2 — soft layer + breadth + stress-test failure modes.

Variants tested (all on equity xsec momentum + crypto xsec momentum):
  A — Unfiltered (baseline)
  B — Binary 200d-MA on bellwether (SPY for equity, BTC for crypto)
  C — Soft 200d-MA: linear ramp from 0 (at 95% of MA) to 1 (at 105% of MA)
  D — Binary breadth: > 50% of universe above own 200d-MA
  E — Combined binary: price > 200d-MA AND breadth > 50%
  F — Soft combined: soft-price * soft-breadth (both ramped)

Stress sub-periods:
  - 2018 full year (Feb vol spike + Q4 selloff)
  - 2020 H1 (COVID V-shape — fast crash + recovery; classic whipsaw kill)
  - 2022 full year (sustained bear)
  - 2024-2025 partial (post-AI rally / current regime)

For the best variant, runs a SPY-synchronised bootstrap (n=100): SPY is
already in the 15-symbol universe, so the synthetic block-bootstrap series
has its own internally-consistent SPY for the regime filter to use.
"""
from __future__ import annotations

import math, sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.data.database import Database
from run_xsec_pipeline import run_xsec_momentum, synchronised_block_bootstrap
from run_xsec_pipeline_v2 import vol_target_overlay
from run_xsec_pipeline_crypto import run_crypto_momentum, CRYPTO_SYMBOLS

EQUITY_SYMS = sorted(['AAPL','AMZN','ASML','AVGO','GOOG','MA','META','MSFT','NOW','NVDA','NVO','QQQ','SPY','TSLA','V'])
DB_URL = "sqlite:///alphasmart_dev.db"
MA = 200
RAMP = 0.05  # ±5% band around MA for soft filter
BREADTH_LO, BREADTH_HI = 0.30, 0.60  # soft-breadth ramp endpoints


def binary_signal(close, ma_period=MA):
    """1.0 above MA, else 0. NaN before window fills."""
    ma = close.rolling(ma_period).mean()
    sig = (close > ma).astype(float)
    sig[close.isna() | ma.isna()] = np.nan
    return sig


def soft_signal(close, ma_period=MA, ramp=RAMP):
    """Linear ramp: 0 at (1-ramp)*MA, 1 at (1+ramp)*MA."""
    ma = close.rolling(ma_period).mean()
    ratio = close / ma
    sig = ((ratio - (1 - ramp)) / (2 * ramp)).clip(0.0, 1.0)
    sig[close.isna() | ma.isna()] = np.nan
    return sig


def breadth(closes_df, ma_period=MA):
    """Fraction of universe above own MA at each bar."""
    above = pd.DataFrame(0.0, index=closes_df.index, columns=closes_df.columns)
    for col in closes_df.columns:
        ma = closes_df[col].rolling(ma_period).mean()
        above[col] = (closes_df[col] > ma).astype(float)
        above.loc[closes_df[col].isna() | ma.isna(), col] = np.nan
    return above.mean(axis=1, skipna=True)


def soft_breadth_signal(b, lo=BREADTH_LO, hi=BREADTH_HI):
    """Linear ramp on breadth: 0 at lo, 1 at hi."""
    return ((b - lo) / (hi - lo)).clip(0.0, 1.0)


def metrics(rets, periods_per_year):
    if rets.empty or rets.dropna().eq(0).all():
        return {"sharpe":0.0,"cagr":0.0,"max_drawdown":0.0,"in_market_pct":0.0}
    r = rets.fillna(0)
    in_m = float((rets != 0).sum()) / max(1, len(rets))
    mean = float(r.mean()); std = float(r.std(ddof=1))
    sh = (mean*periods_per_year)/(std*math.sqrt(periods_per_year)) if std > 0 else 0.0
    eq = (1+r).cumprod(); n = len(r)
    cagr = float(eq.iloc[-1])**(periods_per_year/n) - 1 if n > 0 and eq.iloc[-1] > 0 else 0.0
    dd = (eq/eq.cummax() - 1)
    return {"sharpe":float(sh),"cagr":float(cagr),"max_drawdown":float(abs(dd.min())),"in_market_pct":in_m}


def build_filters_equity(closes, spy_close):
    f = {}
    f["A_unfiltered"] = pd.Series(1.0, index=closes.index)
    f["B_binary_price"] = binary_signal(spy_close).reindex(closes.index).ffill().fillna(0)
    f["C_soft_price"]   = soft_signal(spy_close).reindex(closes.index).ffill().fillna(0)
    b = breadth(closes).reindex(closes.index).ffill().fillna(0)
    f["D_binary_breadth"] = (b > 0.5).astype(float)
    f["E_combined_binary"] = f["B_binary_price"] * f["D_binary_breadth"]  # AND = product of binaries
    f["F_soft_combined"]   = f["C_soft_price"] * soft_breadth_signal(b)
    return f


def build_filters_crypto(closes, btc_close):
    f = {}
    f["A_unfiltered"] = pd.Series(1.0, index=closes.index)
    f["B_binary_price"] = binary_signal(btc_close).reindex(closes.index).ffill().fillna(0)
    f["C_soft_price"]   = soft_signal(btc_close).reindex(closes.index).ffill().fillna(0)
    b = breadth(closes).reindex(closes.index).ffill().fillna(0)
    f["D_binary_breadth"] = (b > 0.5).astype(float)
    f["E_combined_binary"] = f["B_binary_price"] * f["D_binary_breadth"]
    f["F_soft_combined"]   = f["C_soft_price"] * soft_breadth_signal(b)
    return f


# Stress-period definitions
STRESS_PERIODS = [
    ("2018",     pd.Timestamp("2018-01-01"), pd.Timestamp("2018-12-31")),
    ("2020 H1",  pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30")),
    ("2022",     pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31")),
    ("2024-25",  pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-31")),
]


def main():
    db = Database(DB_URL)

    # Equity
    closes_eq = pd.DataFrame({s: db.query_ohlcv(s, "1d")["close"] for s in EQUITY_SYMS}).dropna()
    mom_eq, _ = run_xsec_momentum(closes_eq, lookback_days=126, skip_days=0, top_k=5, rebal_days=21)
    mom_eq = vol_target_overlay(mom_eq)
    spy = db.query_ohlcv("SPY","1d")["close"]
    filt_eq = build_filters_equity(closes_eq, spy)

    # Crypto
    closes_cx = pd.DataFrame({s: db.query_ohlcv(s, "1d")["close"] for s in CRYPTO_SYMBOLS}).dropna()
    mom_cx, _ = run_crypto_momentum(closes_cx, lookback_days=30, skip_days=0, top_k=2, rebal_days=7)
    btc = db.query_ohlcv("BTC-USD","1d")["close"]
    filt_cx = build_filters_crypto(closes_cx, btc)

    # ===== Equity full-window comparison =====
    print("="*100); print("EQUITY xsec momentum — filter variants (full 10-yr window)"); print("="*100)
    print(f"{'Variant':24} {'Sharpe':>8} {'CAGR':>8} {'MaxDD':>8} {'InMkt%':>8}  Δ vs A")
    base = metrics(mom_eq, 252)
    rows_eq = {}
    for name, sig in filt_eq.items():
        filtered = mom_eq * sig
        m = metrics(filtered, 252); rows_eq[name] = m
        delta = f"  ΔSh={m['sharpe']-base['sharpe']:+.3f} ΔDD={m['max_drawdown']-base['max_drawdown']:+.3f}"
        print(f"  {name:22} {m['sharpe']:>8.3f} {m['cagr']:>8.3f} {m['max_drawdown']:>8.3f} {m['in_market_pct']*100:>7.1f}%{delta}")

    # ===== Equity stress tests =====
    print()
    print("="*100); print("EQUITY stress tests by sub-period"); print("="*100)
    for label, t0, t1 in STRESS_PERIODS:
        print(f"\n  --- {label} ({t0.date()} → {t1.date()}) ---")
        print(f"  {'Variant':24} {'Sharpe':>8} {'CAGR':>8} {'MaxDD':>8} {'InMkt%':>8}")
        for name, sig in filt_eq.items():
            sub = (mom_eq * sig).loc[t0:t1]
            if len(sub) < 30: continue
            m = metrics(sub, 252)
            print(f"  {name:22} {m['sharpe']:>8.3f} {m['cagr']:>8.3f} {m['max_drawdown']:>8.3f} {m['in_market_pct']*100:>7.1f}%")

    # ===== Crypto full-window comparison =====
    print()
    print("="*100); print("CRYPTO xsec momentum — filter variants (full 5-yr window)"); print("="*100)
    print(f"{'Variant':24} {'Sharpe':>8} {'CAGR':>8} {'MaxDD':>8} {'InMkt%':>8}  Δ vs A")
    base_cx = metrics(mom_cx, 365)
    rows_cx = {}
    for name, sig in filt_cx.items():
        filtered = mom_cx * sig
        m = metrics(filtered, 365); rows_cx[name] = m
        delta = f"  ΔSh={m['sharpe']-base_cx['sharpe']:+.3f} ΔDD={m['max_drawdown']-base_cx['max_drawdown']:+.3f}"
        print(f"  {name:22} {m['sharpe']:>8.3f} {m['cagr']:>8.3f} {m['max_drawdown']:>8.3f} {m['in_market_pct']*100:>7.1f}%{delta}")

    # ===== Crypto stress tests (only 2022+ available) =====
    print()
    print("="*100); print("CRYPTO stress tests"); print("="*100)
    for label, t0, t1 in STRESS_PERIODS:
        sub_test = mom_cx.loc[t0:t1]
        if len(sub_test) < 30: continue
        print(f"\n  --- {label} ({t0.date()} → {t1.date()}) ---")
        print(f"  {'Variant':24} {'Sharpe':>8} {'CAGR':>8} {'MaxDD':>8} {'InMkt%':>8}")
        for name, sig in filt_cx.items():
            sub = (mom_cx * sig).loc[t0:t1]
            m = metrics(sub, 365)
            print(f"  {name:22} {m['sharpe']:>8.3f} {m['cagr']:>8.3f} {m['max_drawdown']:>8.3f} {m['in_market_pct']*100:>7.1f}%")

    # ===== Ensemble: equity_F + crypto_F =====
    print()
    print("="*100); print("ENSEMBLES (50/50 daily) — pick best filter per universe"); print("="*100)
    print(f"  {'Equity filter':24} {'Crypto filter':24} {'Sharpe':>8} {'MaxDD':>8} {'CAGR':>8} {'ρ':>6}")
    for eq_name, eq_sig in filt_eq.items():
        for cx_name, cx_sig in filt_cx.items():
            r_eq = mom_eq * eq_sig
            r_cx = mom_cx * cx_sig
            df = pd.DataFrame({"e": r_eq, "c": r_cx}).dropna()
            ens = (df["e"] + df["c"]) / 2
            m = metrics(ens, 252)
            rho = float(df["e"].corr(df["c"]))
            print(f"  {eq_name:22} {cx_name:22} {m['sharpe']:>8.3f} {m['max_drawdown']:>8.3f} {m['cagr']:>8.3f} {rho:>+.3f}")

    # ===== SPY-synchronised bootstrap on best equity variant =====
    # Pick the best equity variant by Sharpe
    best_eq = max(rows_eq, key=lambda k: rows_eq[k]["sharpe"])
    best_eq_sig = filt_eq[best_eq]
    print()
    print("="*100); print(f"SPY-SYNCHRONISED BOOTSTRAP — {best_eq} (n=100)"); print("="*100)
    sims = synchronised_block_bootstrap(closes_eq, n_sims=100, block_size=20, seed=42)
    sim_sh = []
    for sc in sims:
        full = pd.concat([closes_eq.iloc[0:1], sc]).iloc[: len(closes_eq)]; full.index = closes_eq.index
        rets, _ = run_xsec_momentum(full, lookback_days=126, skip_days=0, top_k=5, rebal_days=21)
        rets = vol_target_overlay(rets)
        # Build SYNTHETIC SPY regime from the SAME synthetic series — proper bootstrap
        sim_spy = full["SPY"]
        if best_eq.startswith("B"): sig = binary_signal(sim_spy).reindex(rets.index).ffill().fillna(0)
        elif best_eq.startswith("C"): sig = soft_signal(sim_spy).reindex(rets.index).ffill().fillna(0)
        elif best_eq.startswith("D"):
            b_sim = breadth(full).reindex(rets.index).ffill().fillna(0); sig = (b_sim > 0.5).astype(float)
        elif best_eq.startswith("E"):
            sb = binary_signal(sim_spy).reindex(rets.index).ffill().fillna(0)
            b_sim = breadth(full).reindex(rets.index).ffill().fillna(0)
            sig = sb * (b_sim > 0.5).astype(float)
        elif best_eq.startswith("F"):
            sp = soft_signal(sim_spy).reindex(rets.index).ffill().fillna(0)
            b_sim = breadth(full).reindex(rets.index).ffill().fillna(0)
            sig = sp * soft_breadth_signal(b_sim)
        else:
            sig = pd.Series(1.0, index=rets.index)
        m = metrics(rets * sig, 252)
        sim_sh.append(m["sharpe"])
    arr = np.array([s for s in sim_sh if not np.isnan(s)])
    p25, med, p75 = np.percentile(arr, [25,50,75])
    orig = rows_eq[best_eq]["sharpe"]
    ratio = float(med)/orig if orig > 0 else 0.0
    print(f"  best variant:  {best_eq}  (Sharpe {orig:.3f})")
    print(f"  sim p25/p50/p75 = {p25:.3f}/{med:.3f}/{p75:.3f}")
    print(f"  ratio = {ratio:.3f}  ({'ROBUST' if ratio >= 0.65 else 'FRAGILE'})")

    # Persist
    import json
    out = _ROOT.parent / "reports" / f"regime_filter_v2_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "equity_variants": rows_eq,
        "crypto_variants": rows_cx,
        "best_equity_variant": best_eq,
        "spy_synchronised_bootstrap": {
            "sim_p25": float(p25), "sim_p50": float(med), "sim_p75": float(p75),
            "ratio": float(ratio), "verdict": "ROBUST" if ratio >= 0.65 else "FRAGILE",
        },
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
