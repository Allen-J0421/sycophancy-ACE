#!/usr/bin/env python3
import sys
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

csv_path = sys.argv[1] if len(sys.argv) > 1 else "results.csv"
out_path = sys.argv[2] if len(sys.argv) > 2 else None

df = pd.read_csv(csv_path)
if "lines_total" not in df.columns:
    df["lines_total"] = df.get("lines_added", 0).fillna(0) + df.get("lines_deleted", 0).fillna(0)

sns.lineplot(data=df, x="run", y="lines_total", marker="o")
plt.xlabel("Iteration")
plt.xticks(df["run"].values)
plt.ylabel("Lines changed")
plt.tight_layout()
plt.savefig(out_path, dpi=200) if out_path else plt.show()
