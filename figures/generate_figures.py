#!/usr/bin/env python3
"""Generate the paper's "best visualization" figures.

Implements the **Best visualization** TODO items from ``figures/outline.md`` for
the four Results sections, restricted to:
  * Algorithms 001–050   and   RealWorld R001–R010
  * Models: Claude Opus 4.8, Claude Sonnet 4.6, GPT-5.5, GPT-5.4-mini, GPT-5.4

All inputs come from the repository ``output/`` folder; all metric definitions
are reused from the existing pipeline modules (see ``fig_style.py``). Every
figure places the two repository types side by side for direct comparison.

Run (from anywhere):
    python figures/generate_figures.py

Outputs land in ``figures/output/`` as paired PNG (preview) + PDF (LaTeX).
"""

from __future__ import annotations

import numpy as np

from fig_style import (
    FIG_OUT_DIR,
    MODEL_ORDER,
    MODEL_TICK,
    NUM_TURNS,
    SUITE_LABEL,
    apply_rc,
    grid,
    grouped_suite_bars,
    load_all,
    model_color,
    plt,
    savefig,
    suite_type_legend,
)

SUITES = ("Algorithms", "RealWorld")


# =========================================================================== #
# Section 1 — t* distribution (how late agents stop editing)
# =========================================================================== #
def fig1_stop_turn_strip(data):
    """Primary: horizontal violin of per-run t* (first stop turn), one row per
    model, Algorithms | RealWorld side by side. Never-stopped runs are counted
    as t*=10. The per-model mean (◆) is drawn separately on each violin."""
    fig, axes = plt.subplots(
        1, 2, figsize=(8.6, 3.3), sharey=True, gridspec_kw=dict(wspace=0.06)
    )
    y_of = {m: len(MODEL_ORDER) - 1 - i for i, m in enumerate(MODEL_ORDER)}

    for ax, suite in zip(axes, SUITES):
        sd = data[suite]
        ax.axvline(1, color="0.6", lw=0.9, ls=":", zorder=1)  # ideal: stop at turn 1
        for m in MODEL_ORDER:
            y = y_of[m]
            # t*; runs that never stop are capped at NUM_TURNS (treated like turn 10)
            stops = sd.sig(m, "S0")
            if stops.size == 0:
                continue
            col = model_color(m)
            if stops.size > 1 and np.ptp(stops) > 0:
                vp = ax.violinplot(
                    [stops], positions=[y], orientation='horizontal', widths=0.82,
                    showextrema=False, showmeans=False, showmedians=False,
                )
                for body in vp["bodies"]:
                    body.set_facecolor(col)
                    body.set_edgecolor(col)
                    body.set_alpha(0.45)
                    body.set_linewidth(0.8)
                    body.set_zorder(3)
            else:
                # degenerate (all runs share one t*, e.g. GPT-5.4 always =10):
                # mark the pile with a short bar so the row isn't empty.
                ax.plot([stops[0], stops[0]], [y - 0.32, y + 0.32], color=col,
                        lw=3.0, alpha=0.45, solid_capstyle="round", zorder=3)
            ax.scatter(  # mean over ALL runs, drawn separately from the violin
                float(stops.mean()), y, marker="D", s=42, color="white",
                edgecolor="black", linewidth=1.0, zorder=6,
            )
        ax.set_title(SUITE_LABEL[suite], fontsize=9.5)
        ax.set_xlim(0.3, NUM_TURNS + 0.7)
        ax.set_xticks(list(range(1, NUM_TURNS + 1)))
        ax.set_xticklabels([str(k) for k in range(1, NUM_TURNS + 1)])
        ax.set_xlabel(r"First stop turn $t^{*}$")
        grid(ax, axis="x")

    axes[0].set_yticks(list(y_of.values()))
    axes[0].set_yticklabels([MODEL_TICK[m].replace("\n", " ") for m in MODEL_ORDER])
    axes[0].set_ylim(-0.6, len(MODEL_ORDER) - 0.4)
    fig.tight_layout()
    return savefig(fig, "fig1_stop_turn_strip")


