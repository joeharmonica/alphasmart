"""
AlphaSmart Trader — long/short weekly-horizon portfolio backtester.

Differences vs the single-symbol engine in src/backtest/engine.py:
  * Portfolio-level: one weight vector across the whole universe per day.
  * Long AND short weights (negative = short).
  * Cost model suited to a weekly cadence: per-side bps on turnover
    notional + an annualised borrow fee on short notional.
  * Emits a full trade/rationale log per rebalance for the dashboard.

Lookahead discipline: scores are computed from closes up to and including
day t; the resulting weights earn returns from t+1 onward (weights are
shifted by one bar before being applied). Weights are held constant
between rebalances (periodic-rebalance approximation, same as the
xsec pipeline scripts).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_closes(db, symbols: list[str], timeframe: str = "1d") -> pd.DataFrame:
    """Wide close-price frame (columns=symbols) from the OHLCV DB."""
    frames = {}
    for sym in symbols:
        df = db.query_ohlcv(sym, timeframe=timeframe)
        if not df.empty:
            s = df["close"]
            s = s[~s.index.duplicated(keep="last")]
            frames[sym] = s
    closes = pd.DataFrame(frames).sort_index()
    # Drop days where fewer than 3 symbols traded (holiday stubs)
    closes = closes.dropna(how="all")
    return closes


def load_price_volume(db, symbols: list[str], timeframe: str = "1d"
                       ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(close, typical_price, volume) wide frames, aligned index — for VWAP."""
    close_f, typ_f, vol_f = {}, {}, {}
    for sym in symbols:
        df = db.query_ohlcv(sym, timeframe=timeframe)
        if df.empty:
            continue
        df = df[~df.index.duplicated(keep="last")]
        close_f[sym] = df["close"]
        typ_f[sym] = (df["high"] + df["low"] + df["close"]) / 3.0
        vol_f[sym] = df["volume"]
    closes = pd.DataFrame(close_f).sort_index().dropna(how="all")
    typical = pd.DataFrame(typ_f).sort_index().reindex(closes.index)
    volume = pd.DataFrame(vol_f).sort_index().reindex(closes.index)
    return closes, typical, volume


