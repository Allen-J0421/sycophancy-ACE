# codex-line-change-experiment-runner (minimal)

A small Python harness that repeatedly applies a fixed prompt to a target
codebase via the OpenAI Codex CLI in **cumulative mode** (each iteration sees
the modified state from the previous iteration) and records **only** per-iteration
line-change totals (added/deleted/total) to a single CSV.

## Requirements

- Python 3.10+ (standard library only, no third-party deps).
- `git` on `PATH`.
- `codex` CLI on `PATH` and already authenticated (`codex login`).

## Usage

```bash
# Put your prompt in prompt.env as:
#   CODEX_PROMPT=refactor
python run_experiment.py /path/to/codebase 20
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
- `target` (positional): path to the target codebase
- `iterations` (positional): number of cumulative iterations
- `--output`: output directory (default `./results/<utc-timestamp>/`)
- `--model`: forwarded to `codex exec --model`
- `--timeout`: per-iteration timeout seconds (default 600)
- `--branch`: experiment branch (default `codex-exp/<utc-timestamp>`)

The prompt is read from `prompt.env` (`CODEX_PROMPT=...`) or from the `CODEX_PROMPT` environment variable if already set.

## What it does

1. **Bootstrap git.** If `--target` is not a git repo, it runs `git init`. It then
   checks out an experiment branch and commits a baseline snapshot if the repo has
   no commits yet or has uncommitted changes.
2. **For each iteration:**
   - Invoke `codex exec --full-auto --skip-git-repo-check --cd <target> [--model ...] <prompt>`.
   - `git add -A`, compute totals from `git diff --cached --numstat <prev_sha>`.
   - Append one row to `results.csv`.
   - Commit (`--allow-empty`) so the next iteration diffs against this state.

## Output layout

Under `--output` (default `./results/<utc-timestamp>/`):

```
results.csv          # one row per iteration (totals)
```

`results.csv` columns:
`run, files_changed, lines_added, lines_deleted, lines_total, duration_s, exit_code, timed_out`.

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
