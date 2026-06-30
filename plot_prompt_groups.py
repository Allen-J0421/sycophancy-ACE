#!/usr/bin/env python3
"""8-way prompt-ablation comparison charts for a single-codebase suite.

Scans ``<suite-dir>/<cellid>-Agent/`` cell folders (one per B+A ablation cell) and
renders three comparison figures into ``<suite-dir>/plots/``:

- ``prompt_lines_comparison.png``   — lines_total vs run, one series per cell
- ``prompt_signals_comparison.png`` — S0..S7, one grouped bar per cell, per signal
- ``prompt_refdiff_comparison.png`` — RefDiff relationship distribution, cells side by side

Cells are ordered to match ``config/ablation_B_plus_A_core8.json`` (controls first).
Reuses the existing per-experiment readers/renderers:
``plot_lines.render_lines_chart``, ``plot_signals.load_model_signals``,
``plot_refdiff.summarize_jsonl`` / ``plot_refdiff.plot_experiment``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

_AGENT_SUFFIX = "-Agent"
_ABLATION_CONFIG = _SCRIPT_DIR / "config" / "ablation_B_plus_A_core8.json"


def cell_order() -> list[str]:
    """Canonical cell order from the ablation config (controls first)."""
    try:
        data = json.loads(_ABLATION_CONFIG.read_text(encoding="utf-8"))
        return [str(c["id"]) for c in data.get("cells", [])]
    except (OSError, json.JSONDecodeError, KeyError):
        return []


def cell_dirs(suite_dir: Path) -> list[tuple[str, Path]]:
    """Return ``(cell_id, dir)`` for each ``<cellid>-Agent`` folder, in config order."""
    found: dict[str, Path] = {}
    for entry in sorted(suite_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if not entry.name.endswith(_AGENT_SUFFIX):
            continue
        cell_id = entry.name[: -len(_AGENT_SUFFIX)]
        if cell_id:
            found[cell_id] = entry

    ordered: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for cell_id in cell_order():
        if cell_id in found:
            ordered.append((cell_id, found[cell_id]))
            seen.add(cell_id)
    for cell_id in sorted(found):  # any cells not in the config, appended
        if cell_id not in seen:
            ordered.append((cell_id, found[cell_id]))
    return ordered


# ---------------------------------------------------------------------------
# Lines comparison
# ---------------------------------------------------------------------------

def build_lines_chart(suite_dir: Path, cells: list[tuple[str, Path]]) -> bool:
    import pandas as pd
    from plot_lines import render_lines_chart
    from reasoning_cells import iter_log_csvs

    series: list[tuple[str, "pd.DataFrame"]] = []
    for cell_id, cell_dir in cells:
        csvs = iter_log_csvs(cell_dir)
        if not csvs:
            continue
        df = pd.read_csv(csvs[-1])
        if df.empty or "run" not in df or "lines_total" not in df:
            continue
        series.append((cell_id, df))

    if not series:
        print("No lines series found (need <cell>/logs/*-log.csv).", file=sys.stderr)
        return False

    out_path = suite_dir / "plots" / "prompt_lines_comparison.png"
    return render_lines_chart(
        series,
        title=f"Lines Changed per Refactoring Run — {suite_dir.name} (by prompt cell)",
        out_path=out_path,
        legend_title="Prompt cell",
    )


# ---------------------------------------------------------------------------
# Signals comparison
# ---------------------------------------------------------------------------

def build_signals_chart(suite_dir: Path, cells: list[tuple[str, Path]]) -> bool:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    from plot_signals import (
        ModelSignals,
        _format_signal_value,
        _signal_bar_ylim,
        load_model_signals,
    )
    from plot_lines import resolve_styles
    from style_config import SIGNAL_GRID_COLS, SIGNAL_IDS, SIGNAL_TITLES, TURN_SIGNAL_IDS

    # One ModelSignals per cell (each cell ran a single model: gpt-5.5).
    labels: list[str] = []
    sigs: list[ModelSignals] = []
    for cell_id, cell_dir in cells:
        loaded = load_model_signals(cell_dir)
        if not loaded:
            continue
        labels.append(cell_id)
        sigs.append(loaded[-1])
    if not sigs:
        print("No signals found (need <cell>/signals/*-signals.json).", file=sys.stderr)
        return False

    styles = resolve_styles(labels)
    colors = [styles[label][0] for label in labels]

    n = len(SIGNAL_IDS)
    n_rows = (n + SIGNAL_GRID_COLS - 1) // SIGNAL_GRID_COLS
    fig, axes = plt.subplots(
        n_rows,
        SIGNAL_GRID_COLS,
        figsize=(3.4 * SIGNAL_GRID_COLS, 3.0 * n_rows),
        squeeze=False,
    )
    x = list(range(len(labels)))

    for idx, sid in enumerate(SIGNAL_IDS):
        ax = axes[idx // SIGNAL_GRID_COLS][idx % SIGNAL_GRID_COLS]
        values = [m.cont.get(sid, 0.0) for m in sigs]
        ax.bar(x, values, color=colors, edgecolor="white", linewidth=0.5)
        top = max(values + [0.0])
        ax.set_ylim(*_signal_bar_ylim(sid, top))
        ax.set_title(SIGNAL_TITLES.get(sid, sid), fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=6)
        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        if sid in TURN_SIGNAL_IDS:
            ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        for xi, val, m in zip(x, values, sigs):
            never = m.never_stopped.get(sid, False) if sid in TURN_SIGNAL_IDS else False
            ax.text(
                xi,
                val,
                _format_signal_value(sid, val, never_stopped=never),
                ha="center",
                va="bottom",
                fontsize=6,
            )

    for j in range(n, n_rows * SIGNAL_GRID_COLS):  # hide unused cells
        axes[j // SIGNAL_GRID_COLS][j % SIGNAL_GRID_COLS].axis("off")

    fig.suptitle(f"Sycophancy signals by prompt cell — {suite_dir.name}", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    out_path = suite_dir / "plots" / "prompt_signals_comparison.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote: {out_path}")
    return True


# ---------------------------------------------------------------------------
# RefDiff comparison
# ---------------------------------------------------------------------------

def build_refdiff_chart(suite_dir: Path, cells: list[tuple[str, Path]]) -> bool:
    from plot_refdiff import (
        BatchSummary,
        plot_experiment,
        refdiff_jsonl_files,
        summarize_jsonl,
    )

    summaries: list[BatchSummary] = []
    for cell_id, cell_dir in cells:
        jsonl_files = refdiff_jsonl_files(cell_dir)
        if not jsonl_files:
            continue
        summary = summarize_jsonl(jsonl_files[-1])
        if summary.records_total == 0:
            continue
        # Re-label by cell id so each side-by-side subplot is titled with the cell.
        summaries.append(
            BatchSummary(
                jsonl_path=summary.jsonl_path,
                model=cell_id,
                stamp=summary.stamp,
                counts=summary.counts,
                records_total=summary.records_total,
                records_skipped=summary.records_skipped,
            )
        )
    if not summaries:
        print("No refdiff summaries found (need <cell>/refdiff/*-refdiff.jsonl).", file=sys.stderr)
        return False

    out_path = suite_dir / "plots" / "prompt_refdiff_comparison.png"
    plot_experiment(
        suite_dir,
        summaries,
        suptitle=f"RefDiff relationship distribution by prompt cell — {suite_dir.name}",
        out_path=out_path,
    )
    print(f"Wrote: {out_path}")
    return True


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plot 8-way prompt-ablation comparison charts for a single-codebase suite."
    )
    parser.add_argument(
        "--suite-dir",
        type=Path,
        required=True,
        help="Suite dir (e.g. output/prompt-expert/Algorithms/001_binary_search).",
    )
    args = parser.parse_args(argv)

    suite_dir = args.suite_dir.resolve()
    if not suite_dir.is_dir():
        print(f"Suite directory not found: {suite_dir}", file=sys.stderr)
        return 2

    cells = cell_dirs(suite_dir)
    if not cells:
        print(f"No <cellid>-Agent cell folders found in {suite_dir}", file=sys.stderr)
        return 2
    print(f"[plot] {len(cells)} cell(s): {', '.join(c for c, _ in cells)}", file=sys.stderr)

    built = 0
    built += build_lines_chart(suite_dir, cells)
    built += build_signals_chart(suite_dir, cells)
    built += build_refdiff_chart(suite_dir, cells)

    if built == 0:
        print("No comparison charts built.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
