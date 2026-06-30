#!/usr/bin/env bash
#
# Overnight runner. Two connected actions, run in sequence:
#
#   ACTION A — finish the missing Claude runs for G002-G005, then rebuild
#              all their downstream artifacts (plot_lines, refdiff, signals, plots).
#   ACTION B — run the opus-4.8 reasoning sweep (r01-r10, all effort levels),
#              then rebuild its downstream artifacts.
#
# Each stage resumes from output/.pipeline_state.json, so re-running this script
# after an interruption just continues where it left off.
#
# Usage:   ./run_night.sh        (auto-wraps itself in caffeinate so the Mac stays awake)

set -u

# --- keep the machine awake for the whole run (re-exec under caffeinate once) ---
if [ -z "${_CAFFEINATED:-}" ]; then
  exec env _CAFFEINATED=1 caffeinate -dimsu "$0" "$@"
fi

cd "$(dirname "$0")"
PY=python
LOG="night-run-$(date +%Y%m%dT%H%M%S).log"

# tee everything to a log file as well as the terminal
exec > >(tee -a "$LOG") 2>&1

log() { echo; echo "==================== $* ($(date +%H:%M:%S)) ===================="; }

# ============================================================================
# ACTION A — G002-G005 Claude + downstream
# ============================================================================
log "A1  G00: run_exp (fills missing Claude runs; gpt runs already done are skipped)"
$PY run_pipeline.py --task G00 --phase run_exp --no-check

log "A2  G00: rebuild downstream (--force so already-done plots regenerate with Claude data)"
$PY run_pipeline.py --task G00 \
    --phase plot_lines,refdiff,plot_refdiff,signals,plot_signals,dashboard \
    --force --no-check

# ============================================================================
# GATE — verify every opus effort level is actually reachable before the long
# reasoning sweep (this is the check that caught gpt's "none" vs "minimal" bug).
# ============================================================================
log "GATE  verifying opus-4.8 effort levels in sandbox"
for lvl in low medium high xhigh max; do
  if claude -p "Reply with the single word: ready" \
        --model claude-opus-4-8 --effort "$lvl" >/dev/null 2>&1; then
    echo "  ok   opus --effort $lvl"
  else
    echo "  FAIL opus --effort $lvl is NOT reachable -- skipping the reasoning sweep."
    echo "ACTION A finished; ACTION B aborted at the gate. Log: $LOG"
    exit 1
  fi
done

# ============================================================================
# ACTION B — opus-4.8 reasoning sweep + downstream
# ============================================================================
PLAN=pipeline_plan_reasoning_sweep.json

log "B1  reasoning sweep: run_exp (fills 50 opus cells; existing gpt-5.5 cells skipped)"
$PY run_pipeline.py --plan "$PLAN" --phase run_exp --no-check

log "B2  reasoning sweep: rebuild downstream (--force so suite-wide plots pick up opus)"
$PY run_pipeline.py --plan "$PLAN" \
    --phase refdiff,plot_refdiff,signals,plot_signals,dashboard,plot_reasoning_groups \
    --force --no-check

log "ALL DONE"
echo "Full log: $LOG"
