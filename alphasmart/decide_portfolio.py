"""
Portfolio decision gate (todo.md §3 / lessons.md #27).

Reads the latest bootstrap_passers JSON, keeps only ROBUST passers, re-runs each
one's backtest to recover daily returns, then greedily selects the largest
mutually-uncorrelated subset (default |ρ| < 0.5 on daily returns). Reports the
selected set's sector diversity and a final verdict:

  PORTFOLIO_READY   — ≥ 3 selected passers spanning ≥ 2 sectors
  CONCENTRATION     — 1–2 selected passers, OR all in one sector
  NONE              — zero ROBUST passers

Outputs:
  reports/portfolio_decision_<UTC date>.json
  prints a ranked table + correlation matrix to stdout

Usage:
  python decide_portfolio.py
  python decide_portfolio.py path/to/bootstrap_passers.json
  python decide_portfolio.py --corr-threshold 0.6
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.optimizer import _make_strategy
from src.data.database import Database
from src.strategy.risk_manager import RiskConfig

DB_URL = f"sqlite:///{_ROOT / 'alphasmart_dev.db'}"
INITIAL_CAPITAL = 100_000.0

# Sector map mirrors the README "Symbol Universe" table. Update both together.
SECTOR_MAP: dict[str, str] = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "META": "Technology",
    "NVDA": "Semiconductors",
    "AVGO": "Semiconductors",
    "ASML": "Semiconductors",
    "AMZN": "Consumer/Cloud",
    "GOOG": "Advertising/Cloud",
    "NOW":  "Enterprise SaaS",
    "PLTR": "Data/AI",
    "CRWD": "Cybersecurity",
    "TSLA": "Auto/Energy",
    "V":    "Payments",
    "MA":   "Payments",
    "NVO":  "Pharma",
    "SPY":  "Benchmark",
    "QQQ":  "Benchmark",
    "BTC/USDT": "Crypto",
    "ETH/USDT": "Crypto",
}


def _latest_bootstrap_json() -> Path | None:
    reports_dir = _ROOT.parent / "reports"
    if not reports_dir.exists():
        return None
    candidates = sorted(
        reports_dir.glob("bootstrap_passers_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _equity_returns(passer: dict) -> pd.Series | None:
    """Re-run the passer's backtest, return daily simple returns indexed by date."""
    strategy_key = passer["strategy"]
    symbol = passer["symbol"]
    timeframe = passer.get("timeframe", "1d")
    params = passer["params"]

    db = Database(DB_URL)
    data = db.query_ohlcv(symbol, timeframe=timeframe)
    if data.empty:
        return None

    strategy = _make_strategy(strategy_key, symbol, params)
    # Mirror optimizer._run_one: relax single-position cap so strategies that
    # request >5% of equity (e.g. cci_trend's allocation_pct=0.95) actually fill.
    cfg = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        risk_config=RiskConfig(max_position_pct=1.0),
        timeframe=timeframe,
    )
    result = BacktestEngine().run(strategy, data, cfg)
    eq = result.equity_df["equity"] if "equity" in result.equity_df.columns else None
    if eq is None or eq.empty:
        return None
    rets = eq.pct_change().dropna()
    rets.name = f"{strategy_key}::{symbol}::{timeframe}"
    return rets


