"""
Parameter optimization for AlphaSMART strategies.

Implements:
  1. Grid search across all valid parameter combinations (full dataset)
  2. Walk-forward validation (rolling IS/OOS windows)
  3. Stability map for 1D/2D parameter axes
  4. Overfitting score and Gate 2 evaluation
  5. Custom optimization objective (Sharpe, CAGR, MaxDD, ProfitFactor)
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Literal

import pandas as pd

from src.data.database import Database
from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.metrics import bars_per_year_for
from src.strategy.risk_manager import RiskConfig
from src.strategy.trend import EMACrossoverStrategy
from src.strategy.mean_reversion import RSIMeanReversionStrategy
from src.strategy.breakout import DonchianBreakoutStrategy
from src.strategy.macd_momentum import MACDMomentumStrategy
from src.strategy.bollinger_reversion import BollingerReversionStrategy
from src.strategy.triple_screen import TripleScreenStrategy
from src.strategy.atr_breakout import ATRBreakoutStrategy
from src.strategy.zscore_reversion import ZScoreReversionStrategy
from src.strategy.momentum_long import MomentumLongStrategy
from src.strategy.vwap_reversion import VWAPReversionStrategy
from src.strategy.alpha_composite import AlphaCompositeStrategy
from src.strategy.alpha_composite_v2 import AlphaCompositeTrendV2, AlphaMomentumV2

# ---------------------------------------------------------------------------
# Parameter grids — exhaustive but bounded
# ---------------------------------------------------------------------------
PARAM_GRIDS: dict[str, dict[str, list]] = {
    # --- Original 5 ---
    "ema_crossover": {
        "fast_period": [5, 8, 10, 13, 15],
        "slow_period": [20, 26, 30, 40, 50],
    },
    "rsi_reversion": {
        "rsi_period": [10, 14, 21],
        "oversold":   [25, 30, 35],
        "overbought": [65, 70, 75],
    },
    "donchian_bo": {
        "period": [10, 15, 20, 25, 30, 40, 50],
    },
    "macd_momentum": {
        "fast_period":   [8, 12],
        "slow_period":   [21, 26],
        "signal_period": [7, 9],
    },
    "bb_reversion": {
        "period":  [15, 20, 25, 30],
        "std_dev": [1.5, 2.0, 2.5],
    },
    # --- New strategies ---
    "triple_screen": {
        "macro_period":     [30, 50, 100],
        "stoch_period":     [10, 14, 21],
        "oversold_level":   [15.0, 20.0, 25.0],
        "overbought_level": [75.0, 80.0],
    },
    "atr_breakout": {
        "ema_period": [15, 20, 30],
        "atr_period": [10, 14, 20],
        "atr_mult":   [1.5, 2.0, 2.5, 3.0],
    },
    "zscore_reversion": {
        "period":  [20, 30, 40, 60],
        "entry_z": [1.5, 2.0, 2.5],
        "exit_z":  [0.0, 0.25, 0.5],
    },
    "momentum_long": {
        "lookback_period":  [63, 126, 189],   # 3m, 6m, 9m
        "entry_threshold":  [0.03, 0.05, 0.08],
        "exit_threshold":   [-0.05, -0.02, 0.0],
    },
    "vwap_reversion": {
        "vwap_period": [10, 20, 30],
        "entry_z":     [1.0, 1.5, 2.0],
        "exit_z":      [0.0, 0.25],
    },
    # --- Proprietary (AlphaComposite) ---
    "alpha_composite": {
        "fast_ema":        [8, 10, 13],
        "slow_ema":        [25, 30, 40],
        "rsi_period":      [10, 14],
        "rsi_oversold":    [40.0, 45.0, 50.0],
        "trend_weight":    [0.40, 0.45, 0.50],
        "rsi_weight":      [0.30, 0.35, 0.40],
        "entry_threshold": [0.45, 0.50, 0.55],
    },
    # --- V2 data-driven composites (Step 4) — focused 4-dim grids ≤81 combos ---
    # Weights fixed at data-driven defaults; tune EMA, RSI, and entry threshold only.
    "alpha_trend_v2": {
        "fast_ema":        [10, 13, 15],
        "slow_ema":        [28, 30, 35],
        "rsi_oversold":    [38.0, 40.0, 42.0],
        "entry_threshold": [0.47, 0.50, 0.53],
    },
    "alpha_momentum_v2": {
        "fast_ema":        [8, 10, 13],
        "slow_ema":        [22, 25, 28],
        "rsi_oversold":    [38.0, 40.0, 42.0],
        "entry_threshold": [0.42, 0.45, 0.48],
    },
}

# Primary 2D axes for the stability heatmap (ax1=y-axis, ax2=x-axis)
STABILITY_AXES: dict[str, tuple[str, str]] = {
    "ema_crossover":   ("fast_period", "slow_period"),
    "rsi_reversion":   ("oversold", "overbought"),
    "donchian_bo":     ("period", "period"),          # 1D
    "macd_momentum":   ("fast_period", "slow_period"),
    "bb_reversion":    ("period", "std_dev"),
    "triple_screen":   ("macro_period", "stoch_period"),
    "atr_breakout":    ("atr_period", "atr_mult"),
    "zscore_reversion":("period", "entry_z"),
    "momentum_long":   ("lookback_period", "entry_threshold"),
    "vwap_reversion":  ("vwap_period", "entry_z"),
    "alpha_composite":   ("trend_weight", "entry_threshold"),
    "alpha_trend_v2":    ("trend_weight", "entry_threshold"),
    "alpha_momentum_v2": ("rsi_weight",   "entry_threshold"),
}

# Walk-forward window sizes in bars — scaled per timeframe in run_optimization()
# Set to IS=2yr / OOS=6mo / STEP=6mo → ≥3 folds on 5yr daily data (lesson #5)
_IS_YEARS   = 2.0   # 2 years in-sample
_OOS_YEARS  = 0.5   # 6 months out-of-sample
_STEP_YEARS = 0.5   # advance 6 months per fold

# Optimization objectives
OptObjective = Literal["sharpe", "cagr", "max_drawdown", "profit_factor"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_strategy(strategy_key: str, symbol: str, params: dict):
    """Instantiate a strategy with given params."""
    cls_map = {
        "ema_crossover":    EMACrossoverStrategy,
        "rsi_reversion":    RSIMeanReversionStrategy,
        "donchian_bo":      DonchianBreakoutStrategy,
        "macd_momentum":    MACDMomentumStrategy,
        "bb_reversion":     BollingerReversionStrategy,
        "triple_screen":    TripleScreenStrategy,
        "atr_breakout":     ATRBreakoutStrategy,
        "zscore_reversion": ZScoreReversionStrategy,
        "momentum_long":    MomentumLongStrategy,
        "vwap_reversion":    VWAPReversionStrategy,
        "alpha_composite":   AlphaCompositeStrategy,
        "alpha_trend_v2":    AlphaCompositeTrendV2,
        "alpha_momentum_v2": AlphaMomentumV2,
    }
    if strategy_key not in cls_map:
        raise ValueError(f"Unknown strategy: {strategy_key}")
    return cls_map[strategy_key](symbol, **params)


def _score(result: dict, objective: OptObjective) -> float:
    """Extract the scalar score for ranking (higher = better)."""
    if objective == "sharpe":
        return result.get("sharpe", float("nan"))
    if objective == "cagr":
        return result.get("cagr", float("nan"))
    if objective == "max_drawdown":
        # Invert: lower drawdown = better score
        dd = result.get("max_drawdown", float("nan"))
        return -dd if not (dd != dd) else float("nan")  # nan check
    if objective == "profit_factor":
        pf = result.get("profit_factor", float("nan"))
        return min(pf, 10.0) if not (pf != pf) else float("nan")  # cap at 10x
    return result.get("sharpe", float("nan"))


def _run_one(
    strategy_key: str,
    symbol: str,
    data: pd.DataFrame,
    params: dict,
    capital: float,
    timeframe: str = "1d",
) -> dict:
    """Run a single backtest and return key metrics. Returns ok=False on failure."""
    try:
        strat = _make_strategy(strategy_key, symbol, params)
        config = BacktestConfig(
            initial_capital=capital,
            risk_config=RiskConfig(max_position_pct=1.0),
            timeframe=timeframe,
        )
        result = BacktestEngine().run(strat, data, config)
        m = result.metrics
        return {
            "params":        params,
            "sharpe":        float(m.sharpe),
            "cagr":          float(m.cagr),
            "max_drawdown":  float(m.max_drawdown),
            "win_rate":      float(m.win_rate),
            "profit_factor": float(m.profit_factor),
            "trade_count":   int(m.trade_count),
            "total_return":  float(m.total_return),
            "ok": True,
        }
    except Exception as exc:
        return {"params": params, "sharpe": float("nan"), "ok": False, "error": str(exc)}


def _run_one_on_data(
    strategy_key: str,
    symbol: str,
    data: pd.DataFrame,
    params: dict,
    capital: float,
    timeframe: str = "1d",
) -> dict:
    """Public helper used by simulation.py — same as _run_one."""
    return _run_one(strategy_key, symbol, data, params, capital, timeframe)


def _generate_combos(strategy_key: str, custom_grid: dict | None = None) -> list[dict]:
    """Return all valid parameter combinations for the strategy."""
    grid = custom_grid if custom_grid else PARAM_GRIDS.get(strategy_key, {})
    if not grid:
        return []

    combos = []
    for values in itertools.product(*grid.values()):
        params = dict(zip(grid.keys(), values))
        # Strategy-specific hard constraints
        if strategy_key == "ema_crossover" and params.get("fast_period", 0) >= params.get("slow_period", 0):
            continue
        if strategy_key == "rsi_reversion" and params.get("oversold", 0) >= params.get("overbought", 0):
            continue
        if strategy_key == "macd_momentum" and params.get("fast_period", 0) >= params.get("slow_period", 0):
            continue
        if strategy_key == "triple_screen" and params.get("oversold_level", 0) >= params.get("overbought_level", 0):
            continue
        # AlphaComposite family: if weights are in the grid, validate they sum to ~1
        if strategy_key in ("alpha_composite", "alpha_trend_v2", "alpha_momentum_v2"):
            if "trend_weight" in params and "rsi_weight" in params:
                tw = params["trend_weight"]
                rw = params["rsi_weight"]
                vw = round(1.0 - tw - rw, 4)
                if vw < 0.05 or vw > 0.6:
                    continue
                params["vol_weight"] = vw
            if params.get("fast_ema", 0) >= params.get("slow_ema", 99):
                continue
            if params.get("exit_threshold", 0) >= params.get("entry_threshold", 1):
                params["exit_threshold"] = params["entry_threshold"] - 0.15
        combos.append(params)
    return combos


def _build_stability_map(strategy_key: str, grid_results: list[dict]) -> dict:
    """
    Build the stability map structure for the UI.
    For 2D strategies: 2D array of {x, y, sharpe} cells.
    For 1D strategies: flat list of {x, sharpe} points.
    """
    ax1, ax2 = STABILITY_AXES.get(strategy_key, (None, None))
    is_1d = ax1 == ax2

    if is_1d and ax1:
        pts = {}
        for r in grid_results:
            v = r["params"].get(ax1)
            if v is not None:
                pts.setdefault(v, []).append(r["sharpe"])
        return {
            "type": "1d",
            "x_label": ax1,
            "points": [
                {"x": v, "sharpe": sum(sharpes) / len(sharpes)}
                for v, sharpes in sorted(pts.items())
            ],
        }

    if ax1 and ax2:
        cells: dict = defaultdict(list)
        for r in grid_results:
            v1 = r["params"].get(ax1)
            v2 = r["params"].get(ax2)
            if v1 is not None and v2 is not None:
                cells[(v1, v2)].append(r["sharpe"])

        ax1_vals = sorted({r["params"][ax1] for r in grid_results if ax1 in r["params"]})
        ax2_vals = sorted({r["params"][ax2] for r in grid_results if ax2 in r["params"]})

        rows = []
        for v1 in ax1_vals:
            row_cells = []
            for v2 in ax2_vals:
                sharpes = cells.get((v1, v2), [])
                row_cells.append({
                    "x": v2,
                    "y": v1,
                    "sharpe": round(sum(sharpes) / len(sharpes), 4) if sharpes else None,
                })
            rows.append({"y_val": v1, "cells": row_cells})

        return {
            "type": "2d",
            "x_label": ax2,
            "y_label": ax1,
            "x_vals": ax2_vals,
            "y_vals": ax1_vals,
            "rows": rows,
        }

    return {"type": "none"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_optimization(
    strategy_key: str,
    symbol: str,
    timeframe: str,
    db_url: str,
    capital: float = 100_000.0,
    objective: OptObjective = "sharpe",
    custom_param_grid: dict | None = None,
) -> dict:
    """
    Full optimization run: grid search on full dataset + walk-forward validation.

    Args:
        strategy_key:      Strategy identifier
        symbol:            Asset symbol
        timeframe:         Bar interval
        db_url:            SQLAlchemy DB URL
        capital:           Starting capital
        objective:         Optimization objective ("sharpe", "cagr", "max_drawdown", "profit_factor")
        custom_param_grid: Override the default parameter grid (optional, for proprietary strategy)

    Returns:
        dict suitable for JSON serialization.
    """
    db = Database(db_url)
    data = db.query_ohlcv(symbol, timeframe=timeframe)

    if data.empty:
        return {"error": f"No data for {symbol}/{timeframe}"}
    if strategy_key not in PARAM_GRIDS and not custom_param_grid:
        return {"error": f"No parameter grid for strategy '{strategy_key}'"}

    bpy = bars_per_year_for(timeframe)
    combos = _generate_combos(strategy_key, custom_param_grid)
    if not combos:
        return {"error": "No valid parameter combinations generated"}

    # ---- 1. Grid search (full dataset) ----
    grid_results = [
        r for r in (_run_one(strategy_key, symbol, data, p, capital, timeframe) for p in combos)
        if r["ok"]
    ]

    if not grid_results:
        return {"error": "All parameter combinations failed during grid search"}

    grid_results.sort(key=lambda r: _score(r, objective), reverse=True)
    best = grid_results[0]

    # ---- 2. Walk-forward validation ----
    is_bars  = int(_IS_YEARS * bpy)
    oos_bars = int(_OOS_YEARS * bpy)
    wf_step  = int(_STEP_YEARS * bpy)

    n = len(data)
    wf_results = []
    fold = 1
    start = 0
    while start + is_bars + oos_bars <= n:
        is_data  = data.iloc[start : start + is_bars]
        oos_data = data.iloc[start + is_bars : start + is_bars + oos_bars]

        is_grid = sorted(
            [r for r in (_run_one(strategy_key, symbol, is_data, p, capital, timeframe) for p in combos) if r["ok"]],
            key=lambda r: _score(r, objective),
            reverse=True,
        )

        if is_grid:
            best_is = is_grid[0]
            oos_res = _run_one(strategy_key, symbol, oos_data, best_is["params"], capital, timeframe)
            wf_results.append({
                "fold":           fold,
                "is_bars":        len(is_data),
                "oos_bars":       len(oos_data),
                "is_sharpe":      round(best_is["sharpe"], 4),
                "oos_sharpe":     round(oos_res["sharpe"], 4) if oos_res["ok"] else None,
                "best_is_params": best_is["params"],
                "is_cagr":        round(best_is["cagr"], 4),
                "oos_cagr":       round(oos_res["cagr"], 4) if oos_res["ok"] else None,
                "is_period":      f"{is_data.index[0].date()} → {is_data.index[-1].date()}",
                "oos_period":     f"{oos_data.index[0].date()} → {oos_data.index[-1].date()}",
            })

        start += wf_step
        fold  += 1

    # ---- 3. Overfitting score ----
    valid_wf = [
        w for w in wf_results
        if w["oos_sharpe"] is not None and w["is_sharpe"] > 0
    ]
    if valid_wf:
        ratios = [max(0.0, w["oos_sharpe"]) / w["is_sharpe"] for w in valid_wf]
        overfitting_score = round(sum(ratios) / len(ratios), 4)
        gate2_pass = bool(overfitting_score >= 0.70)
    else:
        overfitting_score = None
        gate2_pass = False

    # ---- 4. Stability map ----
    stability_map = _build_stability_map(strategy_key, grid_results)

    return {
        "strategy":          strategy_key,
        "symbol":            symbol,
        "timeframe":         timeframe,
        "objective":         objective,
        "total_combos":      len(combos),
        "valid_combos":      len(grid_results),
        "best_params":       best["params"],
        "best_sharpe":       round(best["sharpe"], 4),
        "best_cagr":         round(best["cagr"], 4),
        "best_max_drawdown": round(best["max_drawdown"], 4),
        "best_trade_count":  best["trade_count"],
        "grid_results":      grid_results,
        "walk_forward":      wf_results,
        "overfitting_score": overfitting_score,
        "gate2_pass":        gate2_pass,
        "stability_map":     stability_map,
    }
