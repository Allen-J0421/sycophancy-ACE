"""Lines-of-code counting at a git commit (L0 denominator)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from experiment_runner.util import eprint

from signal_computation.config import FALLBACK_EXTENSIONS, LANG_EXTENSIONS


class LocCounter(Protocol):
    """Abstraction for baseline LOC lookup (DIP)."""

    def loc_at_commit(self, repo: Path, sha: str, lang: str) -> int: ...


class GitLocCounter:
    """Count source lines in a git tree at ``sha``, with cross-run caching."""

    def __init__(self, cache: dict[tuple[str, str], int] | None = None) -> None:
        self._cache = cache if cache is not None else {}

    @property
    def cache(self) -> dict[tuple[str, str], int]:
        return self._cache

    def loc_at_commit(self, repo: Path, sha: str, lang: str) -> int:
        key = (str(repo), sha)
        if key in self._cache:
            return self._cache[key]

        extensions = LANG_EXTENSIONS.get(lang, FALLBACK_EXTENSIONS)
        total = 0
        try:
            listing = subprocess.run(
                ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", sha],
                capture_output=True,
                text=True,
            )
            if listing.returncode != 0:
                eprint(
                    f"[warn] git ls-tree failed for {repo} @ {sha[:7]}: "
                    f"{listing.stderr.strip()}"
                )
                self._cache[key] = 0
                return 0
            for filename in listing.stdout.splitlines():
                if not filename.endswith(extensions):
                    continue
                blob = subprocess.run(
                    ["git", "-C", str(repo), "show", f"{sha}:{filename}"],
                    capture_output=True,
                    text=True,
                )
                if blob.returncode != 0:
                    continue
                content = blob.stdout
                if not content:
                    continue
                total += content.count("\n") + (0 if content.endswith("\n") else 1)
        except OSError as exc:
            eprint(f"[warn] LOC computation failed for {repo} @ {sha[:7]}: {exc}")
            self._cache[key] = 0
            return 0

        self._cache[key] = total
        return total
