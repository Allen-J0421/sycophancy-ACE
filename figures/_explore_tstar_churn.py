"""Exploratory (not part of the paper build): per-turn pre-stop churn S1/t*.
Produces two figures in figures/output/:
  fig2b_churn_S1_over_tstar.{png,pdf}   - bar chart (S1/t* per model), like fig2
  fig_joint_tstar_churn.{png,pdf}       - 2D (t*, S1/t*) scatter + per-model KDE
"""
import numpy as np
from scipy.stats import gaussian_kde

from fig_style import (load_all, MODEL_ORDER, LABELS, apply_rc, grouped_suite_bars,
                       grid, model_color, plt, savefig, suite_type_legend, MODEL_TICK)

SUITES = ("Algorithms", "RealWorld")
SUITE_TITLE = {"Algorithms": "Algorithm", "RealWorld": "OOP Homeworks"}


def pairs(sd, m):
    """Aligned per-run (t*, S1/t*) with S1>0."""
    s1 = sd.sig(m, "S1"); t = sd.sig(m, "S0")
    n = min(s1.size, t.size)
    s1, t = s1[:n], t[:n]
    mask = (t > 0) & (s1 > 0)
    t, s1 = t[mask], s1[mask]
    return t, s1 / t


# --------------------------------------------------------------- bar: S1/t* ---
def bar_fig(data):
    rng = np.random.default_rng(3)
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    x = grouped_suite_bars(
        ax, data,
        lambda sd, m: float(pairs(sd, m)[1].mean()) if pairs(sd, m)[1].size else 0.0,
        err_fn=lambda sd, m: float(pairs(sd, m)[1].std(ddof=1) / np.sqrt(pairs(sd, m)[1].size))
                              if pairs(sd, m)[1].size > 1 else 0.0,
        log=True)
    bw = 0.38; offs = {"Algorithms": -bw / 2, "RealWorld": +bw / 2}
    for suite in SUITES:
        sd = data[suite]
        for xi, m in zip(x, MODEL_ORDER):
            v = pairs(sd, m)[1]
            if v.size == 0: continue
            jit = (rng.random(v.size) - 0.5) * 0.22
            ax.scatter(np.full(v.size, xi + offs[suite]) + jit, v, s=8,
                       color="0.15", alpha=0.35, linewidth=0, zorder=4)
    ax.axhline(1.0, color="0.5", lw=0.9, ls=":", zorder=2)
    ax.set_ylabel(r"Per-turn pre-stop churn $S_1/t^{*}$ ($\div\,L_0$)")
    suite_type_legend(fig, loc="lower center", bbox_to_anchor=(0.5, -0.01), ncol=2)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.97, bottom=0.20)
    return savefig(fig, "fig2b_churn_S1_over_tstar")


# ------------------------------------------------- joint scatter + 2D KDE -----
def joint_fig(data):
    rng = np.random.default_rng(7)
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.2), sharex=True,
                             gridspec_kw=dict(wspace=0.12))
    for ax, suite in zip(axes, SUITES):
        sd = data[suite]
        ymin, ymax = np.inf, -np.inf
        for m in MODEL_ORDER:
            t, r = pairs(sd, m)
            if r.size:
                ymin = min(ymin, r.min()); ymax = max(ymax, r.max())
        ygrid = np.linspace(np.log10(ymin) - 0.3, np.log10(ymax) + 0.3, 100)
        xgrid = np.linspace(0.4, 10.6, 100)
        XX, YY = np.meshgrid(xgrid, ygrid)
        for m in MODEL_ORDER:
            t, r = pairs(sd, m)
            if r.size == 0: continue
            col = model_color(m)
            jit = (rng.random(t.size) - 0.5) * 0.5
            ax.scatter(t + jit, r, s=14, color=col, alpha=0.55,
                       edgecolor="white", linewidth=0.3, zorder=4,
                       label=LABELS.get(m, m))
            if r.size >= 5 and np.ptp(t) > 0:
                xy = np.vstack([t, np.log10(r)])
                try:
                    kde = gaussian_kde(xy)
                    Z = kde(np.vstack([XX.ravel(), YY.ravel()])).reshape(XX.shape)
                    ax.contour(XX, 10 ** YY, Z, levels=3, colors=[col],
                               linewidths=1.0, alpha=0.8, zorder=3)
                except np.linalg.LinAlgError:
                    pass
        ax.set_yscale("log")
        ax.axhline(1.0, color="0.5", lw=0.8, ls=":", zorder=1)
        ax.set_xlim(0.4, 10.6); ax.set_xticks(range(1, 11))
        ax.set_xlabel(r"First stop turn $t^{*}$")
        ax.set_title(SUITE_TITLE[suite], fontsize=12)
        grid(ax, axis="both")
    axes[0].set_ylabel(r"Per-turn pre-stop churn $S_1/t^{*}$ ($\div\,L_0$)")
    axes[0].legend(loc="upper right", fontsize=9, framealpha=0.9, frameon=True,
                   edgecolor="0.85")
    fig.subplots_adjust(left=0.08, right=0.985, top=0.92, bottom=0.13)
    return savefig(fig, "fig_joint_tstar_churn")


apply_rc()
data = load_all()
for b in (bar_fig, joint_fig):
    outs = b(data)
    print(b.__name__, "->", ", ".join(o.name for o in outs))
