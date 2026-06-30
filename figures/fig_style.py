"""Shared, ICSE-ready figure styling and data loading for the paper figures.

Everything here lives under ``figures/`` and only *reads* result data from the
repository's ``output/`` folder. Metric computation is **reused** from the
existing project modules (``plot_aggregate.py``, ``plot_refdiff.py``,
``style_config.py``) rather than re-implemented, so the figures stay consistent
with the rest of the pipeline.

Scope (fixed for the paper):
  * Algorithms suite: codebases ``001``..``050``
  * RealWorld suite : codebases ``R001``..``R010``
  * Models          : Claude Opus 4.8, Claude Sonnet 4.6, GPT-5.5,
                      GPT-5.4-mini, GPT-5.4  (all others excluded)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------- #
# Make the repository root importable and route matplotlib caches to a temp dir
# (mirrors plot_aggregate.py so we never touch the user's project tree).
# --------------------------------------------------------------------------- #
FIG_DIR = Path(__file__).resolve().parent
REPO_ROOT = FIG_DIR.parent
OUTPUT_ROOT = REPO_ROOT / "output"
FIG_OUT_DIR = FIG_DIR / "output"
FIG_OUT_DIR.mkdir(parents=True, exist_ok=True)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_CACHE_ROOT = Path(tempfile.gettempdir()) / "sycophancy-figures-cache"
for _sub in ("matplotlib", "xdg"):
    (_CACHE_ROOT / _sub).mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_ROOT / "xdg"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# Reused project utilities (metric definitions live here — do not duplicate). #
from style_config import COLORS, LABELS, MARKERS  # noqa: E402
from plot_aggregate import (  # noqa: E402
    collect_refdiff,
    collect_signals,
    experiment_dirs,
    parse_alg_filter,
)
from plot_refdiff import CATEGORIES, NO_RELATIONSHIP_TYPES  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixed analysis scope
# --------------------------------------------------------------------------- #
MODEL_ORDER = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "gpt-5.5",
    "gpt-5.4-mini",
    "gpt-5.4",
]

# Short, two-line tick labels keep the model axis legible at paper size.
MODEL_TICK = {
    "claude-opus-4-8": "Claude\nOpus 4.8",
    "claude-sonnet-4-6": "Claude\nSonnet 4.6",
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4-mini": "GPT-5.4\nmini",
    "gpt-5.4": "GPT-5.4",
}

SUITES = {
    "Algorithms": "001-050",
    "RealWorld": "R001-R010",
}
SUITE_LABEL = {
    "Algorithms": "Algorithms (001–050)",
    "RealWorld": "RealWorld (R001–R010)",
}
# Repository-type styling for the side-by-side Algorithms-vs-RealWorld comparison.
SUITE_HATCH = {"Algorithms": "", "RealWorld": "////"}
SUITE_ALPHA = {"Algorithms": 1.0, "RealWorld": 0.55}
NUM_TURNS = 10  # max refactoring iterations per run

# --------------------------------------------------------------------------- #
# Publication style (serif, vector-friendly, restrained chrome)
# --------------------------------------------------------------------------- #
def apply_rc() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["DejaVu Serif", "Times New Roman", "Nimbus Roman"],
            "mathtext.fontset": "dejavuserif",
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "legend.frameon": False,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "pdf.fonttype": 42,  # embed TrueType so the PDF is editable
            "ps.fonttype": 42,
        }
    )


def model_color(model: str) -> str:
    return COLORS.get(model, "#555555")


def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def lighten(color: str, amount: float = 0.55):
    """Blend ``color`` toward white by ``amount`` (0 = unchanged, 1 = white)."""
    r, g, b = _hex_to_rgb(color)
    return tuple(c + (1.0 - c) * amount for c in (r, g, b))


def grid(ax, axis: str = "y") -> None:
    ax.grid(axis=axis, linestyle="--", linewidth=0.5, alpha=0.45, zorder=0)
    ax.set_axisbelow(True)


def savefig(fig, name: str) -> list[Path]:
    """Write both a PNG (raster preview) and a PDF (vector, for LaTeX)."""
    outs = []
    for ext in ("png", "pdf"):
        out = FIG_OUT_DIR / f"{name}.{ext}"
        fig.savefig(out)
        outs.append(out)
    plt.close(fig)
    return outs


# --------------------------------------------------------------------------- #
# Data loading — reuse collect_signals / collect_refdiff for the exact metrics
# used everywhere else in the project, then restrict to the fixed model scope.
# --------------------------------------------------------------------------- #
class SuiteData:
    """Per-suite, per-model views, restricted to MODEL_ORDER and the id scope."""

    def __init__(self, suite: str):
        self.suite = suite
        suite_dir = OUTPUT_ROOT / suite
        alg = parse_alg_filter(SUITES[suite])
        exp_dirs = experiment_dirs(suite_dir, alg)
        if not exp_dirs:
            raise SystemExit(f"No codebases found for {suite} ({SUITES[suite]}).")
        self.exp_dirs = exp_dirs
        self.n_codebases = len(exp_dirs)

        cont, _scov, s0_never = collect_signals(exp_dirs)
        self.signals = {m: cont[m] for m in MODEL_ORDER if m in cont}
        self.s0_never = {m: list(s0_never.get(m, [])) for m in self.signals}

        summaries, _rcov = collect_refdiff(exp_dirs)
        self.refdiff = {
            s.model: s.counts for s in summaries if s.model in MODEL_ORDER
        }

    # -- per-run signal arrays ------------------------------------------------
    def sig(self, model: str, sid: str) -> np.ndarray:
        return np.asarray(self.signals.get(model, {}).get(sid, []), dtype=float)

    def sig_mean(self, model: str, sid: str) -> float:
        a = self.sig(model, sid)
        return float(a.mean()) if a.size else 0.0

    def sig_sem(self, model: str, sid: str) -> float:
        a = self.sig(model, sid)
        return float(a.std(ddof=1) / np.sqrt(a.size)) if a.size > 1 else 0.0

    def never_stopped(self, model: str) -> np.ndarray:
        return np.asarray(self.s0_never.get(model, []), dtype=bool)

    # -- refdiff helpers ------------------------------------------------------
    def rd(self, model: str, category: str, rel_type: str) -> float:
        return float(self.refdiff.get(model, {}).get(category, {}).get(rel_type, 0.0))

    def rd_same(self, model: str) -> float:
        return self.rd(model, "Matching", "SAME")

    def rd_other_refactor(self, model: str) -> float:
        """All catalogued refactorings except SAME (Matching\\SAME + Non-Matching)."""
        c = self.refdiff.get(model, {})
        matching = sum(
            v for k, v in c.get("Matching", {}).items() if k != "SAME"
        )
        non_matching = sum(c.get("Non-Matching", {}).values())
        return float(matching + non_matching)

    def rd_node_added(self, model: str) -> float:
        return self.rd(model, "No Relationship", "Node Added")

    def rd_node_deleted(self, model: str) -> float:
        return self.rd(model, "No Relationship", "Node Deleted")

    def rd_extract(self, model: str) -> float:
        c = self.refdiff.get(model, {}).get("Non-Matching", {})
        return float(sum(c.get(k, 0.0) for k in ("EXTRACT", "EXTRACT_MOVE", "EXTRACT_SUPER")))

    def rd_inline(self, model: str) -> float:
        return float(self.refdiff.get(model, {}).get("Non-Matching", {}).get("INLINE", 0.0))


def load_all() -> dict[str, SuiteData]:
    return {suite: SuiteData(suite) for suite in SUITES}


# --------------------------------------------------------------------------- #
# Reusable plotting primitive: Algorithms-vs-RealWorld adjacent grouped bars.
# x = models, two bars per model (solid = Algorithms, hatched = RealWorld).
# --------------------------------------------------------------------------- #
def grouped_suite_bars(
    ax,
    data: dict[str, SuiteData],
    value_fn,
    *,
    err_fn=None,
    models=MODEL_ORDER,
    log=False,
    annotate=False,
    annotate_fmt="{:.2f}",
):
    """Draw side-by-side Algorithms/RealWorld bars per model on ``ax``.

    ``value_fn(suite_data, model) -> float`` supplies the bar height;
    ``err_fn`` (optional) supplies a symmetric error bar.
    """
    suites = list(data)
    x = np.arange(len(models))
    bw = 0.38
    offsets = {suites[0]: -bw / 2, suites[1]: +bw / 2}
    for suite in suites:
        sd = data[suite]
        vals = [value_fn(sd, m) for m in models]
        errs = [err_fn(sd, m) for m in models] if err_fn else None
        colors = [model_color(m) for m in models]
        bars = ax.bar(
            x + offsets[suite],
            vals,
            bw,
            yerr=errs,
            color=colors,
            alpha=SUITE_ALPHA[suite],
            hatch=SUITE_HATCH[suite],
            edgecolor="white" if suite == "Algorithms" else "0.25",
            linewidth=0.6,
            error_kw=dict(elinewidth=0.8, capsize=2, ecolor="0.3"),
            zorder=3,
        )
        if annotate:
            for i, (b, v) in enumerate(zip(bars, vals)):
                top = v + (errs[i] if errs else 0.0)
                ax.annotate(
                    annotate_fmt.format(v),
                    (b.get_x() + b.get_width() / 2, top),
                    textcoords="offset points",
                    xytext=(0, 3),
                    ha="center",
                    va="bottom",
                    fontsize=6.5,
                    color="0.2",
                )
    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_TICK.get(m, m) for m in models])
    if log:
        ax.set_yscale("log")
    grid(ax)
    return x


def suite_type_legend(fig, **kw):
    """A single, color-neutral legend explaining the solid/hatched encoding."""
    import matplotlib.patches as mpatches

    handles = [
        mpatches.Patch(
            facecolor="0.45", edgecolor="white",
            alpha=SUITE_ALPHA["Algorithms"], label=SUITE_LABEL["Algorithms"],
        ),
        mpatches.Patch(
            facecolor="0.45", edgecolor="0.25", hatch=SUITE_HATCH["RealWorld"],
            alpha=SUITE_ALPHA["RealWorld"], label=SUITE_LABEL["RealWorld"],
        ),
    ]
    defaults = dict(loc="upper right", ncol=2, frameon=False, handlelength=1.6)
    defaults.update(kw)
    fig.legend(handles=handles, **defaults)