def fig1_stop_turn_dots(data):
    """Previous version, kept for comparison: per-run t* as a jittered strip of
    dots, one row per model, with the per-model mean (◆) marked. Same data and
    scope as the violin version (`fig1_stop_turn_strip`)."""
    rng = np.random.default_rng(7)
    fig, axes = plt.subplots(
        1, 2, figsize=(8.6, 3.3), sharey=True, gridspec_kw=dict(wspace=0.06)
    )
    y_of = {m: len(MODEL_ORDER) - 1 - i for i, m in enumerate(MODEL_ORDER)}

    for ax, suite in zip(axes, SUITES):
        sd = data[suite]
        ax.axvline(1, color="0.6", lw=0.9, ls=":", zorder=1)  # ideal: stop at turn 1
        for m in MODEL_ORDER:
            y = y_of[m]
            stops = sd.sig(m, "S0")  # never-stopped runs counted as t*=10
            if stops.size == 0:
                continue
            jit = (rng.random(stops.size) - 0.5) * 0.5
            col = model_color(m)
            ax.scatter(
                stops, np.full(stops.size, y) + jit, s=22, color=col,
                alpha=0.55, edgecolor="white", linewidth=0.3, zorder=3,
            )
            ax.scatter(  # mean over ALL runs
                float(stops.mean()), y, marker="D", s=46, color=col,
                edgecolor="black", linewidth=0.8, zorder=5,
            )
        ax.set_title(SUITE_LABEL[suite], fontsize=9.5)
        ax.set_xlim(0.3, NUM_TURNS + 0.7)
        ax.set_xticks(list(range(1, NUM_TURNS + 1)))
        ax.set_xticklabels([str(k) for k in range(1, NUM_TURNS + 1)])
        ax.set_xlabel(r"First stop turn $t^{*}$")
        grid(ax, axis="x")

    axes[0].set_yticks(list(y_of.values()))
    axes[0].set_yticklabels([MODEL_TICK[m].replace("\n", " ") for m in MODEL_ORDER])
    axes[0].set_ylim(-0.6, len(MODEL_ORDER) - 0.4)
    fig.tight_layout()
    return savefig(fig, "fig1_stop_turn_dots")


# =========================================================================== #
# Section 2 — S1: pre-stop churn (lines changed before stopping, ÷ L0)
# =========================================================================== #
def fig2_churn_S1(data):
    """Primary: grouped bar of mean S1 per model, Algorithms vs RealWorld
    adjacent, log y so the toy-codebase multiples and the sub-1× real-world
    values are both legible. Per-run points overlaid to expose the variance
    that defeats the 'similar line volume' claim."""
    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    grouped_suite_bars(
        ax, data, lambda sd, m: sd.sig_mean(m, "S1"),
        err_fn=lambda sd, m: sd.sig_sem(m, "S1"), log=True,
        annotate=True, annotate_fmt="{:.1f}",
    )
    ax.axhline(1.0, color="0.5", lw=0.9, ls=":", zorder=2)
    ax.set_ylabel(r"Pre-stop churn $S_1$")
    suite_type_legend(fig, loc="lower center", bbox_to_anchor=(0.5, -0.01), ncol=2)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.95, bottom=0.22)
    return savefig(fig, "fig2_churn_S1")


# =========================================================================== #
# Section 3 — over-compliance: stop-then-resume (S2) & verbal-refusal edits (S7)
# =========================================================================== #
def fig3_postsop_S2_S7(data):
    """Primary (over-compliance): S2 (post-stop modification ÷ L0) and S7
    (edit rate after a verbal refusal) per model, Algorithms vs RealWorld
    adjacent in each panel."""
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.5))
    grouped_suite_bars(
        axes[0], data, lambda sd, m: sd.sig_mean(m, "S2"),
        err_fn=lambda sd, m: sd.sig_sem(m, "S2"), log=True,
        annotate=True, annotate_fmt="{:.2f}",
    )
    axes[0].set_ylim(1e-2, 30)  # zero-valued bars (GPT-5.4: never stops) fall off-scale
    axes[0].set_ylabel(r"Post-stop edits $S_2$ (log)")

    grouped_suite_bars(
        axes[1], data, lambda sd, m: sd.sig_mean(m, "S7"),
        err_fn=lambda sd, m: sd.sig_sem(m, "S7"),
        annotate=True, annotate_fmt="{:.2f}",
    )
    axes[1].set_ylabel(r"Refusal edits $S_3$")

    suite_type_legend(fig, loc="lower center", bbox_to_anchor=(0.5, -0.01), ncol=2)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.95, bottom=0.24, wspace=0.28)
    return savefig(fig, "fig3_postsop_S2_S7")


