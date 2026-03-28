"""
Bootstrapping simulation module for AlphaSMART.

Implements three resampling methods to generate synthetic price series from
limited historical data, producing a distribution of backtest outcomes rather
than a single point estimate:

  1. Block Bootstrap  — Samples overlapping blocks of returns, preserving local
                        autocorrelation. Reconstructs a synthetic OHLCV series.
                        Pros: Distribution-free, respects return clustering.

  2. Jackknife        — Leave-one-block-out: iteratively removes each calendar
                        block (default: monthly), re-runs backtest, measures
                        sensitivity. Identifies fragile periods.

  3. Monte Carlo (GBM) — Fits mu and sigma from historical log-returns, then
                         simulates N paths via Geometric Brownian Motion.
                         Pros: Fast, parametric, good for what-if scenarios.

All simulations maintain the bar-level structure of the original data (same index
length) so the backtest engine runs unchanged.

No lookahead: simulated datasets are fully formed before backtesting — the engine
only sees data[0:i+1] at each step.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd



# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SimulationResult:
    """Distribution of metrics across all simulated paths."""
    strategy_key: str
    symbol: str
    timeframe: str
    simulation_type: str
    n_simulations: int

    original_metrics: dict          # metrics from the real historical data
    sim_sharpes: list[float]
    sim_cagrs: list[float]
    sim_max_drawdowns: list[float]
    sim_win_rates: list[float]
    sim_trade_counts: list[int]

    percentiles: dict = field(default_factory=dict)  # populated by _compute_percentiles()

    def to_dict(self) -> dict:
        self._compute_percentiles()
        return {
            "strategy_key":      self.strategy_key,
            "symbol":            self.symbol,
            "timeframe":         self.timeframe,
            "simulation_type":   self.simulation_type,
            "n_simulations":     self.n_simulations,
            "original_metrics":  self.original_metrics,
            "percentiles":       self.percentiles,
            "sim_sharpes":       [round(v, 4) for v in self.sim_sharpes],
            "sim_cagrs":         [round(v, 4) for v in self.sim_cagrs],
            "sim_max_drawdowns": [round(v, 4) for v in self.sim_max_drawdowns],
            "sim_win_rates":     [round(v, 4) for v in self.sim_win_rates],
            "sim_trade_counts":  self.sim_trade_counts,
        }

    def _compute_percentiles(self) -> None:
        def pcts(vals: list[float]) -> dict:
            if not vals:
                return {}
            arr = np.array(vals)
            arr = arr[~np.isnan(arr)]
            if len(arr) == 0:
                return {}
            return {
                "p5":   round(float(np.percentile(arr, 5)), 4),
                "p25":  round(float(np.percentile(arr, 25)), 4),
                "p50":  round(float(np.percentile(arr, 50)), 4),
                "p75":  round(float(np.percentile(arr, 75)), 4),
                "p95":  round(float(np.percentile(arr, 95)), 4),
                "mean": round(float(np.mean(arr)), 4),
                "std":  round(float(np.std(arr)), 4),
            }

        self.percentiles = {
            "sharpe":       pcts(self.sim_sharpes),
            "cagr":         pcts(self.sim_cagrs),
            "max_drawdown": pcts(self.sim_max_drawdowns),
            "win_rate":     pcts(self.sim_win_rates),
        }


# ---------------------------------------------------------------------------
# Resampling helpers
# ---------------------------------------------------------------------------

def _reconstruct_ohlcv(original: pd.DataFrame, new_returns: np.ndarray) -> pd.DataFrame:
    """
    Reconstruct a synthetic OHLCV DataFrame from a resampled returns array.

    Strategy:
      - Synthesise close prices from the resampled returns, anchored at original close[0].
      - Approximate OHLV by scaling bar body proportions from the original data.
      - Preserve volume by resampling from original volume values.
    """
    n = len(new_returns)
    orig_n = len(original)

    # Reconstruct close prices
    start_price = float(original["close"].iloc[0])
    closes = np.zeros(n)
    closes[0] = start_price
    for i in range(1, n):
        closes[i] = closes[i - 1] * (1.0 + new_returns[i - 1])
    closes = np.maximum(closes, 0.01)  # prevent zero/negative

    # Compute original bar proportions: high/close and low/close ratios
    orig_highs = (original["high"] / original["close"]).clip(1.0, 1.5).values
    orig_lows = (original["low"] / original["close"]).clip(0.5, 1.0).values
    orig_opens = (original["open"] / original["close"]).clip(0.5, 1.5).values

    # Randomly sample bar proportions from original (with replacement)
    rng = np.random.default_rng()
    idx = rng.integers(0, orig_n, size=n)
    highs = closes * orig_highs[idx]
    lows = closes * orig_lows[idx]
    opens = closes * orig_opens[idx]

    # Resample volume from original
    volumes = original["volume"].values[rng.integers(0, orig_n, size=n)]

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=original.index[:n],
    )


def block_bootstrap(
    data: pd.DataFrame,
    n_simulations: int = 100,
    block_size: int = 20,
    seed: int | None = None,
) -> list[pd.DataFrame]:
    """
    Circular block bootstrap on log-returns.

    Samples non-overlapping blocks of `block_size` returns with replacement,
    concatenating them to form a synthetic series of the same length as `data`.

    Preserves short-term autocorrelation structure (volatility clustering).
    """
    rng = np.random.default_rng(seed)
    log_returns = np.log(data["close"] / data["close"].shift(1)).dropna().values
    n = len(log_returns)

    if n < block_size * 2:
        block_size = max(1, n // 10)

    n_blocks = math.ceil(n / block_size)
    datasets = []

    for _ in range(n_simulations):
        # Sample block start indices with replacement (circular)
        starts = rng.integers(0, n, size=n_blocks)
        sampled = []
        for s in starts:
            end = s + block_size
            if end <= n:
                sampled.extend(log_returns[s:end])
            else:
                # Wrap around (circular)
                sampled.extend(log_returns[s:])
                sampled.extend(log_returns[: end - n])

        resampled_returns = np.array(sampled[:n])
        # Convert log returns → simple returns
        simple_returns = np.exp(resampled_returns) - 1.0
        datasets.append(_reconstruct_ohlcv(data, simple_returns))

    return datasets


def jackknife_resample(
    data: pd.DataFrame,
    block_size_bars: int = 21,   # ~1 month of daily bars
) -> list[pd.DataFrame]:
    """
    Jackknife resampling: leave out each block of `block_size_bars` consecutive bars.

    Returns one dataset per jackknife fold (n // block_size folds total).
    Each dataset is the original minus the omitted block, preserving time order.
    Used to measure strategy sensitivity to specific market periods.
    """
    n = len(data)
    n_blocks = n // block_size_bars
    datasets = []

    for b in range(n_blocks):
        start_drop = b * block_size_bars
        end_drop = start_drop + block_size_bars
        # Concatenate before and after the dropped block
        kept = pd.concat([
            data.iloc[:start_drop],
            data.iloc[end_drop:],
        ])
        if len(kept) >= 50:  # need minimum bars to run backtest
            datasets.append(kept.reset_index(drop=False))

    # Restore DatetimeIndex properly
    result = []
    for ds in datasets:
        if "index" in ds.columns:
            ds = ds.set_index("index")
            ds.index.name = None
        result.append(ds)

    return result


def monte_carlo_gbm(
    data: pd.DataFrame,
    n_simulations: int = 100,
    seed: int | None = None,
) -> list[pd.DataFrame]:
    """
    Monte Carlo simulation via Geometric Brownian Motion.

    Fits mu (annualised drift) and sigma (annualised volatility) from historical
    log-returns, then simulates N synthetic paths of the same length.

    GBM: dS = mu*S*dt + sigma*S*dW  where dW ~ N(0, sqrt(dt))

    Note: GBM assumes i.i.d. returns and log-normal prices. It underestimates
    fat tails and volatility clustering, but is fast and parametric.
    """
    rng = np.random.default_rng(seed)
    log_returns = np.log(data["close"] / data["close"].shift(1)).dropna().values
    n = len(log_returns)

    if n < 10:
        return []

    # Fit parameters from historical data
    mu_per_bar = float(np.mean(log_returns))
    sigma_per_bar = float(np.std(log_returns, ddof=1))

    datasets = []
    for _ in range(n_simulations):
        # Simulate log returns: mu - 0.5*sigma^2 + sigma*Z
        drift = mu_per_bar - 0.5 * sigma_per_bar ** 2
        noise = rng.normal(0, sigma_per_bar, size=n)
        sim_log_returns = drift + noise
        simple_returns = np.exp(sim_log_returns) - 1.0
        datasets.append(_reconstruct_ohlcv(data, simple_returns))

    return datasets


# ---------------------------------------------------------------------------
# Public runner
# ---------------------------------------------------------------------------

def run_simulation(
    strategy_key: str,
    symbol: str,
    data: pd.DataFrame,
    simulation_type: Literal["block_bootstrap", "jackknife", "monte_carlo"],
    n_simulations: int,
    params: dict,
    capital: float,
    timeframe: str = "1d",
) -> SimulationResult:
    """
    Run a strategy across N simulated price datasets and collect metric distributions.

    Args:
        strategy_key:     Strategy identifier (e.g. "ema_crossover")
        symbol:           Asset symbol
        data:             Original OHLCV DataFrame (historical data)
        simulation_type:  "block_bootstrap", "jackknife", or "monte_carlo"
        n_simulations:    Number of synthetic datasets to generate
        params:           Strategy parameters dict
        capital:          Starting capital
        timeframe:        Bar interval for correct annualisation

    Returns:
        SimulationResult with metric distributions and percentiles
    """
    from src.backtest.optimizer import _make_strategy, _run_one_on_data

    # Generate synthetic datasets
    if simulation_type == "block_bootstrap":
        block_size = max(5, len(data) // 50)
        datasets = block_bootstrap(data, n_simulations=n_simulations, block_size=block_size)
    elif simulation_type == "jackknife":
        block_size = max(5, len(data) // 20)
        datasets = jackknife_resample(data, block_size_bars=block_size)
        n_simulations = len(datasets)
    elif simulation_type == "monte_carlo":
        datasets = monte_carlo_gbm(data, n_simulations=n_simulations)
    else:
        raise ValueError(f"Unknown simulation_type: {simulation_type}")

    if not datasets:
        raise ValueError("Simulation produced no datasets")

    # Run original backtest for baseline
    original_result = _run_one_on_data(strategy_key, symbol, data, params, capital, timeframe)
    original_metrics = {
        "sharpe":       original_result.get("sharpe", 0.0),
        "cagr":         original_result.get("cagr", 0.0),
        "max_drawdown": original_result.get("max_drawdown", 0.0),
        "win_rate":     original_result.get("win_rate", 0.0),
        "trade_count":  original_result.get("trade_count", 0),
    }

    # Run backtest on each synthetic dataset
    sim_sharpes, sim_cagrs, sim_mdd, sim_wr, sim_tc = [], [], [], [], []

    for ds in datasets:
        if len(ds) < 30:
            continue
        r = _run_one_on_data(strategy_key, symbol, ds, params, capital, timeframe)
        if r.get("ok", False):
            sim_sharpes.append(r["sharpe"])
            sim_cagrs.append(r["cagr"])
            sim_mdd.append(r["max_drawdown"])
            sim_wr.append(r["win_rate"])
            sim_tc.append(r["trade_count"])

    return SimulationResult(
        strategy_key=strategy_key,
        symbol=symbol,
        timeframe=timeframe,
        simulation_type=simulation_type,
        n_simulations=len(sim_sharpes),
        original_metrics=original_metrics,
        sim_sharpes=sim_sharpes,
        sim_cagrs=sim_cagrs,
        sim_max_drawdowns=sim_mdd,
        sim_win_rates=sim_wr,
        sim_trade_counts=sim_tc,
    )
