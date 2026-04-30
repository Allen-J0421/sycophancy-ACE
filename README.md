# codex-line-change-experiment-runner

A small Python harness that repeatedly applies a fixed prompt to a target
codebase via the OpenAI Codex CLI in **cumulative mode** (each iteration sees
the modified state from the previous iteration) and records:

- per-iteration totals (files changed, lines added, lines deleted, duration, exit code),
- a per-file breakdown for every iteration, and
- the full unified diff produced by each iteration.

Intended for studying drift / accumulation of agent behaviour across repeated
edits.

## Requirements

- Python 3.10+ (standard library only, no third-party deps).
- `git` on `PATH`.
- `codex` CLI on `PATH` and already authenticated (`codex login`).

## Usage

```bash
export CODEX_PROMPT="$(cat ./prompt.txt)"
python run_experiment.py \
  --target /path/to/codebase \
  --iterations 20 \
  --output ./results/exp1 \
  [--model gpt-5-codex] \
  [--timeout 600] \
  [--branch codex-exp/my-run]
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--target` | yes | Path to the target codebase. If it is not a git repo, the harness will run `git init` and create a baseline commit. |
| `--iterations` | yes | Number of cumulative codex iterations to run. |
| `--output` | no | Output directory. Defaults to `./results/<utc-timestamp>`. |
| `--model` | no | Forwarded to `codex exec --model`. |
| `--timeout` | no | Per-iteration timeout in seconds (default 600). On timeout the iteration still records whatever diff exists. |
| `--branch` | no | Experiment branch name (default `codex-exp/<utc-timestamp>`). The harness checks out this branch in the target before iterating, so your existing branch state is preserved. |

The prompt is read from the environment variable `CODEX_PROMPT`.

## What it does

1. **Bootstrap git.** If `--target` is not a git repo, it runs `git init` and
   creates a baseline commit. If it is a repo with uncommitted changes, those
   are folded into a `codex-exp: baseline (pre-experiment)` commit on the
   experiment branch (your previous branch is left untouched).
2. **Create an experiment branch** (`codex-exp/<timestamp>` by default) and
   capture the baseline commit SHA.
3. **For each iteration:**
   - Invoke `codex exec --full-auto --skip-git-repo-check --cd <target> [--model ...] <prompt>`.
   - `git add -A`, then capture `git diff --cached --numstat <prev_sha>` and
     `git diff --cached <prev_sha>`.
   - Write a CSV row, per-file rows, the full unified diff, and the captured
     stdout/stderr log.
   - Commit (`--allow-empty`) so the next iteration diffs against this state.

## Output layout

Under `--output` (default `./results/<utc-timestamp>/`):

```
config.json          # prompt, target, iterations, model, baseline SHA, branch, etc.
runs.csv             # one row per iteration (totals)
per_file.csv         # one row per (iteration, file)
diffs/
  run_001.diff       # full unified diff vs. previous iteration's commit
  run_002.diff
  ...
logs/
  run_001.log        # captured stdout+stderr from `codex exec`
  run_002.log
  ...
```

`runs.csv` columns: `run, files_changed, lines_added, lines_deleted, duration_s, exit_code, timed_out, head_sha`.

`per_file.csv` columns: `run, path, added, deleted, binary`. Binary files are
recorded with `added=0, deleted=0, binary=1` (git itself reports `-` for line
counts on binary diffs).

## Cleaning up the experiment branch

The harness leaves the experiment branch checked out in the target so you can
inspect the final state. To return to your previous state:

```bash
cd /path/to/codebase
git checkout -            # switch back to the previously checked-out branch
git branch -D codex-exp/<timestamp>   # delete the experiment branch
```

If the target was originally not a git repo and you want to remove the repo
the harness created, delete the `.git` directory inside the target.

## Notes

- The script never reverts files between runs; that is the point of cumulative
  mode. To run independent trials instead, re-run the script multiple times,
  each against a fresh copy of the target codebase.
- Codex CLI failures (non-zero exit, timeout) are logged but do **not** abort
  the experiment. Each iteration's `exit_code` and `timed_out` columns let you
  filter such runs in analysis.
- All outputs are plain CSV / JSON / text, designed to be loaded into a
  notebook for downstream analysis.
