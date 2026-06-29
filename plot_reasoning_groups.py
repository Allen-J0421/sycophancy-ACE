#!/usr/bin/env python3
"""Suite-level effort comparison charts for reasoning-sweep experiments.

Scans ``<suite-dir>/*-Agent/`` cell folders, groups by model family, and renders
one chart per model with one series/subplot per reasoning-effort level:

- ``plots/{model}_effort_comparison.png`` — lines changed (this script)
- ``plots/{model}_refdiff_effort_comparison.png`` — via ``plot_refdiff.py``
- ``plots/{model}_signals_effort_comparison.png`` — via ``plot_signals.py``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from reasoning_cells import collect_model_series_sorted, model_prefixes_in_suite  # noqa: E402


def build_suite_charts(suite_dir: Path) -> int:
    """Render effort-comparison charts for each model family in the suite."""
    from plot_lines import render_lines_chart

    suite_dir = suite_dir.resolve()
    plots_out = suite_dir / "plots"
    built = 0
    for model_prefix in model_prefixes_in_suite(suite_dir):
        series = collect_model_series_sorted(suite_dir, model_prefix)
        if not series:
            continue
        slug = model_prefix.replace(".", "_")
        out_path = plots_out / f"{slug}_effort_comparison.png"
        title = f"Lines Changed per Refactoring Run — {model_prefix.upper()} (by effort)"
        if render_lines_chart(
            series,
            title=title,
            out_path=out_path,
            legend_title="Effort",
        ):
            built += 1
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plot effort-level comparison charts for a reasoning-sweep suite."
    )
    parser.add_argument(
        "--suite-dir",
        type=Path,
        required=True,
        help="Suite directory (e.g. output/reasoning_test/001_binary_search).",
    )
    args = parser.parse_args(argv)

    suite_dir = args.suite_dir.resolve()
    if not suite_dir.is_dir():
        print(f"Suite directory not found: {suite_dir}", file=sys.stderr)
        return 2

    built = build_suite_charts(suite_dir)
    if built == 0:
        print("No effort comparison charts built (need cell logs/*-log.csv).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