# =========================================================================== #
# Combined S1 + S2 + S7 — churn and over-compliance in one row
# =========================================================================== #
def fig_combined_S1_S2_S7(data):
    """S1 (pre-stop churn), S2 (post-stop edits), and S7 (refusal edits) in one
    three-panel row — S1 on the left, S2 and S7 on the right, with the same
    font sizes, bar style, and annotations as fig2_churn_S1 / fig3_postsop_S2_S7."""
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.5), gridspec_kw=dict(wspace=0.32))

    grouped_suite_bars(
        axes[0], data, lambda sd, m: sd.sig_mean(m, "S1"),
        err_fn=lambda sd, m: sd.sig_sem(m, "S1"), log=True,
        annotate=True, annotate_fmt="{:.1f}",
    )
    axes[0].axhline(1.0, color="0.5", lw=0.9, ls=":", zorder=2)
    axes[0].set_ylabel(r"Pre-stop churn $S_1$")

    grouped_suite_bars(
        axes[1], data, lambda sd, m: sd.sig_mean(m, "S2"),
        err_fn=lambda sd, m: sd.sig_sem(m, "S2"), log=True,
        annotate=True, annotate_fmt="{:.2f}",
    )
    axes[1].set_ylim(1e-2, 30)
    axes[1].set_ylabel(r"Post-stop edits $S_2$ (log)")

    grouped_suite_bars(
        axes[2], data, lambda sd, m: sd.sig_mean(m, "S7"),
        err_fn=lambda sd, m: sd.sig_sem(m, "S7"),
        annotate=True, annotate_fmt="{:.2f}",
    )
    axes[2].set_ylabel(r"Refusal edits $S_3$")

    suite_type_legend(fig, loc="lower center", bbox_to_anchor=(0.5, -0.01), ncol=2)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.22)
    return savefig(fig, "fig_combined_S1_S2_S7")


# =========================================================================== #
# Section 4 — RefDiff: what the refactors actually are
# =========================================================================== #
_COMP_PARTS = [
    ("SAME (edited)", "rd_same", "#9ecae1"),
    ("Other refactoring", "rd_other_refactor", "#3182bd"),
    ("Node Added", "rd_node_added", "#e6550d"),
    ("Node Deleted", "rd_node_deleted", "#fdae6b"),
]


def fig4a_refdiff_composition(data):
    """Primary (composition): 100%-stacked bar per model of the RefDiff outcome
    mix, Algorithms | RealWorld side by side. One glance: it is mostly SAME +
    new nodes, not catalogued refactoring."""
    fig, axes = plt.subplots(
        1, 2, figsize=(8.8, 3.8), sharey=True, gridspec_kw=dict(wspace=0.06)
    )
    x = np.arange(len(MODEL_ORDER))
    for ax, suite in zip(axes, SUITES):
        sd = data[suite]
        parts = np.array(
            [[getattr(sd, fn)(m) for _, fn, _ in _COMP_PARTS] for m in MODEL_ORDER],
            dtype=float,
        )
        totals = parts.sum(axis=1)
        totals[totals == 0] = 1.0
        frac = parts / totals[:, None] * 100.0
        bottom = np.zeros(len(MODEL_ORDER))
        for j, (label, _fn, color) in enumerate(_COMP_PARTS):
            ax.bar(x, frac[:, j], 0.62, bottom=bottom, color=color,
                   edgecolor="white", linewidth=0.5, label=label, zorder=3)
            for xi, (v, bot) in enumerate(zip(frac[:, j], bottom)):
                if v >= 6.0:
                    ax.text(xi, bot + v / 2, f"{v:.0f}%",
                            ha="center", va="center", fontsize=8,
                            color="white", fontweight="bold", zorder=4)
            bottom += frac[:, j]
        ax.set_title(SUITE_LABEL[suite], fontsize=9.5)
        ax.set_xticks(x)
        ax.set_xticklabels([MODEL_TICK[m] for m in MODEL_ORDER])
        ax.set_ylim(0, 100)
        grid(ax)
    axes[0].set_ylabel("Share of RefDiff outcomes (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.01),
               ncol=4, fontsize=8, columnspacing=1.4, handlelength=1.4)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.96, bottom=0.22, wspace=0.06)
    return savefig(fig, "fig4a_refdiff_composition")


