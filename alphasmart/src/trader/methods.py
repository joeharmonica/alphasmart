"""
AlphaSmart Trader — method registry.

Single source of truth for every backtestable/paper-tradeable Trader
method. The backtest grid (scripts/run_trader_backtests.py) and the
paper runner (src/trader/paper_runner.py) both read from here, so the
method selected in the dashboard is guaranteed to be the method that
was backtested.
"""
from __future__ import annotations

from src.trader.backtest import TraderConfig
from src.trader.universe import CORE_EQUITIES, EXTENDED_EQUITIES

DEFAULT_METHOD = "wk_dual_momo_hedged"


def all_methods() -> list[tuple[TraderConfig, list[str]]]:
    """(config, universe) pairs to run."""
    ext = EXTENDED_EQUITIES
    core = CORE_EQUITIES
    return [
        # ---- Benchmark: the live paper-trade book, same engine/costs ----
        (TraderConfig(
            method_id="baseline_monthly_momo",
            label="Baseline — monthly 126d momentum top-5 (live paper book)",
            description="Long-only cross-sectional 126d momentum, top-5 equal "
                        "weight, monthly rebalance, SPY>200dMA long/flat gate. "
                        "Mirrors equity_xsec_momentum_B through the Trader "
                        "engine + cost model (equities only, no SPY/QQQ legs).",
            signal="momentum", signal_params={"lookback": 126, "skip": 0},
            long_k=5, short_k=0, gross_long=1.0, gross_short=0.0,
            rebal_days=21, regime_rule="long_flat",
        ), core),

        # ---- Weekly long/short candidates on the extended universe ----
        (TraderConfig(
            method_id="wk_momo_rev_ls",
            label="Weekly momo+reversal L8/S4 (100/30)",
            description="z(63d momentum) + 0.5·z(5d reversal); long top 8, "
                        "short bottom 4; weekly; defensive regime scaling.",
            signal="momo_rev",
            signal_params={"momo_lookback": 63, "rev_lookback": 5, "rev_weight": 0.5},
            long_k=8, short_k=4, gross_long=1.0, gross_short=0.3,
            rebal_days=5, regime_rule="defensive",
        ), ext),

        (TraderConfig(
            method_id="wk_dual_momo_hedged",
            label="Monthly dual momentum L5, regime-hedged shorts (100/50)",
            description="Concentrated long top-5 dual momentum, checked "
                        "daily but only rebalanced at monthly cadence; "
                        "short book (bottom 5, 50% gross) only activates "
                        "when SPY < 200dMA, with the long book halved. "
                        "Long alpha + crash hedge.",
            signal="dual_momentum",
            signal_params={"fast": 63, "slow": 126, "rev_lookback": 5, "rev_weight": 0.3},
            long_k=5, short_k=5, gross_long=1.0, gross_short=0.5,
            rebal_days=21, regime_rule="hedge",
            max_drawdown_halt=0.20, halt_cooldown_bars=20,
        ), ext),

        (TraderConfig(
            method_id="wk_momo126_hedged",
            label="Weekly 126d momentum L5, regime-hedged shorts (100/50)",
            description="The live book's own 126d signal, run weekly on the "
                        "extended universe with a risk-off-only short book "
                        "(bottom 5, 50% gross) replacing the flat-to-cash gate.",
            signal="momentum", signal_params={"lookback": 126, "skip": 0},
            long_k=5, short_k=5, gross_long=1.0, gross_short=0.5,
            rebal_days=5, regime_rule="hedge",
        ), ext),

        (TraderConfig(
            method_id="wk_core_momo126_hedged",
            label="Weekly 126d momentum L5 on core 19, hedged shorts",
            description="Same as wk_momo126_hedged but restricted to the "
                        "existing 19-name core pool — isolates universe "
                        "breadth from cadence/short effects.",
            signal="momentum", signal_params={"lookback": 126, "skip": 0},
            long_k=5, short_k=5, gross_long=1.0, gross_short=0.5,
            rebal_days=5, regime_rule="hedge",
        ), core),

        (TraderConfig(
            method_id="wk_dual_momo_ls",
            label="Weekly dual momentum L8/S4 (100/30)",
            description="z(63d)+z(126d) momentum − 0.3·z(5d run-up); long top 8, "
                        "short bottom 4; weekly; defensive regime scaling.",
            signal="dual_momentum",
            signal_params={"fast": 63, "slow": 126, "rev_lookback": 5, "rev_weight": 0.3},
            long_k=8, short_k=4, gross_long=1.0, gross_short=0.3,
            rebal_days=5, regime_rule="defensive",
        ), ext),

        (TraderConfig(
            method_id="wk_dual_momo_concentrated",
            label="Weekly dual momentum L6/S3 (100/30) concentrated",
            description="Same dual-momentum composite, concentrated book: "
                        "long top 6, short bottom 3.",
            signal="dual_momentum",
            signal_params={"fast": 63, "slow": 126, "rev_lookback": 5, "rev_weight": 0.3},
            long_k=6, short_k=3, gross_long=1.0, gross_short=0.3,
            rebal_days=5, regime_rule="defensive",
        ), ext),

        (TraderConfig(
            method_id="biwk_dual_momo_ls",
            label="Biweekly dual momentum L8/S4 (100/30)",
            description="Dual-momentum composite at 10-day cadence — tests "
                        "whether the weekly edge survives at half the turnover.",
            signal="dual_momentum",
            signal_params={"fast": 63, "slow": 126, "rev_lookback": 5, "rev_weight": 0.3},
            long_k=8, short_k=4, gross_long=1.0, gross_short=0.3,
            rebal_days=10, regime_rule="defensive",
        ), ext),

        (TraderConfig(
            method_id="wk_voladj_momo_ls",
            label="Weekly vol-adjusted momentum L8/S4 (100/30)",
            description="63d momentum / 20d realised vol; long top 8, short "
                        "bottom 4; weekly; defensive regime scaling.",
            signal="vol_adj_momentum",
            signal_params={"lookback": 63, "vol_lookback": 20},
            long_k=8, short_k=4, gross_long=1.0, gross_short=0.3,
            rebal_days=5, regime_rule="defensive",
        ), ext),

        (TraderConfig(
            method_id="wk_reversal_mn",
            label="Weekly 5d reversal L6/S6 market-neutral (60/60)",
            description="Pure short-term reversal, market-neutral 60/60 — "
                        "control experiment for whether weekly reversal still "
                        "pays in large caps after costs.",
            signal="reversal", signal_params={"lookback": 5},
            long_k=6, short_k=6, gross_long=0.6, gross_short=0.6,
            rebal_days=5, regime_rule="none",
        ), ext),

        (TraderConfig(
            method_id="wk_pure_momo_ls",
            label="Weekly 126d momentum L8/S4 (100/30)",
            description="Plain 126d cross-sectional momentum long/short at "
                        "weekly cadence — isolates the value of the composite "
                        "signals vs the simple one.",
            signal="momentum", signal_params={"lookback": 126, "skip": 0},
            long_k=8, short_k=4, gross_long=1.0, gross_short=0.3,
            rebal_days=5, regime_rule="defensive",
        ), ext),
    ]


def get_method(method_id: str) -> tuple[TraderConfig, list[str]]:
    for cfg, universe in all_methods():
        if cfg.method_id == method_id:
            return cfg, universe
    raise KeyError(f"unknown trader method: {method_id}")
