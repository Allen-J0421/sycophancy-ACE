#!/usr/bin/env python3
"""Minimal Codex experiment runner (cumulative mode).

Set a fixed prompt in `prompt.env` as `CODEX_PROMPT=...` (or export CODEX_PROMPT).

Each iteration:
- runs `codex exec` on the target codebase
- computes total line changes via `git diff --cached --numstat <prev_sha>`
- appends one row to `./result/<target_repo>/<stamp>-<model>-log.csv` (see `--output`).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def eprint(*args) -> None:
    print(*args, file=sys.stderr)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sanitize_slug(s: str, *, max_len: int = 64) -> str:
    """Safe fragment for git branch paths and filenames."""
    t = (s or "").strip().replace("\\", "-").replace("/", "-").replace(" ", "_")
    t = re.sub(r"[^a-zA-Z0-9._-]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-_.")
    if not t:
        t = "default"
    return t[:max_len]


def resolve_effective_model(cli_model: str | None) -> str:
    """Model string passed to codex (--model); if unset, try ~/.codex/config.toml."""
    if cli_model and cli_model.strip():
        return cli_model.strip()
    config_path = Path.home() / ".codex" / "config.toml"
    if sys.version_info >= (3, 11) and config_path.exists():
        try:
            import tomllib

            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
            m = data.get("model") if isinstance(data, dict) else None
            if isinstance(m, str) and m.strip():
                return m.strip()
            prof = os.environ.get("CODEX_PROFILE")
            if isinstance(prof, str) and prof.strip():
                profiles = data.get("profiles") if isinstance(data, dict) else None
                if isinstance(profiles, dict) and isinstance(profiles.get(prof.strip()), dict):
                    mp = profiles[prof.strip()].get("model")
                    if isinstance(mp, str) and mp.strip():
                        return mp.strip()
        except Exception:
            pass
    return "default"


def eprint_codex_account() -> None:
    """Print one line describing how Codex is authenticated (from `codex login status`)."""
    proc = subprocess.run(
        ["codex", "login", "status"],
        capture_output=True,
        text=True,
        timeout=15,
    )

    def _non_warning_lines(text: str) -> list[str]:
        out: list[str] = []
        for raw in (text or "").splitlines():
            s = raw.strip()
            if not s:
                continue
            if s.startswith("WARNING:") or s.startswith("WARNING "):
                continue
            out.append(s)
        return out

    # Codex may print the real status on stderr; stdout can be empty.
    lines = _non_warning_lines(proc.stdout) + _non_warning_lines(proc.stderr)
    status_line = None
    for line in lines:
        low = line.lower()
        if "logged in" in low or "not logged" in low:
            status_line = line
            break
    if status_line is None and lines:
        status_line = " ".join(lines)

    if status_line:
        eprint(f"[setup] Codex account: {status_line}")
    elif proc.returncode == 0:
        eprint("[setup] Codex account: (no text from `codex login status`)")
    else:
        tail = " ".join(_non_warning_lines((proc.stderr or "") + (proc.stdout or "")))
        eprint(f"[setup] Codex account: unknown (exit {proc.returncode}){(' — ' + tail) if tail else ''}")


def load_prompt() -> str:
    # Prefer env var if already set.
    prompt = (os.environ.get("CODEX_PROMPT") or "").strip()
    if prompt:
        return prompt

    # Otherwise load from prompt.env (cwd first, then alongside this script).
    candidates = [Path.cwd() / "prompt.env", Path(__file__).resolve().parent / "prompt.env"]
    for p in candidates:
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "CODEX_PROMPT":
                val = v.strip().strip('"').strip("'").strip()
                if val:
                    return val

    raise SystemExit("Missing CODEX_PROMPT (set it in prompt.env or export CODEX_PROMPT).")


def git(target: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{proc.stderr}")
    return proc


BASELINE_MESSAGE = "codex-exp: baseline"


def latest_baseline_sha(target: Path) -> str | None:
    """Most recent matching commit reachable from `--all` (subject line equals BASELINE_MESSAGE)."""
    proc = git(
        target,
        [
            "log",
            "--all",
            "--format=%H",
            "--grep",
            f"^{BASELINE_MESSAGE}$",
            "-n",
            "1",
        ],
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip().splitlines()[0]


def ensure_git_baseline(target: Path, branch: str) -> str:
    if git(target, ["rev-parse", "--is-inside-work-tree"], check=False).returncode != 0:
        eprint(f"[setup] {target} is not a git repo; running `git init`.")
        git(target, ["init"])

    has_head = git(target, ["rev-parse", "--verify", "HEAD"], check=False).returncode == 0
    dirty = bool(git(target, ["status", "--porcelain"], check=False).stdout.strip())

    # If clean, detach to latest `codex-exp: baseline` commit (globally newest), then branch from there.
    if has_head and not dirty:
        sha = latest_baseline_sha(target)
        if sha:
            co = git(target, ["checkout", sha], check=False)
            if co.returncode == 0:
                eprint(f"[setup] Baseline commit:   {sha[:12]} ({BASELINE_MESSAGE})")
            else:
                eprint("[setup] Baseline checkout: (failed; branching from HEAD)\n" + co.stderr.strip())
        else:
            eprint("[setup] Baseline commit:   none yet (branch from current HEAD)")
    elif dirty:
        eprint("[setup] Baseline checkout:   skipped (dirty working tree)")

    git(target, ["checkout", "-b", branch])

    tip_has_commit = git(target, ["rev-parse", "--verify", "HEAD"], check=False).returncode == 0
    tip_subj = ""
    if tip_has_commit:
        tip_subj = git(target, ["log", "-1", "--format=%s"], check=False).stdout.strip()

    if (not tip_has_commit) or tip_subj != BASELINE_MESSAGE:
        git(target, ["add", "-A"])
        git(target, ["commit", "-m", BASELINE_MESSAGE, "--allow-empty"])

    return git(target, ["rev-parse", "HEAD"]).stdout.strip()


def sum_numstat(numstat_text: str) -> tuple[int, int, int]:
    files = 0
    added = 0
    deleted = 0
    for line in numstat_text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        a_str, d_str, _path = parts
        files += 1
        if a_str != "-" and d_str != "-":
            added += int(a_str)
            deleted += int(d_str)
    return files, added, deleted


def run_codex(target: Path, prompt: str, model: str | None, timeout: int) -> tuple[int, float, bool]:
    cmd = ["codex", "exec", "--full-auto", "--skip-git-repo-check", "--cd", str(target)]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)

    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, time.time() - t0, False
    except subprocess.TimeoutExpired:
        return 124, time.time() - t0, True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Codex repeatedly and record line-change totals per iteration.")
    p.add_argument("target", type=Path, help="Target codebase directory OR a single file path.")
    p.add_argument("iterations", type=int, help="Number of cumulative iterations.")
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Override CSV path: if it ends with .csv, use as file; otherwise a directory "
            "and writes <stamp>-<model>-log.csv there. Default: ./result/<target_repo>/<stamp>-<model>-log.csv"
        ),
    )
    p.add_argument("--model", type=str, default=None, help="Forwarded to `codex exec --model`.")
    p.add_argument("--timeout", type=int, default=600, help="Per-iteration timeout seconds (default 600).")
    p.add_argument(
        "--branch",
        type=str,
        default=None,
        help="Experiment branch (default codex-exp/<utc-ts>-<model-slug>).",
    )
    args = p.parse_args(argv)
    if args.iterations < 1:
        p.error("iterations must be >= 1")
    if args.timeout < 1:
        p.error("--timeout must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if shutil.which("codex") is None:
        eprint("error: `codex` CLI not found on PATH.")
        return 2
    if shutil.which("git") is None:
        eprint("error: `git` not found on PATH.")
        return 2

    eprint_codex_account()

    prompt = load_prompt()

    target_path: Path = args.target.expanduser().resolve()
    if not target_path.exists():
        eprint(f"error: target does not exist: {target_path}")
        return 2

    # Allow either a whole codebase directory or a single file within a codebase.
    if target_path.is_dir():
        work_root = target_path
        pathspec: list[str] | None = None
    else:
        work_root = target_path.parent
        pathspec = [str(target_path.relative_to(work_root))]

    stamp = utc_stamp()
    effective_model = resolve_effective_model(args.model)
    model_slug = sanitize_slug(effective_model)
    target_repo_name = work_root.name or "target"

    branch = args.branch or f"codex-exp/{stamp}-{model_slug}"

    sandbox_dir = Path(__file__).resolve().parent
    default_csv = sandbox_dir / "result" / target_repo_name / f"{stamp}-{model_slug}-log.csv"
    if args.output is None:
        results_csv = default_csv.resolve()
    else:
        out = args.output.expanduser().resolve()
        if out.suffix.lower() == ".csv":
            results_csv = out
        else:
            results_csv = out / f"{stamp}-{model_slug}-log.csv"

    results_csv.parent.mkdir(parents=True, exist_ok=True)

    eprint(f"[setup] Model (effective): {effective_model}")
    eprint(f"[setup] Experiment branch:  {branch}")
    eprint(f"[setup] CSV log:            {results_csv}")

    prev_sha = ensure_git_baseline(work_root, branch)

    with results_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "run",
                "files_changed",
                "lines_added",
                "lines_deleted",
                "lines_total",
                "duration_s",
                "exit_code",
                "timed_out",
                "commit_sha",
                "commit_message",
                "model",
                "git_branch",
            ]
        )

        for i in range(1, args.iterations + 1):
            rc, duration, timed_out = run_codex(work_root, prompt, args.model, args.timeout)

            # Always stage the whole repo.
            git(work_root, ["add", "-A"])

            diff_args = ["diff", "--cached", "--numstat", prev_sha]
            if pathspec is not None:
                diff_args += ["--", *pathspec]
            numstat = git(work_root, diff_args).stdout
            files_changed, lines_added, lines_deleted = sum_numstat(numstat)
            lines_total = lines_added + lines_deleted

            commit_message = f"codex-exp: iteration {i}"
            git(work_root, ["commit", "-m", commit_message, "--allow-empty"])
            prev_sha = git(work_root, ["rev-parse", "HEAD"]).stdout.strip()
            w.writerow(
                [
                    i,
                    files_changed,
                    lines_added,
                    lines_deleted,
                    lines_total,
                    f"{duration:.3f}",
                    rc,
                    int(timed_out),
                    prev_sha,
                    commit_message,
                    effective_model,
                    branch,
                ]
            )
            eprint(f"[run_{i:03d}] +{lines_added} -{lines_deleted} total={lines_total} exit={rc}")

    eprint(f"[done] Wrote: {results_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