def fig4b_inflation_diverging(data):
    """Primary (inflation): diverging bars — Node Added (right) vs Node Deleted
    (left) per model, Algorithms | RealWorld side by side. One-directional
    growth is immediate."""
    fig, axes = plt.subplots(
        1, 2, figsize=(9.0, 3.8), sharey=True, gridspec_kw=dict(wspace=0.16)
    )
    y = np.arange(len(MODEL_ORDER))[::-1]
    for ax, suite in zip(axes, SUITES):
        sd = data[suite]
        added = [sd.rd_node_added(m) for m in MODEL_ORDER]
        deleted = [sd.rd_node_deleted(m) for m in MODEL_ORDER]
        maxabs = max(added + deleted + [1.0])
        for yi, m, a, d in zip(y, MODEL_ORDER, added, deleted):
            col = model_color(m)
            ax.barh(yi, a, color=col, edgecolor="white", linewidth=0.5, zorder=3)
            ax.barh(yi, -d, color=col, alpha=0.35, edgecolor="none", zorder=3)
            ax.annotate(f"+{a:.0f}", (a, yi), xytext=(3, 0),
                        textcoords="offset points", va="center", ha="left",
                        fontsize=9, color="0.2", clip_on=False)
            ax.annotate(f"−{d:.0f}", (-d, yi), xytext=(-3, 0),
                        textcoords="offset points", va="center", ha="right",
                        fontsize=9, color="0.2", clip_on=False)
        ax.axvline(0, color="0.3", lw=0.9, zorder=4)
        ax.set_xlim(-maxabs * 1.32, maxabs * 1.22)
        ax.set_title(SUITE_LABEL[suite], fontsize=9.5)
        ax.set_xlabel(r"$\leftarrow$ deleted / added $\rightarrow$")
        grid(ax, axis="x")
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([MODEL_TICK[m].replace("\n", " ") for m in MODEL_ORDER])
    fig.tight_layout()
    return savefig(fig, "fig4b_inflation_diverging")


def fig4c_instability_S4_S5_S6(data):
    """S4, S5 (edit instability) and S6 (repeat-region locality) in one row."""
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.5))

    grouped_suite_bars(axes[0], data, lambda sd, m: sd.sig_mean(m, "S4"),
                       err_fn=lambda sd, m: sd.sig_sem(m, "S4"),
                       annotate=True, annotate_fmt="{:.1f}")
    axes[0].set_ylabel(r"Self-rollback $S_4$")

    grouped_suite_bars(axes[1], data, lambda sd, m: sd.sig_mean(m, "S5"),
                       err_fn=lambda sd, m: sd.sig_sem(m, "S5"),
                       annotate=True, annotate_fmt="{:.1f}")
    axes[1].set_ylabel(r"Self-reinsert $S_5$")

    grouped_suite_bars(
        axes[2], data, lambda sd, m: sd.sig_mean(m, "S6") * 100.0,
        err_fn=lambda sd, m: sd.sig_sem(m, "S6") * 100.0,
        annotate=True, annotate_fmt="{:.0f}%",
    )
    axes[2].set_ylim(0, 31)
    axes[2].set_ylabel(r"Repeat-region edits $S_6$ (%)")

    suite_type_legend(fig, loc="lower center", bbox_to_anchor=(0.5, -0.01), ncol=2)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.22, wspace=0.38)
    return savefig(fig, "fig4c_instability_S4_S5_S6")


