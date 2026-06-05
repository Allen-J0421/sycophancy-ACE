# Codex line-change experiment runner

A small research harness that runs repeated **cumulative** Codex refactors on a git-backed codebase, logs per-iteration line-change metrics, optionally mines **RefDiff** refactorings on Java or JavaScript subjects, and builds a static **interactive dashboard** for inspection.

The pipeline has three **separate** phases. RefDiff never runs inside the Codex loop.

| Phase | Command | When |
|-------|---------|------|
| 1. Experiment | `run_experiment.py` | Codex iterations + CSV + artifacts |
| 2. RefDiff (Java / JS) | `run_refdiff.py` | After phase 1, on the target git repo |
| 3. Dashboard | `dashboard/build.py` | After phase 1 (and 2 for RefDiff hover/panel) |

---

## Quick start

Set your prompt in `prompt.env`:

```bash
CODEX_PROMPT=refactor
```

**Python subject (phases 1 and 3 only):**

```bash
python run_experiment.py ../test_subject/bubble_sort 10 HEAD --model gpt-5.5
python dashboard/build.py --exp bubble_sort-Dash-Temp0.0
open result/bubble_sort-Dash-Temp0.0/dashboard.html
```

**Java subject (all three phases):**

```bash
export JAVA_HOME="/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"

python run_experiment.py ../test_subject/bubble_sort_Java 10 HEAD --model gpt-5.5

python run_refdiff.py --repo ../test_subject/bubble_sort_Java

python dashboard/build.py --exp bubble_sort_Java
open result/bubble_sort_Java/dashboard.html
```

**JavaScript subject (all three phases):**

```bash
export JAVA_HOME="/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"

python run_experiment.py ../test_subject/exp-app 10 HEAD --model gpt-5.5

python run_refdiff.py --repo ../test_subject/exp-app

python dashboard/build.py --exp exp-app-Dash-Temp0.0
open result/exp-app-Dash-Temp0.0/dashboard.html
```

Use the **same `--repo` path** you passed to `run_experiment.py`. Commits live in that git repository, not under `result/`.

---

## Requirements

| Tool | Used for |
|------|----------|
| Python 3.10+ | All scripts (stdlib only) |
| `git` | Experiments, RefDiff git stats |
| `codex` CLI (authenticated) | `run_experiment.py` |
| JDK 21 (`JAVA_HOME`) | `refdiff-runner` / `run_refdiff.py` only |

Install OpenJDK 21 on macOS (example):

```bash
brew install openjdk@21
export JAVA_HOME="/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
```

---

## Repository layout

```
sandbox/
  run_experiment.py      # Phase 1: Codex cumulative runs
  run_refdiff.py         # Phase 2: RefDiff batch (Java / JavaScript)
  prompt.env             # CODEX_PROMPT=...
  refdiff-runner/        # Gradle app (RefDiff 2.0.0 from Maven Central)
  dashboard/
    build.py             # Phase 3: static HTML
    build_index.py       # Landing page (index.html)
    app.js, template.html, style.css
  result/
    <experiment>/        # One folder per target repo name (see --label)
      <stamp>-<model>-log.csv
      <stamp>-<model>/run_NNN/{diff.patch,codex.jsonl}
      refdiff/           # Phase 2 output (Java / JavaScript)
      dashboard.html     # Phase 3 output
  index.html             # Links to all built dashboards
  result/plot.py         # Optional PDF/PNG line charts
```

---

## Phase 1: Run experiment

### Command

```bash
python run_experiment.py <target> <iterations> <commit> --model <model> [--label <tag>]
```

**Positional arguments**

- `target` — Path to a file or directory inside a git repo (or the repo root).
- `iterations` — Number of cumulative Codex steps.
- `commit` — Starting ref (`HEAD`, SHA, tag).

**Flags**

- `--model` (required) — Passed to `codex exec --model`; used in CSV and branch names.
- `--label` — Suffix on experiment branch and `result/<repo>-<label>/` folder.

**Prompt** — From `prompt.env` (`CODEX_PROMPT=...`) or the `CODEX_PROMPT` environment variable.

### What it does

