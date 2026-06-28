"""Git repository operations for experiment iterations."""

from __future__ import annotations

import subprocess
from pathlib import Path

from experiment_runner.models import LineStats
from experiment_runner.util import run_text_command


def _parse_numstat_line(line: str) -> LineStats | None:
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


def _sum_numstat(numstat_text: str) -> LineStats:
    total = LineStats.empty()
    for line in numstat_text.splitlines():
        stats = _parse_numstat_line(line)
        if stats is not None:
            total = total.plus(stats)
    return total


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


class GitRepository:
    """Git subprocess wrapper scoped to one repository root."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def run_git(self, args: list[str], *, check: bool = True):
        proc = run_text_command(
            ["git", *args],
            cwd=self.repo_root,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed:\n{proc.stderr}")
        return proc

    def setup_branch(self, commit: str, branch: str) -> str:
        """Checkout commit and create experiment branch."""
        self.run_git(["checkout", commit])
        self.run_git(["checkout", "-b", branch])
        return self.run_git(["rev-parse", "HEAD"]).stdout.strip()

    def _cached_diff_args(self, previous_sha: str, pathspec: list[str] | None) -> list[str]:
        diff_args = ["diff", "--cached", previous_sha]
        if pathspec is not None:
            diff_args += ["--", *pathspec]
        return diff_args

    def diff_stats(self, previous_sha: str, pathspec: list[str] | None) -> LineStats:
        diff_args = ["diff", "--cached", "--numstat", previous_sha]
        if pathspec is not None:
            diff_args += ["--", *pathspec]
        return _sum_numstat(self.run_git(diff_args).stdout)

    def capture_step_diff(self, previous_sha: str, pathspec: list[str] | None) -> str:
        """Unified diff for staged changes vs ``previous_sha`` (repo must already be staged)."""
        proc = self.run_git(
            self._cached_diff_args(previous_sha, pathspec),
            check=False,
        )
        return proc.stdout or ""

    def snapshot_at_commit(self, commit: str, pathspec: list[str] | None) -> str:
        """Read scoped text files from ``commit`` as a single snapshot string."""
        ls_args = ["ls-tree", "-r", "--name-only", commit]
        if pathspec is not None:
            ls_args += ["--", *pathspec]

        paths = [
            line.strip()
            for line in self.run_git(ls_args).stdout.splitlines()
            if line.strip()
        ]

        parts: list[str] = []
        for path in paths:
            # Read the blob as raw bytes: binary files (PNG icons, jars, etc. in
            # real-world repos) are not valid UTF-8 and would crash a text-mode
            # `git show`. Decode-test instead and skip anything non-text.
            proc = subprocess.run(
                ["git", "show", f"{commit}:{path}"],
                cwd=self.repo_root,
                capture_output=True,
            )
            if proc.returncode != 0:
                continue
            raw = proc.stdout
            if b"\0" in raw:
                continue
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            parts.append(f"=== {path} ===\n{content.rstrip()}\n")
        return "\n".join(parts)

    def stage_all_and_diff_stats(
        self,
        previous_sha: str,
        pathspec: list[str] | None,
    ) -> LineStats:
        """Stage the whole repo, then return scoped ``git diff --cached`` stats vs ``previous_sha``."""
        self.run_git(["add", "-A"])
        return self.diff_stats(previous_sha, pathspec)

    def commit(self, message: str) -> str:
        self.run_git(["commit", "-m", message, "--allow-empty"])
        return self.run_git(["rev-parse", "HEAD"]).stdout.strip()
