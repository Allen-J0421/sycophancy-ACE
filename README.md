# codex-line-change-experiment-runner (minimal)

A small Python harness that repeatedly applies a fixed prompt to a target
codebase via the OpenAI Codex CLI in **cumulative mode** (each iteration sees
the modified state from the previous iteration), records per-iteration
line-change totals to a CSV, and saves per-step artifacts for the interactive
dashboard.

## Requirements

- Python 3.10+ (standard library only, no third-party deps).
- `git` on `PATH`.
- `codex` CLI on `PATH` and already authenticated (`codex login`).

## Usage

```bash
# Put your prompt in prompt.env as:
#   CODEX_PROMPT=refactor
python run_experiment.py /path/to/codebase 20 <commit> --model gpt-5.5
# Example:
python run_experiment.py /path/to/codebase 20 HEAD --model gpt-5.5
# With a run label (suffix on branch and result folder):
python run_experiment.py /path/to/codebase 20 HEAD --model gpt-5.5 --label trial2
```

Flags:

- `target` (positional): path to a target directory or file within a git repo
- `iterations` (positional): number of cumulative iterations
- `commit` (positional): commit hash/ref to branch from (e.g. `HEAD`, a SHA, or a tag)
- `--model` (required): model for `codex exec --model` and for log/branch naming (e.g. `gpt-5.5`)
- `--label`: optional tag appended to the experiment git branch (`codex-exp/...-<label>`) and result directory (`result/<repo>-<label>/`)

The prompt is read from `prompt.env` (`CODEX_PROMPT=...`) or from the `CODEX_PROMPT` environment variable if already set.

## What it does

1. **Find repo root + branch from a specific commit.** The script locates the git
   repository root containing `target`, checks out the provided `commit`, then
   creates a new `codex-exp/...` branch from that commit.
2. **For each iteration:**
   - Iteration 1: invoke `codex exec --json --full-auto --skip-git-repo-check --cd <codex_cd> [--model ...] <prompt>` with `cwd=<codex_cd>`, then parse a resume id from JSONL (`thread_id` from `thread.started`, or `session_meta.payload.id` if present).
   - Iteration 2+: invoke `codex exec resume <id> --json --full-auto --skip-git-repo-check [--model ...] <prompt>` with **`cwd=<codex_cd>`** (your Codex CLI does not accept `--cd` on `resume`, so the harness sets the process working directory instead).
   - `git add -A` (stages the whole repo), compute totals from `git diff --cached --numstat <prev_sha> [-- <pathspec>]`.
   - Append one row to `<stamp>-<model>-log.csv` under `result/<target_repo_name>/` (or `result/<target_repo_name>-<label>/` when `--label` is set).
   - Write step artifacts under `<stamp>-<model>/run_NNN/` (diff, Codex JSONL, parsed response).
   - Commit (`--allow-empty`) so the next iteration diffs against this state.

## Output layout

Default log path layout:

```
result/<target_repo_name>[-<label>]/<timestamp>-<model-slug>-log.csv
```

`...-log.csv` columns:
`run, files_changed, lines_added, lines_deleted, lines_total, duration_s, exit_code, timed_out, commit_sha, commit_message, model, git_branch`.

The **`model`** column is the `--model` value passed on the command line. **`git_branch`** is the experiment branch created in the target repo (includes timestamp, model slug, and optional `--label` suffix).

### Per-step artifacts (for interactive dashboard)

For each CSV log, a sibling folder is created:

```
result/<target_repo_name>[-<label>]/<timestamp>-<model-slug>/
  run_001/
    diff.patch      # unified diff (scoped like CSV line stats)
    codex.jsonl     # raw Codex --json output (dashboard parses at build time)
  run_002/
    ...
```

Runs started before this feature have CSV data only; the dashboard chart still works, but diff/response panels show a missing-artifact message until you re-run the experiment.

## Interactive dashboard

Build a static HTML dashboard (Chart.js, no server) for one experiment folder:

```bash
python dashboard/build.py --exp target
open result/target/dashboard.html
```

Building a dashboard also regenerates the root landing page (`index.html`) listing all built dashboards under `result/`. Skip that with `--no-index`, or rebuild only the index with `python dashboard/build_index.py`.

Build every experiment that has CSV logs:

```bash
python dashboard/build.py --all
```

The dashboard shows one model at a time (tabs for each `*-log.csv` run). Click a chart point or use **Prev** / **Next** to inspect that step’s diff and agent response. Arrow keys also step through runs.

**Static plots** (unchanged, for papers): `python result/plot.py` — reads only `*-log.csv` files; artifact folders are ignored.

## GitHub Pages (landing page)

The repo includes a generated [`index.html`](index.html) at the root and [`.nojekyll`](.nojekyll) so GitHub Pages serves static HTML without Jekyll.

1. In the repo on GitHub: **Settings → Pages** → deploy from branch `main` (or your default branch), folder **/ (root)**.
2. After building dashboards, commit and push `index.html` (and experiment `result/.../dashboard.html` files).
3. Open `https://<username>.github.io/sycophancy-ACE/` (replace with your GitHub username/org if different).

Workflow when you add a new experiment:

```bash
python dashboard/build.py --exp <folder-name>
git add index.html result/<folder-name>/dashboard.html
git push
```

New experiment folders with CSV logs but no `dashboard.html` appear on the landing page as “Dashboard not built” until you run `build.py`.

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