def _greedy_uncorrelated(
    rankings: list[dict],
    corr_matrix: pd.DataFrame,
    threshold: float,
) -> list[dict]:
    """Greedy: walk highest-Sharpe first, accept if max |ρ| with selected < threshold."""
    selected: list[dict] = []
    selected_keys: list[str] = []
    for rec in rankings:
        key = rec["key"]
        if key not in corr_matrix.index:
            continue
        if not selected_keys:
            selected.append(rec)
            selected_keys.append(key)
            continue
        max_corr = corr_matrix.loc[key, selected_keys].abs().max()
        if max_corr < threshold:
            selected.append(rec)
            selected_keys.append(key)
    return selected


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bootstrap_json", nargs="?", default=None,
                    help="Path to bootstrap_passers JSON (default: latest in reports/)")
    ap.add_argument("--corr-threshold", type=float, default=0.5,
                    help="Max |pairwise correlation| for two passers to coexist (default 0.5)")
    args = ap.parse_args(argv[1:])

    if args.bootstrap_json:
        bootstrap_path = Path(args.bootstrap_json)
    else:
        latest = _latest_bootstrap_json()
        if latest is None:
            print("ERROR: no bootstrap_passers JSON found in reports/. "
                  "Run run_bootstrap_passers.py first.")
            return 1
        bootstrap_path = latest

    if not bootstrap_path.exists():
        print(f"ERROR: file does not exist: {bootstrap_path}")
        return 1

    payload = json.loads(bootstrap_path.read_text())
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not records:
        print(f"No records in {bootstrap_path} — nothing to decide.")
        return 0

    print(f"Source: {bootstrap_path}")
    print(f"Loaded {len(records)} bootstrap records "
          f"(ROBUST={sum(1 for r in records if r.get('verdict') == 'ROBUST')}, "
          f"FRAGILE={sum(1 for r in records if r.get('verdict') == 'FRAGILE')}, "
          f"ERROR={sum(1 for r in records if r.get('verdict') == 'ERROR')})")
    print(f"Correlation threshold |ρ| < {args.corr_threshold}")
    print()

    robust = [r for r in records if r.get("verdict") == "ROBUST"]
    if not robust:
        verdict = "NONE"
        out = {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source_bootstrap": str(bootstrap_path),
            "corr_threshold": args.corr_threshold,
            "verdict": verdict,
            "robust_count": 0,
            "selected": [],
            "message": "No ROBUST passers — widen strategy search or extend history (todo.md §3).",
        }
        out_path = _write_decision(out)
        print(f"Verdict: {verdict}  (no ROBUST passers)")
        print(f"Wrote {out_path}")
        return 0

    # Re-run each ROBUST passer's backtest to get daily returns
    print(f"Re-running {len(robust)} ROBUST passer backtests for return series...")
    return_series: dict[str, pd.Series] = {}
    rankings: list[dict] = []
    for rec in robust:
        key = f"{rec['strategy']}::{rec['symbol']}::{rec.get('timeframe', '1d')}"
        try:
            rets = _equity_returns(rec)
        except Exception as exc:
            print(f"  ✗ {key}  backtest failed: {type(exc).__name__}: {exc}")
            continue
        if rets is None or rets.empty:
            print(f"  ✗ {key}  empty equity curve")
            continue
        return_series[key] = rets
        rankings.append({
            "key": key,
            "strategy": rec["strategy"],
            "symbol": rec["symbol"],
            "timeframe": rec.get("timeframe", "1d"),
            "sector": SECTOR_MAP.get(rec["symbol"], "Unknown"),
            "original_sharpe": rec["original_sharpe"],
            "sim_sharpe_median": rec["sim_sharpe_median"],
            "ratio": rec["ratio_median_to_original"],
            "params": rec.get("params", {}),
        })
        print(f"  ✓ {key}  ({len(rets)} return obs, Sharpe={rec['original_sharpe']:.3f})")

    if not rankings:
        verdict = "NONE"
        out = {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source_bootstrap": str(bootstrap_path),
            "corr_threshold": args.corr_threshold,
            "verdict": verdict,
            "robust_count": len(robust),
            "selected": [],
            "message": "All ROBUST passers failed re-backtest — investigate.",
        }
        out_path = _write_decision(out)
        print(f"Verdict: {verdict}  (re-backtests all failed)")
        print(f"Wrote {out_path}")
        return 0

    # Build correlation matrix on aligned daily returns
    rankings.sort(key=lambda r: r["original_sharpe"], reverse=True)
    df = pd.concat([return_series[r["key"]] for r in rankings], axis=1, join="outer")
    df.columns = [r["key"] for r in rankings]
    # Restrict to dates where at least 2 series have observations to keep
    # correlation interpretable; pandas .corr() handles NaN pairwise.
    corr = df.corr(method="pearson", min_periods=30)

    print()
    print("Pairwise return correlation (Pearson, min 30 overlapping bars):")
    with pd.option_context("display.float_format", lambda v: f"{v:+.2f}",
                            "display.width", 240,
                            "display.max_columns", 50):
        print(corr.round(2))

    # Greedy selection
    selected = _greedy_uncorrelated(rankings, corr, args.corr_threshold)
    sectors = sorted({r["sector"] for r in selected})
    n_sel = len(selected)
    n_sectors = len(sectors)

    if n_sel >= 3 and n_sectors >= 2:
        verdict = "PORTFOLIO_READY"
        msg = (f"{n_sel} uncorrelated ROBUST passers across {n_sectors} sectors — "
               f"defensible to start paper-trading shadow mode (todo.md §4).")
    elif n_sel >= 1:
        verdict = "CONCENTRATION"
        msg = (f"Only {n_sel} uncorrelated passer(s) in {n_sectors} sector(s). "
               "Widen the search (momentum_long+stop, donchian_bo+stop, "
               "alpha_composite+stop) or extend history before paper-trading "
               "(todo.md §3a/3b, lessons.md #27).")
    else:
        verdict = "NONE"
        msg = "No usable ROBUST passers."

    print()
    print(f"Greedy selection (Sharpe-ranked, |ρ| < {args.corr_threshold}):")
    for r in selected:
        print(f"  • {r['key']:50}  Sharpe={r['original_sharpe']:.2f}  "
              f"sector={r['sector']}")
    print()
    print(f"Verdict: {verdict}")
    print(msg)

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_bootstrap": str(bootstrap_path),
        "corr_threshold": args.corr_threshold,
        "verdict": verdict,
        "message": msg,
        "robust_count": len(robust),
        "selected_count": n_sel,
        "sectors_covered": sectors,
        "selected": selected,
        "all_robust_ranked": rankings,
        "correlation_matrix": {
            k: {kk: (None if pd.isna(v) else round(float(v), 4))
                for kk, v in row.items()}
            for k, row in corr.to_dict().items()
        },
    }
    out_path = _write_decision(out)
    print(f"Wrote {out_path}")
    return 0


def _write_decision(payload: dict) -> Path:
    reports_dir = _ROOT.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = reports_dir / f"portfolio_decision_{date_tag}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    return out_path


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
