"""Pure helpers for reasoning-sweep cell folder naming and CSV collection."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_AGENT_SUFFIX = "-Agent"
_CODEX_EFFORT_LEVELS = ("none", "low", "medium", "high", "xhigh")
_CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
EFFORT_COLORS = {
    "none": "#7f7f7f",
    "low": "#1f77b4",
    "medium": "#ff7f0e",
    "high": "#2ca02c",
    "xhigh": "#9467bd",
    "max": "#d62728",
}


def effort_display(effort: str) -> str:
    return {"none": "None", "xhigh": "XHigh", "max": "Max"}.get(effort, effort.title())


def effort_color(effort: str) -> str:
    return EFFORT_COLORS.get(effort, "#4878a8")


def is_reasoning_suite(suite_dir: Path) -> bool:
    """True when ``suite_dir`` holds multiple effort cells for one model family."""
    for prefix in model_prefixes_in_suite(suite_dir):
        n = sum(
            1
            for exp_dir in experiment_dirs(suite_dir)
            if parse_cell_folder(exp_dir.name, prefix) is not None
        )
        if n >= 2:
            return True
    return False


def effort_cell_dirs(suite_dir: Path, model_prefix: str) -> list[tuple[str, Path]]:
    """Return ``(effort, cell_dir)`` pairs for ``model_prefix``, sorted by effort."""
    cells: list[tuple[str, Path]] = []
    for exp_dir in experiment_dirs(suite_dir):
        effort = parse_cell_folder(exp_dir.name, model_prefix)
        if effort is not None:
            cells.append((effort, exp_dir))
    cells.sort(key=lambda item: effort_sort_key(model_prefix, item[0]))
    return cells


def experiment_dirs(result_dir: Path) -> list[Path]:
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


def parse_cell_folder(name: str, model_prefix: str) -> str | None:
    """Return effort level from ``{model}-{effort}-Agent``, or None."""
    suffix = f"{model_prefix}-"
    if not name.endswith(_AGENT_SUFFIX) or not name.startswith(suffix):
        return None
    core = name[: -len(_AGENT_SUFFIX)]
    effort = core[len(suffix) :]
    return effort or None


def effort_sort_key(model: str, effort: str) -> int:
    order = _CLAUDE_EFFORT_LEVELS if model.strip().lower().startswith("claude") else _CODEX_EFFORT_LEVELS
    try:
        return order.index(effort)
    except ValueError:
        return len(order)


def model_prefixes_in_suite(suite_dir: Path) -> list[str]:
    prefixes: set[str] = set()
    for exp_dir in experiment_dirs(suite_dir):
        if not exp_dir.name.endswith(_AGENT_SUFFIX):
            continue
        core = exp_dir.name[: -len(_AGENT_SUFFIX)]
        if "-" not in core:
            continue
        model, _effort = core.rsplit("-", 1)
        if model:
            prefixes.add(model)
    return sorted(prefixes)


def iter_log_csvs(exp_dir: Path) -> list[Path]:
    logs = exp_dir / "logs"
    if not logs.is_dir():
        return []
    return sorted(logs.glob("*-log.csv"))


def collect_model_series_sorted(suite_dir: Path, model_prefix: str) -> list[tuple[str, pd.DataFrame]]:
    """Collect one CSV series per effort cell for ``model_prefix``, sorted by effort level."""
    cells: list[tuple[str, pd.DataFrame]] = []
    for exp_dir in experiment_dirs(suite_dir):
        effort = parse_cell_folder(exp_dir.name, model_prefix)
        if effort is None:
            continue
        csv_files = iter_log_csvs(exp_dir)
        if not csv_files:
            continue
        df = pd.read_csv(csv_files[-1])
        if df.empty or "run" not in df or "lines_total" not in df:
            continue
        cells.append((effort, df))
    cells.sort(key=lambda item: effort_sort_key(model_prefix, item[0]))
    return [(f"{model_prefix} ({effort})", df) for effort, df in cells]
