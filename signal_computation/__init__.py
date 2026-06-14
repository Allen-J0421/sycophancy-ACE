from __future__ import annotations

from pathlib import Path

from signal_computation.calculator import SignalCalculator, TurnAccumulator
from signal_computation.cli import main
from signal_computation.config import (
    DEFAULT_EPS1,
    DEFAULT_EPS3,
    DEFAULT_EPS6,
    ENV_EPS1,
    ENV_EPS3,
    ENV_EPS6,
    FALLBACK_EXTENSIONS,
    LANG_EXTENSIONS,
    float_env,
    load_thresholds,
)
from signal_computation.discovery import experiment_dirs, refdiff_jsonl_files
from signal_computation.line_signals import lc_of
from signal_computation.lineage import (
    LineageIndex,
    agent_created_deletions,
    build_lineage_index,
)
from signal_computation.loc import GitLocCounter, LocCounter
from signal_computation.models import SignalResult, Thresholds, TurnData
from signal_computation.nodes import extract_change_sets, iter_relationships, node_key, version_keys
from signal_computation.pipeline import ExperimentSignalPipeline, process_experiment
from signal_computation.presence import (
    count_present_absent_present,
    present_absent_present_nodes,
)
from signal_computation.serialization import CSV_FIELDS, result_to_csv_row, result_to_json


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


__all__ = [
    "CSV_FIELDS",
    "DEFAULT_EPS1",
    "DEFAULT_EPS3",
    "DEFAULT_EPS6",
    "ENV_EPS1",
    "ENV_EPS3",
    "ENV_EPS6",
    "ExperimentSignalPipeline",
    "FALLBACK_EXTENSIONS",
    "GitLocCounter",
    "LANG_EXTENSIONS",
    "LineageIndex",
    "LocCounter",
    "SignalCalculator",
    "SignalResult",
    "Thresholds",
    "TurnAccumulator",
    "TurnData",
    "agent_created_deletions",
    "build_lineage_index",
    "compute_signals_for_jsonl",
    "count_present_absent_present",
    "experiment_dirs",
    "extract_change_sets",
    "float_env",
    "iter_relationships",
    "lc_of",
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

# Backward-compatible alias used by legacy imports.
_FALLBACK_EXTENSIONS = FALLBACK_EXTENSIONS
