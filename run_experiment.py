#!/usr/bin/env python3
"""Minimal Codex experiment runner (cumulative mode).

Set a fixed prompt in `prompt.env` as `CODEX_PROMPT=...` (or export CODEX_PROMPT).

Each iteration:
- runs `codex exec` on the target codebase
- computes total line changes via `git diff --cached --numstat <prev_sha>`
- appends one row to `./result/<target_repo>/<stamp>-<model>-log.csv`.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CSV_COLUMNS = (
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
)
CODEX_AUTO_FLAGS = ("--full-auto", "--skip-git-repo-check")
DEFAULT_TIMEOUT = 600


@dataclass(frozen=True)
class TargetScope:
    root: Path
    rel_path: str
    pathspec: list[str] | None
    codex_cd: Path

    @property
    def repo_name(self) -> str:
        return self.root.name or "target"


@dataclass(frozen=True)
class LineStats:
    files_changed: int
    lines_added: int
    lines_deleted: int

    @classmethod
    def empty(cls) -> LineStats:
        return cls(files_changed=0, lines_added=0, lines_deleted=0)

    @property
    def lines_total(self) -> int:
        return self.lines_added + self.lines_deleted

    def plus(self, other: LineStats) -> LineStats:
        return LineStats(
            files_changed=self.files_changed + other.files_changed,
            lines_added=self.lines_added + other.lines_added,
            lines_deleted=self.lines_deleted + other.lines_deleted,
        )


@dataclass(frozen=True)
class CodexResult:
    exit_code: int
    duration_s: float
    timed_out: bool
    session_id: str | None = None


def codex_run_ok(codex: CodexResult) -> bool:
    """True only if Codex exited 0 and did not time out."""
    return codex.exit_code == 0 and not codex.timed_out


@dataclass(frozen=True)
class IterationResult:
    number: int
    stats: LineStats
    codex: CodexResult
    commit_sha: str
    commit_message: str

    def as_csv_row(self, *, model: str, branch: str) -> list[object]:
        return [
            self.number,
            self.stats.files_changed,
            self.stats.lines_added,
            self.stats.lines_deleted,
            self.stats.lines_total,
            f"{self.codex.duration_s:.3f}",
            self.codex.exit_code,
            int(self.codex.timed_out),
            self.commit_sha,
            self.commit_message,
            model,
            branch,
        ]


@dataclass(frozen=True)
class ExperimentConfig:
    target: TargetScope
    prompt: str
    requested_model: str
    effective_model: str
    branch: str
    results_csv: Path
    start_commit: str
    iterations: int


@dataclass(frozen=True)
class CliArgs:
    target: Path
    iterations: int
    commit: str
    model: str
    label: str | None


@dataclass(frozen=True)
class ModelInfo:
    effective: str
    slug: str


def eprint(*args) -> None:
    print(*args, file=sys.stderr)


def run_text_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def sanitize_slug(s: str, *, max_len: int = 64) -> str:
    """Safe fragment for git branch paths and filenames."""
    t = (s or "").strip().replace("\\", "-").replace("/", "-").replace(" ", "_")
    t = re.sub(r"[^a-zA-Z0-9._-]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-_.")
    if not t:
        t = "default"
    return t[:max_len]


def non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def resolve_label_slug(label: str | None) -> str | None:
    """Sanitized label slug for branch/result paths, or None if no label was given."""
    text = non_empty_string(label)
    if not text:
        return None
    return sanitize_slug(text)


def resolve_model_info(model: str) -> ModelInfo:
    return ModelInfo(effective=model, slug=sanitize_slug(model))


def prompt_file_candidates() -> list[Path]:
    return [Path.cwd() / "prompt.env", script_dir() / "prompt.env"]


def prompt_from_env_line(raw: str) -> str | None:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None

    key, value = line.split("=", 1)
    if key.strip() != "CODEX_PROMPT":
        return None

    prompt = value.strip().strip('"').strip("'").strip()
    return prompt or None


def load_prompt_file(path: Path) -> str | None:
    if not path.exists():
        return None

    for raw in path.read_text(encoding="utf-8").splitlines():
        prompt = prompt_from_env_line(raw)
        if prompt:
            return prompt
    return None


def load_prompt() -> str:
    # Prefer env var if already set.
    prompt = non_empty_string(os.environ.get("CODEX_PROMPT"))
    if prompt:
        return prompt

    # Otherwise load from prompt.env (cwd first, then alongside this script).
    for path in prompt_file_candidates():
        prompt = load_prompt_file(path)
        if prompt:
            return prompt

    raise SystemExit("Missing CODEX_PROMPT (set it in prompt.env or export CODEX_PROMPT).")


def run_git(target: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = run_text_command(
        ["git", *args],
        cwd=target,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{proc.stderr}")
    return proc


def find_git_root(path: Path) -> Path:
    """Find the git repository root containing the given path."""
    cwd = path if path.is_dir() else path.parent
    proc = run_text_command(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Not inside a git repository: {path}")
    return Path(proc.stdout.strip())


def setup_branch(repo_root: Path, commit: str, branch: str) -> str:
    """Checkout commit and create experiment branch."""
    run_git(repo_root, ["checkout", commit])
    run_git(repo_root, ["checkout", "-b", branch])
    return run_git(repo_root, ["rev-parse", "HEAD"]).stdout.strip()


def parse_numstat_line(line: str) -> LineStats | None:
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None

    added, deleted, _path = parts
    if added == "-" or deleted == "-":
        return LineStats(files_changed=1, lines_added=0, lines_deleted=0)

    return LineStats(
        files_changed=1,
        lines_added=int(added),
        lines_deleted=int(deleted),
    )


def sum_numstat(numstat_text: str) -> LineStats:
    total = LineStats.empty()
    for line in numstat_text.splitlines():
        stats = parse_numstat_line(line)
        if stats is not None:
            total = total.plus(stats)
    return total


def resolve_existing_path(target: Path) -> Path:
    target_path = target.expanduser().resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"target does not exist: {target_path}")
    return target_path


def target_pathspec(repo_root: Path, target_path: Path) -> tuple[str, list[str] | None]:
    if target_path.is_dir() and target_path == repo_root:
        return "", None

    rel_path = str(target_path.relative_to(repo_root))
    return rel_path, [rel_path]


def codex_cd_for_target(target_path: Path) -> Path:
    if target_path.is_dir():
        return target_path
    return target_path.parent


def resolve_target_scope(target: Path) -> TargetScope:
    target_path = resolve_existing_path(target)
    repo_root = find_git_root(target_path)
    rel_path, pathspec = target_pathspec(repo_root, target_path)
    return TargetScope(
        root=repo_root,
        rel_path=rel_path,
        pathspec=pathspec,
        codex_cd=codex_cd_for_target(target_path),
    )


def default_branch_name(
    stamp: str,
    model_slug: str,
    target_rel: str,
    *,
    label_slug: str | None = None,
) -> str:
    branch = f"codex-exp/{stamp}-{model_slug}"
    if label_slug:
        branch += f"-{label_slug}"
    if target_rel:
        branch += f"-{sanitize_slug(target_rel)}"
    return branch


def diff_stats(
    repo_root: Path,
    previous_sha: str,
    pathspec: list[str] | None,
) -> LineStats:
    diff_args = ["diff", "--cached", "--numstat", previous_sha]
    if pathspec is not None:
        diff_args += ["--", *pathspec]
    return sum_numstat(run_git(repo_root, diff_args).stdout)


def build_codex_command(
    codex_cd: Path,
    prompt: str,
    model: str,
    *,
    is_first: bool,
    session_id: str | None = None,
) -> list[str]:
    if is_first:
        cmd = ["codex", "exec", "--json", *CODEX_AUTO_FLAGS, "--cd", str(codex_cd)]
    else:
        if not session_id:
            raise RuntimeError("Missing Codex session id for resume.")
        # `codex exec resume` does not accept `--cd` in some Codex CLI versions.
        # We enforce the working directory via `subprocess.run(..., cwd=...)` instead.
        cmd = ["codex", "exec", "resume", session_id, "--json", *CODEX_AUTO_FLAGS]

    cmd = [*cmd, "--model", model, prompt]
    return cmd


def parse_codex_session_id(jsonl_text: str) -> str | None:
    """
    Extract the Codex resume id from `codex exec --json` output (session fields only).

    We look for an event like:
      {"type":"session_meta","payload":{"id":"..."}}

    Some Codex versions emit:
      {"type":"thread.started","thread_id":"..."}
    """
    for raw in jsonl_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "thread.started":
            tid = obj.get("thread_id")
            if isinstance(tid, str) and tid.strip():
                return tid.strip()

        if obj.get("type") != "session_meta":
            continue

        payload = obj.get("payload")
        if isinstance(payload, dict):
            sid = payload.get("id")
            if isinstance(sid, str) and sid.strip():
                return sid.strip()
    return None


def run_codex(
    *,
    codex_cd: Path,
    prompt: str,
    model: str,
    timeout: int,
    is_first: bool = True,
    session_id: str | None = None,
) -> CodexResult:
    cmd = build_codex_command(codex_cd, prompt, model, is_first=is_first, session_id=session_id)
    t0 = time.monotonic()
    try:
        proc = run_text_command(cmd, cwd=codex_cd, timeout=timeout)
        out = proc.stdout or ""
        err = proc.stderr or ""
        jsonl = "\n".join([out, err])
        sid: str | None = None
        if is_first:
            # Different Codex versions may emit JSONL to stdout, stderr, or both.
            sid = parse_codex_session_id(jsonl)
            if not sid:
                preview: list[str] = []
                if out.strip():
                    preview.append("stdout (first 10 lines):\n" + "\n".join(out.splitlines()[:10]))
                if err.strip():
                    preview.append("stderr (first 10 lines):\n" + "\n".join(err.splitlines()[:10]))
                detail = ("\n\n" + "\n\n".join(preview)) if preview else ""
                raise RuntimeError(
                    "Could not parse Codex session id from `codex exec --json` output. "
                    "Try running with a longer timeout, or run `codex exec --json ...` manually to inspect output."
                    f"{detail}"
                )
        return CodexResult(
            exit_code=proc.returncode,
            duration_s=time.monotonic() - t0,
            timed_out=False,
            session_id=sid,
        )
    except subprocess.TimeoutExpired:
        return CodexResult(
            exit_code=124,
            duration_s=time.monotonic() - t0,
            timed_out=True,
        )


def _stage_all_and_diff_stats(
    repo_root: Path,
    previous_sha: str,
    pathspec: list[str] | None,
) -> LineStats:
    """Stage the whole repo, then return scoped ``git diff --cached`` stats vs ``previous_sha``."""
    run_git(repo_root, ["add", "-A"])
    return diff_stats(repo_root, previous_sha, pathspec)


def run_iteration(
    repo_root: Path,
    *,
    iteration: int,
    codex_cd: Path,
    prompt: str,
    model: str,
    session_id: str | None,
    previous_sha: str,
    pathspec: list[str] | None,
) -> IterationResult:
    """Run Codex once for one logged iteration, then stage, diff, and commit."""
    is_first_codex = iteration == 1 and session_id is None

    codex = run_codex(
        codex_cd=codex_cd,
        prompt=prompt,
        model=model,
        timeout=DEFAULT_TIMEOUT,
        is_first=is_first_codex,
        session_id=session_id if not is_first_codex else None,
    )

    stats = _stage_all_and_diff_stats(repo_root, previous_sha, pathspec)

    commit_message = f"codex-exp: iteration {iteration}"
    if not codex_run_ok(codex):
        commit_message += f" [codex failed exit={codex.exit_code} timed_out={int(codex.timed_out)}]"

    run_git(repo_root, ["commit", "-m", commit_message, "--allow-empty"])
    commit_sha = run_git(repo_root, ["rev-parse", "HEAD"]).stdout.strip()

    return IterationResult(
        number=iteration,
        stats=stats,
        codex=codex,
        commit_sha=commit_sha,
        commit_message=commit_message,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run Codex repeatedly and record line-change totals per iteration.")
    p.add_argument("target", type=Path, help="Target codebase directory OR a single file path.")
    p.add_argument("iterations", type=int, help="Number of cumulative iterations.")
    p.add_argument("commit", type=str, help="Commit hash to branch from.")
    p.add_argument(
        "--model",
        type=str,
        required=True,
        help="Model for codex exec and log naming (e.g. gpt-5.5).",
    )
    p.add_argument(
        "--label",
        type=str,
        default=None,
        help="Optional tag appended to experiment branch and result/<repo>-<label>/ folder.",
    )
    return p


def parse_args(argv: list[str] | None = None) -> CliArgs:
    p = build_arg_parser()
    namespace = p.parse_args(argv)
    if namespace.iterations < 1:
        p.error("iterations must be >= 1")
    model = non_empty_string(namespace.model)
    if not model:
        p.error("--model must be non-empty")
    if namespace.label is not None and not non_empty_string(namespace.label):
        p.error("--label must be non-empty")
    return CliArgs(
        target=namespace.target,
        iterations=namespace.iterations,
        commit=namespace.commit,
        model=model,
        label=namespace.label,
    )


def require_tools(*tools: str) -> bool:
    missing_tools = [tool for tool in tools if shutil.which(tool) is None]
    if missing_tools:
        for tool in missing_tools:
            eprint(f"error: `{tool}` not found on PATH.")
        return False
    return True


def build_experiment_config(args: CliArgs) -> ExperimentConfig:
    target = resolve_target_scope(args.target)
    stamp = utc_stamp()
    model = resolve_model_info(args.model)
    label_slug = resolve_label_slug(args.label)
    branch = default_branch_name(stamp, model.slug, target.rel_path, label_slug=label_slug)
    result_dir = target.repo_name
    if label_slug:
        result_dir = f"{target.repo_name}-{label_slug}"
    results_csv = (script_dir() / "result" / result_dir / f"{stamp}-{model.slug}-log.csv").resolve()
    return ExperimentConfig(
        target=target,
        prompt=load_prompt(),
        requested_model=args.model,
        effective_model=model.effective,
        branch=branch,
        results_csv=results_csv,
        start_commit=args.commit,
        iterations=args.iterations,
    )


def eprint_setup(config: ExperimentConfig) -> None:
    eprint(f"[setup] Model (effective): {config.effective_model}")
    eprint(f"[setup] Experiment branch:  {config.branch}")
    eprint(f"[setup] CSV log:            {config.results_csv}")


def iter_experiment_results(
    config: ExperimentConfig,
    initial_sha: str,
) -> Iterator[IterationResult]:
    prev_sha = initial_sha
    session_id: str | None = None
    for i in range(1, config.iterations + 1):
        result = run_iteration(
            config.target.root,
            iteration=i,
            codex_cd=config.target.codex_cd,
            prompt=config.prompt,
            model=config.requested_model,
            session_id=session_id,
            previous_sha=prev_sha,
            pathspec=config.target.pathspec,
        )
        if i == 1:
            session_id = result.codex.session_id
        prev_sha = result.commit_sha
        yield result


def write_iteration_row(
    writer: csv.writer,
    result: IterationResult,
    config: ExperimentConfig,
) -> None:
    writer.writerow(result.as_csv_row(model=config.effective_model, branch=config.branch))


def eprint_iteration_result(result: IterationResult) -> None:
    c = result.codex
    if not codex_run_ok(c):
        eprint(
            f"[run_{result.number:03d}] ERROR: Codex did not complete successfully "
            f"(exit={c.exit_code}, timed_out={int(c.timed_out)}). "
            "CSV line-change totals reflect the staged diff at commit time and may be partial."
        )
        return
    eprint(
        f"[run_{result.number:03d}] "
        f"+{result.stats.lines_added} -{result.stats.lines_deleted} "
        f"total={result.stats.lines_total} exit={c.exit_code}"
    )


def write_experiment_log(config: ExperimentConfig) -> int:
    """Returns the number of iterations where Codex did not complete successfully."""
    config.results_csv.parent.mkdir(parents=True, exist_ok=True)
    eprint_setup(config)

    prev_sha = setup_branch(config.target.root, config.start_commit, config.branch)
    codex_failures = 0

    with config.results_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)

        for result in iter_experiment_results(config, prev_sha):
            write_iteration_row(w, result, config)
            eprint_iteration_result(result)
            if not codex_run_ok(result.codex):
                codex_failures += 1

    eprint(f"[done] Wrote: {config.results_csv}")
    return codex_failures


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not require_tools("codex", "git"):
        return 2

    try:
        config = build_experiment_config(args)
        codex_failures = write_experiment_log(config)
    except (FileNotFoundError, RuntimeError) as exc:
        eprint(f"error: {exc}")
        return 2

    if codex_failures:
        eprint(f"error: {codex_failures} iteration(s) failed: Codex did not exit successfully.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