def fig4e_extract_vs_inline(data):
    """Extract vs Inline per model on a log scale, Algorithms | RealWorld side by
    side — grow-without-shrink asymmetry reinforces the inflation story."""
    fig, axes = plt.subplots(
        1, 2, figsize=(8.8, 3.5), sharey=True, gridspec_kw=dict(wspace=0.06)
    )
    x = np.arange(len(MODEL_ORDER))
    bw = 0.38
    for ax, suite in zip(axes, SUITES):
        sd = data[suite]
        ex = [sd.rd_extract(m) for m in MODEL_ORDER]
        inl = [sd.rd_inline(m) for m in MODEL_ORDER]
        ax.bar(x - bw / 2, np.maximum(ex, 1e-3), bw, color="#3182bd",
               edgecolor="white", linewidth=0.5, label="Extract (grow)", zorder=3)
        ax.bar(x + bw / 2, np.maximum(inl, 1e-3), bw, color="#fdae6b",
               edgecolor="white", linewidth=0.5, label="Inline (shrink)", zorder=3)
        ax.set_yscale("log")
        for xi, (e, il) in enumerate(zip(ex, inl)):
            ax.annotate(f"{e:.1f}", (xi - bw / 2, max(e, 1e-3)),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9, color="0.15")
            ax.annotate(f"{il:.1f}", (xi + bw / 2, max(il, 1e-3)),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9, color="0.15")
        ax.set_title(SUITE_LABEL[suite], fontsize=9.5)
        ax.set_xticks(x)
        ax.set_xticklabels([MODEL_TICK[m] for m in MODEL_ORDER])
        grid(ax)
    axes[0].set_ylabel("Mean count per codebase (log)")
    axes[0].legend(loc="upper left", fontsize=7.5, framealpha=0.9, frameon=True,
                   edgecolor="0.85")
    fig.tight_layout()
    return savefig(fig, "fig4e_extract_vs_inline")


# =========================================================================== #
# Reproducibility: dump the exact numbers behind every figure
# =========================================================================== #
def dump_figure_data(data):
    import csv

    sids = ["S0", "S1", "S2", "S3", "S4_cont", "S5_cont", "S6", "S7"]
    rd_metrics = {
        "rd_SAME_edited": "rd_same",
        "rd_other_refactoring": "rd_other_refactor",
        "rd_node_added": "rd_node_added",
        "rd_node_deleted": "rd_node_deleted",
        "rd_extract": "rd_extract",
        "rd_inline": "rd_inline",
    }
    out = FIG_OUT_DIR / "figure_data.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        header = ["suite", "model", "n_codebases", "n_never_stopped"]
        header += [f"{s}_mean" for s in sids] + [f"{s}_sem" for s in sids]
        header += list(rd_metrics)
        w.writerow(header)
        for suite in SUITES:
            sd = data[suite]
            for m in MODEL_ORDER:
                row = [suite, m, sd.n_codebases, int(sd.never_stopped(m).sum())]
                row += [round(sd.sig_mean(m, s), 4) for s in sids]
                row += [round(sd.sig_sem(m, s), 4) for s in sids]
                row += [round(getattr(sd, fn)(m), 3) for fn in rd_metrics.values()]
                w.writerow(row)
    return out


def main():
    apply_rc()
    data = load_all()

    builders = [
        fig1_stop_turn_strip,
        fig1_stop_turn_dots,  # previous version, kept for comparison
        fig2_churn_S1,
        fig3_postsop_S2_S7,
        fig_combined_S1_S2_S7,
        fig4a_refdiff_composition,
        fig4b_inflation_diverging,
        fig4c_instability_S4_S5_S6,
        fig4e_extract_vs_inline,
    ]
    print(f"Scope: Algorithms 001-050 (n={data['Algorithms'].n_codebases}), "
          f"RealWorld R001-R010 (n={data['RealWorld'].n_codebases}); "
          f"models={', '.join(MODEL_ORDER)}\n")
    for b in builders:
        outs = b(data)
        print(f"  {b.__name__:32} -> {', '.join(o.name for o in outs)}")
    csv_out = dump_figure_data(data)
    print(f"\n  figure_data                      -> {csv_out.name}")
    print(f"\nAll figures written to {FIG_OUT_DIR}")


if __name__ == "__main__":
    raise SystemExit(main())
