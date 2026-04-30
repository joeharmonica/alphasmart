#!/usr/bin/env bash
#
# Post-sweep pipeline: bootstrap → portfolio decision → opt-params export.
# Runs after run_walkforward_top4.py has produced reports/walkforward_top4_*_passers.json.
#
# Usage:
#   ./run_phase4_pipeline.sh                       # auto-discover latest inputs
#   ./run_phase4_pipeline.sh --workers 4           # cap bootstrap pool size
#   ./run_phase4_pipeline.sh --corr-threshold 0.6  # loosen portfolio selection
#   ./run_phase4_pipeline.sh --skip-export         # bootstrap + decide only
#
# Exits non-zero on the first failing stage (set -e). Each stage's stdout is
# also tee'd to logs/phase4_pipeline_<UTC>.log so the run is reproducible.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-./venv/bin/python}"
WORKERS=""
CORR_THRESHOLD=""
SKIP_EXPORT="0"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workers)
            WORKERS="$2"; shift 2 ;;
        --corr-threshold)
            CORR_THRESHOLD="$2"; shift 2 ;;
        --skip-export)
            SKIP_EXPORT="1"; shift ;;
        -h|--help)
            sed -n '2,13p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *)
            echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: python interpreter not found at $PYTHON" >&2
    echo "       Set PYTHON=path/to/python or run from alphasmart/ with venv/ created." >&2
    exit 1
fi

# Sweep guard: refuse to run if no passers JSON exists yet — the sweep is the
# upstream input and a missing file usually means it hasn't finished.
LATEST_PASSERS="$(ls -t ../reports/walkforward_top4_*_passers.json 2>/dev/null | head -n 1 || true)"
if [[ -z "$LATEST_PASSERS" ]]; then
    echo "ERROR: no walkforward_top4_*_passers.json under ../reports/." >&2
    echo "       Has run_walkforward_top4.py finished? Check logs/ for the sweep log." >&2
    exit 1
fi

mkdir -p logs
LOG="logs/phase4_pipeline_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "Pipeline log: $LOG"
echo "Latest passers: $LATEST_PASSERS"
echo

# Helper: pretty header for each stage
banner() {
    echo
    echo "=========================================================================="
    echo "  $1"
    echo "=========================================================================="
}

# Stage 1: bootstrap
BOOTSTRAP_ARGS=()
if [[ -n "$WORKERS" ]]; then
    BOOTSTRAP_ARGS+=(--workers "$WORKERS")
fi
banner "[1/3] run_bootstrap_passers.py"
"$PYTHON" run_bootstrap_passers.py "${BOOTSTRAP_ARGS[@]}" 2>&1 | tee -a "$LOG"

# Stage 2: portfolio decision
DECIDE_ARGS=()
if [[ -n "$CORR_THRESHOLD" ]]; then
    DECIDE_ARGS+=(--corr-threshold "$CORR_THRESHOLD")
fi
banner "[2/3] decide_portfolio.py"
"$PYTHON" decide_portfolio.py "${DECIDE_ARGS[@]}" 2>&1 | tee -a "$LOG"

# Stage 3: sanitised opt-params export
if [[ "$SKIP_EXPORT" == "1" ]]; then
    banner "[3/3] export_opt_params.py — SKIPPED (--skip-export)"
else
    banner "[3/3] export_opt_params.py"
    "$PYTHON" export_opt_params.py 2>&1 | tee -a "$LOG"
fi

# Final verdict echo for grep-ability in the log
banner "DONE"
LATEST_DECISION="$(ls -t ../reports/portfolio_decision_*.json 2>/dev/null | head -n 1 || true)"
if [[ -n "$LATEST_DECISION" ]]; then
    VERDICT="$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','?'))" "$LATEST_DECISION")"
    echo "Verdict: $VERDICT  ($LATEST_DECISION)" | tee -a "$LOG"
fi
echo "Log: $LOG"
