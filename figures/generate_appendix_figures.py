#!/usr/bin/env python3
"""Generate the supplementary-material (appendix) figures and tables.

Covers the three ablation studies promised in the paper's Method section
(``30_method.tex`` §Ablation Studies), reading only from ``output/``:

  * Reasoning effort   — ``output/reasoning_test/001_binary_search_r01..r10``,
                         GPT-5.5 at effort none/low/medium/high/xhigh.
  * Prompt variation   — ``output/prompt-expert/Algorithms/001_binary_search``,
                         the 8-cell B+A factorial (config/ablation_B_plus_A_core8.json)
                         plus the novice baseline from the main experiment.
  * Codebase scale     — ``output/RealWorld/G001..G005`` (five large GitHub
                         repositories), per-turn line logs + per-run signals.

Signal names follow the *paper* numbering: the signals CSV column ``S7_cont``
(verbal-refusal edit rate) is the paper's S3; the CSV column ``S3`` (volatility)
is not used by the paper and is ignored here.

Run (from anywhere):
    python figures/generate_appendix_figures.py

Outputs land in ``figures/output/`` as paired PNG + PDF (``appA_*``), plus
LaTeX tables in ``figures/output/tables/`` and the exact numbers behind every
figure in ``figures/output/appendix_figure_data.csv``.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from fig_style import (
    FIG_OUT_DIR,
    MODEL_ORDER,
    NUM_TURNS,
    OUTPUT_ROOT,
    TEXT_W,
    apply_rc,
    grid,
    lighten,
    model_color,
    plt,
    savefig,
)

TBL_OUT_DIR = FIG_OUT_DIR / "tables"

GPT55 = "gpt-5.5"
EFFORTS = ["none", "low", "medium", "high", "xhigh"]

# Paper-numbered signals -> signals-CSV column. CSV `S7_cont` is paper S3;
# CSV `S3` (volatility) is not a paper signal.
PAPER_SIG_COL = {
    "S1": "S1",
    "S2": "S2",
    "S3": "S7_cont",
    "S4": "S4_cont",
    "S5": "S5_cont",
    "S6": "S6_cont",
}


def read_signal_rows(csv_path: Path) -> list[dict]:
    with csv_path.open() as f:
        return list(csv.DictReader(f))


def sig_val(row: dict, paper_sid: str) -> float | None:
    col = PAPER_SIG_COL[paper_sid]
    raw = row.get(col, "")
    return float(raw) if raw not in ("", None) else None


def tstar(row: dict) -> float:
    """First stop turn; runs that never stop (t0 = NUM_TURNS+1) are capped at
    NUM_TURNS, matching fig1 in the main body."""
    return min(float(row["t0"]), float(NUM_TURNS))


def never_stopped(row: dict) -> bool:
    return float(row["t0"]) > NUM_TURNS


def only_signals_csv(exp_dir: Path) -> Path | None:
    hits = sorted((exp_dir / "signals").glob("*_signals.csv")) if (exp_dir / "signals").is_dir() else []
    return hits[0] if hits else None


# =========================================================================== #
# Ablation 1 — Reasoning effort (GPT-5.5 x 5 efforts x 10 replicas)
# =========================================================================== #
def load_reasoning() -> dict[str, dict[str, np.ndarray]]:
    """effort -> {metric: per-seed array} for t* and the paper signals."""
    root = OUTPUT_ROOT / "reasoning_test"
    out: dict[str, dict[str, list[float]]] = {}
    for eff in EFFORTS:
        vals: dict[str, list[float]] = {k: [] for k in ("tstar", "S1", "S2", "S4", "S5", "S6")}
        for seed_dir in sorted(root.glob("001_binary_search_r*")):
            csv_path = only_signals_csv(seed_dir / f"{GPT55}-{eff}-Agent")
            if not csv_path:
                continue
            for row in read_signal_rows(csv_path):
                vals["tstar"].append(tstar(row))
                for sid in ("S1", "S2", "S4", "S5", "S6"):
                    v = sig_val(row, sid)
                    if v is not None:
                        vals[sid].append(v)
        out[eff] = {k: np.asarray(v, dtype=float) for k, v in vals.items()}
    return out


def figA_reasoning_effort(reasoning):
    """t*, pre-stop churn S1, and rollback S4 (with S5) vs reasoning effort.
    Mean over the ten replicas, error bar = 1 s.d. across replicas."""
    fig, axes = plt.subplots(1, 3, figsize=(TEXT_W, 2.4), gridspec_kw=dict(wspace=0.32))
    x = np.arange(len(EFFORTS))
    col = model_color(GPT55)

    def series(metric):
        m = np.array([reasoning[e][metric].mean() for e in EFFORTS])
        s = np.array([reasoning[e][metric].std(ddof=1) for e in EFFORTS])
        return m, s

    panels = [
        ("tstar", r"First stop turn $t^{*}$"),
        ("S1", r"$S_1$: pre-stop churn ($\div\,L_0$)"),
        ("S4", r"$S_4$: additions rolled back"),
    ]
    tick_lbl = {"none": "none", "low": "low", "medium": "med",
                "high": "high", "xhigh": "xhigh"}
    for ax, (metric, ylab) in zip(axes, panels):
        m, s = series(metric)
        ax.errorbar(
            x, m, yerr=s, color=col, marker="o", ms=4.5, lw=1.4,
            elinewidth=0.8, capsize=2.5, ecolor="0.4", zorder=4,
        )
        ax.set_xticks(x)
        ax.set_xticklabels([tick_lbl[e] for e in EFFORTS])
        ax.set_xlim(-0.4, len(EFFORTS) - 0.6)
        ax.set_xlabel("Reasoning effort")
        ax.set_ylabel(ylab)
        grid(ax)
    # t* panel: show the 10-turn ceiling (= never stopped within the horizon)
    axes[0].axhline(NUM_TURNS, color="0.6", lw=0.9, ls=":", zorder=1)
    axes[0].set_ylim(0, NUM_TURNS + 1.6)
    axes[0].annotate("horizon (never stops)", (len(EFFORTS) - 0.65, NUM_TURNS),
                     xytext=(0, 4), textcoords="offset points",
                     ha="right", va="bottom", fontsize=7, color="0.35")
    # S4 panel: overlay S5 (reimplementation) as the lighter companion series
    m5, s5 = series("S5")
    axes[2].errorbar(
        x, m5, yerr=s5, color=lighten(col, 0.45), marker="s", ms=4, lw=1.2,
        elinewidth=0.8, capsize=2.5, ecolor="0.6", zorder=3,
    )
    axes[2].legend([r"$S_4$ rollback", r"$S_5$ reimplementation"], fontsize=7.5,
                   loc="upper left")
    fig.tight_layout()
    return savefig(fig, "appA_reasoning_effort")


def tableA_reasoning(reasoning) -> Path:
    """LaTeX table: mean +- s.d. per effort level for t* and paper signals."""
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Reasoning-effort ablation: GPT-5.5 on the Java binary-search"
        r" subject, ten replicas per effort level (mean $\pm$ s.d.). $t^{*}$ is"
        r" capped at the 10-turn horizon.}",
        r"\label{tab:app-reasoning}",
        r"\small",
        r"\begin{tabular}{lccccc}",
        r"\toprule",
        r"Metric & \texttt{none} & \texttt{low} & \texttt{medium} & \texttt{high} & \texttt{xhigh} \\",
        r"\midrule",
    ]
    rows = [
        ("tstar", r"$t^{*}$ (stop turn)", "{:.1f}"),
        ("S1", r"$S_1$ pre-stop churn", "{:.1f}"),
        ("S2", r"$S_2$ post-stop churn", "{:.2f}"),
        ("S4", r"$S_4$ rollback", "{:.1f}"),
        ("S5", r"$S_5$ reimplementation", "{:.1f}"),
        ("S6", r"$S_6$ region recurrence", "{:.2f}"),
    ]
    for metric, label, fmt in rows:
        cells = []
        for e in EFFORTS:
            a = reasoning[e][metric]
            cells.append(f"${fmt.format(a.mean())} \\pm {fmt.format(a.std(ddof=1))}$")
        lines.append(f"{label} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
    out = TBL_OUT_DIR / "appA_reasoning.tex"
    out.write_text("\n".join(lines))
    return out


# =========================================================================== #
# Ablation 2 — Simulated-developer prompt variation (8-cell B+A factorial)
# =========================================================================== #
# Cell order and display labels: novice baseline first, then examples-on cells,
# then examples-off cells (matching config/ablation_B_plus_A_core8.json).
PROMPT_CELLS = [
    ("novice", "Novice (main experiment)"),
    ("BA__ex__none", "Expert, examples"),
    ("BA__ex__vague", "Expert, examples + vague"),
    ("BA__ex__deflect1+deflect2", "Expert, examples + deflection"),
    ("BA__ex__noleak", "Expert, examples + anti-leak"),
    ("BA__ex__vague+deflect1+deflect2+noleak", "Expert, examples + all"),
    ("BA__noex__none", "Expert, no examples"),
    ("BA__noex__vague", "Expert, no examples + vague"),
    ("BA__noex__vague+deflect1+deflect2+noleak", "Expert, no examples + all"),
]


def load_prompt_cells() -> dict[str, dict]:
    """cell id -> gpt-5.5 signals row (paper-numbered values + t*)."""
    out: dict[str, dict] = {}

    def keep(cell_id: str, row: dict) -> None:
        entry = {"tstar": tstar(row), "never": never_stopped(row)}
        for sid in PAPER_SIG_COL:
            entry[sid] = sig_val(row, sid)
        out[cell_id] = entry

    novice_csv = only_signals_csv(
        OUTPUT_ROOT / "Algorithms" / "001_binary_search-high-Agent"
    )
    for row in read_signal_rows(novice_csv):
        if row["model"] == GPT55:
            keep("novice", row)

    suite = OUTPUT_ROOT / "prompt-expert" / "Algorithms" / "001_binary_search"
    for cell_id, _label in PROMPT_CELLS[1:]:
        csv_path = only_signals_csv(suite / f"{cell_id}-Agent")
        if csv_path:
            for row in read_signal_rows(csv_path):
                keep(cell_id, row)
    return out


def figA_prompt_ablation(cells):
    """Pre-stop churn S1 and rollback S4 across the prompt-ablation cells,
    single 10-turn run each (GPT-5.5, high). Horizontal bars so the cell
    names stay legible; the novice baseline is the reference row."""
    ids = [c for c, _ in PROMPT_CELLS if c in cells]
    labels = {c: l for c, l in PROMPT_CELLS}
    y = np.arange(len(ids))[::-1]
    col = model_color(GPT55)

    def bar_color(cell_id):
        if cell_id == "novice":
            return "0.45"
        return col if "__ex__" in cell_id else lighten(col, 0.45)

    fig, axes = plt.subplots(
        1, 2, figsize=(TEXT_W, 2.6), sharey=True, gridspec_kw=dict(wspace=0.08)
    )
    for ax, sid, xlab in (
        (axes[0], "S1", r"$S_1$: pre-stop churn ($\div\,L_0$)"),
        (axes[1], "S4", r"$S_4$: additions rolled back"),
    ):
        vals = [cells[c][sid] for c in ids]
        ax.barh(y, vals, 0.62, color=[bar_color(c) for c in ids],
                edgecolor="white", linewidth=0.5, zorder=3)
        for yi, v in zip(y, vals):
            ax.annotate(f"{v:.1f}", (v, yi), xytext=(3, 0),
                        textcoords="offset points", va="center", ha="left",
                        fontsize=7, color="0.2")
        ax.set_xlim(0, max(vals) * 1.14)
        ax.set_xlabel(xlab)
        grid(ax, axis="x")
    # novice reference line on the churn panel
    axes[0].axvline(cells["novice"]["S1"], color="0.35", lw=0.9, ls=":", zorder=2)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([labels[c] for c in ids], fontsize=8)
    fig.tight_layout()
    return savefig(fig, "appA_prompt_ablation")


def tableA_prompt(cells) -> Path:
    """LaTeX table: every prompt cell x paper signals (single run per cell)."""
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Prompt-variation ablation: GPT-5.5 (high effort) on the Java"
        r" binary-search subject, one 10-turn run per prompt cell. $t^{*}>10$"
        r" means the agent never produced a no-edit turn within the horizon."
        r" Cells add novice-prompt constraint lines (vagueness, deflection,"
        r" anti-leak) to the expert base prompt with or without its few-shot"
        r" examples.}",
        r"\label{tab:app-prompt}",
        r"\small",
        r"\begin{tabular}{lcccccc}",
        r"\toprule",
        r"Prompt cell & $t^{*}$ & $S_1$ & $S_3$ & $S_4$ & $S_5$ & $S_6$ \\",
        r"\midrule",
    ]
    for cell_id, label in PROMPT_CELLS:
        if cell_id not in cells:
            continue
        c = cells[cell_id]
        ts = r"$>10$" if c["never"] else f"{c['tstar']:.0f}"
        s3 = "--" if c["S3"] is None else f"{c['S3']:.2f}"
        lines.append(
            f"{label} & {ts} & {c['S1']:.1f} & {s3} & {c['S4']:.0f} & "
            f"{c['S5']:.0f} & {c['S6']:.2f} \\\\"
        )
        if cell_id == "novice":
            lines.append(r"\midrule")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
    out = TBL_OUT_DIR / "appA_prompt.tex"
    out.write_text("\n".join(lines))
    return out


# =========================================================================== #
# Ablation 3 — Codebase scale (five large GitHub Java repositories)
# =========================================================================== #
# G002 (Elasticsearch) is excluded: RefDiff was not run for it, so it has no
# structural signals and the paper reports the four covered repositories.
G_REPOS = [
    ("G001_dbeaver", "DBeaver"),
    ("G003_guava", "Guava"),
    ("G004_spring_boot", "Spring Boot"),
    ("G005_termux", "Termux"),
]
# The paper reports the G-series with the GPT family only.
G_MODELS = ["gpt-5.5", "gpt-5.4-mini", "gpt-5.4"]


def load_scale() -> dict[str, dict]:
    """repo id -> {model: {"lines": per-turn list, "sig": signals row or None}}."""
    out: dict[str, dict] = {}
    for gid, _label in G_REPOS:
        exp_dir = OUTPUT_ROOT / "RealWorld" / f"{gid}-high-Agent"
        per_model: dict[str, dict] = {}
        # newest log per model (filenames: <stamp>-<model>-log.csv)
        logs_by_model: dict[str, Path] = {}
        for log in sorted((exp_dir / "logs").glob("*-log.csv")):
            stem = log.name[: -len("-log.csv")]
            stamp, _, model = stem.partition("-")
            if model in G_MODELS:
                logs_by_model[model] = log  # sorted() keeps the newest last
        for model, log in logs_by_model.items():
            with log.open() as f:
                turns = sorted(csv.DictReader(f), key=lambda r: int(r["run"]))
            per_model[model] = {
                "lines": [float(r["lines_total"]) for r in turns],
                "sig": None,
            }
        sig_csv = only_signals_csv(exp_dir)
        if sig_csv:
            for row in read_signal_rows(sig_csv):
                if row["model"] in per_model:
                    per_model[row["model"]]["sig"] = row
        # Trust a signals row only if its stop turn agrees with the raw line
        # log (first zero-edit turn). Two Sonnet rows (Guava, Termux) fail
        # this: their branches drifted from the run the log recorded, so
        # their structural signals describe the wrong commits.
        for m, d in per_model.items():
            if d["sig"] is None:
                continue
            zeros = [i + 1 for i, v in enumerate(d["lines"]) if v <= 0]
            log_t0 = zeros[0] if zeros else NUM_TURNS + 1
            if int(float(d["sig"]["t0"])) != log_t0:
                print(f"  !! {gid}/{m}: signals t0={d['sig']['t0']} disagrees "
                      f"with line log (t0={log_t0}); dropping signals row")
                d["sig"] = None
        out[gid] = per_model
    return out


def figA_codebase_scale(scale):
    """Per-turn lines changed on the five large repositories, one panel per
    repo, one line per model, log y. Gaps mark no-edit turns."""
    fig, axes = plt.subplots(
        1, len(G_REPOS), figsize=(TEXT_W, 2.3), sharey=True,
        gridspec_kw=dict(wspace=0.08),
    )
    turns = np.arange(1, NUM_TURNS + 1)
    for ax, (gid, label) in zip(axes, G_REPOS):
        per_model = scale[gid]
        for m in G_MODELS:
            if m not in per_model:
                continue
            vals = np.asarray(per_model[m]["lines"][:NUM_TURNS], dtype=float)
            vals[vals <= 0] = np.nan  # log scale: no-edit turns become gaps
            ax.plot(turns[: vals.size], vals, color=model_color(m), lw=1.1,
                    marker="o", ms=2.4, alpha=0.9, zorder=3)
        ax.set_yscale("log")
        ax.set_title(label, fontsize=9)
        ax.set_xticks([1, 5, 10])
        ax.set_xlabel("Turn")
        grid(ax)
    axes[0].set_ylabel("Lines changed (log)")
    handles = [
        plt.Line2D([], [], color=model_color(m), lw=1.4, marker="o", ms=3,
                   label=lbl)
        for m, lbl in (
            ("gpt-5.5", "GPT-5.5"),
            ("gpt-5.4-mini", "GPT-5.4-mini"),
            ("gpt-5.4", "GPT-5.4"),
        )
    ]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.04),
               ncol=3, fontsize=7.5, columnspacing=1.2, handlelength=1.6)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.88, bottom=0.30)
    return savefig(fig, "appA_codebase_scale")


def tableA_scale(scale) -> Path:
    """LaTeX table: per repo x model — L0, t*, total lines changed, and the
    structural signals where the RefDiff pipeline produced them."""
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Codebase-scale ablation: one 10-turn run per GPT-family"
        r" model on each repository. $\Sigma|\Delta l|$ is the total lines"
        r" changed over the ten turns; $t^{*}>10$ means no no-edit turn"
        r" occurred.}",
        r"\label{tab:app-scale}",
        r"\small",
        r"\begin{tabular}{llrrrrrr}",
        r"\toprule",
        r"Repository & Model & $t^{*}$ & $\Sigma|\Delta l|$ & $S_1$ & $S_3$ & $S_4$ & $S_6$ \\",
        r"\midrule",
    ]
    tick = {
        "claude-opus-4-8": "Opus 4.8",
        "claude-sonnet-4-6": "Sonnet 4.6",
        "gpt-5.5": "GPT-5.5",
        "gpt-5.4-mini": "GPT-5.4-mini",
        "gpt-5.4": "GPT-5.4",
    }
    for gid, label in G_REPOS:
        per_model = scale[gid]
        first = True
        for m in G_MODELS:
            if m not in per_model:
                continue
            d = per_model[m]
            total = int(sum(d["lines"]))
            sig = d["sig"]
            if sig is not None:
                ts = r"$>10$" if never_stopped(sig) else f"{tstar(sig):.0f}"
                s1 = f"{sig_val(sig, 'S1'):.4f}"
                s3v = sig_val(sig, "S3")
                s3 = "--" if s3v is None else f"{s3v:.2f}"
                s4 = f"{sig_val(sig, 'S4'):.0f}"
                s6 = f"{sig_val(sig, 'S6'):.2f}"
            else:
                # line-log fallback: t* = first zero-edit turn
                zero = [i + 1 for i, v in enumerate(d["lines"]) if v <= 0]
                ts = f"{zero[0]}" if zero else r"$>10$"
                s1 = s3 = s4 = s6 = "--"
            name = label if first else ""
            first = False
            lines.append(
                f"{name} & {tick[m]} & {ts} & {total:,} & {s1} & {s3} & {s4} & {s6} \\\\"
            )
        lines.append(r"\midrule")
    lines[-1] = r"\bottomrule"
    lines += [r"\end{tabular}", r"\end{table*}", ""]
    out = TBL_OUT_DIR / "appA_scale.tex"
    out.write_text("\n".join(lines))
    return out


# =========================================================================== #
# Reproducibility dump
# =========================================================================== #
def dump_appendix_data(reasoning, cells, scale) -> Path:
    out = FIG_OUT_DIR / "appendix_figure_data.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ablation", "cell", "model", "metric", "mean", "sd", "n"])
        for e in EFFORTS:
            for metric, a in reasoning[e].items():
                w.writerow(["reasoning", e, GPT55, metric,
                            round(a.mean(), 4), round(a.std(ddof=1), 4), a.size])
        for cell_id, _ in PROMPT_CELLS:
            if cell_id not in cells:
                continue
            for metric, v in cells[cell_id].items():
                if metric == "never" or v is None:
                    continue
                w.writerow(["prompt", cell_id, GPT55, metric, round(v, 4), "", 1])
        for gid, _ in G_REPOS:
            for m, d in scale[gid].items():
                w.writerow(["scale", gid, m, "total_lines", int(sum(d["lines"])), "", 1])
                if d["sig"] is not None:
                    w.writerow(["scale", gid, m, "tstar", tstar(d["sig"]), "", 1])
                    for sid in PAPER_SIG_COL:
                        v = sig_val(d["sig"], sid)
                        if v is not None:
                            w.writerow(["scale", gid, m, sid, round(v, 4), "", 1])
    return out


def main():
    apply_rc()
    TBL_OUT_DIR.mkdir(parents=True, exist_ok=True)

    reasoning = load_reasoning()
    cells = load_prompt_cells()
    scale = load_scale()

    outs = []
    outs += figA_reasoning_effort(reasoning)
    outs += figA_prompt_ablation(cells)
    outs += figA_codebase_scale(scale)
    for p in (tableA_reasoning(reasoning), tableA_prompt(cells), tableA_scale(scale),
              dump_appendix_data(reasoning, cells, scale)):
        outs.append(p)
    for p in outs:
        print(f"  -> {p.relative_to(FIG_OUT_DIR.parent)}")


if __name__ == "__main__":
    raise SystemExit(main())
