#!/usr/bin/env python3
"""Plot sycophancy signals (S1-S7) per experiment.

Reads the per-model JSON written by ``compute_signals.py``
(``result/<exp>/signals/<stamp>-signals.json``) and renders, per experiment, a
grid of grouped bar charts (one panel per continuous signal, models side by
side) plus a binary-flag matrix (models x S1..S6). Saves
``result/<exp>/plots/<exp>_signals.png``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_RESULT_DIR = _SCRIPT_DIR / "result"
sys.path.insert(0, str(_SCRIPT_DIR))

from experiment_runner.result_paths import plots_dir, signals_dir  # noqa: E402

_CACHE_ROOT = Path(tempfile.gettempdir()) / "sycophancy-plot-signals-cache"
_MPL_CACHE = _CACHE_ROOT / "matplotlib"
_XDG_CACHE = _CACHE_ROOT / "xdg"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
_XDG_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))
os.environ.setdefault("XDG_CACHE_HOME", str(_XDG_CACHE))

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.gridspec as gridspec  # noqa: E402
import matplotlib.ticker as ticker  # noqa: E402

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 10,
        "axes.linewidth": 0.8,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "figure.dpi": 150,
    }
)


from style_config import (  # noqa: E402
    BINARY_SIGNAL_IDS,
    COLORS,
    DEFAULT_NUM_TURNS,
    LABELS,
    RATIO_SIGNAL_IDS,
    SIGNAL_GRID_COLS,
    SIGNAL_IDS,
    SIGNAL_TITLES,
    TURN_SIGNAL_IDS,
)


def _signal_bar_ylim(sid: str, top: float) -> tuple[float, float]:
    if sid in TURN_SIGNAL_IDS:
        return 0.5, DEFAULT_NUM_TURNS + 0.5
    if sid in RATIO_SIGNAL_IDS:
        return 0.0, min(1.0, max(top * 1.12, 0.1))
    return 0.0, top * 1.18 if top > 0 else 1.0


def _format_signal_value(
    sid: str, val: float, *, never_stopped: bool = False
) -> str:
    if sid in TURN_SIGNAL_IDS:
        text = f"{int(round(val))}"
        if never_stopped:
            text += "\u2020"
        return text
    if sid in RATIO_SIGNAL_IDS:
        return f"{val:.3f}"
    return f"{val:.2f}"


@dataclass
class ModelSignals:
    model: str
    label: str
    color: str
    cont: dict[str, float]
    binary: dict[str, int]
    never_stopped: dict[str, bool]


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


def load_model_signals(exp_dir: Path) -> list[ModelSignals]:
    path = signals_dir(exp_dir)
    if not path.is_dir():
        return []

    models: list[ModelSignals] = []
    for json_path in sorted(path.glob("*-signals.json")):
        data = json.loads(json_path.read_text(encoding="utf-8"))
        model = str(data.get("model") or json_path.stem)
        signals = data.get("signals") or {}
        cont = {sid: float(signals.get(sid, {}).get("cont", 0.0)) for sid in SIGNAL_IDS}
        binary = {
            sid: int(signals.get(sid, {}).get("bin", 0)) for sid in BINARY_SIGNAL_IDS
        }
        never_stopped = {
            sid: bool(signals.get(sid, {}).get("never_stopped", False))
            for sid in TURN_SIGNAL_IDS
        }
        models.append(
            ModelSignals(
                model=model,
                label=LABELS.get(model, model),
                color=COLORS.get(model, "#4878a8"),
                cont=cont,
                binary=binary,
                never_stopped=never_stopped,
            )
        )
    return models


def plot_experiment(
    exp_dir: Path,
    models: list[ModelSignals],
    *,
    suptitle: str | None = None,
    out_path: Path | None = None,
) -> Path:
    n_models = len(models)
    fig = plt.figure(figsize=(max(12.0, 2.2 * n_models + 8.0), 9.0))
    outer = gridspec.GridSpec(
        2, 1, figure=fig, height_ratios=[3.0, 1.0], hspace=0.45
    )
    bar_grid = outer[0].subgridspec(
        (len(SIGNAL_IDS) + SIGNAL_GRID_COLS - 1) // SIGNAL_GRID_COLS,
        SIGNAL_GRID_COLS,
        hspace=0.55,
        wspace=0.3,
    )

    labels = [m.label for m in models]
    colors = [m.color for m in models]
    x = list(range(n_models))

    for idx, sid in enumerate(SIGNAL_IDS):
        ax = fig.add_subplot(bar_grid[idx // SIGNAL_GRID_COLS, idx % SIGNAL_GRID_COLS])
        values = [m.cont[sid] for m in models]
        ax.bar(x, values, color=colors, edgecolor="white", linewidth=0.6)
        ax.set_title(SIGNAL_TITLES[sid], fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        ax.margins(x=0.15)
        top = max(values + [0.0])
        ax.set_ylim(*_signal_bar_ylim(sid, top))
        for xi, val, m in zip(x, values, models):
            censored = sid in TURN_SIGNAL_IDS and m.never_stopped.get(sid, False)
            ax.text(
                xi,
                val + (top * 0.02 if top > 0 else 0.02),
                _format_signal_value(sid, val, never_stopped=censored),
                ha="center",
                va="bottom",
                fontsize=8,
            )
        if sid in TURN_SIGNAL_IDS and any(m.never_stopped.get(sid, False) for m in models):
            ax.text(
                0.02,
                0.98,
                "\u2020 = never stopped",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=7,
                color="0.35",
            )

    matrix_ax = fig.add_subplot(outer[1])
    grid = [[m.binary[sid] for sid in BINARY_SIGNAL_IDS] for m in models]
    matrix_ax.imshow(grid, cmap="Greens", vmin=0, vmax=1, aspect="auto")
    matrix_ax.set_xticks(range(len(BINARY_SIGNAL_IDS)))
    matrix_ax.set_xticklabels(BINARY_SIGNAL_IDS)
    matrix_ax.set_yticks(range(n_models))
    matrix_ax.set_yticklabels(labels, fontsize=8)
    matrix_ax.set_title("Binary signal flags (1 = triggered)", fontsize=10)
    for r in range(n_models):
        for c in range(len(BINARY_SIGNAL_IDS)):
            val = grid[r][c]
            matrix_ax.text(
                c,
                r,
                str(val),
                ha="center",
                va="center",
                fontsize=9,
                color="white" if val else "0.4",
            )
    matrix_ax.set_xticks([i - 0.5 for i in range(1, len(BINARY_SIGNAL_IDS))], minor=True)
    matrix_ax.set_yticks([i - 0.5 for i in range(1, n_models)], minor=True)
    matrix_ax.grid(which="minor", color="white", linewidth=1.2)
    matrix_ax.tick_params(which="minor", length=0)
    matrix_ax.xaxis.set_major_locator(ticker.FixedLocator(range(len(BINARY_SIGNAL_IDS))))

    fig.suptitle(
        suptitle or f"Sycophancy signals: {exp_dir.name}",
        fontsize=13,
    )
    fig.subplots_adjust(left=0.08, right=0.97, top=0.92, bottom=0.08)

    if out_path is None:
        plots_out_dir = plots_dir(exp_dir)
        plots_out_dir.mkdir(parents=True, exist_ok=True)
        out_path = plots_out_dir / f"{exp_dir.name}_signals.png"
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def build_reasoning_suite(suite_dir: Path) -> int:
    """One combined signals chart per model family (effort levels side by side)."""
    from reasoning_cells import effort_cell_dirs, effort_color, effort_display, model_prefixes_in_suite

    suite_dir = suite_dir.resolve()
    plots_out = suite_dir / "plots"
    built = 0
    for model_prefix in model_prefixes_in_suite(suite_dir):
        models: list[ModelSignals] = []
        for effort, cell_dir in effort_cell_dirs(suite_dir, model_prefix):
            cell_models = load_model_signals(cell_dir)
            if not cell_models:
                continue
            src = cell_models[-1]
            models.append(
                ModelSignals(
                    model=effort,
                    label=effort_display(effort),
                    color=effort_color(effort),
                    cont=src.cont,
                    binary=src.binary,
                )
            )
        if len(models) < 2:
            continue
        slug = model_prefix.replace(".", "_")
        out_path = plots_out / f"{slug}_signals_effort_comparison.png"
        plot_experiment(
            suite_dir,
            models,
            suptitle=f"Sycophancy signals — {model_prefix.upper()} (by effort)",
            out_path=out_path,
        )
        print(f"Built: {model_prefix} effort comparison -> {out_path}")
        built += 1
    return built


def build_one(exp_dir: Path) -> bool:
    models = load_model_signals(exp_dir)
    if not models:
        print(f"Skipped: {exp_dir.name} (no signals/*-signals.json)")
        return False
    out_path = plot_experiment(exp_dir, models)
    print(f"Built: {exp_dir.name} -> {out_path}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot S1-S7 signals per experiment.")
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
            print("No signals effort comparison plots built.", file=sys.stderr)
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
        print("No signal plots built (run compute_signals.py first).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
