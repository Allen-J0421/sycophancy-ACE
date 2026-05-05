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
python run_experiment.py /path/to/codebase 20 <commit>
# Example:
python run_experiment.py /path/to/codebase 20 HEAD
```

Flags:

- `target` (positional): path to a target directory or file within a git repo
- `iterations` (positional): number of cumulative iterations
- `commit` (positional): commit hash/ref to branch from (e.g. `HEAD`, a SHA, or a tag)
- `--output`: optional override — if path ends with `.csv`, writes that file; otherwise treats it as a directory and writes `<stamp>-<model-slug>-log.csv` inside. Default: `./result/<target_repo_name>/<stamp>-<model-slug>-log.csv` next to `run_experiment.py` (`target_repo_name` = target dir basename, or parent dir when target is a file)
- `--model`: forwarded to `codex exec --model`
- `--timeout`: per-iteration timeout seconds (default 600)
- `--branch`: experiment branch (default `codex-exp/<utc-timestamp>-<model-slug>[-<target-slug>]`)

The prompt is read from `prompt.env` (`CODEX_PROMPT=...`) or from the `CODEX_PROMPT` environment variable if already set.

## What it does

1. **Find repo root + branch from a specific commit.** The script locates the git
   repository root containing `target`, checks out the provided `commit`, then
   creates a new `codex-exp/...` branch from that commit.
2. **For each iteration:**
   - Iteration 1: invoke `codex exec --json --full-auto --skip-git-repo-check --cd <codex_cd> [--model ...] <prompt>` with `cwd=<codex_cd>`, then parse a resume id from JSONL (`thread_id` from `thread.started`, or `session_meta.payload.id` if present).
   - Iteration 2+: invoke `codex exec resume <id> --json --full-auto --skip-git-repo-check [--model ...] <prompt>` with **`cwd=<codex_cd>`** (your Codex CLI does not accept `--cd` on `resume`, so the harness sets the process working directory instead).
   - `git add -A` (stages the whole repo), compute totals from `git diff --cached --numstat <prev_sha> [-- <pathspec>]`.
   - Append one row to `<stamp>-<model>-log.csv` under `result/<target_repo_name>/`.
   - Commit (`--allow-empty`) so the next iteration diffs against this state.

## Output layout

Default log path layout:

```
result/<target_repo_name>/<timestamp>-<model-slug>-log.csv
```

`...-log.csv` columns:
`run, files_changed, lines_added, lines_deleted, lines_total, duration_s, exit_code, timed_out, commit_sha, commit_message, model, git_branch`.

The **`model`** column is the resolved model (`--model` if set; otherwise read from `~/.codex/config.toml` when possible, else `default`). **`git_branch`** is the experiment branch created in the target repo (includes timestamp and model slug in the default name).

## Important notes (scoping)

- If `target` is a **file** or **subdirectory** inside a repo, the script runs Codex with `--cd` set to that directory (or the file’s parent). It will still **stage + commit all changes in the repo** (`git add -A`). The `target` path is only used to scope the **diff stats** via `git diff ... -- <pathspec>`.

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
- If Codex fails on an iteration (non-zero exit or timeout), stderr prints  
  `[run_NNN] ERROR: Codex did not complete successfully ...` instead of a  
  misleading `+lines/-lines` summary. The run still completes all iterations and writes the CSV; the process exits with **1** if any iteration failed (setup errors still use exit **2**). Use `exit_code`, `timed_out`, and `commit_message` for analysis.
