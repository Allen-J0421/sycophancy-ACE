import os
import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiment_runner.result_paths import iter_log_csvs, plots_dir

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style_config import COLORS, LABELS, MARKERS

# Paper-friendly style settings
plt.rcParams.update({
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
})

base = os.path.dirname(os.path.abspath(__file__))

for exp in sorted(os.listdir(base)):
    exp_dir = os.path.join(base, exp)
    if not os.path.isdir(exp_dir):
        continue
    csv_files = iter_log_csvs(Path(exp_dir))
    if not csv_files:
        continue

    fig, ax = plt.subplots(figsize=(5.5, 3.5))

    for csv_path in csv_files:
        df = pd.read_csv(csv_path)
        model = df["model"].iloc[0]
        color  = COLORS.get(model, None)
        marker = MARKERS.get(model, "D")
        label  = LABELS.get(model, model)
        ax.plot(df["run"], df["lines_total"],
                marker=marker, markersize=5, linewidth=1.2,
                color=color, label=label)

    ax.set_xlabel("Refactoring Iteration (run)")
    ax.set_ylabel("Lines Total Changed")
    ax.set_title(f"Lines Changed per Refactoring Run — {exp.upper()}")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.legend(loc="upper right")
    fig.tight_layout()

    plots_dir_path = plots_dir(Path(exp_dir))
    plots_dir_path.mkdir(parents=True, exist_ok=True)
    out_path = plots_dir_path / f"{exp}_lines_total.pdf"
    fig.savefig(str(out_path), bbox_inches="tight")
    png_path = str(out_path).replace(".pdf", ".png")
    fig.savefig(png_path, bbox_inches="tight")
    print(f"Saved: {out_path}")
    print(f"Saved: {png_path}")
    plt.close(fig)