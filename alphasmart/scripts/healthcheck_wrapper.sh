#!/bin/bash
# Health-check wrapper for AlphaSMART paper-trade runner.
# Invoked by launchd (com.alphasmart.healthcheck). Two responsibilities:
#   1. Run `runner_main health-check --check-broker` and capture output.
#   2. On nonzero exit, append the output to logs/health-alerts.log and
#      fire a macOS notification so the operator notices within minutes.
#
# Exit codes from runner_main health-check (see runner_main.py):
#   0  ok
#   10 halt_active     — strategy paused (halt file present)
#   11 state_stale     — last_updated_utc older than --max-state-age-hours
#   12 broker_unreachable
#   13 state_missing
set -u

cd /Users/joepong/alphasmart/alphasmart || exit 99
PY=/Users/joepong/alphasmart/alphasmart/venv/bin/python
LOG=/Users/joepong/alphasmart/alphasmart/logs/health-alerts.log
OUT=/tmp/alphasmart_health.json

mkdir -p "$(dirname "$LOG")"

"$PY" -m src.execution.runner_main health-check --check-broker > "$OUT" 2>&1
rc=$?

if [ "$rc" -ne 0 ]; then
    {
        echo "==== $(date -u +'%Y-%m-%dT%H:%M:%SZ') rc=$rc ===="
        cat "$OUT"
        echo ""
    } >> "$LOG"

    # macOS user notification (requires the Mac to have a logged-in GUI session).
    /usr/bin/osascript -e "display notification \"AlphaSMART health-check FAILED (rc=$rc) — see logs/health-alerts.log\" with title \"AlphaSMART\"" 2>/dev/null || true
fi

exit "$rc"