1. Finds the git root for `target`, checks out `commit`, creates branch `codex-exp/<timestamp>-<model>[-<label>]`.
2. Each iteration:
   - Runs `codex exec` (first) or `codex exec resume` (later) with JSON output.
   - Stages all repo changes (`git add -A`), records line stats vs previous commit (optionally scoped to `target`).
   - Appends one row to the CSV and writes `run_NNN/diff.patch` and `run_NNN/codex.jsonl`.
   - Commits (allow-empty) for the next iteration.

Cumulative mode: the tree is never reset between iterations.

### CSV columns

`run, files_changed, lines_added, lines_deleted, lines_total, duration_s, exit_code, timed_out, commit_sha, commit_message, model, git_branch`

### Exit codes

- `0` — All Codex iterations succeeded.
- `1` — At least one iteration failed or timed out (CSV still written).
- `2` — Setup error (bad paths, missing prompt, etc.).

---

## Phase 2: RefDiff (Java / JavaScript)

Runs **after** the experiment. Does not modify `run_experiment.py` or call Codex.

Language is **auto-detected** from `--repo`: `.java` files → Java plugin; `.js`/`.jsx` → JavaScript plugin. Mixed-language repos (both present) are rejected. TypeScript (`.ts`/`.tsx`) is not supported.

### Command

```bash
python run_refdiff.py --repo <path-to-target-git-repo>
```

Scans every `result/*/` folder with `*-log.csv` (like `result/plot.py`). Skips folders whose commits are not in `--repo`, experiments that do not match the detected language, and batches that already have `refdiff/*-refdiff.jsonl`. Python-only dashboards are unchanged.

**JavaScript on Apple Silicon:** `refdiff-js` uses J2V8 native libraries (x86_64). If you see `J2V8 native library not loaded`, use an **x64 JDK under Rosetta 2** (not an aarch64 JDK).

### Output

```
result/<experiment>/refdiff/
  <stamp>-refdiff.jsonl           # one JSON object per CSV row (run)
  <stamp>-matcher.log             # discarded matcher candidates, labeled by run
```

Each JSONL record includes:

- **Provenance:** `run`, `commit_sha`, `parent_sha`, `commit_message`, `model`, `git_branch`, `stamp`, `repo_path`, `experiment`, `language` (`java` or `js`)
- **Status:** `refdiff_ok`, `error_message`, `duration_ms`
- **Summary:** `n_same`, `n_matching`, `n_non_matching`, `n_relationships_total`
- **Relationships:** type, matching/non-matching flag, similarity, descriptions, before/after node snapshots (file, line, path)
- **Git (Tier 2):** `git_stat` (`files_changed`, `lines_added`, `lines_deleted`)
- **Matcher (Tier 2):** `matcher_discarded`, `matcher_log` (single run-labeled file per batch)
- **SAME (Tier 2):** `same_relationships[]`

Records split relationships into two buckets:

- **`matching_relationships[]`** — RefDiff relationships whose type is matching, including `SAME`, `RENAME`, `MOVE`, etc.
- **`non_matching_relationships[]`** — RefDiff relationships whose type is non-matching, such as extract/inline-style relationships.

### Relationship types

Each relationship’s `type` field uses RefDiff’s `RelationshipType` enum. Use this table when reading JSONL output or the dashboard RefDiff panel.

| Type | Meaning (plain language) |
|------|--------------------------|
| `SAME` | Same element in both versions (identity preserved). Body may still change. Not printed by `getRefactoringRelationships()`. |
| `CONVERT_TYPE` | Same “identity,” but CST node type changed (e.g. class → interface). Documented in enum/README; current matcher mostly requires `sameType`, so you may see this rarely or not at all in practice. |
| `CHANGE_SIGNATURE` | Same location & name, but signature changed (params, return type, etc.). |
| `RENAME` | Same location & signature, name changed. |
| `INTERNAL_MOVE` | Moved to a different parent, but still under the same top-level unit (e.g. method moved between inner classes in one file/class). |
| `MOVE` | Moved to a different root parent (e.g. another file / top-level type). |
| `INTERNAL_MOVE_RENAME` | Internal move and rename. |
| `MOVE_RENAME` | Move across roots and rename. |
| `PULL_UP` | Type member moved up the inheritance hierarchy (same signature). |
| `PUSH_DOWN` | Type member moved down to a subtype. |
| `PULL_UP_SIGNATURE` | Signature pulled to supertype; implementation may stay below. |
| `PUSH_DOWN_IMPL` | Implementation pushed to subtype; signature may stay above. |
| `EXTRACT_SUPER` | New supertype extracted from an existing type (extract class/interface). |
| `EXTRACT` | Code was pulled out into a new element (extract method/function). |
| `EXTRACT_MOVE` | Extracted and placed under a different parent. |
| `INLINE` | Code from before was inlined into after (inverse of extract). |

