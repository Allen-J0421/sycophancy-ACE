#!/usr/bin/env python3
"""Run a fixed prompt against a target codebase via Codex CLI in cumulative mode,
recording per-iteration line-change metrics, per-file breakdowns, and unified diffs.

See README.md for usage.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# ---------- small helpers ----------------------------------------------------


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def _as_text(x: object) -> str:
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    return str(x)


def git(target: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command inside the target codebase and return the completed process."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {proc.returncode}):\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    return proc


# ---------- numstat parsing --------------------------------------------------


@dataclass
class FileChange:
    path: str
    added: int
    deleted: int
    binary: bool


def parse_numstat(text: str) -> list[FileChange]:
    """Parse `git diff --numstat` output.

    Each line is `<added>\\t<deleted>\\t<path>`. Binary files show `-` for the
    counts. Renames may show paths like `dir/{old => new}/file` or
    `old => new`; we keep the raw path so the CSV faithfully reports git's view.
    """
    rows: list[FileChange] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        a_str, d_str, path = parts
        binary = a_str == "-" and d_str == "-"
        added = 0 if binary else int(a_str)
        deleted = 0 if binary else int(d_str)
        rows.append(FileChange(path=path, added=added, deleted=deleted, binary=binary))
    return rows


# ---------- prompt loading ---------------------------------------------------


def load_prompt_from_env() -> str:
    prompt = (os.environ.get("CODEX_PROMPT") or "").strip()
    if not prompt:
        raise SystemExit("Missing/empty CODEX_PROMPT environment variable.")
    return prompt


# ---------- git bootstrapping ------------------------------------------------


def is_git_repo(target: Path) -> bool:
    proc = git(target, ["rev-parse", "--is-inside-work-tree"], check=False)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def has_any_commits(target: Path) -> bool:
    proc = git(target, ["rev-parse", "--verify", "HEAD"], check=False)
    return proc.returncode == 0


def working_tree_dirty(target: Path) -> bool:
    proc = git(target, ["status", "--porcelain"], check=False)
    return bool(proc.stdout.strip())


def bootstrap_git(target: Path, branch: str) -> str:
    """Ensure target is a git repo on a fresh experiment branch.

    Returns the baseline commit SHA (the starting point against which
    iteration 1 will be diffed).
    """
    if not is_git_repo(target):
        _eprint(f"[setup] {target} is not a git repo; running `git init`.")
        git(target, ["init"])

    git(target, ["checkout", "-b", branch])

    dirty = working_tree_dirty(target)
    if not has_any_commits(target):
        _eprint("[setup] Repository has no commits yet; creating baseline commit.")
        dirty = True
    elif dirty:
        _eprint(
            "[setup] Working tree has uncommitted changes; folding them into a "
            "pre-experiment baseline commit on the experiment branch."
        )

    if dirty:
        git(target, ["add", "-A"])
        commit_res = git(
            target,
            ["commit", "-m", "codex-exp: baseline (pre-experiment)", "--allow-empty"],
            check=False,
        )
        if commit_res.returncode != 0:
            raise RuntimeError(
                f"Failed to create baseline commit:\n"
                f"stdout: {commit_res.stdout}\nstderr: {commit_res.stderr}"
            )

    head = git(target, ["rev-parse", "HEAD"]).stdout.strip()
    _eprint(f"[setup] Experiment branch: {branch}")
    _eprint(f"[setup] Baseline SHA:      {head}")
    return head


# ---------- codex invocation -------------------------------------------------


def run_codex(
    target: Path,
    prompt: str,
    model: str | None,
    timeout: int,
) -> tuple[int, str, str, float, bool]:
    """Invoke `codex exec` non-interactively against the target codebase.

    Returns (returncode, stdout, stderr, duration_s, timed_out).
    """
    cmd = [
        "codex",
        "exec",
        "--full-auto",
        "--skip-git-repo-check",
        "--cd",
        str(target),
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    t0 = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        rc = 124
        out = _as_text(exc.stdout)
        err = _as_text(exc.stderr) + f"\n[harness] codex exec timed out after {timeout}s\n"
    duration = time.time() - t0
    return rc, out, err, duration, timed_out


# ---------- output writers ---------------------------------------------------


RUNS_CSV_HEADERS = [
    "run",
    "files_changed",
    "lines_added",
    "lines_deleted",
    "duration_s",
    "exit_code",
    "timed_out",
    "head_sha",
]

PER_FILE_CSV_HEADERS = [
    "run",
    "path",
    "added",
    "deleted",
    "binary",
]


def init_csv(path: Path, headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(headers)


def append_run_row(
    path: Path,
    run: int,
    files_changed: int,
    lines_added: int,
    lines_deleted: int,
    duration_s: float,
    exit_code: int,
    timed_out: bool,
    head_sha: str,
) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            [
                run,
                files_changed,
                lines_added,
                lines_deleted,
                f"{duration_s:.3f}",
                exit_code,
                int(bool(timed_out)),
                head_sha,
            ]
        )


def append_per_file_rows(path: Path, run: int, changes: Iterable[FileChange]) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for c in changes:
            w.writerow([run, c.path, c.added, c.deleted, int(c.binary)])


def write_config(
    path: Path,
    *,
    target: Path,
    prompt: str,
    iterations: int,
    model: str | None,
    timeout: int,
    branch: str,
    baseline_sha: str,
    started_at: str,
) -> None:
    payload = {
        "target": str(target),
        "prompt": prompt,
        "iterations": iterations,
        "model": model,
        "timeout_s": timeout,
        "experiment_branch": branch,
        "baseline_sha": baseline_sha,
        "started_at_utc": started_at,
        "harness": "run_experiment.py",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------- main loop --------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run a fixed prompt against a target codebase via Codex CLI in "
            "cumulative mode and record per-iteration line-change metrics."
        ),
    )
    p.add_argument(
        "--target",
        required=True,
        type=Path,
        help="Path to the target codebase (will be initialised as a git repo if not already one).",
    )
    p.add_argument(
        "--iterations",
        type=int,
        required=True,
        help="Number of cumulative codex iterations to run.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: ./results/<utc-timestamp>).",
    )
    p.add_argument(
        "--model",
        type=str,
        default=None,
        help="Optional model name forwarded to `codex exec --model`.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Per-iteration codex exec timeout in seconds (default: 600).",
    )
    p.add_argument(
        "--branch",
        type=str,
        default=None,
        help="Experiment branch name (default: codex-exp/<utc-timestamp>).",
    )
    args = p.parse_args(argv)
    if args.iterations < 1:
        p.error("--iterations must be >= 1")
    if args.timeout < 1:
        p.error("--timeout must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if shutil.which("codex") is None:
        _eprint("error: `codex` CLI not found on PATH.")
        return 2
    if shutil.which("git") is None:
        _eprint("error: `git` not found on PATH.")
        return 2

    target: Path = args.target.expanduser().resolve()
    if not target.is_dir():
        _eprint(f"error: --target {target} is not a directory.")
        return 2

    prompt = load_prompt_from_env()
    stamp = _utc_stamp()
    branch = args.branch or f"codex-exp/{stamp}"
    out_dir: Path = (args.output or Path("results") / stamp).resolve()
    diffs_dir = out_dir / "diffs"
    logs_dir = out_dir / "logs"
    diffs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    runs_csv = out_dir / "runs.csv"
    per_file_csv = out_dir / "per_file.csv"
    init_csv(runs_csv, RUNS_CSV_HEADERS)
    init_csv(per_file_csv, PER_FILE_CSV_HEADERS)

    started_at = datetime.now(timezone.utc).isoformat()
    baseline_sha = bootstrap_git(target, branch)

    write_config(
        out_dir / "config.json",
        target=target,
        prompt=prompt,
        iterations=args.iterations,
        model=args.model,
        timeout=args.timeout,
        branch=branch,
        baseline_sha=baseline_sha,
        started_at=started_at,
    )

    _eprint(f"[setup] Output directory: {out_dir}")
    _eprint(f"[setup] Iterations:       {args.iterations}")
    if args.model:
        _eprint(f"[setup] Model:            {args.model}")
    _eprint(f"[setup] Timeout/iter:     {args.timeout}s")
    _eprint("")

    prev_sha = baseline_sha

    for i in range(1, args.iterations + 1):
        tag = f"run_{i:03d}"
        _eprint(f"[{tag}] invoking codex exec...")
        rc, out, err, duration, timed_out = run_codex(
            target=target,
            prompt=prompt,
            model=args.model,
            timeout=args.timeout,
        )
        (logs_dir / f"{tag}.log").write_text(
            f"$ codex exec --full-auto --skip-git-repo-check --cd {target}"
            + (f" --model {args.model}" if args.model else "")
            + f" <prompt>\nexit_code={rc} timed_out={timed_out} duration_s={duration:.3f}\n"
            f"\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n",
            encoding="utf-8",
        )

        git(target, ["add", "-A"])
        numstat_text = git(target, ["diff", "--cached", "--numstat", prev_sha]).stdout
        full_diff = git(target, ["diff", "--cached", prev_sha]).stdout
        changes = parse_numstat(numstat_text)
        files_changed = len(changes)
        lines_added = sum(c.added for c in changes)
        lines_deleted = sum(c.deleted for c in changes)

        (diffs_dir / f"{tag}.diff").write_text(full_diff, encoding="utf-8")

        commit_msg = f"codex-exp: iteration {i}"
        commit_res = git(
            target,
            ["commit", "-m", commit_msg, "--allow-empty"],
            check=False,
        )
        if commit_res.returncode != 0:
            _eprint(
                f"[{tag}] warning: git commit failed (rc={commit_res.returncode}); "
                f"stderr: {commit_res.stderr.strip()}"
            )
        head_sha = git(target, ["rev-parse", "HEAD"]).stdout.strip()

        append_run_row(
            runs_csv,
            run=i,
            files_changed=files_changed,
            lines_added=lines_added,
            lines_deleted=lines_deleted,
            duration_s=duration,
            exit_code=rc,
            timed_out=timed_out,
            head_sha=head_sha,
        )
        append_per_file_rows(per_file_csv, i, changes)

        _eprint(
            f"[{tag}] files={files_changed:<3} +{lines_added:<5} -{lines_deleted:<5} "
            f"duration={duration:6.2f}s exit={rc}{' TIMEOUT' if timed_out else ''} "
            f"sha={head_sha[:10]}"
        )

        prev_sha = head_sha

    _eprint("")
    _eprint(f"[done] Wrote results to: {out_dir}")
    _eprint(
        f"[done] Experiment branch `{branch}` is checked out in {target}. "
        f"To clean up:\n"
        f"         cd {target} && git checkout - && git branch -D {branch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
