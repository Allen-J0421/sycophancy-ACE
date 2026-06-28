"""Shared chart styling for plot_lines.py and dashboard/build.py.

One distinct color + marker + display label per model. Keep colors and markers
mutually distinct so overlapping lines stay readable.
"""

COLORS = {
    "gpt-5.5":           "#2ca02c",  # green
    "gpt-5.4":           "#1f77b4",  # blue
    "gpt-5.4-mini":      "#17becf",  # teal
    "gpt-5.2":           "#bcbd22",  # olive (legacy)
    "claude-opus-4-8":   "#9467bd",  # purple
    "claude-sonnet-4-6": "#ff7f0e",  # orange
    "claude-haiku-4-5":  "#d62728",  # red
}

MARKERS = {
    "gpt-5.5":           "^",
    "gpt-5.4":           "o",
    "gpt-5.4-mini":      "v",
    "gpt-5.2":           ">",
    "claude-opus-4-8":   "P",
    "claude-sonnet-4-6": "s",
    "claude-haiku-4-5":  "D",
}

LABELS = {
    "gpt-5.5":           "GPT-5.5",
    "gpt-5.4":           "GPT-5.4",
    "gpt-5.4-mini":      "GPT-5.4-mini",
    "gpt-5.2":           "GPT-5.2",
    "claude-opus-4-8":   "Claude Opus 4.8",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-haiku-4-5":  "Claude Haiku 4.5",
}

# Sycophancy signal plot metadata (plot_signals.py, plot_aggregate.py, dashboard).
SIGNAL_IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
BINARY_SIGNAL_IDS = ("S1", "S2", "S3", "S4", "S5", "S6")
RATIO_SIGNAL_IDS = frozenset({"S6", "S7"})

SIGNAL_TITLES = {
    "S1": "S1: Pre-convergence churn",
    "S2": "S2: Post-convergence mod.",
    "S3": "S3: Line-change volatility",
    "S4": "S4: Feature rollback",
    "S5": "S5: Reimplementation loop",
    "S6": "S6: Patch-region recurrence",
    "S7": "S7: Verbal-refusal edit rate",
}

SIGNAL_TITLES_AGG = {
    "S1": "S1 Pre-conv churn (÷L0)",
    "S2": "S2 Post-conv mod (÷L0)",
    "S3": "S3 Volatility (÷L0)",
    "S4": "S4 Feature rollback (count)",
    "S5": "S5 Reimpl. loop (count)",
    "S6": "S6 Patch recurrence (ratio)",
    "S7": "S7 Verbal-refusal edit rate",
}

SIGNAL_GRID_COLS = 4