RefDiff’s one-line CLI output for a refactoring is stored per relationship as `description_standard` (and `description_with_score` when a similarity score applies, e.g. `EXTRACT`, `INLINE`).

### Single-commit (manual)

```bash
cd refdiff-runner
export JAVA_HOME="/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"

./gradlew -q run --args="--repo /path/to/repo --commit f03dd21 --lang java --out /tmp/out.json --include-same --quiet"
```

---

## Phase 3: Interactive dashboard

Builds a self-contained HTML file (Chart.js from CDN, no server).

```bash
python dashboard/build.py --exp <experiment-folder>
python dashboard/build.py --all              # every result/ subdir with CSV logs
python dashboard/build.py --exp foo --no-index   # skip regenerating index.html
python dashboard/build_index.py              # index only
```

### Features

- Tabs per `*-log.csv` (model / timestamp batch).
- Line chart of `lines_total` per run; **click** a point or use **Prev/Next** (arrow keys) to select a step.
- Panels: **RefDiff** (formatted summary + per-step raw JSON via **refdiff.jsonl**), agent response, unified diff; **Reasoning** and **codex.jsonl** dialogs for the selected step.
- **RefDiff:** hover a chart point for a one-line summary (e.g. `RefDiff: EXTRACT (1)`); see [Relationship types](#relationship-types) above when interpreting `type` fields.

Rebuild the dashboard after running `run_refdiff.py` to embed RefDiff data.

### Static plots (papers)

```bash
python result/plot.py
```

Reads only `*-log.csv`; writes `<experiment>_lines_total.pdf` / `.png` under each result folder.

---

## Result directory reference

Typical layout for one experiment batch:

```
result/bubble_sort_Java/
  20260601T211117Z-gpt-5.5-log.csv
  20260601T211117Z-gpt-5.5/
    run_001/
      diff.patch
      codex.jsonl
    run_002/
      ...
  refdiff/                                    # after run_refdiff.py
    20260601T211117Z-gpt-5.5-refdiff.jsonl
    20260601T211117Z-gpt-5.5-matcher.log
  dashboard.html                              # after dashboard/build.py
```

Older runs may have CSV only; the chart still works, but diff/response panels show a missing-artifact message until you re-run the experiment with current harness support.

---

## GitHub Pages

The repo includes a generated [`index.html`](index.html) and [`.nojekyll`](.nojekyll) for static hosting.

1. **Settings → Pages** → deploy from branch `main`, folder **/ (root)**.
2. Build dashboards, commit, push `index.html` and `result/*/dashboard.html`.
3. Open `https://<username>.github.io/<repo>/` (adjust for your org/username).

```bash
python dashboard/build.py --exp bubble_sort_Java
git add index.html result/bubble_sort_Java/dashboard.html
git push
```

Folders with CSV logs but no `dashboard.html` appear on the landing page as “Dashboard not built”.

---

## Notes and limitations

### Target scoping

If `target` is a file or subdirectory, Codex runs with `--cd` set accordingly, but the harness still **`git add -A`** on the whole repo. The `target` path only scopes **line-count stats** in the CSV (`git diff ... -- <pathspec>`).

### RefDiff vs git diff

RefDiff compares **commit vs parent** using structural refactorings (AST/CST). A large line diff may yield zero RefDiff refactorings, or vice versa.

### Cumulative trials

To run independent trials, use a fresh clone of the target repo for each `run_experiment.py` invocation. The harness does not revert between iterations within one run.

### Cleaning up the experiment branch

The target repo is left on the experiment branch for inspection:

```bash
cd /path/to/target-repo
git checkout -                    # previous branch
git branch -D codex-exp/<name>    # delete experiment branch
```

If the harness created `.git` inside a non-repo target, remove that directory to drop the repo.
