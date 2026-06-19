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
