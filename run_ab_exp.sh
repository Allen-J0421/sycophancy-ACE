#!/usr/bin/env bash
#
# ab-exp — single-prompt / single-model ablation sweep.
#
#   Prompt : "Expert, examples + vague"  (== config/prompt_cells/BA__ex__vague.txt,
#            the BA__ex__vague cell from the prompt-expert study)
#   Model  : claude-sonnet-4-6  (effort high, Gemini prompter mode, 10 iterations)
#   Scope  : all 50 Algorithms + R001-R010 RealWorld modules (60 codebases)
#   Output : output/ab-exp/{Algorithms,RealWorld}/  (isolated from the main output/ tree)
#
# Plan file:  pipeline_plan_ab_exp.json
# State:      output/ab-exp/.pipeline_state.json  (resumable — re-run to continue)
#
# Usage:
#   ./run_ab_exp.sh              # run the whole chain, phase by phase, resumable
#   ./run_ab_exp.sh --dry-run    # print the command plan, execute nothing
#   ./run_ab_exp.sh --task R00   # filter to a subset of codebases (substring match)
#
# Any extra args are forwarded to run_pipeline.py.

set -u
cd "$(dirname "$0")"

# Use the conda env that has google-genai + the CLIs (same one the study uses).
PY=/Users/allenjiang/miniforge3/envs/sycophancy-sandbox/bin/python
PLAN=pipeline_plan_ab_exp.json
OUT_ROOT=output/ab-exp

# keep the Mac awake for the whole sweep (re-exec under caffeinate once)
if [ -z "${_CAFFEINATED:-}" ]; then
  exec env _CAFFEINATED=1 caffeinate -dimsu "$0" "$@"
fi

# preflight
"$PY" check_plan.py --plan "$PLAN" || { echo "preflight failed"; exit 2; }

# run_exp first (the long, provider-limited phase), then the deterministic downstream
# phases. Splitting the phases keeps the run resumable and provider-limit friendly.
"$PY" run_pipeline.py --plan "$PLAN" --output-root "$OUT_ROOT" --phase run_exp "$@"
"$PY" run_pipeline.py --plan "$PLAN" --output-root "$OUT_ROOT" \
    --phase plot_lines,refdiff,plot_refdiff,signals,plot_signals,dashboard "$@"

echo "[ab-exp] done — results under $OUT_ROOT/"
