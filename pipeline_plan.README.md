# Pipeline planner (`pipeline_plan.json`)

`pipeline_plan.json` is the editable TODO that drives `run_pipeline.py`. It lists
the codebases to run, the models, iterations, and which pipeline phases to
execute, split into two groups that route outputs to separate directories.

JSON has no comments, so this file documents every field.

## Top-level shape

```json
{
  "defaults": { ... },     // applied to every task; each task may override
  "algorithms": [ ... ],   // tasks whose outputs go to output/Algorithms/
  "realworld":  [ ... ]    // tasks whose outputs go to output/RealWorld/
}
```

A **task** is one codebase. The orchestrator expands a task into the
cross-product of its `models` for the `run_exp` phase, then runs the remaining
phases once per experiment folder (they auto-discover all model batches).

## Fields (in `defaults` or per-task; per-task wins)

| Field        | Type            | Meaning |
|--------------|-----------------|---------|
| `target`     | string (path)   | Path to the codebase (dir or file inside a git repo). **Required per task.** Passed to `run_experiment.py` / `run_refdiff.py`. |
| `commit`     | string          | Git ref to branch from (`HEAD`, SHA, tag). **Required per task.** |
| `models`     | list of strings | Models to run. Each becomes one `<stamp>-<model>` batch. Names starting with `claude` use the Claude CLI; others use Codex. |
| `iterations` | int             | Cumulative agent iterations per model run (`run_001`..`run_NNN`). |
| `phases`     | list of strings | Subset of `["run_exp","refdiff","plot_refdiff","signals","plot_signals","dashboard"]`. Only these phases run; they always execute in that canonical order regardless of how they are listed. |
| `prompter`   | bool            | Use the Gemini user-agent prompter (`--prompter`). Adds the `-Agent` suffix to the experiment folder. |
| `label`      | string \| null  | Optional tag appended to the experiment folder (`<repo>-<label>`). |

## Group → output directory

| Group key     | Output base          |
|---------------|----------------------|
| `algorithms`  | `output/Algorithms/` |
| `realworld`   | `output/RealWorld/`  |

Inside each base, the structure is identical to the legacy `result/<exp>/`:
`logs/`, `<stamp>-<model>/run_NNN/`, `refdiff/`, `signals/`, `plots/`,
`dashboard.html`, plus `pipeline-logs/` (per-step orchestrator logs).

## Example: the headline use case

> 6 models × N codebases × 10 iterations, then refdiff → plot → signals.

Put the 6 models and `iterations: 10` once in `defaults`, list the codebases
under the right group, keep the full `phases` list. Per-task overrides handle
exceptions:

```json
{
  "defaults": {
    "iterations": 10,
    "models": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini",
               "claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6"],
    "phases": ["run_exp", "refdiff", "plot_refdiff", "signals", "plot_signals", "dashboard"]
  },
  "algorithms": [
    { "target": "../test_subject/bubble_sort_Java", "commit": "HEAD" },
    { "target": "../test_subject/quicksort_Java",   "commit": "HEAD",
      "models": ["gpt-5.5", "claude-opus-4-6"], "iterations": 5, "label": "Temp0.0" }
  ],
  "realworld": [
    { "target": "../test_subject/exp-app", "commit": "HEAD",
      "prompter": true, "phases": ["run_exp", "signals"] }
  ]
}
```

## Running it

Phase-first (recommended for long runs — finish each phase across the whole
plan before the next):

```bash
python run_pipeline.py --phase run_exp        # all codebases × all models, then stop
python run_pipeline.py --phase refdiff
python run_pipeline.py --phase plot_refdiff
python run_pipeline.py --phase signals
python run_pipeline.py --phase plot_signals
python run_pipeline.py --phase dashboard
```

Full chain per experiment (omit `--phase`):

```bash
python run_pipeline.py
```

Useful flags:

| Flag                       | Effect |
|----------------------------|--------|
| `--plan FILE`              | Use a different planner (default `pipeline_plan.json`). |
| `--phase a,b`              | Run only these phases across the plan. Comma list. |
| `--only-category algorithms` / `realworld` | Restrict to one group. |
| `--task SUBSTR`            | Only tasks whose target path / exp folder contains SUBSTR. |
| `--dry-run`                | Print the ordered command plan; execute nothing. |
| `--force`                  | Re-run steps even if already `done`. |
| `--retry-failed`           | Re-run only steps marked `failed`. |
| `--no-dep-check`           | Skip the upstream-phase guard (run a phase before its upstream finished). |

## Resume

Progress is tracked in `output/.pipeline_state.json` keyed by step
(`<Category>/<exp>::<phase>[::<model>]`). On restart, `done` steps are skipped
and the run continues. A failed step is recorded and the batch keeps going, so
one bad codebase or model never halts the rest. `run_exp` exit code `1`
(partial — CSV still written) counts as done; exit code `2` (setup error) and
other nonzero codes are `failed`.
