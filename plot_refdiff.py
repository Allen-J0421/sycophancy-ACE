#!/usr/bin/env python3
"""Build stacked RefDiff relationship plots for every result folder."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_RESULT_DIR = _SCRIPT_DIR / "result"
sys.path.insert(0, str(_SCRIPT_DIR))

from experiment_runner.result_paths import plots_dir, refdiff_dir  # noqa: E402

_CACHE_ROOT = Path(tempfile.gettempdir()) / "sycophancy-plot-refdiff-cache"
_MPL_CACHE = _CACHE_ROOT / "matplotlib"
_XDG_CACHE = _CACHE_ROOT / "xdg"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
_XDG_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))
os.environ.setdefault("XDG_CACHE_HOME", str(_XDG_CACHE))

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as patches  # noqa: E402
import matplotlib.gridspec as gridspec  # noqa: E402
import matplotlib.ticker as ticker  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

CATEGORIES = ("Matching", "Non-Matching", "No Relationship")
NO_RELATIONSHIP_TYPES = ("Node Deleted", "Node Added")
FALLBACK_COLORS = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 10,
        "axes.linewidth": 0.8,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.major.size": 4,
        "ytick.major.size": 4,
        "legend.frameon": True,
        "legend.framealpha": 0.9,
        "legend.edgecolor": "0.8",
        "figure.dpi": 150,
    }
)


from style_config import LABELS  # noqa: E402


@dataclass
class BatchSummary:
    jsonl_path: Path
    model: str
    stamp: str
    counts: dict[str, Counter[str]]
    records_total: int
    records_skipped: int


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


def count_no_relationships(record: dict) -> Counter[str]:
    """Count nodes with no RefDiff relationships, matching dashboard semantics."""
    node_relationships = record.get("node_relationships") or {}
    if node_relationships:
        seen_before: set[str] = set()
        seen_after: set[str] = set()

        for key, entry in node_relationships.items():
            if not key.startswith("before:"):
                continue
            relationships = entry.get("relationships") or []
            if not relationships:
                continue
            seen_before.add(key)
            for rel in relationships:
                counterpart_key = rel.get("counterpart_key")
                if counterpart_key:
                    seen_after.add(counterpart_key)

        counts: Counter[str] = Counter()
        for key in node_relationships:
            if key.startswith("before:") and key not in seen_before:
                counts["Node Deleted"] += 1
            elif key.startswith("after:") and key not in seen_after:
                counts["Node Added"] += 1
        return counts

    seen_before_ids: set[int] = set()
    seen_after_ids: set[int] = set()
    relationships = (record.get("matching_relationships") or []) + (
        record.get("non_matching_relationships") or []
    )
    for rel in relationships:
        before = rel.get("before") or {}
        after = rel.get("after") or {}
        if "id" in before:
            seen_before_ids.add(int(before["id"]))
        if "id" in after:
            seen_after_ids.add(int(after["id"]))

    counts = Counter()
    for node in record.get("nodes_before") or []:
        if int(node.get("id", 0)) not in seen_before_ids:
            counts["Node Deleted"] += 1
    for node in record.get("nodes_after") or []:
        if int(node.get("id", 0)) not in seen_after_ids:
            counts["Node Added"] += 1
    return counts


def empty_counts() -> dict[str, Counter[str]]:
    return {category: Counter() for category in CATEGORIES}


def summarize_jsonl(jsonl_path: Path) -> BatchSummary:
    counts = empty_counts()
    records_total = 0
    records_skipped = 0
    model = ""
    stamp = ""

    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            records_total += 1
            record = json.loads(line)
            model = model or str(record.get("model") or "")
            stamp = stamp or str(record.get("stamp") or "")

            if not record.get("refdiff_ok", False):
                records_skipped += 1
                continue

            for rel in record.get("matching_relationships") or []:
                rel_type = str(rel.get("type") or "UNKNOWN")
                if rel_type == "SAME" and not rel.get("same_edited"):
                    continue
                counts["Matching"][rel_type] += 1
            for rel in record.get("non_matching_relationships") or []:
                counts["Non-Matching"][str(rel.get("type") or "UNKNOWN")] += 1
            counts["No Relationship"].update(count_no_relationships(record))

    if not model:
        model = model_from_filename(jsonl_path)
    if not stamp:
        stamp = jsonl_path.name.removesuffix("-refdiff.jsonl")

    return BatchSummary(
        jsonl_path=jsonl_path,
        model=model,
        stamp=stamp,
        counts=counts,
        records_total=records_total,
        records_skipped=records_skipped,
    )


def model_from_filename(jsonl_path: Path) -> str:
    stem = jsonl_path.name.removesuffix("-refdiff.jsonl")
    parts = stem.split("-", 1)
    return parts[1] if len(parts) > 1 else stem


def series_order(summaries: list[BatchSummary]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    preferred = (
        "SAME",
        "RENAME",
        "CHANGE_SIGNATURE",
        "MOVE",
        "INTERNAL_MOVE",
        "MOVE_RENAME",
        "INTERNAL_MOVE_RENAME",
        "PULL_UP",
        "PUSH_DOWN",
        "PULL_UP_SIGNATURE",
        "PUSH_DOWN_IMPL",
        "EXTRACT_SUPER",
        "EXTRACT",
        "EXTRACT_MOVE",
        "INLINE",
        *NO_RELATIONSHIP_TYPES,
    )

    available = {
        rel_type
        for summary in summaries
        for category in CATEGORIES
        for rel_type in summary.counts[category]
    }
    for rel_type in preferred:
        if rel_type in available:
            seen.add(rel_type)
            ordered.append(rel_type)
    for rel_type in sorted(available - seen):
        ordered.append(rel_type)
    return ordered


def colors_for(series: list[str]) -> dict[str, str]:
    colors: dict[str, str] = {
        "Node Deleted": "#7f7f7f",
        "Node Added": "#bcbd22",
    }
    for i, rel_type in enumerate(series):
        colors.setdefault(rel_type, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
    return colors


def subplot_title(summary: BatchSummary) -> str:
    return LABELS.get(summary.model, summary.model or "Unknown model")


def render_summary_widget(
    ax: plt.Axes,
    summary: BatchSummary,
    series: list[str],
    colors: dict[str, str],
) -> None:
    ax.axis("off")
    x0 = 0.0
    y = 0.98

    for category in CATEGORIES:
        category_counts = summary.counts[category]
        total = sum(category_counts.values())

        ax.text(
            x0,
            y,
            f"{category} ({total})",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10,
            fontweight="bold",
        )
        y -= 0.075

        if total == 0:
            ax.text(
                x0 + 0.16,
                y,
                "None",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=9,
                color="0.35",
            )
            y -= 0.075
        else:
            for rel_type in series:
                count = category_counts.get(rel_type, 0)
                if count == 0:
                    continue

                proportion = count / total
                ax.add_patch(
                    patches.Rectangle(
                        (x0, y - 0.035),
                        0.1,
                        0.055,
                        transform=ax.transAxes,
                        color=colors[rel_type],
                        clip_on=False,
                    )
                )
                ax.text(
                    x0 + 0.13,
                    y,
                    f"{rel_type}: {count} ({proportion:.1%})",
                    transform=ax.transAxes,
                    ha="left",
                    va="center",
                    fontsize=9,
                )
                y -= 0.062

        y -= 0.04


def plot_experiment(
    exp_dir: Path,
    summaries: list[BatchSummary],
    *,
    suptitle: str | None = None,
    out_path: Path | None = None,
) -> Path:
    n_plots = len(summaries)
    fig_width = max(12.0, 6.8 * n_plots)
    fig_height = 8.8
    fig = plt.figure(figsize=(fig_width, fig_height))
    outer = gridspec.GridSpec(1, n_plots, figure=fig, wspace=0.22)
    series = series_order(summaries)
    colors = colors_for(series)

    for i, summary in enumerate(summaries):
        inner = outer[i].subgridspec(
            1,
            2,
            width_ratios=[3.9, 1.55],
            wspace=0.03,
        )
        ax = fig.add_subplot(inner[0])
        widget_ax = fig.add_subplot(inner[1])
        bottoms = [0] * len(CATEGORIES)
        totals = [sum(summary.counts[category].values()) for category in CATEGORIES]

        for rel_type in series:
            values = [summary.counts[category].get(rel_type, 0) for category in CATEGORIES]
            if not any(values):
                continue

            ax.bar(
                CATEGORIES,
                values,
                bottom=bottoms,
                color=colors[rel_type],
                edgecolor="white",
                linewidth=0.5,
                label=rel_type,
            )
            bottoms = [bottom + value for bottom, value in zip(bottoms, values)]

        ax.set_title(subplot_title(summary), fontsize=11)
        ax.set_ylabel("Frequency")
        ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        ax.tick_params(axis="x", rotation=20)
        ax.set_ylim(0, max(totals + [1]) * 1.08)
        ax.margins(x=0.18)
        if summary.records_skipped:
            ax.text(
                0.98,
                0.96,
                f"Skipped failed: {summary.records_skipped}",
                transform=ax.transAxes,
                ha="right",
                va="top",
                fontsize=8,
            )

        render_summary_widget(widget_ax, summary, series, colors)

    fig.suptitle(
        suptitle or f"RefDiff relationship distribution: {exp_dir.name}",
        fontsize=13,
    )
    fig.subplots_adjust(left=0.04, right=0.98, top=0.88, bottom=0.12)

    if out_path is None:
        plots_out_dir = plots_dir(exp_dir)
        plots_out_dir.mkdir(parents=True, exist_ok=True)
        out_path = plots_out_dir / f"{exp_dir.name}_refdiff.png"
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def build_reasoning_suite(suite_dir: Path) -> int:
    """One combined RefDiff chart per model family (effort levels side by side)."""
    from reasoning_cells import effort_cell_dirs, effort_display, model_prefixes_in_suite

    suite_dir = suite_dir.resolve()
    plots_out = suite_dir / "plots"
    built = 0
    for model_prefix in model_prefixes_in_suite(suite_dir):
        summaries: list[BatchSummary] = []
        for effort, cell_dir in effort_cell_dirs(suite_dir, model_prefix):
            jsonl_files = refdiff_jsonl_files(cell_dir)
            if not jsonl_files:
                continue
            summary = summarize_jsonl(jsonl_files[-1])
            if summary.records_total == 0:
                continue
            summaries.append(
                BatchSummary(
                    jsonl_path=summary.jsonl_path,
                    model=effort_display(effort),
                    stamp=summary.stamp,
                    counts=summary.counts,
                    records_total=summary.records_total,
                    records_skipped=summary.records_skipped,
                )
            )
        if len(summaries) < 2:
            continue
        slug = model_prefix.replace(".", "_")
        out_path = plots_out / f"{slug}_refdiff_effort_comparison.png"
        plot_experiment(
            suite_dir,
            summaries,
            suptitle=f"RefDiff relationship distribution — {model_prefix.upper()} (by effort)",
            out_path=out_path,
        )
        print(f"Built: {model_prefix} effort comparison -> {out_path}")
        built += 1
    return built


def build_one(exp_dir: Path) -> bool:
    jsonl_files = refdiff_jsonl_files(exp_dir)
    if not jsonl_files:
        print(f"Skipped: {exp_dir.name} (no refdiff/*-refdiff.jsonl)")
        return False

    summaries = [summarize_jsonl(path) for path in jsonl_files]
    summaries = [summary for summary in summaries if summary.records_total > 0]
    if not summaries:
        print(f"Skipped: {exp_dir.name} (empty refdiff JSONL files)")
        return False

    out_path = plot_experiment(exp_dir, summaries)
    skipped = sum(summary.records_skipped for summary in summaries)
    suffix = f"; skipped {skipped} failed records" if skipped else ""
    print(f"Built: {exp_dir.name} -> {out_path}{suffix}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot RefDiff relationship distribution per experiment.")
    parser.add_argument(
        "--output-base",
        type=Path,
        default=_RESULT_DIR,
        help="Base dir holding experiment folders (default: <repo>/result).",
    )
    args = parser.parse_args(argv)
    output_base = args.output_base.resolve()

    from reasoning_cells import is_reasoning_suite

    if is_reasoning_suite(output_base):
        built = build_reasoning_suite(output_base)
        if built == 0:
            print("No RefDiff effort comparison plots built.", file=sys.stderr)
            return 1
        return 0

    exp_dirs = experiment_dirs(output_base)
    if not exp_dirs:
        print(f"No result folders found in {output_base}", file=sys.stderr)
        return 2

    built = 0
    for exp_dir in exp_dirs:
        if build_one(exp_dir):
            built += 1

    if built == 0:
        print("No RefDiff plots built.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
