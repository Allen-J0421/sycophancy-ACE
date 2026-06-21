#!/usr/bin/env python3
"""Aggregate line-changes / signals / refdiff across ALL codebases in a suite.

Produces three per-model aggregate figures (and a CSV of the underlying numbers)
for one suite (``Algorithms`` or ``RealWorld``), chosen with ``--suite``.

Aggregation design:
  * LINES  - each codebase's ``lines_total`` series is normalized by that
             codebase's baseline LOC ``L0`` (raw line counts scale with codebase
             size, so we MUST divide by L0 before averaging). We then average the
             normalized series across codebases, per model, with a ±SEM band.
  * SIGNALS- plain mean of each continuous S1..S6 across codebases, per model.
             (S1/S2/S3 are already ÷L0 and S6 is a bounded ratio; S4/S5 are raw
             counts and are meaned as-is per project direction.)
  * REFDIFF- plain mean of each RefDiff relationship-type count across codebases,
             per model.

A ``--alg`` flag restricts which codebases participate (e.g. ``--alg 001-020``);
default is everything.

Usage:
  python plot_aggregate.py --suite Algorithms
  python plot_aggregate.py --suite Algorithms --alg 001-020
  python plot_aggregate.py --suite Algorithms --alg 001-010,015
  python plot_aggregate.py --suite RealWorld

Caveat: dead runs (spend-cap / session-limit empty diffs, e.g. GPT on
algorithms 041-050) contribute 0 to the line means and will pull a model's curve
toward 0 in those ranges. Use ``--alg`` to scope to clean ranges; this tool does
not auto-drop them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

_CACHE_ROOT = Path(tempfile.gettempdir()) / "sycophancy-plot-aggregate-cache"
for _sub in ("matplotlib", "xdg"):
    (_CACHE_ROOT / _sub).mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_ROOT / "xdg"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.gridspec as gridspec  # noqa: E402
import matplotlib.patches as patches  # noqa: E402
import matplotlib.ticker as ticker  # noqa: E402

from style_config import COLORS, LABELS  # noqa: E402
from plot_lines import resolve_styles  # noqa: E402
from plot_refdiff import (  # noqa: E402
    BatchSummary,
    CATEGORIES,
    colors_for,
    refdiff_jsonl_files,
    series_order,
    subplot_title,
    summarize_jsonl,
)
from experiment_runner.result_paths import (  # noqa: E402
    iter_log_csvs,
    signals_dir,
    signals_csv_path,
)

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 11,
        "axes.linewidth": 0.8,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "figure.dpi": 150,
    }
)

SIGNAL_IDS = ("S1", "S2", "S3", "S4", "S5", "S6")
SIGNAL_TITLES = {
    "S1": "S1 Pre-conv churn (÷L0)",
    "S2": "S2 Post-conv mod (÷L0)",
    "S3": "S3 Volatility (÷L0)",
    "S4": "S4 Feature rollback (count)",
    "S5": "S5 Reimpl. loop (count)",
    "S6": "S6 Patch recurrence (ratio)",
}
BUCKETS = CATEGORIES  # ("Matching", "Non-Matching", "No Relationship")


# --------------------------------------------------------------------------- #
# --alg filtering
# --------------------------------------------------------------------------- #
def exp_number(dir_name: str) -> int | None:
    """First run of digits in an exp dir name. '001_binary..' -> 1, 'R001_..' -> 1."""
    m = re.search(r"\d+", dir_name)
    return int(m.group()) if m else None


def parse_alg_filter(spec: str | None) -> set[int] | None:
    """Parse '001-020', '005', '001-010,015' -> set of ints. None = take all."""
    if not spec:
        return None
    wanted: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi:
                lo, hi = hi, lo
            wanted.update(range(lo, hi + 1))
        else:
            wanted.add(int(part))
    return wanted or None


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def experiment_dirs(suite_dir: Path, alg: set[int] | None) -> list[Path]:
    if not suite_dir.is_dir():
        return []
    out = []
    for d in sorted(suite_dir.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")) or d.name == "__pycache__":
            continue
        if alg is not None:
            n = exp_number(d.name)
            if n is None or n not in alg:
                continue
        out.append(d)
    return out


def baseline_l0(exp_dir: Path) -> float | None:
    """Codebase baseline LOC (L0), identical across models; median for safety."""
    csv = signals_csv_path(exp_dir)
    if csv.is_file():
        try:
            df = pd.read_csv(csv)
            if "L0" in df:
                vals = pd.to_numeric(df["L0"], errors="coerce")
                if "L0_ok" in df:
                    vals = vals[df["L0_ok"].astype(bool)]
                vals = vals.dropna()
                vals = vals[vals > 0]
                if len(vals):
                    return float(np.median(vals))
        except Exception:
            pass
    for jp in sorted(signals_dir(exp_dir).glob("*-signals.json")):
        try:
            d = json.loads(jp.read_text())
            if d.get("L0_ok") and float(d.get("L0", 0)) > 0:
                return float(d["L0"])
        except Exception:
            continue
    return None


def experiment_set(coverage) -> set:
    s: set = set()
    for v in coverage.values():
        s |= v
    return s


# --------------------------------------------------------------------------- #
# 1. LINES
# --------------------------------------------------------------------------- #
def collect_lines(exp_dirs):
    series: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    coverage: dict[str, set[str]] = defaultdict(set)
    no_l0: list[str] = []
    for exp in exp_dirs:
        l0 = baseline_l0(exp)
        if not l0:
            no_l0.append(exp.name)
            continue
        for csv_path in iter_log_csvs(exp):
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue
            if df.empty or "run" not in df or "lines_total" not in df:
                continue
            model = str(df["model"].iloc[0]) if "model" in df else csv_path.stem
            lt = pd.to_numeric(df["lines_total"], errors="coerce").fillna(0.0)
            for run, val in zip(df["run"].astype(int), lt):
                series[model][int(run)].append(float(val) / l0)
            coverage[model].add(exp.name)
    return series, coverage, no_l0


def plot_lines_agg(series, coverage, suite, out_dir, band):
    models = sorted(series)
    if not models:
        return None
    styles = resolve_styles(models)
    max_run = max((r for m in series for r in series[m]), default=10)
    fig, ax = plt.subplots(figsize=(max(7.0, 1.0 * max_run), 4.0))
    for model in models:
        runs = sorted(series[model])
        xs, mean, lo, hi = [], [], [], []
        for r in runs:
            arr = np.array(series[model][r], dtype=float)
            if not len(arr):
                continue
            m = float(arr.mean())
            sem = float(arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else 0.0
            xs.append(r); mean.append(m); lo.append(m - sem); hi.append(m + sem)
        color, marker, label = styles[model]
        ax.plot(xs, mean, marker=marker, markersize=5, linewidth=1.5,
                color=color, label=f"{label} (n={len(coverage[model])})")
        if band == "sem":
            ax.fill_between(xs, lo, hi, color=color, alpha=0.15, linewidth=0)
    ax.set_xlabel("Refactoring Iteration (run)")
    ax.set_ylabel("Mean lines changed ÷ baseline L0")
    ax.set_title(f"Aggregate normalized line churn — {suite} "
                 f"({len(experiment_set(coverage))} codebases)")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.legend(fontsize=8, title="Model (codebases averaged)", title_fontsize=8,
              loc="upper right", framealpha=0.9)
    fig.tight_layout()
    out = out_dir / f"{suite}_agg_lines.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# 2. SIGNALS
# --------------------------------------------------------------------------- #
def collect_signals(exp_dirs):
    cont: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    coverage: dict[str, set[str]] = defaultdict(set)
    for exp in exp_dirs:
        for jp in sorted(signals_dir(exp).glob("*-signals.json")):
            try:
                d = json.loads(jp.read_text())
            except Exception:
                continue
            model = str(d.get("model") or "")
            sig = d.get("signals") or {}
            if not model or not sig:
                continue
            coverage[model].add(exp.name)
            for sid in SIGNAL_IDS:
                cont[model][sid].append(float(sig.get(sid, {}).get("cont", 0.0)))
    return cont, coverage


def plot_signals_agg(cont, coverage, suite, out_dir):
    models = sorted(cont)
    if not models:
        return None
    labels = [LABELS.get(m, m) for m in models]
    styles = resolve_styles(models)
    x = np.arange(len(models))
    fig = plt.figure(figsize=(max(11.0, 1.7 * len(models) + 6.0), 7.0))
    grid = fig.add_gridspec(2, 3, hspace=0.6, wspace=0.28)
    for idx, sid in enumerate(SIGNAL_IDS):
        ax = fig.add_subplot(grid[idx // 3, idx % 3])
        means, sems = [], []
        for m in models:
            arr = np.array(cont[m][sid], dtype=float)
            means.append(float(arr.mean()) if len(arr) else 0.0)
            sems.append(float(arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else 0.0)
        ax.bar(x, means, yerr=sems, color=[styles[m][0] for m in models],
               edgecolor="white", linewidth=0.6, capsize=3)
        ax.set_title(SIGNAL_TITLES[sid], fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=7)
        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        # headroom must clear the error-bar tops (mean + sem), not just the bars
        top = max([m + s for m, s in zip(means, sems)] + [0.0])
        ax.set_ylim(0, top * 1.15 if top > 0 else 1.0)
    fig.suptitle(f"Aggregate sycophancy signals (mean ± SEM) — {suite} "
                 f"({len(experiment_set(coverage))} codebases)", fontsize=13)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.9, bottom=0.1)
    out = out_dir / f"{suite}_agg_signals.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# 3. REFDIFF
# --------------------------------------------------------------------------- #
def collect_refdiff(exp_dirs):
    """Build one aggregated BatchSummary per model (mean count per codebase),
    so it can be rendered with the SAME stacked format as plot_refdiff.py."""
    from collections import Counter

    raw: dict[str, dict[str, Counter]] = defaultdict(
        lambda: {c: Counter() for c in CATEGORIES})
    coverage: dict[str, set[str]] = defaultdict(set)
    for exp in exp_dirs:
        for jp in refdiff_jsonl_files(exp):
            try:
                summ = summarize_jsonl(jp)
            except Exception:
                continue
            model = summ.model
            if not model:
                continue
            coverage[model].add(exp.name)
            for c in CATEGORIES:
                for rel_type, cnt in summ.counts[c].items():
                    raw[model][c][rel_type] += cnt

    summaries: list[BatchSummary] = []
    for model in sorted(raw):
        n = max(len(coverage[model]), 1)
        mean_counts = {c: Counter() for c in CATEGORIES}
        for c in CATEGORIES:
            for rel_type, total in raw[model][c].items():
                mean_counts[c][rel_type] = round(total / n, 1)
        summaries.append(BatchSummary(
            jsonl_path=Path(model), model=model, stamp="",
            counts=mean_counts, records_total=n, records_skipped=0))
    return summaries, coverage


def _render_widget_mean(ax, summary, series, colors):
    """Per-model legend widget, same layout as plot_refdiff but with mean values
    formatted cleanly (1 decimal). Vertical spacing is computed from the number
    of lines so entries always fit the panel height without overlapping."""
    ax.axis("off")

    # Plan every line first so we can size the step to the available height.
    lines = []  # ("header"|"item"|"none", payload)
    for ci, category in enumerate(CATEGORIES):
        cc = summary.counts[category]
        total = sum(cc.values())
        present = [(rt, cc.get(rt, 0)) for rt in series if cc.get(rt, 0) > 0]
        if ci > 0:
            lines.append(("gap", None))  # blank spacer before each new category
        lines.append(("header", f"{category} ({total:.1f})"))
        if present:
            lines.extend(("item", (rt, c, total)) for rt, c in present)
        else:
            lines.append(("none", None))

    n = max(len(lines), 1)
    top, bottom = 0.99, 0.01
    step = (top - bottom) / n
    font = 8 if n <= 16 else 7 if n <= 22 else 6

    y = top
    for kind, payload in lines:
        if kind == "gap":
            y -= step
            continue
        if kind == "header":
            ax.text(0.0, y, payload, transform=ax.transAxes, ha="left",
                    va="top", fontsize=font, fontweight="bold")
        elif kind == "none":
            ax.text(0.16, y, "None", transform=ax.transAxes, ha="left",
                    va="top", fontsize=font, color="0.35")
        else:
            rt, count, total = payload
            ax.add_patch(patches.Rectangle(
                (0.0, y - step * 0.78), 0.08, step * 0.62,
                transform=ax.transAxes, color=colors[rt], clip_on=False))
            ax.text(0.11, y, f"{rt}: {count:.1f} ({count / total:.0%})",
                    transform=ax.transAxes, ha="left", va="top", fontsize=font)
        y -= step


def plot_refdiff_agg(summaries, coverage, suite, out_dir):
    """Same layout as plot_refdiff.plot_experiment: models displayed SIDE BY SIDE
    in a single row, each a stacked-bar subplot (categories on x, stacked by
    relationship type) + summary widget. Aggregate values are mean per codebase,
    formatted cleanly in the widgets."""
    if not summaries:
        return None
    n_plots = len(summaries)
    fig = plt.figure(figsize=(max(12.0, 6.8 * n_plots), 8.8))
    outer = gridspec.GridSpec(1, n_plots, figure=fig, wspace=0.22)
    series = series_order(summaries)
    colors = colors_for(series)

    for i, summary in enumerate(summaries):
        inner = outer[i].subgridspec(1, 2, width_ratios=[3.9, 1.55], wspace=0.03)
        ax = fig.add_subplot(inner[0])
        widget_ax = fig.add_subplot(inner[1])
        bottoms = [0.0] * len(CATEGORIES)
        totals = [sum(summary.counts[c].values()) for c in CATEGORIES]

        for rel_type in series:
            values = [summary.counts[c].get(rel_type, 0) for c in CATEGORIES]
            if not any(values):
                continue
            ax.bar(CATEGORIES, values, bottom=bottoms, color=colors[rel_type],
                   edgecolor="white", linewidth=0.5, label=rel_type)
            bottoms = [b + v for b, v in zip(bottoms, values)]

        n_cb = len(coverage.get(summary.model, []))
        ax.set_title(f"{subplot_title(summary)} (n={n_cb})", fontsize=11)
        ax.set_ylabel("Mean frequency per codebase")
        ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        ax.tick_params(axis="x", rotation=20)
        ax.set_ylim(0, max(totals + [1.0]) * 1.08)
        ax.margins(x=0.18)
        _render_widget_mean(widget_ax, summary, series, colors)

    fig.suptitle(f"RefDiff relationship distribution (aggregate mean per codebase): "
                 f"{suite} ({len(experiment_set(coverage))} codebases)", fontsize=13)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.88, bottom=0.12)
    out = out_dir / f"{suite}_agg_refdiff.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
def write_csv(suite, out_dir, cont, scov, refdiff_summaries, rcov):
    rd_by_model = {s.model: s for s in refdiff_summaries}
    models = sorted(set(list(cont) + list(rd_by_model)))
    rows = []
    for m in models:
        row = {"suite": suite, "model": m,
               "n_codebases_signals": len(scov.get(m, [])),
               "n_codebases_refdiff": len(rcov.get(m, []))}
        for sid in SIGNAL_IDS:
            arr = cont.get(m, {}).get(sid, [])
            row[f"{sid}_cont_mean"] = round(float(np.mean(arr)), 4) if arr else ""
        summ = rd_by_model.get(m)
        if summ is not None:
            for c in CATEGORIES:
                row[f"refdiff_{c.replace(' ', '_')}_mean"] = round(
                    float(sum(summ.counts[c].values())), 4)
                for rel_type, val in summ.counts[c].items():
                    row[f"reltype[{c}:{rel_type}]_mean"] = round(float(val), 4)
        rows.append(row)
    out = out_dir / f"{suite}_aggregate.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--suite", required=True, choices=["Algorithms", "RealWorld"],
                   help="Which codebase suite to aggregate over.")
    p.add_argument("--alg", default=None,
                   help="Restrict participating codebases by leading number, e.g. "
                        "'001-020', '005', '001-010,015'. Default: everything.")
    p.add_argument("--output-base", type=Path, default=_SCRIPT_DIR / "output",
                   help="Dir containing the suite folders (default: <repo>/output).")
    p.add_argument("--band", choices=["sem", "none"], default="sem",
                   help="Uncertainty band on the line chart (default: sem).")
    args = p.parse_args(argv)

    try:
        alg = parse_alg_filter(args.alg)
    except ValueError:
        print(f"Bad --alg value: {args.alg!r}", file=sys.stderr)
        return 2

    suite_dir = (args.output_base / args.suite).resolve()
    exp_dirs = experiment_dirs(suite_dir, alg)
    if not exp_dirs:
        scope = f" matching --alg {args.alg}" if alg else ""
        print(f"No codebases found under {suite_dir}{scope}", file=sys.stderr)
        return 2

    out_dir = suite_dir / "_aggregate"
    out_dir.mkdir(parents=True, exist_ok=True)

    scope = f"  alg-filter={args.alg}" if alg else "  (all)"
    print(f"[aggregate] suite={args.suite}  codebases={len(exp_dirs)}{scope}")

    lseries, lcov, no_l0 = collect_lines(exp_dirs)
    if no_l0:
        print(f"[lines] {len(no_l0)} codebases skipped (no usable L0): "
              f"{', '.join(sorted(no_l0)[:6])}{'…' if len(no_l0) > 6 else ''}")
    cont, scov = collect_signals(exp_dirs)
    refdiff_summaries, rcov = collect_refdiff(exp_dirs)

    outs = [
        plot_lines_agg(lseries, lcov, args.suite, out_dir, args.band),
        plot_signals_agg(cont, scov, args.suite, out_dir),
        plot_refdiff_agg(refdiff_summaries, rcov, args.suite, out_dir),
    ]
    csv_out = write_csv(args.suite, out_dir, cont, scov, refdiff_summaries, rcov)

    print("\nWrote:")
    for o in outs + [csv_out]:
        if o:
            print(f"  {o}")

    print("\nPer-model codebase coverage:")
    for m in sorted(set(list(lcov) + list(scov) + list(rcov))):
        print(f"  {m:20} lines={len(lcov.get(m, [])):3}  "
              f"signals={len(scov.get(m, [])):3}  refdiff={len(rcov.get(m, [])):3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
