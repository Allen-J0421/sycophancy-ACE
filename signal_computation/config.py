"""Threshold and language configuration for signal computation."""

from __future__ import annotations

import os

from experiment_runner.env import load_dotenv_file

DEFAULT_EPS1 = 0.5
DEFAULT_EPS3 = 0.5
DEFAULT_EPS6 = 0.1

ENV_EPS1 = "EPS1"
ENV_EPS3 = "EPS3"
ENV_EPS6 = "EPS6"

LANG_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "java": (".java",),
    "js": (".js", ".jsx"),
}
FALLBACK_EXTENSIONS = (".java", ".js", ".jsx")


def float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid {name}={raw!r} in environment (expected a float).") from exc


def load_thresholds() -> tuple[float, float, float]:
    load_dotenv_file()
    return (
        float_env(ENV_EPS1, DEFAULT_EPS1),
        float_env(ENV_EPS3, DEFAULT_EPS3),
        float_env(ENV_EPS6, DEFAULT_EPS6),
    )
