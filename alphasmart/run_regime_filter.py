"""
Regime filter overlay on the PORTFOLIO_READY strategies.

Filter rules:
  Equity strategy: trade only when SPY close > SPY 200-day MA
  Crypto strategy: trade only when BTC close > BTC 200-day MA
  When filter is OFF → cash (0 daily return)

Compares filtered vs unfiltered:
  - Sharpe / CAGR / MaxDD across the full window
  - Per-period (bear vs bull) breakdown
  - Bootstrap robustness on the filtered series
  - Equal-weight ensemble metrics (filtered equity + filtered crypto)
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
MA_PERIOD = 200


def regime_signal(close: pd.Series, ma_period: int = MA_PERIOD) -> pd.Series:
    """1.0 when close > MA(close), else 0.0. NaN before MA window fills."""
    ma = close.rolling(ma_period).mean()
    sig = (close > ma).astype(float)
    sig[close.isna() | ma.isna()] = np.nan
    return sig


def metrics(rets: pd.Series, periods_per_year: int) -> dict:
    if rets.empty:
        return {"sharpe": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "n_active": 0, "pct_in_market": 0.0}
    in_market = (rets != 0).sum()
    pct = float(in_market) / len(rets) if len(rets) else 0.0
    mean = float(rets.mean()); std = float(rets.std(ddof=1))
    sharpe = (mean * periods_per_year) / (std * math.sqrt(periods_per_year)) if std > 0 else 0.0
    eq = (1 + rets.fillna(0)).cumprod()
    n = len(rets)
    cagr = float(eq.iloc[-1]) ** (periods_per_year / n) - 1 if n > 0 and eq.iloc[-1] > 0 else 0.0
    dd = (eq / eq.cummax() - 1)
    return {"sharpe": float(sharpe), "cagr": float(cagr),
            "max_drawdown": float(abs(dd.min())),
            "n_active": int(in_market), "pct_in_market": float(pct)}


def main():
    db = Database(DB_URL)

    # ===== Equity strategy =====
    print("="*78); print("EQUITY STRATEGY — xsec momentum + SPY 200d-MA filter"); print("="*78)
    closes_eq = pd.DataFrame({s: db.query_ohlcv(s, "1d")["close"] for s in EQUITY_SYMS}).dropna()
    mom_eq, _ = run_xsec_momentum(closes_eq, lookback_days=126, skip_days=0, top_k=5, rebal_days=21)
    mom_eq = vol_target_overlay(mom_eq)
    spy_close = db.query_ohlcv("SPY", "1d")["close"]
    regime_eq = regime_signal(spy_close, MA_PERIOD).reindex(mom_eq.index).ffill().fillna(0.0)
    mom_eq_filtered = mom_eq * regime_eq

    m_unf = metrics(mom_eq, 252); m_filt = metrics(mom_eq_filtered, 252)
    print(f"{'':35} {'Unfiltered':>12} {'+SPY>200MA':>12}  Δ")
    print(f"{'  Sharpe':35} {m_unf['sharpe']:>12.3f} {m_filt['sharpe']:>12.3f}  {m_filt['sharpe']-m_unf['sharpe']:+.3f}")
    print(f"{'  CAGR':35} {m_unf['cagr']:>12.3f} {m_filt['cagr']:>12.3f}  {m_filt['cagr']-m_unf['cagr']:+.3f}")
    print(f"{'  MaxDD':35} {m_unf['max_drawdown']:>12.3f} {m_filt['max_drawdown']:>12.3f}  {m_filt['max_drawdown']-m_unf['max_drawdown']:+.3f}")
    print(f"{'  Days in market':35} {m_unf['n_active']:>12} {m_filt['n_active']:>12}  ({m_filt['pct_in_market']*100:.0f}%)")

    # 2022 bear sub-period (heuristic: SPY peak Jan 2022 to trough Oct 2022)
    bear_2022 = pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31")
    eq_2022_unf = mom_eq.loc[bear_2022[0]:bear_2022[1]]
    eq_2022_filt = mom_eq_filtered.loc[bear_2022[0]:bear_2022[1]]
    if len(eq_2022_unf) > 30:
        m_2022_unf = metrics(eq_2022_unf, 252); m_2022_filt = metrics(eq_2022_filt, 252)
        print(f"\n  2022 bear-year breakdown:")
        print(f"    Sharpe   unfiltered: {m_2022_unf['sharpe']:+.3f}   filtered: {m_2022_filt['sharpe']:+.3f}")
        print(f"    CAGR     unfiltered: {m_2022_unf['cagr']:+.3f}   filtered: {m_2022_filt['cagr']:+.3f}")
        print(f"    MaxDD    unfiltered: {m_2022_unf['max_drawdown']:.3f}   filtered: {m_2022_filt['max_drawdown']:.3f}")
        print(f"    InMarket unfiltered: {m_2022_unf['pct_in_market']*100:.0f}%   filtered: {m_2022_filt['pct_in_market']*100:.0f}%")

    # ===== Crypto strategy =====
    print()
    print("="*78); print("CRYPTO STRATEGY — xsec momentum + BTC 200d-MA filter"); print("="*78)
    closes_cx = pd.DataFrame({s: db.query_ohlcv(s, "1d")["close"] for s in CRYPTO_SYMBOLS}).dropna()
    mom_cx, _ = run_crypto_momentum(closes_cx, lookback_days=30, skip_days=0, top_k=2, rebal_days=7)
    btc_close = db.query_ohlcv("BTC-USD", "1d")["close"]
    regime_cx = regime_signal(btc_close, MA_PERIOD).reindex(mom_cx.index).ffill().fillna(0.0)
    mom_cx_filtered = mom_cx * regime_cx

    m_unf_cx = metrics(mom_cx, 365); m_filt_cx = metrics(mom_cx_filtered, 365)
    print(f"{'':35} {'Unfiltered':>12} {'+BTC>200MA':>12}  Δ")
    print(f"{'  Sharpe':35} {m_unf_cx['sharpe']:>12.3f} {m_filt_cx['sharpe']:>12.3f}  {m_filt_cx['sharpe']-m_unf_cx['sharpe']:+.3f}")
    print(f"{'  CAGR':35} {m_unf_cx['cagr']:>12.3f} {m_filt_cx['cagr']:>12.3f}  {m_filt_cx['cagr']-m_unf_cx['cagr']:+.3f}")
    print(f"{'  MaxDD':35} {m_unf_cx['max_drawdown']:>12.3f} {m_filt_cx['max_drawdown']:>12.3f}  {m_filt_cx['max_drawdown']-m_unf_cx['max_drawdown']:+.3f}")
    print(f"{'  Days in market':35} {m_unf_cx['n_active']:>12} {m_filt_cx['n_active']:>12}  ({m_filt_cx['pct_in_market']*100:.0f}%)")

    # 2022 crypto winter
    cx_2022_unf = mom_cx.loc[bear_2022[0]:bear_2022[1]]
    cx_2022_filt = mom_cx_filtered.loc[bear_2022[0]:bear_2022[1]]
    if len(cx_2022_unf) > 30:
        m_c_unf = metrics(cx_2022_unf, 365); m_c_filt = metrics(cx_2022_filt, 365)
        print(f"\n  2022 crypto-winter breakdown:")
        print(f"    Sharpe   unfiltered: {m_c_unf['sharpe']:+.3f}   filtered: {m_c_filt['sharpe']:+.3f}")
        print(f"    CAGR     unfiltered: {m_c_unf['cagr']:+.3f}   filtered: {m_c_filt['cagr']:+.3f}")
        print(f"    MaxDD    unfiltered: {m_c_unf['max_drawdown']:.3f}   filtered: {m_c_filt['max_drawdown']:.3f}")
        print(f"    InMarket unfiltered: {m_c_unf['pct_in_market']*100:.0f}%   filtered: {m_c_filt['pct_in_market']*100:.0f}%")

    # ===== Ensemble =====
    print()
    print("="*78); print("ENSEMBLE — equal-weight equity_filtered + crypto_filtered"); print("="*78)
    df_ens = pd.DataFrame({"equity_filt": mom_eq_filtered, "crypto_filt": mom_cx_filtered}).dropna()
    ens = (df_ens["equity_filt"] + df_ens["crypto_filt"]) / 2
    m_ens = metrics(ens, 252)  # daily ensemble — equity-frequency is the bottleneck
    print(f"  Aligned bars: {len(df_ens)}")
    print(f"  Sharpe (filtered ensemble): {m_ens['sharpe']:.3f}")
    print(f"  CAGR:   {m_ens['cagr']:.3f}")
    print(f"  MaxDD:  {m_ens['max_drawdown']:.3f}")
    print(f"  ρ(equity_filt, crypto_filt) = {df_ens['equity_filt'].corr(df_ens['crypto_filt']):+.3f}")

    # ===== Quick bootstrap on filtered equity strategy =====
    print()
    print("="*78); print("BOOTSTRAP on filtered equity strategy (n=50)"); print("="*78)
    sims = synchronised_block_bootstrap(closes_eq, n_sims=50, block_size=20, seed=42)
    sim_sharpes = []
    spy_full_idx = mom_eq.index  # use original SPY index for the regime
    for sc in sims:
        full = pd.concat([closes_eq.iloc[0:1], sc]).iloc[: len(closes_eq)]; full.index = closes_eq.index
        rets, _ = run_xsec_momentum(full, lookback_days=126, skip_days=0, top_k=5, rebal_days=21)
        rets = vol_target_overlay(rets)
        # apply same regime mask (uses real SPY) — assesses if filtered series stays robust
        sim_filtered = rets * regime_eq.reindex(rets.index).fillna(0)
        m = metrics(sim_filtered, 252)
        sim_sharpes.append(m["sharpe"])
    arr = np.array([s for s in sim_sharpes if not np.isnan(s)])
    p25, med, p75 = np.percentile(arr, [25,50,75])
    ratio = float(med) / m_filt["sharpe"] if m_filt["sharpe"] > 0 else 0.0
    print(f"  sim p25/p50/p75 = {p25:.3f}/{med:.3f}/{p75:.3f}")
    print(f"  ratio = {ratio:.3f}  ({'ROBUST' if ratio >= 0.65 else 'FRAGILE'})")

    # Persist
    import json
    out = _ROOT.parent / "reports" / f"regime_filter_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    out.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "ma_period": MA_PERIOD,
        "equity_unfiltered": m_unf, "equity_filtered": m_filt,
        "crypto_unfiltered": m_unf_cx, "crypto_filtered": m_filt_cx,
        "ensemble_filtered": m_ens,
        "ensemble_corr": float(df_ens["equity_filt"].corr(df_ens["crypto_filt"])),
        "bootstrap_filtered_equity": {"sim_p25": float(p25), "sim_p50": float(med), "sim_p75": float(p75), "ratio": float(ratio)},
    }, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
