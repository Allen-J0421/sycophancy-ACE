"""Discover experiment directories and RefDiff JSONL inputs."""

from __future__ import annotations

from pathlib import Path

from experiment_runner.result_paths import refdiff_dir


def experiment_dirs(result_dir: Path) -> list[Path]:
    """Return immediate result subdirectories, skipping hidden/cache folders."""
    if not result_dir.is_dir():
        return []
    dirs: list[Path] = []
    for exp_dir in sorted(result_dir.iterdir()):
        if not exp_dir.is_dir() or exp_dir.name.startswith("."):
            continue
        if exp_dir.name == "__pycache__":
            continue
        dirs.append(exp_dir)
    return dirs


def refdiff_jsonl_files(exp_dir: Path) -> list[Path]:
    path = refdiff_dir(exp_dir)
    if not path.is_dir():
        return []
    return sorted(path.glob("*-refdiff.jsonl"))
