# AlphaSMART Implementation Plan v2 — Fail-Fast Strategy Search

_Authored: 2026-05-02 — incorporates lessons #22–34 from the architectural-falsification session._

---

## 1. Why this plan exists

The 2026-04-30 → 05-02 session ran 4 walk-forward sweeps × 3 bootstrap rounds × 1 wrapper retrofit × 1 history extension on a single-asset 17-symbol universe and confirmed **zero bootstrap-robust passers** (lessons.md #34). The pipeline correctly rejected every candidate, but it took ~10 hours of compute and several days of human attention to learn what the bootstrap could have told us in 15 minutes if it had run first.

The previous pipeline order:

```
broad sweep (hours) → optimize (hours) → walk-forward (built-in) → bootstrap (minutes)
                                                                  ^ where the killer signal lives
```

This plan reorders the gates so the **most discriminating, cheapest tests run first**, kill candidates fast, and only let survivors consume the expensive optimization budget. It also pivots the strategy search away from single-asset directional bets — which lesson #34 showed are structurally path-dependent — toward cross-sectional and cross-asset edges, where the same lessons predict the bootstrap will not collapse.

---

## 2. Lessons distilled into operating principles

| Lesson | Principle |
|---|---|
| #22 | Trade count is binding. Floor at 30 for trend strategies, 60 for mean-reversion, scaled by timeframe. |
| #25 | Some strategies need intraday — don't sweep them on daily. Pre-tag each strategy with its viable timeframes. |
| #26 | Cross-cutting risk behaviour goes in wrappers, not concrete strategies. Stops, vol targeting, regime filters all wrap. |
| #27 | Single passer = concentration. Need ≥ 3 uncorrelated ROBUST passers across ≥ 2 sectors before paper-trading. |
| #28 | Time-box. Estimate `combos × (1+folds) × symbols × strategies × seconds_per_backtest` before launch. > 60 min → trim or parallelize. |
| #30 | OFR is the real Gate 2 number. Sort by it; use the bool only as a filter. |
| #31 | Relax gates for *analysis*, never for *promotion*. Codified strict thresholds stay strict. |
| #32 | Equity-curve correlation includes cash-zero overlap. Mask to in-trade bars before concluding two strategies are redundant. |
| **#33** | **OFR ≠ bootstrap.** Both required, no relaxation tradeoff. Strong OFR + weak bootstrap = path-dependent edge fitted to a specific macro arc. |
| **#34** | **When every lever within an architecture has been falsified, the architecture is the result.** Single-asset 1d/1wk long-only is exhausted. Pivot or stop. |

**Three rules I'm baking into the pipeline:**

1. **Bootstrap-first, not bootstrap-last.** The cheapest path to falsification is 50 sims at default params, not 200 sims after 36-combo grid search.
2. **Cross-asset by default.** Single-asset signals are now suspect by construction; the burden of proof flips. New strategies are tested cross-sectionally first; single-asset is the special case.
3. **Time-boxed kill criteria.** Every experiment has explicit pre-registered conditions under which we stop without expanding the search.

---

## 3. The reordered pipeline — five stages, each with a kill gate

```
Stage 0 (1 min)    — Universe + strategy compatibility check
Stage 1 (5 min)    — Coarse smoke screen: 1 default-param backtest per (strategy, symbol)
Stage 2 (15 min)   — Fast bootstrap (n=50) on survivors at default params
Stage 3 (1-2 hr)   — Full grid optimization + walk-forward on survivors only
Stage 4 (5 min)    — Confirmation bootstrap (n=200) on Gate1+Gate2 passers
Stage 5 (immediate)— Portfolio decision gate: cross-asset diversity check
```

Each stage has explicit kill criteria. If the survivor set is empty at the end of any stage, we stop and reframe — we do not expand search.

### Stage 0 — Compatibility check (1 min)

For each strategy in the registry, declare:
- Viable timeframes (e.g. squeeze_momentum: 1h only — lessons #25)
- Minimum bar count (e.g. trend_period × 2)
- Mechanic class (trend / mean-reversion / breakout / composite / cross-sectional)

Before any sweep, validate every (strategy, symbol, timeframe) tuple satisfies the compatibility gate. Skip incompatible combos rather than running and rejecting them.

**Implementation:** small `STRATEGY_COMPATIBILITY` dict in `optimizer.py`. ~20 LOC.

### Stage 1 — Coarse smoke screen (5 min wall-clock)

Run **one default-param backtest** per (strategy, symbol, timeframe) combo. Filter on:
- Trade count ≥ 50% of class-specific floor (15 for trend, 30 for mean-rev)
- Sharpe > 0 (positive expected value)
- MaxDD < 30% (didn't blow up)

The aim is to drop candidates that *cannot generate a meaningful signal at all* — irrespective of optimization. This is the cheapest way to filter dead combos.

**Kill gate:** if < 20% of combos survive, the strategy library has too many incompatible-with-universe entries — fix the compatibility table before continuing.

**Implementation:** `run_smoke_screen.py`, ~80 LOC. Reuses `_run_one()` directly with strategy defaults from the constructor.

### Stage 2 — Fast bootstrap (n=50) at default params (15 min wall-clock)

For Stage 1 survivors, run a **50-sim block bootstrap at the default params** (no optimization yet). Filter on:
- Bootstrap ratio ≥ 0.5 (loose threshold — final gate is 0.65)
- Sim p25 > 0 (bottom-quartile of synthetic paths is still profitable)

This is the headline new gate. It catches path-dependent strategies in 15 minutes instead of after hours of optimization. Lesson #33 is now structural: any strategy that fails this stage will not pass the post-optimization bootstrap either.

**Kill gate:** if 0 candidates survive, the strategy class is path-dependent on this universe. Move to a different mechanic class or a different universe before continuing.

**Why n=50 is enough:** the goal here is *rejection*, not measurement. n=50 has SE ≈ 0.14 on the median ratio — plenty to distinguish path-dependent failures (typically ratio < 0) from candidates worth investigating (ratio ≥ 0.5). Reserve n=200 for the confirmation stage.

**Implementation:** `run_bootstrap_screen.py`, ~120 LOC. Parallel (one worker per candidate) — 200-symbol universe should fit in 15 min on 8 cores.

### Stage 3 — Full optimization + walk-forward (1–2 hr) — survivors only

Standard `run_optimization()`: full grid × walk-forward (IS=2y/OOS=1y/step=0.5y → 4 folds on 5-yr daily, 14 folds on 10-yr). Apply Gate 1 (Sh > 1.2, MaxDD < 25%, trades ≥ 30, +CAGR) and Gate 2 (OFR ≥ 0.70).

**Kill gate:** if 0 G1+G2 strict passers, log the relaxed-gate set as research material but do *not* promote them to Stage 4. Lesson #31 is strict.

**Time-box:** 2 hours. If projected runtime exceeds, trim grids per lessons #28. We've already paid that cost twice this session — trimmed grids are cheap insurance.

### Stage 4 — Confirmation bootstrap (n=200, 5 min) on G1+G2 passers

Standard `run_bootstrap_passers.py`. Threshold ratio ≥ 0.65. The new role: **confirmation**, not discovery. By this stage every candidate has already passed the fast bootstrap at default params; the n=200 run is a precision check, not a hunt for survivors.

**Kill gate:** if 0 ROBUST, the post-Stage-3 candidates are signal-noise outliers. Reframe — do not relax the threshold.

### Stage 5 — Portfolio decision (immediate)

`decide_portfolio.py` — pairwise return-correlation matrix on ROBUST passers, sector-bucket check, greedy uncorrelated selection. Verdict:
- ≥ 3 uncorrelated ROBUST passers across ≥ 2 sectors → `PORTFOLIO_READY`
- 1–2 ROBUST → `CONCENTRATION` — widen the search OR extend history (but per lesson #34, neither will help if the underlying mechanic class is single-asset directional)
- 0 ROBUST → `NONE`

**Lessons #32 caveat:** if ρ > threshold but trade-overlap is dominated by both-flat days, recompute on in-trade-only bars before concluding redundancy.

---

## 4. Architecture pivot — Phase 8 — Cross-sectional engine

The single-asset architecture has been falsified (lesson #34). Continuing to search for indicators within it is unlikely to produce ROBUST passers. The next material architectural lever is cross-sectional signals, where the edge is *relative ranking* across many assets rather than directional bets on individual asset paths.

### 4.1 Engine extension required

The current `BacktestEngine.run()` accepts one `(strategy, data)` pair and processes one asset. For cross-sectional we need:

```python
class PortfolioEngine:
    def run(self, strategy: PortfolioStrategy,
            data: dict[str, pd.DataFrame],   # symbol → OHLCV
            config: BacktestConfig) -> BacktestResult
```

The portfolio strategy receives a dict of all symbols' data up to bar `i` and returns a `dict[symbol → Signal]` (one signal per asset). Position sizing distributes capital across the long-set / short-set per the strategy's allocation logic.

**Effort:** ~1 day. Reuse existing `Portfolio`, `RiskEngine`, `Fill` machinery; only the bar loop and signal-collection need to span multiple assets.

### 4.2 Cross-sectional strategy templates

Six initial candidates, each well-documented in academic literature with empirical persistence claims to test:

| # | Strategy | Signal | Known persistence |
|---|---|---|---|
| 1 | Cross-sectional momentum | Long top-K by trailing N-month return, short bottom-K (or long-only top-K vs cash) | Jegadeesh & Titman 1993; one of the most replicated factors |
| 2 | Cross-sectional low-volatility | Long top-K by inverse trailing 60-day vol | Frazzini & Pedersen 2014; "betting against beta" |
| 3 | Cross-sectional reversal | Long bottom-K by 1-month return (short-term reversal) | DeBondt & Thaler 1985; works at short horizons |
| 4 | Sector rotation | 11 sector ETFs (XLK, XLF, XLV, XLE, XLI, XLP, XLY, XLU, XLB, XLRE, XLC); long top-2 by 6mo return | Practitioner standard; less academic but widely deployed |
| 5 | Statistical arbitrage on residuals | Regress each asset's return on SPY/QQQ; trade residual via z-score reversion | Capture idiosyncratic alpha; market-neutral by construction |
| 6 | Quality composite | Combine momentum + low-vol + low-correlation-to-market into a single score; long top-K | Composite-of-factors approach; reduces single-factor cyclicality |

### 4.3 Universe expansion required for sector rotation (#4)

Need 11 sector SPDR ETFs. Cheap fetch (~5 min). Adds `--period 10y --timeframe 1d` for: XLK, XLF, XLV, XLE, XLI, XLP, XLY, XLU, XLB, XLRE, XLC.

### 4.4 Cross-sectional bootstrap

Block bootstrap on a multi-asset portfolio is not the same as single-asset. Two options:
- **Per-asset bootstrap with synchronised blocks** — preserves cross-asset correlation structure within blocks but the cross-sectional signal is computed on synthetic data. Cleanest test of "does the relative-ranking signal survive randomization?"
- **Cross-asset block resampling** — sample whole bar-blocks across all assets simultaneously. Preserves correlation perfectly but adds little new randomization.

Default: per-asset synchronised. Implementation: extend `block_bootstrap()` to accept a dict of dataframes and sample synchronised block-start indices.

---

## 5. Strategy candidates worth testing — prioritized list

After the falsification of single-asset directional strategies, the candidate space narrows significantly. These are ranked by **expected probability of clearing both Gate 2 (OFR) and the bootstrap**, not by expected Sharpe.

### Tier A — Cross-sectional, well-documented persistence

1. **Cross-sectional momentum (12-1 month)** — long top-3 by trailing 12-mo return excluding the last month (skip-month convention to avoid short-term reversal). Monthly rebalance. The single most-replicated factor in academic finance.

2. **Cross-sectional low-volatility** — long top-3 by lowest trailing 60-day vol. Slowly-changing universe (vol is autocorrelated), so low turnover. Documented persistence post-2008.

3. **Sector rotation 6-mo momentum** — on 11 sector SPDRs. Long top-2. Different universe entirely; cleanly addresses the lesson-#34 single-asset trap.

### Tier B — Pair / spread, but on different pair-construction methods

4. **Cointegration-residual pairs** — for each (A, B) in cohabitant sectors, run cointegration test; if cointegrated, trade the residual via z-score reversion. The previous session tested *ratio* spreads which weren't optimally cointegrated. Engle-Granger or Johansen test; threshold p < 0.05.

5. **Triplet cointegration** — extend to 3-asset cointegrated baskets (e.g. V/MA/AXP). Higher-dimensional spreads tend to be more stable; more degrees of freedom to find a stationary linear combination.

### Tier C — Single-asset but with structural changes

6. **Single-asset momentum with cross-asset filter** — e.g. trade NVDA momentum *only when* NVDA's relative strength vs SPY is above its 6-month average. The filter conditions on relative ranking, breaking some path-dependence.

7. **Vol-targeted multi-asset basket** — equal-weighted basket of 5 uncorrelated symbols, with vol-targeting on the basket-level returns. Single signal across many assets.

### Tier D — Higher-frequency (1h) — only after Tier A delivers something

8. **Squeeze momentum on 1h** — lesson #25 explicitly recommends this timeframe. Requires fetching 2-yr 1h data for the universe.

9. **Order-flow signals on 1h** — VWAP deviation z-score, intraday autocorrelation. Requires intraday data.

---

## 6. Operating discipline — fail-fast in practice

### 6.1 Time-boxes

| Stage | Hard limit | Soft target |
|---|---:|---:|
| Smoke screen (Stage 1) | 10 min | 5 min |
| Bootstrap screen (Stage 2) | 30 min | 15 min |
| Full optimization (Stage 3) | 4 hr | 2 hr |
| Confirmation bootstrap (Stage 4) | 30 min | 5 min |
| Portfolio decision (Stage 5) | 5 min | 1 min |
| **Total per strategy class** | **5 hr** | **2.5 hr** |

If projected wall-clock for a stage exceeds the hard limit, **trim grids or universe before launching**, never after. Re-launching a partial sweep is more expensive than running a smaller one to completion.

### 6.2 Pre-registered kill criteria

Before each new strategy class, write down (in a one-line `tasks/experiment_<name>.md` file) the following:

1. **Hypothesis** (1 sentence): "Cross-sectional momentum on 17-symbol universe will produce ≥ 1 ROBUST passer."
2. **Stage 2 kill condition**: "If 0 of 5 representative symbols have bootstrap ratio ≥ 0.4 at default params, the strategy class is killed."
3. **Stage 3 kill condition**: "If best Stage-3 OFR < 0.6, kill."
4. **Final success criterion**: "≥ 1 candidate clears Stage 4 (n=200 bootstrap, ratio ≥ 0.65)."

Avoids motivated reasoning when results are mixed (lesson from this session: bb_reversion+stop NVDA was emotionally promoted past several gates before bootstrap killed it).

### 6.3 The session dashboard — auto-generated

A single `reports/session_dashboard_<date>.md` that auto-updates after each stage:

```
## AlphaSMART session 2026-XX-XX

### Active hypothesis
- Strategy class: cross-sectional momentum
- Status: Stage 2 (running)
- Kill criterion not yet met

### Stage gate funnel
- Stage 0 (compatibility):     45 → 38 (7 dropped — incompatible TF)
- Stage 1 (smoke screen):      38 → 12 (26 dropped — no signal)
- Stage 2 (fast bootstrap):    12 → ?  (running)
- Stage 3 (full opt):           ? → ?
- Stage 4 (confirm bootstrap):  ? → ?
- Stage 5 (portfolio):          ? → ?

### Total compute used: 23 min / 5 hr budget
### Survivors so far: see ...
```

Generated by a small `update_dashboard.py` that scans the latest reports and writes the markdown. Single source of truth for "where am I."

### 6.4 Fail-fast log

A running `tasks/falsifications.md` that records each killed hypothesis with one line:

```
2026-04-30  Single-asset trend mechanics (top-4 +stop, 5-yr 1d)        FALSIFIED — bootstrap < 0.4 across all 4
2026-05-02  Single-asset mechanic widening (4 strategies, 5-yr 1d)     FALSIFIED — 0 G1+G2 strict
2026-05-02  Cross-timeframe replication (1wk × 8 strategies)            FALSIFIED — 8 relaxed-gate, all FRAGILE
2026-05-02  Pair spreads on sector cohabitants                         FALSIFIED — robust mechanic, no edge after costs
2026-05-02  Vol-targeting overlay on fragile candidates                 FALSIFIED — top ratio 0.28 vs 0.65
2026-05-02  10-yr extended history on 3 1d candidates                   FALSIFIED — Sharpe collapses 30-50%
```

Forward-looking purpose: when designing a new experiment, check this log first. We've already learned that "more history" doesn't fix path-dependence — don't re-test it next session.

---

## 7. Implementation sequence — week by week

This sequence is built so that each week produces a working, reusable artifact, even if subsequent weeks are deferred or cancelled.

### Week 1 — Pipeline redesign (no new strategies)

**Deliverables:**
- `STRATEGY_COMPATIBILITY` table in `optimizer.py`
- `run_smoke_screen.py` (Stage 1)
- `run_bootstrap_screen.py` (Stage 2 — fast n=50 bootstrap on default params)
- `update_dashboard.py` (Stage 0–5 funnel auto-generator)
- `tasks/falsifications.md` initial entries from this session

**Validation:** re-run the entire previous session's experiments through the new pipeline. Every existing falsification should reproduce in <30% of the original wall-clock. If not, the new pipeline isn't faster than the old one — fix that before moving on.

**Estimated effort:** 8 hours.

### Week 2 — Cross-sectional engine

**Deliverables:**
- `src/backtest/portfolio_engine.py` (new — multi-symbol bar loop)
- `src/strategy/cross_sectional/momentum.py` (Tier A #1)
- `src/strategy/cross_sectional/lowvol.py` (Tier A #2)
- `src/backtest/cross_sectional_bootstrap.py` (synchronised block bootstrap across symbols)

**Validation:** smoke-test cross-sectional momentum on the 17-symbol universe. Should produce reasonable trade counts (~20–40 rebalances over 5 yr) and Sharpes in the 0.5–1.5 range historically.

**Estimated effort:** 12 hours.

### Week 3 — Cross-sectional sweep + sector rotation

**Deliverables:**
- Run Tier A #1, #2, #3 through the full pipeline (Stages 0–5)
- Fetch 11 sector SPDR ETFs (one-time)
- `tasks/experiment_xs_momentum.md`, `tasks/experiment_xs_lowvol.md`, `tasks/experiment_sector_rotation.md` with pre-registered kill criteria

**Validation:** each experiment produces a definitive verdict (PORTFOLIO_READY / CONCENTRATION / NONE) within the 5-hr time-box. Falsifications log updated.

**Estimated effort:** ~6 hours of dev + 15 hours of compute (which runs unattended).

### Week 4 — Tier B (cointegration pairs) if Tier A produced anything

**Deliverables:**
- `src/data/cointegration.py` — Engle-Granger and Johansen tests
- `build_cointegration_pairs.py` — auto-discover cointegrated pairs/triplets in universe
- `run_walkforward_cointegrated_pairs.py` — sweep `zscore_reversion+stop` on the discovered pairs

**Validation:** at least one cointegration-tested pair clears Stage 5 with verdict PORTFOLIO_READY. If not, escalate to alt-data or accept the project's negative verdict.

**Estimated effort:** ~8 hours of dev + 4 hours of compute.

### Week 5 (contingent) — Higher-frequency / alternative data

Only proceed if Weeks 2–4 surfaced ≥ 1 PORTFOLIO_READY verdict. Otherwise, the project's empirical conclusion is that **technical-indicator alpha on this universe is not extractable with retail-data, retail-strategy methods**, and the honest move is to publish that result and stop.

---

## 8. Stopping criteria — when do we accept the negative result?

This is the most important section of the plan, given lesson #34. We define explicit stop conditions so we don't iterate indefinitely:

### 8.1 Hard stop — accept the negative result if:

- **Tier A delivers 0 PORTFOLIO_READY.** Cross-sectional momentum is the most-replicated factor in finance; if it doesn't pass our pipeline on a 10-yr 17-symbol universe + 11 sector ETFs, the pipeline is either too strict (publish the methodology) or the data/universe is unsuited (acknowledge and stop).
- **Total session compute exceeds 50 hours without a single PORTFOLIO_READY.** Compute discipline as commitment device.
- **Tier B (cointegration) delivers 0 PORTFOLIO_READY after Tier A failed.** Statistical arbitrage on cointegrated baskets is the next-most-documented persistent edge; if it also fails, the universe is the bottleneck.

### 8.2 Soft stop — escalate scope only if:

- Tier A delivers ≥ 1 ROBUST but no PORTFOLIO_READY (CONCENTRATION verdict). Then escalate to Tier B and sector rotation.
- A single experiment falsifies an assumption that makes the rest of the plan obsolete (e.g. discovers that cross-asset bootstrap behaves fundamentally differently than single-asset). Update the lessons file, redesign before continuing.

### 8.3 What "publishing the negative result" means

If the hard stop triggers, AlphaSMART becomes a research artifact rather than a trading system. The deliverable is:
- A short paper / writeup documenting the methodology and the falsified hypotheses
- The codebase as a runnable robustness pipeline (others can plug in their own strategies)
- Lessons #1–#34 as a methodological record

This is not a failure mode. It's a real and unusual contribution: most retail backtest tooling will declare any 5-yr Sharpe-1.4 strategy tradable; this pipeline correctly refuses, and the refusal is documented enough for others to learn from.

---

## 9. Concrete first steps — what to do at the start of the next session

**Before any compute:**
1. Read this plan + lessons.md #34 + falsifications.md.
2. Pick the active hypothesis (default: Tier A #1 cross-sectional momentum).
3. Write `tasks/experiment_xs_momentum.md` with the four pre-registered fields (hypothesis, Stage 2 kill, Stage 3 kill, success criterion).

**Then, if Week 1 deliverables aren't built:**
4. Build the smoke-screen + bootstrap-screen pipeline first (Week 1). No new strategies until the fail-fast machinery exists.

**Then:**
5. Run the active hypothesis through the new pipeline.
6. Regardless of result, append to `falsifications.md` (success or kill) with a one-line summary.

**Hard rule:** do not begin a new architecture-level experiment without first checking falsifications.md. We've already proven that more history, vol-targeting, and pair spreads don't fix path-dependence. Don't redo those; the lessons file is the institutional memory.

---

## 10. Why this plan is different from the previous one

The original `tasks/todo.md` (and its earlier versions) followed a "build → test → if-fail-widen" pattern that committed compute to expensive optimization before knowing whether the candidate's mechanic was even bootstrap-eligible. This plan inverts that: **the cheapest discriminator (bootstrap) runs first**, and the expensive optimizer only operates on candidates that have already cleared a path-independence check.

In numbers, on the 2026-04-30 → 05-02 session: the previous pipeline spent ~10 hours of compute and produced 0 ROBUST. Run through the new pipeline, the same hypotheses would have failed at Stage 2 in ~30 minutes total. **The point isn't to find more candidates — it's to falsify the wrong ones faster, freeing budget for genuinely different architectures (Tier A cross-sectional) where the lessons predict bootstrap won't immediately collapse.**

We've already learned what kills single-asset directional strategies. The next session's job is to check whether that lesson generalises (in which case we stop) or whether cross-sectional structurally escapes it (in which case we have a portfolio).
