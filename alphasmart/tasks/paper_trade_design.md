# AlphaSMART Paper-Trade Adapter — Design Sketch

_Authored: 2026-05-05 — Phase 11 build plan, follows the 4-step roadmap (multi-asset → regime filter → execution validation → L/S deferred). Goal: catch implementation drift before any real-money deployment._

---

## 1. What we're paper-trading

**Strategy:** the 2-strategy regime-filtered ensemble (50/50 daily allocation):

| Leg | Universe | Mechanic | Filter | Best params |
|---|---|---|---|---|
| Equity | 15 mega-caps (AAPL/AMZN/ASML/AVGO/GOOG/MA/META/MSFT/NOW/NVDA/NVO/QQQ/SPY/TSLA/V) | Cross-sectional 6-month momentum, top-5 equal-weight, monthly rebalance | **B**: SPY > 200d-MA → invest, else cash | lookback=126d, top_k=5, rebal=21d |
| Crypto | 9 USD pairs (BTC/ETH/SOL/BNB/XRP/ADA/AVAX/DOGE/LINK) | Cross-sectional 30-day momentum, top-2 equal-weight, weekly rebalance | **F**: soft (price + breadth) — linear ramp 0–1 around BTC 200d-MA × universe-breadth ramp | lookback=30d, top_k=2, rebal=7d |

Vol-targeting overlay applied before filter on both legs (target 15% equity / 20% crypto, 60-day or 30-day vol window).

**Why we're paper-trading:** lessons #34/#36/#38 confirmed the architecture; lesson #40/#41 confirmed the filter; bootstrap and walk-forward all clear. **The remaining unknown is execution drift** — does the strategy *as-implemented* match the backtested simulation when there's a real broker, real timestamps, and real fills?

---

## 2. The four implementation gaps to catch

Per the user's note ("most strategies don't fail on alpha — they fail on implementation"), the adapter exists primarily to surface these:

### (a) Timestamp drift — bar-close → order-submission gap
Backtest assumes signal computed at bar `i`'s close, order executed at bar `i+1`'s open. In live trading:
- **Equity**: SPY closes at 16:00 ET; our adapter must compute signals before next-day market open (09:30 ET). Cron at 17:00 ET, dry-run check, submit by 06:00 ET.
- **Crypto**: 24/7 market; rebalance at fixed UTC hour (e.g. 00:00) using prior-day close.

**What to log per rebalance:**
```
{
  "rebalance_utc": "2026-XX-XX 23:55:00",
  "bar_close_utc": "2026-XX-XX 21:00:00",         # the bar we computed signals from
  "signal_computed_utc": "2026-XX-XX 21:02:13",   # how long after bar close
  "order_submitted_utc": "2026-XX-XX 21:02:45",   # how long until orders sent
  "first_fill_utc": "2026-XX-XX 21:02:48",        # how long until filled
  "intent_to_fill_seconds": 195
}
```

If `intent_to_fill_seconds` > 60s (equity) or > 10s (crypto), flag for review.

### (b) Slippage realism — backtest used 0.05%; what's the real number?
At each fill, log:
```
{
  "symbol": "NVDA", "side": "buy", "qty": 12.0,
  "intent_price": 875.42,       # mid at signal time
  "submitted_price": 875.50,    # quoted at order submit
  "fill_price": 875.61,         # actual fill
  "slippage_bps": 22,           # (fill - intent) / intent × 10000
  "spread_bps": 6,
  "delay_ms": 187
}
```

Aggregate over 30 days → per-symbol mean slippage. If realised slippage > backtest assumption (5 bps) by > 2x, the backtest's expected return is overstated and we re-tune position sizing.

### (c) Rebalance timing — partial fills, weekend gaps, halts
- **Partial fills**: equity rebalance day might fill 4 of 5 positions in one go, the 5th queues for next bar. Track `fill_completion_pct` per rebalance.
- **Weekend gaps (crypto)**: weekly crypto rebalance lands on a specific UTC hour, but funding-rate hours / illiquid hours can move prices. Try multiple windows; record best.
- **Halts**: if a name is halted at our intended fill time, the backtest assumed we got in. Live, we sit on cash for the position until reopen. Track `halt_skip_count`.

### (d) Position reconciliation drift
Run reconciliation after every rebalance:
```
local_position[symbol] vs broker_position[symbol]
  expected_qty: 12.0
  broker_qty:   11.97   ← drift due to fractional-share rounding
  drift_pct:    0.25%
```

If `drift_pct > 1%` for any symbol, halt the strategy and investigate. Cumulative drift over 30 days is the integrity check; should be < 0.5% per symbol per month.

---

## 3. Architecture — minimal viable adapter

```
alphasmart/src/execution/
├── broker/
│   ├── alpaca_paper.py       # equity broker adapter (Alpaca paper API)
│   └── coinbase_paper.py     # crypto broker adapter (Coinbase Sandbox API)
├── live_data.py              # yfinance/coinbase polling for current prices
├── strategy_runner.py        # orchestrates: poll data → compute signals → diff vs current positions → submit
├── reconciler.py             # post-rebalance reconciliation; integrity check
└── shadow_log.py             # writes structured JSON per event for forensic review

alphasmart/src/execution/runner_main.py  # entry point; reads config, kicks off scheduler
alphasmart/configs/paper_trade.yaml      # which strategies, position sizing, broker creds env vars
alphasmart/reports/paper_trade/<date>/   # daily JSON logs (rebalances, fills, recons)
```

**Scheduler:** simple `cron`-style or `apscheduler`:
- Equity: daily at 16:30 ET (after close, before next-day pre-market) — but only acts on monthly rebalance dates
- Crypto: weekly at 00:00 UTC Sunday → Monday handoff

