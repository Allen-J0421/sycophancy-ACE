#!/usr/bin/env python3
import sys
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

if len(sys.argv) < 2:
    sys.exit("usage: plot.py <csv|dir> [out.png]")

root, out = Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None
paths = sorted(root.glob("*.csv")) if root.is_dir() else [root]
if not paths:
    sys.exit(f"no .csv in {root}")

loaded, keys = [], []
for path in paths:
    d = pd.read_csv(path)
    if "lines_total" not in d.columns:
        d["lines_total"] = d.get("lines_added", 0).fillna(0) + d.get("lines_deleted", 0).fillna(0)
    k = (
        str(d["model"].dropna().iloc[0])
        if "model" in d.columns and d["model"].notna().any()
        else path.stem
    )
    loaded.append((d, path, k))
    keys.append(k)

cnt = Counter(keys)
for d, path, k in loaded:
    d["series"] = f"{k} ({path.stem})" if cnt[k] > 1 else k

df = pd.concat([d for d, _, _ in loaded], ignore_index=True)
sns.lineplot(data=df, x="run", y="lines_total", hue="series", marker="o")
plt.xlabel("Iteration")
plt.ylabel("Lines changed")
plt.legend(title="model")
plt.tight_layout()
plt.savefig(out, dpi=200) if out else plt.show()
