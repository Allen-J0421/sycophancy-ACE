#!/usr/bin/env python3
"""Compute sycophancy signals (S1-S6) from RefDiff JSONL + git stats.

Phase 4 of the pipeline (after run_experiment.py / run_refdiff.py). Scans
``result/`` for ``<exp>/refdiff/<stamp>-refdiff.jsonl`` files (one per
experiment+model), where each JSONL line is a transition ``V_{t-1} -> V_t``
keyed by ``run`` (= turn ``t``). For each model run-sequence it derives the six
behavioral signals defined in ``doc/sycophancy_signals.tex`` and writes:

  * ``result/<exp>/signals/<stamp>-signals.json`` - full per-model breakdown
    (per-turn series + S1..S6 continuous/binary values).
  * ``result/<exp>/signals/<exp>_signals.csv`` - one row per model for quick comparison.

Implementation lives in the ``signal_computation`` package; this module re-exports
the public API and provides the CLI entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_RESULT_DIR = _SCRIPT_DIR / "result"
sys.path.insert(0, str(_SCRIPT_DIR))

from experiment_runner.env import dotenv_file_candidates, load_dotenv_file  # noqa: E402
from experiment_runner.util import eprint  # noqa: E402
from signal_computation import (  # noqa: E402
    CSV_FIELDS,
    DEFAULT_EPS1,
    DEFAULT_EPS3,
    DEFAULT_EPS6,
    ENV_EPS1,
    ENV_EPS3,
    ENV_EPS6,
    LANG_EXTENSIONS,
    LineageIndex,
    SignalCalculator,
    SignalResult,
    Thresholds,
    TurnData,
    agent_created_deletions,
    build_lineage_index,
    count_present_absent_present,
    experiment_dirs,
    extract_change_sets,
    float_env,
    iter_relationships,
    lc_of,
    load_thresholds,
    node_key,
    present_absent_present_nodes,
    process_experiment,
    refdiff_jsonl_files,
    result_to_csv_row,
    result_to_json,
    version_keys,
)
from signal_computation.cli import main  # noqa: E402
from signal_computation.loc import GitLocCounter  # noqa: E402

__all__ = [
    "CSV_FIELDS",
    "DEFAULT_EPS1",
    "DEFAULT_EPS3",
    "DEFAULT_EPS6",
    "ENV_EPS1",
    "ENV_EPS3",
    "ENV_EPS6",
    "LANG_EXTENSIONS",
    "LineageIndex",
    "SignalCalculator",
    "SignalResult",
    "Thresholds",
    "TurnData",
    "_FALLBACK_EXTENSIONS",
    "_RESULT_DIR",
    "agent_created_deletions",
    "build_lineage_index",
    "compute_signals_for_jsonl",
    "count_present_absent_present",
    "env_file_candidates",
    "eprint",
    "experiment_dirs",
    "extract_change_sets",
    "float_env",
    "iter_relationships",
    "lc_of",
    "load_env_file",
    "load_thresholds",
    "loc_at_commit",
    "main",
    "node_key",
    "present_absent_present_nodes",
    "process_experiment",
    "refdiff_jsonl_files",
    "result_to_csv_row",
    "result_to_json",
    "version_keys",
]

_FALLBACK_EXTENSIONS = (".java", ".js", ".jsx")


def env_file_candidates() -> list[Path]:
    return dotenv_file_candidates()


def load_env_file() -> None:
    load_dotenv_file()


def loc_at_commit(
    repo: Path,
    sha: str,
    lang: str,
    cache: dict[tuple[str, str], int],
) -> int:
    return GitLocCounter(cache=cache).loc_at_commit(repo, sha, lang)


def compute_signals_for_jsonl(
    jsonl_path: Path,
    exp_name: str,
    *,
    eps1: float,
    eps3: float,
    eps6: float,
    loc_cache: dict[tuple[str, str], int],
) -> SignalResult | None:
    calculator = SignalCalculator(
        GitLocCounter(cache=loc_cache),
        Thresholds(eps1=eps1, eps3=eps3, eps6=eps6),
    )
    return calculator.compute_for_jsonl(jsonl_path, exp_name)


def result_to_json_compat(
    result: SignalResult,
    *,
    eps1: float,
    eps3: float,
    eps6: float,
) -> dict:
    return result_to_json(
        result,
        thresholds=Thresholds(eps1=eps1, eps3=eps3, eps6=eps6),
    )


# Preserve original keyword-only signature: result_to_json(..., eps1=, eps3=, eps6=)
result_to_json = result_to_json_compat  # type: ignore[assignment]


if __name__ == "__main__":
    raise SystemExit(main())
