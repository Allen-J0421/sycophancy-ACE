# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A research harness measuring **coding-agent sycophancy**. It runs repeated *cumulative* refactors of a git-backed codebase with a coding agent (Claude or Codex), mines structural refactorings with **RefDiff**, derives sycophancy signals **S0–S7**, and builds an interactive dashboard. `README.md` is the authoritative, exhaustive reference — read it for any phase you touch. This file is the orientation map.

## Setup & common commands

```bash
conda env create -f environment.yml && conda activate syco   # env name is `syco` (NOT sycophancy-sandbox, despite some docs)
pytest                              # full suite (tests/)
pytest tests/test_s7_signals.py     # single file
pytest tests/test_s7_signals.py::test_name -q
```

External tools the Python code shells out to (not installed by conda): `git`; `claude` CLI (for `claude-*` models); `codex` CLI (other models, e.g. `gpt-5.5`); a JDK ≤ 23 with `JAVA_HOME` set (RefDiff only — `run_refdiff.py`); `google-genai` + `GEMINI_API_KEY` (`--prompter` mode only).

RefDiff is a Gradle app; run it via its wrapper:
```bash
cd refdiff-runner && ./gradlew -q run --args="--repo /path --commit SHA --lang java --out /tmp/o.json --include-same --quiet"
```

## The pipeline is phased — phases are separate entry points run in order

RefDiff **never** runs inside the coding-agent loop. Canonical order (fixed regardless of how requested):

```
run_exp → plot_lines → refdiff → plot_refdiff → signals → plot_signals → dashboard
```

| Phase | Entry point | Library package | Output |
|-------|-------------|-----------------|--------|
| 1 Experiment | `run_experiment.py` | `experiment_runner/` | agent iterations + CSV + per-run artifacts |
| 2 RefDiff (Java/JS only) | `run_refdiff.py` | `refdiff-runner/` (Gradle) | structural refactorings JSONL |
| 3 Signals S0–S7 | `compute_signals.py` | `signal_computation/` | signals JSON + CSV |
| 4 Dashboard | `dashboard/build.py` | `dashboard/` | self-contained HTML |

**Python subjects skip RefDiff/signals** (run_exp + plot_lines + dashboard only). **Java/JS subjects run the full chain.** TypeScript unsupported; mixed-language repos rejected.

## Two ways to run, two output trees

- **Manual single experiment** — call each phase script yourself → output under `result/<exp>/`.
- **Batch pipeline** — `run_pipeline.py` reads `pipeline_plan.json` (editable planner: `defaults` + `algorithms[]`/`realworld[]` task lists), runs many codebases × models × phases unattended and resumable → output under `output/Algorithms/` and `output/RealWorld/`. State in `output/.pipeline_state.json` (keyed `<Category>/<exp>::<phase>[::<model>]`, value `done|failed|blocked`). `check_plan.py` runs as preflight.

```bash
python run_pipeline.py --phase run_exp     # one phase across whole plan, then stop (recommended for long runs)
python run_pipeline.py --dry-run           # show command plan, execute nothing
python run_pipeline.py --task SUBSTR       # filter tasks by path/folder substring
```

## Key architectural facts (non-obvious, easy to get wrong)

- **Cumulative trials**: the harness never resets the target tree between iterations — each turn commits (allow-empty) and the next builds on it. For independent trials, use a fresh clone per `run_experiment.py` invocation.
- **Commits live in the *target* git repo** (the `--repo` / `target` path), on branch `<agent>-exp/<timestamp>-<model>[-<label>]` — **not** under `result/`.
- **`target` scoping is stats-only**: the harness always `git add -A` on the whole repo; a file/dir `target` only narrows the CSV line-count `git diff` pathspec (and Codex's `--cd`).
- **Provider-limit auto-pause**: Claude session limits return a normal `result` line with `is_error:true`/`429` and exit 0 — undetected, that burns iterations on empty diffs and marks the run `done`. The pipeline detects this on the first dead turn, aborts before persisting (`run_experiment.py` exit `3` → step `blocked`, re-run after reset), and works other providers meanwhile. Exit codes: `0` all ok · `1` some failed (CSV still written, counts as done) · `2` setup error · `3` provider limit.
- **Corrupted-branch cleanup is manual**: discarded runs are logged to `output/corrupted_branches.jsonl`; delete the leftover experiment branches with `clean_corrupted_branches.py` (`--scan`, `--apply`). It only ever deletes `<agent>-exp/…` branches, never baseline branches.
- **Signals aggregate by N₀ lineage**: node identity is canonical `(kind, qualified-name/signature)`; nodes participating in a RefDiff relationship are excluded from the "completely added/removed" sets so refactors aren't miscounted as rollbacks (S4) or reimplementation (S5). S5 has two layers (exact present-absent-present + cross-turn RefDiff soft links); `--skip-s5-refdiff` uses layer 1 only. S7 (verbal-refusal edit rate) additionally reads agent text and the refusal regex in `refusal_analysis/keyword_regex_config.json`; patch it alone with `--s7-only`.

## Config locations

- `config/prompt.env` — `AGENT_FIXED_PROMPT`, prompter profile/nudge, limit-detection knobs (`LIMIT_*`).
- `config/` — prompter system prompts (`prompter_system_prompt.txt`, `..._expert.txt`) and clarification patterns; `*_FILE` keys resolve relative to `config/` first.
- `.env` (repo root) — `GEMINI_API_KEY`, `PROMPTER_MODEL` (prompter mode); signal binary thresholds `EPS1`/`EPS3`/`EPS6`.
