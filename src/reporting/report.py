"""
Backtest report generator for AlphaSMART.

generate_report(df):
  1. Computes a composite score per row
  2. Ranks all (strategy, symbol, timeframe) combinations
  3. Prints a formatted ranked table to console
  4. Prints a strategy-level summary
  5. Saves CSV to reports/ directory (auto-timestamped)
  6. Returns the enriched DataFrame

Composite score formula (higher = better):
  score = sharpe × 0.40
        + cagr × 10 × 0.30
        + (1 - max_drawdown) × 0.20
        + win_rate × 0.10
  Forced to 0 if total_return <= 0 (losing strategies rank last).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Column display config
# ---------------------------------------------------------------------------

_DISPLAY_COLS = [
    ("rank",          "Rank",        4,  "d"),
    ("strategy",      "Strategy",    15, "s"),
    ("symbol",        "Symbol",      9,  "s"),
    ("timeframe",     "TF",          4,  "s"),
    ("sharpe",        "Sharpe",      7,  ".3f"),
    ("sortino",       "Sortino",     7,  ".3f"),
    ("cagr",          "CAGR",        7,  ".1%"),
    ("max_drawdown",  "MaxDD",       7,  ".1%"),
    ("win_rate",      "WinRate",     8,  ".1%"),
    ("profit_factor", "PF",          6,  ".2f"),
    ("total_return",  "TotalRet",    9,  ".1%"),
    ("trade_count",   "Trades",      7,  "d"),
    ("score",         "Score",       7,  ".3f"),
    ("gate1_pass",    "Gate1",       6,  "s"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_report(
    df: pd.DataFrame,
    output_csv: str | Path | None = None,
    initial_capital: float = 100_000.0,
) -> pd.DataFrame:
    """
    Rank, print, and save the backtest results.

    Args:
        df:              DataFrame from BatchRunner.run_all()
        output_csv:      Path to save CSV. If None, auto-names in reports/
        initial_capital: Used only for display in header

    Returns:
        Enriched DataFrame with 'score' and 'rank' columns, sorted by rank.
    """
    if df.empty:
        print("\n⚠  No backtest results to report.\n")
        return df

    # ------------------------------------------------------------------
    # 1. Compute composite score
    # ------------------------------------------------------------------
    df = df.copy()
    df["score"] = df.apply(_composite_score, axis=1)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    # ------------------------------------------------------------------
    # 2. Print header
    # ------------------------------------------------------------------
    now = datetime.now()
    n_strategies = df["strategy"].nunique()
    n_symbols = df["symbol"].nunique()
    n_runs = len(df)
    gate1_passes = int(df["gate1_pass"].sum())

    print()
    print("=" * 110)
    print("  ALPHASMART BACKTEST REPORT")
    print(f"  Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Universe:  {n_symbols} symbols  |  {n_strategies} strategies  |  {n_runs} total runs")
    print(f"  Capital:   ${initial_capital:,.0f}  |  Gate 1 passes: {gate1_passes}/{n_runs}")
    print("=" * 110)

    # ------------------------------------------------------------------
    # 3. Print full ranked table
    # ------------------------------------------------------------------
    _print_ranked_table(df)

    # ------------------------------------------------------------------
    # 4. Print strategy summary
    # ------------------------------------------------------------------
    _print_strategy_summary(df)

    # ------------------------------------------------------------------
    # 5. Print top-5 highlight
    # ------------------------------------------------------------------
    _print_top5(df)

    # ------------------------------------------------------------------
    # 6. Save CSV
    # ------------------------------------------------------------------
    csv_path = _save_csv(df, output_csv, now)
    print(f"\n  CSV saved → {csv_path}\n")

    return df


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _composite_score(row: pd.Series) -> float:
    """
    Composite score (higher = better).
    Forced to 0 for losing strategies so they sink to the bottom.
    """
    if row.get("total_return", 0) <= 0:
        return 0.0

    sharpe_component  = float(row.get("sharpe", 0))       * 0.40
    cagr_component    = float(row.get("cagr", 0)) * 10    * 0.30
    dd_component      = (1 - float(row.get("max_drawdown", 1))) * 0.20
    wr_component      = float(row.get("win_rate", 0))      * 0.10

    score = sharpe_component + cagr_component + dd_component + wr_component
    return max(0.0, score)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _print_ranked_table(df: pd.DataFrame) -> None:
    # Build header
    headers = [name for _, name, _, _ in _DISPLAY_COLS]
    widths  = [w   for _, _,    w, _ in _DISPLAY_COLS]

    sep = "  ".join("-" * w for w in widths)
    hdr = "  ".join(f"{h:<{w}}" for h, w in zip(headers, widths))

    print(f"\n  {'FULL RANKINGS':^{sum(widths) + 2 * len(widths)}}")
    print("  " + sep)
    print("  " + hdr)
    print("  " + sep)

    for _, row in df.iterrows():
        parts = []
        for col, _, width, fmt in _DISPLAY_COLS:
            val = row.get(col, "")
            if col == "gate1_pass":
                val = "✅" if val else "❌"
                parts.append(f"{val:<{width}}")
            elif fmt == "d":
                try:
                    parts.append(f"{int(val):{width}d}")
                except (ValueError, TypeError):
                    parts.append(f"{'—':>{width}}")
            elif fmt == "s":
                parts.append(f"{str(val):<{width}}")
            elif "%" in fmt:
                try:
                    parts.append(f"{float(val):{width}{fmt}}")
                except (ValueError, TypeError):
                    parts.append(f"{'—':>{width}}")
            else:
                try:
                    parts.append(f"{float(val):{width}{fmt}}")
                except (ValueError, TypeError):
                    parts.append(f"{'—':>{width}}")
        print("  " + "  ".join(parts))

    print("  " + sep)


def _print_strategy_summary(df: pd.DataFrame) -> None:
    print(f"\n  {'STRATEGY SUMMARY':^80}")
    print("  " + "-" * 80)
    fmt = f"  {'Strategy':<18} {'Avg Sharpe':>10} {'Avg CAGR':>9} {'Avg Score':>10} {'Gate1 Passes':>13} {'Runs':>6}"
    print(fmt)
    print("  " + "-" * 80)

    for strat, grp in df.groupby("strategy"):
        avg_sharpe = grp["sharpe"].mean()
        avg_cagr   = grp["cagr"].mean()
        avg_score  = grp["score"].mean()
        passes     = int(grp["gate1_pass"].sum())
        runs       = len(grp)
        print(
            f"  {str(strat):<18} {avg_sharpe:>10.3f} {avg_cagr:>8.1%} "
            f"{avg_score:>10.3f} {passes:>8}/{runs:<4} {runs:>6}"
        )

    print("  " + "-" * 80)


def _print_top5(df: pd.DataFrame) -> None:
    top = df.head(5)
    print(f"\n  {'TOP 5 COMBINATIONS':^60}")
    print("  " + "-" * 60)
    for _, row in top.iterrows():
        gate = "✅" if row["gate1_pass"] else "❌"
        print(
            f"  #{int(row['rank']):<3} {str(row['strategy']):<18} {str(row['symbol']):<10} "
            f"{str(row['timeframe']):<5}  "
            f"Sharpe={row['sharpe']:.2f}  CAGR={row['cagr']:.1%}  "
            f"MaxDD={row['max_drawdown']:.1%}  Score={row['score']:.3f}  {gate}"
        )
    print("  " + "-" * 60)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def _save_csv(df: pd.DataFrame, output_csv: str | Path | None, now: datetime) -> Path:
    if output_csv is not None:
        path = Path(output_csv)
    else:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        filename = f"backtest_report_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        path = reports_dir / filename

    path.parent.mkdir(parents=True, exist_ok=True)

    # Round floats before saving
    float_cols = ["sharpe", "sortino", "cagr", "max_drawdown", "win_rate",
                  "profit_factor", "total_return", "exposure", "avg_trade",
                  "best_trade", "worst_trade", "score"]
    out = df.copy()
    for c in float_cols:
        if c in out.columns:
            out[c] = out[c].round(4)

    out.to_csv(path, index=False)
    return path
