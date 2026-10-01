"""
AlphaSmart Trader — simulated paper-trade runner.

A deliberately broker-less paper loop: fills are simulated at the latest
close (± cost bps) against a local simulated account. This keeps the
Trader's forward test fully isolated from the production Alpaca paper
account that equity_xsec_momentum_B trades (lessons.md #60: diagnostics
must never be able to corrupt live state).

State (all under reports/paper_trade/state/, separate channel):
    alphasmart_trader.json           — current sim account (cash, positions)
    alphasmart_trader.equity.jsonl   — daily mark-to-market history
    alphasmart_trader.trades.jsonl   — every simulated fill + rationale
    trader_method.json               — active method selection (set from UI)

Event log: ShadowLog channel "alphasmart_trader" under
reports/paper_trade/<date>/ — same forensic format as the live book.

CLI (run daily by scheduler; also invoked one-shot):
    python -m src.trader.paper_runner run [--no-fetch] [--force-rebalance]
    python -m src.trader.paper_runner status
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from src.data.database import Database
from src.execution.shadow_log import ShadowLog
from src.trader.backtest import SIGNALS, TraderConfig, load_closes
from src.trader.methods import DEFAULT_METHOD, get_method
from src.trader.universe import MARKET_SYMBOLS

STATE_ROOT = _ROOT.parent / "reports" / "paper_trade" / "state"
CHANNEL = "alphasmart_trader"
INITIAL_CASH = 100_000.0
COST_BPS = 5.0


# ---------------------------------------------------------------------------
# Sim account
# ---------------------------------------------------------------------------

@dataclass
class SimAccount:
    cash: float = INITIAL_CASH
    positions: dict[str, float] = field(default_factory=dict)  # symbol -> signed qty
    method_id: str = DEFAULT_METHOD
    inception_utc: str = ""
    last_rebalance_utc: Optional[str] = None
    last_rebalance_date: Optional[str] = None   # bar date of last rebalance
    last_long_book: list[str] = field(default_factory=list)
    last_mark_utc: Optional[str] = None
    peak_equity: float = 0.0            # highest equity seen; drives the
                                         # drawdown circuit breaker below
    halt_remaining_days: int = 0        # >0 while cooling down from a
                                         # drawdown halt (no trading, flat)

    def equity(self, prices: dict[str, float]) -> float:
        pos_val = sum(q * prices.get(s, 0.0) for s, q in self.positions.items())
        return self.cash + pos_val


def _state_path() -> Path:
    return STATE_ROOT / f"{CHANNEL}.json"


def load_account() -> SimAccount:
    p = _state_path()
    if not p.exists():
        return SimAccount(inception_utc=datetime.now(timezone.utc).isoformat())
    d = json.loads(p.read_text())
    return SimAccount(**d)


def save_account(acct: SimAccount) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(acct), indent=2))
    tmp.replace(_state_path())


def _append_jsonl(name: str, rec: dict) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with (STATE_ROOT / name).open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def active_method_id() -> str:
    p = STATE_ROOT / "trader_method.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("method_id", DEFAULT_METHOD)
        except json.JSONDecodeError:
            pass
    return DEFAULT_METHOD


# ---------------------------------------------------------------------------
# Signal → target weights (same math as the backtest engine's loop body)
# ---------------------------------------------------------------------------

def compute_targets(
    closes: pd.DataFrame, cfg: TraderConfig
) -> tuple[dict[str, float], dict]:
    """Target weights at the LATEST bar + a rationale/context dict."""
    tradeable = [c for c in closes.columns if c not in ("SPY", "QQQ")]
    px = closes[tradeable]
    scores = SIGNALS[cfg.signal](px, **cfg.signal_params)

    valid_counts = px.notna().rolling(cfg.min_history, min_periods=1).count().iloc[-1]
    s = scores.iloc[-1][valid_counts >= cfg.min_history].dropna()
    if len(s) < cfg.long_k + cfg.short_k + 2:
        return {}, {"error": f"only {len(s)} valid symbols"}

    risk_on = True
    if cfg.regime_symbol in closes.columns:
        reg = closes[cfg.regime_symbol].dropna()
        if len(reg) >= cfg.regime_ma:
            risk_on = bool(reg.iloc[-1] > reg.rolling(cfg.regime_ma).mean().iloc[-1])

    gl, gs = cfg.gross_long, cfg.gross_short
    if cfg.regime_rule == "defensive" and not risk_on:
        gl, gs = cfg.gross_long * 0.5, cfg.gross_long * 0.5
    elif cfg.regime_rule == "long_flat" and not risk_on:
        gl = 0.0
    elif cfg.regime_rule == "hedge":
        if risk_on:
            gs = 0.0
        else:
            gl = cfg.gross_long * 0.5

    longs = s.nlargest(cfg.long_k)
    shorts = s.nsmallest(cfg.short_k)
    weights: dict[str, float] = {}
    if cfg.long_k > 0 and gl > 0:
        for sym in longs.index:
            weights[sym] = gl / cfg.long_k
    if cfg.short_k > 0 and gs > 0:
        for sym in shorts.index:
            weights[sym] = weights.get(sym, 0.0) - gs / cfg.short_k

    regime_tag = "risk_on" if risk_on else "risk_off"
    context = {
        "regime": regime_tag,
        "gross_long": gl,
        "gross_short": gs,
        "long_book": list(longs.index),
        "short_book": list(shorts.index) if gs > 0 else [],
        "scores": {k: round(float(v), 4) for k, v in pd.concat([longs, shorts]).items()},
        "rationale": (
            f"{cfg.signal} targets: long top {cfg.long_k} ({', '.join(longs.index)})"
            + (f", short bottom {cfg.short_k} ({', '.join(shorts.index)})" if gs > 0 else ", short book OFF")
            + f"; regime {regime_tag} (SPY {'>' if risk_on else '<'} {cfg.regime_ma}d MA)"
            + f" → gross {gl:.0%}L / {gs:.0%}S."
        ),
    }
    return weights, context


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def fetch_universe(db: Database, symbols: list[str], log: ShadowLog) -> None:
    """Best-effort incremental fetch (last ~2 months) for the trader universe."""
    from src.data.fetcher import StockDataFetcher
    fetcher = StockDataFetcher()
    errors = []
    for sym in symbols:
        try:
            df = fetcher.get_ohlcv(sym, period="2mo", interval="1d")
            if getattr(df.index, "tz", None) is not None:
                df.index = df.index.tz_localize(None)
            if not df.empty:
                db.upsert_ohlcv(df, symbol=sym, timeframe="1d", source="yfinance")
        except Exception as exc:
            errors.append(f"{sym}: {exc}")
    log.event("trader_fetch", {"n_symbols": len(symbols), "n_errors": len(errors),
                               "errors": errors[:5]},
              level="warn" if errors else "info")


def trading_days_since(closes: pd.DataFrame, date_str: Optional[str]) -> int:
    if not date_str:
        return 10 ** 6
    try:
        anchor = pd.Timestamp(date_str)
    except ValueError:
        return 10 ** 6
    return int((closes.index > anchor).sum())


def cmd_run(args: argparse.Namespace) -> int:
    log = ShadowLog(channel=CHANNEL)
    method_id = active_method_id()
    cfg, universe = get_method(method_id)
    db = Database(f"sqlite:///{_ROOT / 'alphasmart_dev.db'}")

    symbols = sorted(set(universe) | set(MARKET_SYMBOLS))
    if not args.no_fetch:
        fetch_universe(db, symbols, log)

    closes = load_closes(db, symbols)
    closes = closes[closes.index >= closes.index[-1] - pd.Timedelta(days=900)]
    latest_bar = closes.index[-1]
    prices = {s: float(closes[s].dropna().iloc[-1])
              for s in closes.columns if closes[s].notna().any()}

    # Data freshness guard: latest bar must be < 5 calendar days old
    age_days = (pd.Timestamp.now() - latest_bar).days
    if age_days > 5:
        log.event("trader_halt", {"reason": f"stale data: latest bar {latest_bar.date()} "
                                            f"is {age_days}d old"}, level="error")
        print(json.dumps({"status": "halted", "reason": "stale_data",
                          "latest_bar": str(latest_bar.date())}))
        return 1

    acct = load_account()
    acct.method_id = method_id
    equity_before = acct.equity(prices)

    # ---- Portfolio drawdown circuit breaker (mirrors the backtest engine's
    # max_drawdown_halt / halt_cooldown_bars, validated by walk-forward
    # before deployment — see tasks/lessons.md). Checked BEFORE the signal
    # is even computed: while cooling down, or the instant a breach fires,
    # the book stays flat and no rebalance trigger is evaluated. ----
    if acct.peak_equity <= 0:
        acct.peak_equity = equity_before

    if acct.halt_remaining_days > 0:
        acct.halt_remaining_days -= 1
        if acct.halt_remaining_days == 0:
            # Cooldown just ended: reset the peak to today's equity rather
            # than the stale pre-halt peak, or a drawdown computed against
            # that old peak would immediately re-trigger the halt forever.
            acct.peak_equity = equity_before
        acct.last_mark_utc = datetime.now(timezone.utc).isoformat()
        save_account(acct)
        mark = {
            "ts_utc": acct.last_mark_utc, "bar_date": str(latest_bar.date()),
            "equity": round(equity_before, 2), "cash": round(acct.cash, 2),
            "n_long": sum(1 for q in acct.positions.values() if q > 0),
            "n_short": sum(1 for q in acct.positions.values() if q < 0),
            "regime": None, "method_id": method_id, "rebalanced": False,
            "halted": True, "halt_remaining_days": acct.halt_remaining_days,
        }
        _append_jsonl(f"{CHANNEL}.equity.jsonl", mark)
        log.event("trader_halt_continue", mark, level="warn")
        print(json.dumps({"status": "halted", "reason": "drawdown_cooldown",
                          "halt_remaining_days": acct.halt_remaining_days,
                          "equity": round(equity_before, 2)}))
        return 0

    acct.peak_equity = max(acct.peak_equity, equity_before)
    if cfg.max_drawdown_halt is not None and acct.peak_equity > 0:
        dd = 1.0 - equity_before / acct.peak_equity
        if dd >= cfg.max_drawdown_halt:
            for sym, qty in list(acct.positions.items()):
                px_ = prices.get(sym)
                if px_ is None or qty == 0:
                    continue
                fill_px = px_ * (1 - COST_BPS / 1e4) if qty > 0 else px_ * (1 + COST_BPS / 1e4)
                acct.cash += qty * fill_px
                _append_jsonl(f"{CHANNEL}.trades.jsonl", {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "bar_date": str(latest_bar.date()), "symbol": sym,
                    "side": "sell" if qty > 0 else "buy", "qty": round(abs(qty), 4),
                    "fill_price": round(fill_px, 4), "notional": round(abs(qty) * fill_px, 2),
                    "position_after": 0.0, "direction_after": "flat",
                    "trigger": "drawdown_halt", "method_id": method_id,
                    "rationale": f"drawdown {dd:.1%} >= halt threshold "
                                 f"{cfg.max_drawdown_halt:.1%} — flattening.",
                })
            acct.positions = {}
            acct.halt_remaining_days = cfg.halt_cooldown_bars
            equity_after = acct.equity(prices)
            acct.last_mark_utc = datetime.now(timezone.utc).isoformat()
            save_account(acct)
            mark = {
                "ts_utc": acct.last_mark_utc, "bar_date": str(latest_bar.date()),
                "equity": round(equity_after, 2), "cash": round(acct.cash, 2),
                "n_long": 0, "n_short": 0, "regime": None, "method_id": method_id,
                "rebalanced": False, "halted": True,
                "halt_remaining_days": acct.halt_remaining_days,
            }
            _append_jsonl(f"{CHANNEL}.equity.jsonl", mark)
            log.event("trader_drawdown_halt", {
                "drawdown": round(dd, 4), "threshold": cfg.max_drawdown_halt,
                "peak_equity": round(acct.peak_equity, 2),
                "equity": round(equity_after, 2),
                "halt_days": cfg.halt_cooldown_bars,
            }, level="error")
            print(json.dumps({"status": "halted", "reason": "drawdown_breach",
                              "drawdown": round(dd, 4), "halt_days": cfg.halt_cooldown_bars,
                              "equity": round(equity_after, 2)}))
            return 0

    weights, context = compute_targets(closes, cfg)
    if not weights and "error" in context:
        log.event("trader_halt", {"reason": context["error"]}, level="error")
        print(json.dumps({"status": "halted", "reason": context["error"]}))
        return 1

    # ---- Trigger evaluation ----
    # Top-5 targets are computed and logged every run (see trader_evaluate
    # below), but a rebalance only executes on cfg.rebal_days cadence — the
    # book is checked daily, not traded daily.
    tds = trading_days_since(closes, acct.last_rebalance_date)
    new_long_book = context["long_book"]
    rotation = sorted(new_long_book) != sorted(acct.last_long_book)
    trigger = None
    if args.force_rebalance:
        trigger = "forced"
    elif acct.last_rebalance_date is None:
        trigger = "first_run"
    elif tds >= cfg.rebal_days:
        trigger = f"cadence ({tds} trading days ≥ {cfg.rebal_days})"

    log.event("trader_evaluate", {
        "method_id": method_id, "latest_bar": str(latest_bar.date()),
        "equity": round(equity_before, 2), "trigger": trigger,
        "trading_days_since_rebalance": tds, **context,
    })

    executed = False
    fills = []
    if trigger:
        # Simulate fills: move positions to target qty at latest close ± cost
        target_qty = {s: (w * equity_before) / prices[s]
                      for s, w in weights.items() if s in prices}
        all_syms = set(target_qty) | set(acct.positions)
        for sym in sorted(all_syms):
            cur = acct.positions.get(sym, 0.0)
            tgt = target_qty.get(sym, 0.0)
            dq = tgt - cur
            px = prices.get(sym)
            if px is None or abs(dq * px) < 0.001 * equity_before:
                continue
            side = "buy" if dq > 0 else "sell"
            fill_px = px * (1 + COST_BPS / 1e4) if dq > 0 else px * (1 - COST_BPS / 1e4)
            acct.cash -= dq * fill_px
            new_qty = round(cur + dq, 6)
            if abs(new_qty) < 1e-9:
                acct.positions.pop(sym, None)
            else:
                acct.positions[sym] = new_qty
            fill = {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "bar_date": str(latest_bar.date()),
                "symbol": sym, "side": side,
                "qty": round(abs(dq), 4), "fill_price": round(fill_px, 4),
                "notional": round(abs(dq) * fill_px, 2),
                "position_after": round(new_qty, 4),
                "direction_after": ("long" if new_qty > 0 else
                                    "short" if new_qty < 0 else "flat"),
                "trigger": trigger,
                "method_id": method_id,
                "rationale": context["rationale"],
            }
            fills.append(fill)
            _append_jsonl(f"{CHANNEL}.trades.jsonl", fill)

        now_iso = datetime.now(timezone.utc).isoformat()
        acct.last_rebalance_utc = now_iso
        acct.last_rebalance_date = str(latest_bar.date())
        acct.last_long_book = new_long_book
        executed = True
        log.event("trader_rebalance", {
            "trigger": trigger, "n_fills": len(fills),
            "target_weights": {k: round(v, 4) for k, v in weights.items()},
            "equity": round(acct.equity(prices), 2),
            "rationale": context["rationale"],
        })

    # ---- Daily mark-to-market ----
    equity_after = acct.equity(prices)
    acct.last_mark_utc = datetime.now(timezone.utc).isoformat()
    save_account(acct)
    mark = {
        "ts_utc": acct.last_mark_utc,
        "bar_date": str(latest_bar.date()),
        "equity": round(equity_after, 2),
        "cash": round(acct.cash, 2),
        "n_long": sum(1 for q in acct.positions.values() if q > 0),
        "n_short": sum(1 for q in acct.positions.values() if q < 0),
        "regime": context["regime"],
        "method_id": method_id,
        "rebalanced": executed,
    }
    _append_jsonl(f"{CHANNEL}.equity.jsonl", mark)
    log.event("trader_mark", mark)

    print(json.dumps({
        "status": "ok", "trigger": trigger, "executed": executed,
        "n_fills": len(fills), "equity": round(equity_after, 2),
        "positions": {s: round(q, 4) for s, q in sorted(acct.positions.items())},
        "regime": context["regime"], "method_id": method_id,
    }, indent=2))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    acct = load_account()
    print(json.dumps(asdict(acct), indent=2))
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="trader.paper_runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="Evaluate triggers, maybe rebalance, mark to market.")
    p_run.add_argument("--no-fetch", action="store_true",
                       help="Skip the incremental yfinance fetch (use DB as-is).")
    p_run.add_argument("--force-rebalance", action="store_true")
    p_run.set_defaults(fn=cmd_run)
    p_st = sub.add_parser("status")
    p_st.set_defaults(fn=cmd_status)
    args = ap.parse_args()
    raise SystemExit(args.fn(args))


if __name__ == "__main__":
    main()