**Two modes:**
- `--mode shadow` — compute signals, diff positions, log what *would* be submitted, no actual order
- `--mode paper` — same as shadow but actually submits to paper broker

Default: shadow first 7 days, then paper.

---

## 4. Pre-flight checks (run before any rebalance)

Each check returns `{ok: bool, reason: str}`. If any fails, abort the rebalance and alert.

1. **Data freshness**: latest bar close timestamp ≤ 6 hours old (equity) or ≤ 30 min old (crypto).
2. **Universe completeness**: all 15 equity symbols + 9 crypto pairs returned non-NaN closes.
3. **Regime filter inputs**: SPY's 200d-MA computable (need ≥ 200 trailing bars); same for BTC.
4. **Broker connectivity**: `GET /account` returns 200, account is in good standing.
5. **Cash buffer**: free cash ≥ 1% of portfolio (covers commission + slippage worst case).
6. **Position sanity**: no symbol holds > 25% of portfolio (catches a runaway bug before submission).

---

## 5. The 30-day shadow-mode rubric — pass criteria

Pass to "real paper orders" mode after 7 days of shadow if:

| Metric | Threshold |
|---|---|
| Pre-flight failures | 0 |
| Mean intent-to-submit delay | < 60 s (equity), < 10 s (crypto) |
| Mean realised slippage (when actually submitting) | < 15 bps per symbol |
| Reconciliation drift (cumulative, all symbols) | < 0.1% over the 7 days |
| Signals computed match backtest's signals on the same dates | 100% |

Last point is the most important: at the end of each rebalance, also run the strategy *backtest-style* on the bars seen so far, and confirm the resulting target weights match what the live strategy_runner emitted. **Any divergence is a bug.**

After 7 shadow days: 30 days of paper orders. Pass criteria same as above plus:

| Metric | Threshold |
|---|---|
| 30-day Sharpe (live) vs backtest expected | within ±0.5 |
| 30-day MaxDD (live) | not worse than backtest p25 of 30-day rolling MaxDDs |
| Halts triggered by risk engine | 0 (would indicate strategy is misbehaving) |

If any threshold breaks, halt strategy and triage.

---

## 6. What we're NOT doing (deferred per scope)

- **L/S momentum live** — deferred per user's lesson #37 caveat (borrow costs, factor crashes)
- **Multi-account orchestration** — single account per asset class for now
- **Tax-aware rebalancing** — paper-trading doesn't have tax events
- **GUI / dashboard for live mode** — JSON logs + a daily summary script is enough for v1
- **Real-money trading** — that's a separate gate after 30+ days of paper success

---

## 7. Build sequence

| Step | Effort | Deliverable |
|---|---:|---|
| 1. `broker/alpaca_paper.py` — auth, GET /account, GET /positions, POST /orders | 3h | unit-tested adapter against Alpaca paper sandbox |
| 2. `broker/coinbase_paper.py` — same shape, Coinbase Sandbox API | 3h | adapter |
| 3. `live_data.py` — incremental yfinance/coinbase polling, write to existing DB | 2h | continuous data freshness |
| 4. `strategy_runner.py` — load filter+strategy, compute signals, diff vs broker positions | 3h | signal-emit module (no orders yet) |
| 5. `reconciler.py` + `shadow_log.py` — structured logging | 2h | log infrastructure |
| 6. `runner_main.py` + cron config — scheduling + pre-flight checks | 2h | runnable end-to-end |
| 7. **Smoke test** — run shadow mode for 1 day, inspect logs | 1h | confirms wiring works |
| 8. **7-day shadow run** — passive | 7 days wall-clock | shadow log dir |
| 9. **30-day paper run** — passive | 30 days wall-clock | paper log dir |
| **Total dev** | **~16 hours** | |
| **Total wall-clock to first paper-tradable validation** | **~37 days** | |

---

## 8. Open decisions before build

1. **Account sizing for paper** — start with notional $100k matching the backtest's `INITIAL_CAPITAL`, or scale down to $10k for tighter slippage realism? Recommend $100k since paper-trading P&L is fictional anyway and we want to hit Alpaca's normal-order-routing path, not the small-order one.
2. **Crypto broker** — Coinbase Advanced (good API, $0 fees on Pro) vs Binance.US (better liquidity but harder to access from US). Recommend Coinbase first for build velocity.
3. **Reconciliation cadence** — every rebalance only, or also nightly? Recommend nightly because mid-cycle drift can still happen (corporate actions, splits).
4. **Failure escalation** — when reconciliation drift > 1%, what halts? Recommend: stop new orders, send a single email/Slack notification, leave existing positions alone (no panicked liquidation).
5. **Reproducibility** — should every shadow/paper run also persist a snapshot of the strategy code git SHA? Yes — a one-liner in shadow_log.py captures `git rev-parse HEAD`.

---

## 9. Why this design is robust against the failure modes you flagged

| User's failure mode | How the adapter catches it |
|---|---|
| Data lag | `data_freshness` pre-flight + `intent_to_fill_seconds` log per rebalance |
| Rebalance timing mismatch | `partial_fills`, `halt_skip_count`, `fill_completion_pct` logged per rebalance |
| Slippage assumption vs reality | per-fill `slippage_bps` logged; aggregate report at end of every shadow day |
| Strategy-vs-implementation divergence | post-rebalance signal-recomputation cross-check (Section 5 last bullet) |

If any of these surfaces a real issue during the 7-day shadow, we catch it in 7 days of compute-time, not 30 days of wallet-burn. That's the entire point of the shadow phase.