def compute_vwap(typical_price: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """Intraday VWAP per symbol, cumulative from each trading day's open."""
    day = typical_price.index.normalize()
    pv = typical_price * volume
    cum_pv = pv.groupby(day).cumsum()
    cum_vol = volume.groupby(day).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Cross-sectional score functions
# Each returns a DataFrame (dates × symbols): higher score = more long.
# ---------------------------------------------------------------------------

def _zscore_xs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def score_momentum(closes: pd.DataFrame, lookback: int = 126, skip: int = 0) -> pd.DataFrame:
    return closes.shift(skip) / closes.shift(skip + lookback) - 1.0


def score_reversal(closes: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Short-term reversal: recent losers score high (buy dips)."""
    return -(closes / closes.shift(lookback) - 1.0)


def score_momo_rev(
    closes: pd.DataFrame,
    momo_lookback: int = 63,
    rev_lookback: int = 5,
    rev_weight: float = 0.5,
) -> pd.DataFrame:
    """Composite: medium-term momentum, entry-timed by short-term reversal."""
    momo = _zscore_xs(score_momentum(closes, momo_lookback, 0))
    rev = _zscore_xs(score_reversal(closes, rev_lookback))
    return momo + rev_weight * rev


def score_dual_momentum(
    closes: pd.DataFrame,
    fast: int = 63,
    slow: int = 126,
    rev_lookback: int = 5,
    rev_weight: float = 0.3,
) -> pd.DataFrame:
    """z(fast momo) + z(slow momo) − rev_weight·z(recent run-up)."""
    f = _zscore_xs(score_momentum(closes, fast, 0))
    s = _zscore_xs(score_momentum(closes, slow, 0))
    r = _zscore_xs(score_reversal(closes, rev_lookback))
    return f + s + rev_weight * r


def score_vol_adj_momentum(
    closes: pd.DataFrame, lookback: int = 63, vol_lookback: int = 20
) -> pd.DataFrame:
    """Momentum scaled by inverse realised vol (quality trends rank higher)."""
    momo = score_momentum(closes, lookback, 0)
    vol = closes.pct_change().rolling(vol_lookback).std() * math.sqrt(TRADING_DAYS)
    return momo / vol.replace(0, np.nan)


def score_vwap_momentum(
    closes: pd.DataFrame, vwap: pd.DataFrame,
    mom_lookback: int = 10, dev_weight: float = 1.0,
) -> pd.DataFrame:
    """Trend-following day-trade signal: momentum confirmed by distance
    above/below the running intraday VWAP (breakout-with-the-trend)."""
    mom = _zscore_xs(score_momentum(closes, mom_lookback, 0))
    dev = _zscore_xs(closes / vwap - 1.0)
    return mom + dev_weight * dev


def score_vwap_reversion(
    closes: pd.DataFrame, vwap: pd.DataFrame,
    mom_lookback: int = 10, dev_weight: float = 1.0,
) -> pd.DataFrame:
    """Mean-reversion day-trade signal: fade extension away from VWAP,
    lightly confirmed by momentum having stalled/reversed."""
    mom = _zscore_xs(score_momentum(closes, mom_lookback, 0))
    dev = _zscore_xs(closes / vwap - 1.0)
    return -dev + dev_weight * -mom


def score_vwap_volume_breakout(
    closes: pd.DataFrame, vwap: pd.DataFrame, volume: pd.DataFrame,
    mom_lookback: int = 10, vol_lookback: int = 20, dev_weight: float = 1.0,
) -> pd.DataFrame:
    """Breakout above/below VWAP confirmed by a volume surge vs its own
    rolling average (classic day-trade breakout filter)."""
    mom = _zscore_xs(score_momentum(closes, mom_lookback, 0))
    dev = _zscore_xs(closes / vwap - 1.0)
    vol_ratio = volume / volume.rolling(vol_lookback).mean().replace(0, np.nan)
    vol_z = _zscore_xs(vol_ratio.clip(upper=vol_ratio.quantile(0.95, axis=1), axis=0))
    return mom + dev_weight * dev + 0.5 * vol_z.clip(lower=0)


SIGNALS: dict[str, Callable[..., pd.DataFrame]] = {
    "momentum": score_momentum,
    "reversal": score_reversal,
    "momo_rev": score_momo_rev,
    "dual_momentum": score_dual_momentum,
    "vol_adj_momentum": score_vol_adj_momentum,
    "vwap_momentum": score_vwap_momentum,
    "vwap_reversion": score_vwap_reversion,
    "vwap_volume_breakout": score_vwap_volume_breakout,
}

# Signals whose function needs the VWAP frame (and, for one, raw volume)
# as an extra positional arg after `closes` — the engine special-cases these.
VWAP_SIGNALS = {"vwap_momentum", "vwap_reversion"}
VWAP_VOLUME_SIGNALS = {"vwap_volume_breakout"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class TraderConfig:
    method_id: str
    label: str
    description: str
    signal: str
    signal_params: dict = field(default_factory=dict)
    long_k: int = 8
    short_k: int = 4
    gross_long: float = 1.0
    gross_short: float = 0.3
    rebal_days: int = 5                 # trading days between rebalances
    regime_symbol: str = "SPY"
    regime_ma: int = 200
    # 'none'      — constant gross either side
    # 'defensive' — risk-off: halve long gross, raise short gross to match
    #               (net ≈ 0 in downtrends, net long in uptrends)
    # 'long_flat' — risk-off: long book to cash, keep short book
    # 'hedge'     — risk-on: long book only (no shorts); risk-off: halve the
    #               long book and switch the short book ON. The short leg is
    #               a downtrend hedge, not an always-on alpha source.
    regime_rule: str = "defensive"
    cost_bps: float = 5.0               # per side, on turnover notional
    short_borrow_apr: float = 0.015
    min_history: int = 260              # bars a symbol needs before tradeable
    entry_z: float = 0.0                # min |score| (z-units) to hold a slot;
                                         # unfilled slots sit in cash instead of
                                         # forcing a trade on a weak/noisy rank
    stop_loss_pct: Optional[float] = None   # per-position: exit if unrealised
                                             # loss since entry exceeds this
    max_drawdown_halt: Optional[float] = None  # portfolio: go flat + pause
                                                # new entries after this much
                                                # drawdown from peak equity
    halt_cooldown_bars: int = 20            # bars to stay flat after a halt

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class RebalanceEvent:
    date: str
    regime: str                          # 'risk_on' | 'risk_off'
    gross_long: float
    gross_short: float
    longs: dict[str, float]              # symbol -> weight
    shorts: dict[str, float]             # symbol -> weight (negative)
    turnover: float                      # sum |Δw| this rebalance
    cost_pct: float                      # cost charged this rebalance (fraction)
    rationale: str
    top_scores: dict[str, float]         # symbol -> score, for the log


def _metrics_from_returns(returns: pd.Series, equity: pd.Series,
                           periods_per_year: float = TRADING_DAYS) -> dict:
    r = returns.dropna()
    if len(r) < 10:
        return {}
    ann = math.sqrt(periods_per_year)
    vol = float(r.std() * ann)
    sharpe = float(r.mean() / r.std() * ann) if r.std() > 0 else 0.0
    downside = r[r < 0]
    dstd = float(np.sqrt((downside ** 2).mean())) if len(downside) else 0.0
    sortino = float(r.mean() / dstd * ann) if dstd > 0 else sharpe
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    years = len(r) / periods_per_year
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1.0) if years > 0 else 0.0
    peak = equity.cummax()
    dd = ((peak - equity) / peak).max()
    maxdd = float(dd) if not np.isnan(dd) else 0.0
    calmar = cagr / maxdd if maxdd > 0 else 0.0
    return {
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "cagr": round(cagr, 4),
        "total_return": round(total, 4),
        "max_drawdown": round(maxdd, 4),
        "volatility": round(vol, 4),
        "calmar": round(calmar, 3),
        "daily_win_rate": round(float((r > 0).mean()), 4),
        "best_day": round(float(r.max()), 4),
        "worst_day": round(float(r.min()), 4),
        "n_days": int(len(r)),
    }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _regime_gross(cfg: TraderConfig, regime_px, regime_ma, i: int) -> tuple[bool, float, float]:
    """Risk-on/off flag + regime-adjusted (gross_long, gross_short) at bar i."""
    risk_on = True
    if regime_ma is not None and not (
        pd.isna(regime_ma.iloc[i]) or pd.isna(regime_px.iloc[i])
    ):
        risk_on = bool(regime_px.iloc[i] > regime_ma.iloc[i])

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
    return risk_on, gl, gs


def run_ls_backtest(
    closes: pd.DataFrame,
    cfg: TraderConfig,
    start: Optional[str] = None,
    end: Optional[str] = None,
    periods_per_year: float = TRADING_DAYS,
    allow_intrabar_flip: bool = False,
    intraday: bool = False,
    volumes: Optional[pd.DataFrame] = None,
    vwap: Optional[pd.DataFrame] = None,
    flatten_eod: bool = False,
    entry_window: Optional[tuple] = None,
    debug: bool = False,
) -> dict:
    """
    Run one long/short backtest. Returns a JSON-serialisable report dict.
    """
    closes = closes.sort_index()
    if start:
        closes = closes[closes.index >= pd.Timestamp(start)]
    if end:
        closes = closes[closes.index <= pd.Timestamp(end)]

    regime_px = closes[cfg.regime_symbol] if cfg.regime_symbol in closes.columns else None
    tradeable_cols = [c for c in closes.columns if c not in ("SPY", "QQQ")]
    px = closes[tradeable_cols]
    rets = px.pct_change()

    signal_fn = SIGNALS[cfg.signal]
    if cfg.signal in VWAP_VOLUME_SIGNALS:
        scores = signal_fn(px, vwap.reindex_like(px), volumes.reindex_like(px), **cfg.signal_params)
    elif cfg.signal in VWAP_SIGNALS:
        scores = signal_fn(px, vwap.reindex_like(px), **cfg.signal_params)
    else:
        scores = signal_fn(px, **cfg.signal_params)

    # A symbol is eligible on day t if it has min_history bars of data by t
    valid = px.notna().rolling(cfg.min_history, min_periods=cfg.min_history).count() >= cfg.min_history

    regime_ma = regime_px.rolling(cfg.regime_ma).mean() if regime_px is not None else None

    n = len(px)
    dates = px.index
    weights = pd.DataFrame(0.0, index=dates, columns=tradeable_cols)
    events: list[RebalanceEvent] = []

    warmup = max(cfg.min_history,
                 cfg.signal_params.get("lookback", 0)
                 + cfg.signal_params.get("skip", 0),
                 cfg.signal_params.get("slow", 0),
                 cfg.regime_ma) + 1

    current = pd.Series(0.0, index=tradeable_cols)
    last_rebal_i = -(10 ** 9)
    total_cost = pd.Series(0.0, index=dates)
    entry_price = pd.Series(np.nan, index=tradeable_cols)
    running_equity, peak_equity, halt_until_i = 1.0, 1.0, -1

    def _ts_label(ts) -> str:
        return str(ts) if intraday else str(ts.date())

    def _mark_entries(old: pd.Series, new_w: pd.Series, price_row: pd.Series) -> None:
        """Record/clear per-symbol entry price whenever a position opens,
        flips side, or closes — drives the stop-loss check below."""
        for sym in tradeable_cols:
            o, w = old.get(sym, 0.0), new_w.get(sym, 0.0)
            if w == 0.0:
                entry_price[sym] = np.nan
            elif o == 0.0 or (o > 0) != (w > 0):
                entry_price[sym] = price_row.get(sym, np.nan)

    for i in range(warmup, n):
        if flatten_eod and i > 0 and dates[i].normalize() != dates[i - 1].normalize():
            # Day trading: no position carries overnight. Flatten at the
            # first bar of a new session; the next entry waits for the
            # normal cadence/flip checks below, same as any other bar.
            if (current != 0).any():
                turnover = float(current.abs().sum())
                total_cost.iloc[i] += turnover * cfg.cost_bps / 1e4
                _mark_entries(current, pd.Series(0.0, index=tradeable_cols), px.iloc[i])
                current = pd.Series(0.0, index=tradeable_cols)

        if cfg.max_drawdown_halt is not None and i >= warmup + 2:
            # Lagged (1-bar) mark: by now total_cost.iloc[i-1] is final, so
            # the return realised AT i-1 (from weights set at i-2) is fully
            # known. Reacting to it at bar i is not lookahead.
            realized = float((weights.iloc[i - 2] * rets.iloc[i - 1]).sum()) - float(total_cost.iloc[i - 1])
            running_equity *= (1.0 + realized)
            if i == halt_until_i + 1:
                # Just coming off a halt: while flat, running_equity was
                # frozen at the trough, so drawdown-from-old-peak would
                # still read as breached and re-trigger forever. Give the
                # resumed book a clean slate instead of an unrecoverable
                # halt loop.
                peak_equity = running_equity
            peak_equity = max(peak_equity, running_equity)
            dd = 1.0 - running_equity / peak_equity if peak_equity > 0 else 0.0
            if dd >= cfg.max_drawdown_halt and i > halt_until_i:
                halt_until_i = i + cfg.halt_cooldown_bars

        if cfg.max_drawdown_halt is not None and i <= halt_until_i:
            if (current != 0).any():
                turnover = float(current.abs().sum())
                total_cost.iloc[i] += turnover * cfg.cost_bps / 1e4
                _mark_entries(current, pd.Series(0.0, index=tradeable_cols), px.iloc[i])
                current = pd.Series(0.0, index=tradeable_cols)
            weights.iloc[i] = current
            continue

        if cfg.stop_loss_pct is not None and (current != 0).any():
            stopped = current.copy()
            hit = False
            for sym, w in current[current != 0].items():
                ep = entry_price.get(sym, np.nan)
                p_now = px.iloc[i].get(sym, np.nan)
                if pd.isna(ep) or pd.isna(p_now):
                    continue
                unreal = (p_now / ep - 1.0) * (1.0 if w > 0 else -1.0)
                if unreal <= -cfg.stop_loss_pct:
                    stopped[sym] = 0.0
                    hit = True
            if hit:
                turnover = float((stopped - current).abs().sum())
                total_cost.iloc[i] += turnover * cfg.cost_bps / 1e4
                _mark_entries(current, stopped, px.iloc[i])
                current = stopped

        if entry_window is not None:
            hhmm = dates[i].strftime("%H:%M")
            if not (entry_window[0] <= hhmm <= entry_window[1]):
                # Outside the allowed entry/signal window (e.g. first-hour-
                # only day trading): no new entries, flips, or exits here —
                # just carry whatever position was set during the window
                # until it's flattened at the next day boundary.
                weights.iloc[i] = current
                continue

        if i - last_rebal_i < cfg.rebal_days:
            # Not a scheduled full rebalance. Still checked every bar: if
            # intrabar flips are enabled and a *held* position's ranking has
            # crossed to the opposite side (long -> short zone or vice
            # versa), flip that single symbol immediately instead of
            # waiting for the next cadence rebalance.
            if allow_intrabar_flip and (current != 0).any():
                s_now = scores.iloc[i].where(valid.iloc[i]).dropna()
                if len(s_now) >= cfg.long_k + cfg.short_k + 2:
                    _, gl_now, gs_now = _regime_gross(cfg, regime_px, regime_ma, i)
                    longs_now = set(s_now.nlargest(cfg.long_k).index)
                    shorts_now = set(s_now.nsmallest(cfg.short_k).index)
                    flipped = current.copy()
                    changed = False
                    for sym, w in current[current != 0].items():
                        sc = s_now.get(sym, np.nan)
                        if pd.isna(sc):
                            continue
                        if w > 0:
                            if sym in shorts_now and sc <= -cfg.entry_z and cfg.short_k > 0 and gs_now > 0:
                                flipped[sym] = -gs_now / cfg.short_k
                                changed = True
                            elif cfg.entry_z > 0 and sc < cfg.entry_z:
                                # signal no longer clears the entry bar for
                                # this side either -> exit to cash rather
                                # than keep holding a decayed edge.
                                flipped[sym] = 0.0
                                changed = True
                        elif w < 0:
                            if sym in longs_now and sc >= cfg.entry_z and cfg.long_k > 0 and gl_now > 0:
                                flipped[sym] = gl_now / cfg.long_k
                                changed = True
                            elif cfg.entry_z > 0 and sc > -cfg.entry_z:
                                flipped[sym] = 0.0
                                changed = True
                    if changed:
                        turnover = float((flipped - current).abs().sum())
                        total_cost.iloc[i] += turnover * cfg.cost_bps / 1e4
                        _mark_entries(current, flipped, px.iloc[i])
                        current = flipped
            weights.iloc[i] = current
            continue
        s = scores.iloc[i].where(valid.iloc[i])
        s = s.dropna()
        if len(s) < cfg.long_k + cfg.short_k + 2:
            weights.iloc[i] = current
            continue

        risk_on, gl, gs = _regime_gross(cfg, regime_px, regime_ma, i)

        longs = s.nlargest(cfg.long_k)
        shorts = s.nsmallest(cfg.short_k)
        if cfg.entry_z > 0:
            longs = longs[longs >= cfg.entry_z]
            shorts = shorts[shorts <= -cfg.entry_z]

        new = pd.Series(0.0, index=tradeable_cols)
        if cfg.long_k > 0 and gl > 0 and len(longs):
            new[longs.index] = gl / cfg.long_k
        if cfg.short_k > 0 and gs > 0 and len(shorts):
            new[shorts.index] = -gs / cfg.short_k

        turnover = float((new - current).abs().sum())
        cost = turnover * cfg.cost_bps / 1e4
        total_cost.iloc[i] += cost

        regime_tag = "risk_on" if risk_on else "risk_off"
        rationale = (
            f"{cfg.signal} rebalance: long top {cfg.long_k} "
            f"({', '.join(longs.index)}), short bottom {cfg.short_k} "
            f"({', '.join(shorts.index)}); regime {regime_tag} "
            f"(SPY {'>' if risk_on else '<'} {cfg.regime_ma}d MA) → "
            f"gross {gl:.0%}L / {gs:.0%}S."
        )
        events.append(RebalanceEvent(
            date=_ts_label(dates[i]),
            regime=regime_tag,
            gross_long=gl,
            gross_short=gs,
            longs={k: round(float(v), 4) for k, v in (new[new > 0]).items()},
            shorts={k: round(float(v), 4) for k, v in (new[new < 0]).items()},
            turnover=round(turnover, 4),
            cost_pct=round(cost, 6),
            rationale=rationale,
            top_scores={k: round(float(v), 4)
                        for k, v in pd.concat([longs, shorts]).items()},
        ))
        _mark_entries(current, new, px.iloc[i])
        current = new
        last_rebal_i = i
        weights.iloc[i] = current

    # Apply weights to NEXT day's returns (no lookahead)
    w_shift = weights.shift(1).fillna(0.0)
    gross_ret = (w_shift * rets).sum(axis=1)

    # Borrow fee on short notional (daily accrual)
    short_notional = w_shift.clip(upper=0.0).abs().sum(axis=1)
    borrow = short_notional * cfg.short_borrow_apr / periods_per_year

    net_ret = gross_ret - total_cost - borrow
    live = weights.abs().sum(axis=1) > 0
    if live.sum() < 30:
        return {"error": f"not enough live bars ({int(live.sum())}) for {cfg.method_id}"}
    first_live = live.idxmax()
    net_ret = net_ret[net_ret.index >= first_live]

    equity = (1.0 + net_ret).cumprod() * 100_000.0
    metrics = _metrics_from_returns(net_ret, equity, periods_per_year)

    # Sub-period robustness
    halfway = net_ret.index[len(net_ret) // 2]
    m1 = _metrics_from_returns(net_ret[net_ret.index < halfway],
                               equity[equity.index < halfway], periods_per_year)
    m2 = _metrics_from_returns(net_ret[net_ret.index >= halfway],
                               equity[equity.index >= halfway] /
                               float(equity[equity.index >= halfway].iloc[0]) * 100_000.0,
                               periods_per_year)

    # Annual turnover
    n_years = max(len(net_ret) / periods_per_year, 1e-9)
    ann_turnover = float(sum(e.turnover for e in events) / n_years)

    # Monthly returns table
    monthly = (1.0 + net_ret).resample("ME").prod() - 1.0
    monthly_rows = [
        {"month": str(ts.date())[:7], "return": round(float(v), 4)}
        for ts, v in monthly.items() if not np.isnan(v)
    ]

    # Downsample equity curve for the report (~600 points max)
    step = max(1, len(equity) // 600)
    curve = [
        {"date": _ts_label(ts), "equity": round(float(v), 2)}
        for ts, v in equity.iloc[::step].items()
    ]
    if curve and curve[-1]["date"] != _ts_label(equity.index[-1]):
        curve.append({"date": _ts_label(equity.index[-1]),
                      "equity": round(float(equity.iloc[-1]), 2)})

    avg_gl = float(w_shift.clip(lower=0.0).sum(axis=1)[live.reindex(w_shift.index, fill_value=False)].mean())
    avg_gs = float(short_notional[live.reindex(w_shift.index, fill_value=False)].mean())

    return {
        "method_id": cfg.method_id,
        "label": cfg.label,
        "description": cfg.description,
        "config": cfg.to_dict(),
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "window": {"start": _ts_label(net_ret.index[0]),
                   "end": _ts_label(net_ret.index[-1])},
        "universe_size": len(tradeable_cols),
        "metrics": metrics,
        "sub_periods": {"first_half": m1, "second_half": m2},
        "annual_turnover": round(ann_turnover, 2),
        "avg_gross_long": round(avg_gl, 3),
        "avg_gross_short": round(avg_gs, 3),
        "n_rebalances": len(events),
        "monthly_returns": monthly_rows,
        "equity_curve": curve,
        "recent_rebalances": [asdict(e) for e in events[-12:]],
        **({"all_rebalances": [asdict(e) for e in events],
            "_debug": {"weights": weights, "rets": rets, "px": px,
                       "total_cost": total_cost, "net_ret": net_ret}}
           if debug else {}),
    }
