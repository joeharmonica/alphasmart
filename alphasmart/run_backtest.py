#!/usr/bin/env python3
"""
AlphaSMART JSON bridge — called as subprocess by Next.js API routes.

Outputs one JSON object to stdout. All logs go to stderr (level WARNING+).

Modes:
    python run_backtest.py symbols
    python run_backtest.py strategies
    python run_backtest.py backtest <strategy> <symbol> <timeframe> [capital]
    python run_backtest.py summary
    python run_backtest.py optimize <strategy> <symbol> [timeframe]
    python run_backtest.py insights <strategy> <symbol> [timeframe]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

# Force ALL sub-module imports now so their module-level code (including
# setup_logger()) runs before we reconfigure loguru below.
import src.monitoring.logger          # noqa: F401 — triggers setup_logger()
import src.data.database              # noqa: F401
import src.backtest.engine            # noqa: F401
import src.backtest.runner            # noqa: F401
import src.backtest.optimizer         # noqa: F401
import src.backtest.simulation        # noqa: F401
import src.llm.client                 # noqa: F401
import api                            # noqa: F401

# Reconfigure loguru: send everything to stderr, suppress INFO noise.
# This overrides the stdout sink added by setup_logger() above.
from loguru import logger as _logger
_logger.remove()
_logger.add(sys.stderr, level="WARNING", colorize=False,
            format="{time:HH:mm:ss} | {level} | {message}")

# ---------------------------------------------------------------------------
# Public imports (modules now cached in sys.modules — no re-init)
# ---------------------------------------------------------------------------
from src.data.database import Database
from api import _run_backtest_sync, _run_summary_sync, _run_simulate_sync, _load_opt_params, _save_opt_params, STRATEGY_LABELS
from src.backtest.optimizer import run_optimization
from src.llm.client import analyze_backtest


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    args = sys.argv[1:]
    if not args:
        _err("Usage: run_backtest.py <mode> [args...]")

    mode = args[0]

    if mode == "symbols":
        db = Database(f"sqlite:///{ROOT / 'alphasmart_dev.db'}")
        rows = db.fetch_status()
        _out({
            "symbols": [
                {
                    "symbol": r["symbol"],
                    "timeframe": r["timeframe"],
                    "record_count": r["record_count"],
                    "last_fetched_at": str(r["last_fetched_at"]) if r["last_fetched_at"] else None,
                }
                for r in rows
            ]
        })

    elif mode == "strategies":
        from api import STRATEGY_MAP
        _out({
            "strategies": [
                {"key": k, "label": STRATEGY_LABELS[k]}
                for k in STRATEGY_MAP
            ]
        })

    elif mode == "backtest":
        if len(args) < 4:
            _err("Usage: run_backtest.py backtest <strategy> <symbol> <timeframe> [capital]")
        strategy = args[1]
        symbol = args[2]
        timeframe = args[3]
        capital = float(args[4]) if len(args) > 4 else 100_000.0
        result = _run_backtest_sync(strategy, symbol, timeframe, capital)
        _out(result)

    elif mode == "summary":
        result = _run_summary_sync()
        _out(result)

    elif mode == "cached-results":
        db = Database(f"sqlite:///{ROOT / 'alphasmart_dev.db'}")
        rows = db.query_cache_results()
        if not rows:
            _out({"results": [], "cached": False, "total_runs": 0, "gate1_passes": 0})
        else:
            for r in rows:
                r["strategy_label"] = STRATEGY_LABELS.get(r["strategy"], r["strategy"])
            gate1 = sum(1 for r in rows if r.get("gate1_pass"))
            _out({
                "results": rows,
                "cached": True,
                "total_runs": len(rows),
                "gate1_passes": gate1,
                "cached_at": rows[0].get("run_at") if rows else None,
            })

    elif mode == "optimize":
        if len(args) < 3:
            _err("Usage: run_backtest.py optimize <strategy> <symbol> [timeframe] [objective]")
        strategy  = args[1]
        symbol    = args[2]
        timeframe = args[3] if len(args) > 3 else "1d"
        objective = args[4] if len(args) > 4 else "sharpe"
        db_url    = f"sqlite:///{ROOT / 'alphasmart_dev.db'}"
        result    = run_optimization(strategy, symbol, timeframe, db_url, objective=objective)
        _out(result)

    elif mode == "simulate":
        if len(args) < 3:
            _err("Usage: run_backtest.py simulate <strategy> <symbol> [timeframe] [sim_type] [n_sims]")
        strategy  = args[1]
        symbol    = args[2]
        timeframe = args[3] if len(args) > 3 else "1d"
        sim_type  = args[4] if len(args) > 4 else "block_bootstrap"
        n_sims    = int(args[5]) if len(args) > 5 else 50
        capital   = float(args[6]) if len(args) > 6 else 100_000.0
        result    = _run_simulate_sync(strategy, symbol, timeframe, sim_type, n_sims, capital)
        _out(result)

    elif mode == "insights":
        if len(args) < 3:
            _err("Usage: run_backtest.py insights <strategy> <symbol> [timeframe]")
        strategy  = args[1]
        symbol    = args[2]
        timeframe = args[3] if len(args) > 3 else "1d"
        # Run backtest first to get fresh metrics + equity curve
        bt = _run_backtest_sync(strategy, symbol, timeframe, 100_000.0)
        if "error" in bt:
            _out({"error": bt["error"]})
        strategy_label = STRATEGY_LABELS.get(strategy, strategy)  # type: ignore[attr-defined]
        try:
            insights = analyze_backtest(
                strategy_key=strategy,
                strategy_label=strategy_label,
                symbol=symbol,
                metrics=bt["metrics"],
                equity_curve=bt["equity_curve"],
                optimization=None,  # insights run without pre-computed opt
            )
            _out({"insights": insights, "strategy": strategy, "symbol": symbol})
        except RuntimeError as e:
            # ANTHROPIC_API_KEY not set
            _out({"error": str(e), "needs_api_key": True})

    elif mode == "load_opt_params":
        _out(_load_opt_params())

    elif mode == "save_opt_params":
        # args: strategy symbol timeframe objective params_json sharpe cagr max_drawdown gate2_pass
        if len(args) < 10:
            _err("Usage: save_opt_params <strategy> <symbol> <timeframe> <objective> <params_json> <sharpe> <cagr> <max_drawdown> <gate2_pass>")
        import json as _j
        _save_opt_params(
            strategy=args[1],
            symbol=args[2],
            timeframe=args[3],
            objective=args[4],
            params=_j.loads(args[5]),
            sharpe=float(args[6]),
            cagr=float(args[7]),
            max_drawdown=float(args[8]),
            gate2_pass=args[9].lower() in ("true", "1", "yes"),
        )
        _out({"ok": True})

    else:
        _err(f"Unknown mode: {mode}")


class _NumpyEncoder(json.JSONEncoder):
    """Serialize numpy scalars and sanitize non-finite floats."""
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                v = float(obj)
                if not (v == v) or v == float("inf") or v == float("-inf"):  # nan or inf
                    return None
                return v
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        return super().default(obj)

    def iterencode(self, obj, _one_shot=False):
        """Replace any remaining Python inf/nan before encoding."""
        def _sanitize(o):
            if isinstance(o, float):
                if not (o == o) or o == float("inf") or o == float("-inf"):
                    return None
                return o
            if isinstance(o, dict):
                return {k: _sanitize(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [_sanitize(v) for v in o]
            return o
        return super().iterencode(_sanitize(obj), _one_shot)


def _out(data: dict) -> None:
    print(json.dumps(data, cls=_NumpyEncoder), flush=True)
    sys.exit(0)


def _err(msg: str) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
