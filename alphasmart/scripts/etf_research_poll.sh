#!/bin/bash
# Low-frequency research poll for the leveraged-ETF DCA study symbols.
#
# These tickers (QLD/TQQQ/UPRO + QLD/SPY proxies) are NOT in the live
# trade universe (equity_xsec_momentum_B), so the daily LiveDataPoller
# never refreshes them — they go stale by design (see lessons.md #58).
# This job keeps their daily bars current at a weekly cadence so the
# leveraged-ETF research apparatus (run_xsec_*.py, DCA backtests) can be
# re-run on demand without a manual multi-symbol fetch.
#
# Invoked by launchd (com.alphasmart.etf_research_poll), weekly.
# Intentionally separate from the trade pipeline: a failure here must
# NEVER block or alarm the live rebalance / health-check.
set -u

cd /Users/joepong/alphasmart/alphasmart || exit 99
PY=/Users/joepong/alphasmart/alphasmart/venv/bin/python
LOG=/Users/joepong/alphasmart/alphasmart/logs/etf_research_poll.log

mkdir -p "$(dirname "$LOG")"

SYMBOLS=(QLD TQQQ UPRO)
PERIOD=10y

{
    echo "==== $(date -u +'%Y-%m-%dT%H:%M:%SZ') etf_research_poll start ===="
    for sym in "${SYMBOLS[@]}"; do
        echo "--- fetch $sym (period=$PERIOD) ---"
        # main.py fetch upserts idempotently; failures are logged, not fatal.
        "$PY" main.py fetch "$sym" --period "$PERIOD" --timeframe 1d 2>&1 \
            || echo "WARN: fetch failed for $sym (continuing)"
    done
    echo "==== done ===="
    echo ""
} >> "$LOG" 2>&1

exit 0
