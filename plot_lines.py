#!/usr/bin/env python3
"""Plot total lines changed per refactoring run, per experiment.

Reads the per-model CSVs written by ``run_experiment.py``
(``<base>/<exp>/logs/<stamp>-<model>-log.csv``) and renders, per experiment, a
line chart of ``lines_total`` vs run number with one line per model. Saves
``<base>/<exp>/plots/<exp>_lines.png``.

This is the ``plot_lines`` pipeline phase (runs right after ``run_exp``); it is
the formal successor to the old ``result/plot.py`` helper.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_RESULT_DIR = _SCRIPT_DIR / "result"
sys.path.insert(0, str(_SCRIPT_DIR))

from experiment_runner.result_paths import iter_log_csvs, plots_dir  # noqa: E402
from style_config import COLORS, LABELS, MARKERS  # noqa: E402

_CACHE_ROOT = Path(tempfile.gettempdir()) / "sycophancy-plot-lines-cache"
_MPL_CACHE = _CACHE_ROOT / "matplotlib"
_XDG_CACHE = _CACHE_ROOT / "xdg"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
_XDG_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))
os.environ.setdefault("XDG_CACHE_HOME", str(_XDG_CACHE))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as ticker  # noqa: E402

# Paper-friendly style settings.
plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 11,
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


# Defensive fallbacks so any model absent from style_config still gets a
# distinct color/marker rather than silently repeating one.
_FALLBACK_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]
_FALLBACK_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*", "<", ">", "p", "h"]


def resolve_styles(models: list[str]) -> dict[str, tuple[str, str, str]]:
    """Map each model -> (color, marker, label), all mutually distinct.

    Prefer style_config; fill any gaps/collisions from the fallback palettes
    without reusing a color or marker already taken in this chart.
    """
    styles: dict[str, tuple[str, str, str]] = {}
    used_colors: set[str] = set()
    used_markers: set[str] = set()

    def pick(preferred, palette, used):
        if preferred and preferred not in used:
            return preferred
        for cand in palette:
            if cand not in used:
                return cand
        return preferred  # palettes exhausted; accept a repeat

    for model in models:
        color = pick(COLORS.get(model), _FALLBACK_COLORS, used_colors)
        marker = pick(MARKERS.get(model), _FALLBACK_MARKERS, used_markers)
        used_colors.add(color)
        used_markers.add(marker)
        styles[model] = (color, marker, LABELS.get(model, model))
    return styles


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


def render_lines_chart(
    series: list[tuple[str, "pd.DataFrame"]],
    *,
    title: str,
    out_path: Path,
    legend_title: str = "Model",
) -> bool:
    """Render a lines_total vs run chart. Returns True if written."""
    if not series:
        return False

    styles = resolve_styles([m for m, _ in series])

    n_runs = max((int(df["run"].max()) for _, df in series if len(df)), default=10)
    width = max(6.0, 1.1 * n_runs)
    fig, ax = plt.subplots(figsize=(width, 3.5))
    for model, df in series:
        color, marker, label = styles[model]
        ax.plot(
            df["run"],
            df["lines_total"],
            marker=marker,
            markersize=5,
            linewidth=1.2,
            color=color,
            label=label,
        )

    ax.set_xlabel("Refactoring Iteration (run)")
    ax.set_ylabel("Lines Total Changed")
    ax.set_title(title)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)

    leg = ax.legend(
        loc="upper right",
        fontsize=7,
        title=legend_title,
        title_fontsize=8,
        framealpha=0.9,
        markerscale=0.8,
        handlelength=1.6,
        labelspacing=0.3,
        borderpad=0.4,
    )
    fig.tight_layout()

    lines_xy = [
        (df["run"].to_numpy(dtype=float), df["lines_total"].to_numpy(dtype=float))
        for _, df in series
        if len(df)
    ]

    def max_line_height(x0: float, x1: float) -> float:
        peak = 0.0
        for xs, ys in lines_xy:
            cand = list(ys[(xs >= x0) & (xs <= x1)])
            for xe in (x0, x1):
                if xs.min() <= xe <= xs.max():
                    cand.append(float(np.interp(xe, xs, ys)))
            if cand:
                peak = max(peak, max(cand))
        return peak

    if lines_xy:
        for _ in range(6):
            fig.canvas.draw()
            lb = leg.get_window_extent().transformed(ax.transData.inverted())
            x0, x1 = sorted((lb.x0, lb.x1))
            y_bottom = min(lb.y0, lb.y1)
            peak = max_line_height(x0, x1)
            if peak * 1.05 < y_bottom:
                break
            top = ax.get_ylim()[1]
            scale = (peak * 1.06) / max(y_bottom, 1e-9)
            ax.set_ylim(top=top * max(scale, 1.02))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote: {out_path}")
    return True


def build_one(exp_dir: Path) -> bool:
    """Render the lines_total chart for one experiment. Returns True if written."""
    csv_files = iter_log_csvs(exp_dir)
    if not csv_files:
        return False

    series: list[tuple[str, "pd.DataFrame"]] = []
    for csv_path in csv_files:
        df = pd.read_csv(csv_path)
        if df.empty or "run" not in df or "lines_total" not in df:
            continue
        model = str(df["model"].iloc[0]) if "model" in df else csv_path.stem
        series.append((model, df))

    if not series:
        return False

    plots_out_dir = plots_dir(exp_dir)
    out_path = plots_out_dir / f"{exp_dir.name}_lines.png"
    return render_lines_chart(
        series,
        title=f"Lines Changed per Refactoring Run — {exp_dir.name.upper()}",
        out_path=out_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plot total lines changed per run per experiment."
    )
    parser.add_argument(
        "--output-base",
        type=Path,
        default=_RESULT_DIR,
        help="Base dir holding experiment folders (default: <repo>/result).",
    )
    args = parser.parse_args(argv)

    exp_dirs = experiment_dirs(args.output_base.resolve())
    if not exp_dirs:
        print(f"No result folders found in {args.output_base}", file=sys.stderr)
        return 2

    built = 0
    for exp_dir in exp_dirs:
        if build_one(exp_dir):
            built += 1

    if built == 0:
        print("No line-change plots built (need logs/*-log.csv).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
