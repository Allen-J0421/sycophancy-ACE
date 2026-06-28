"""CLI entry point for signal computation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from experiment_runner.util import eprint, script_dir

from signal_computation.config import ENV_EPS1, ENV_EPS3, ENV_EPS6, load_thresholds
from signal_computation.discovery import experiment_dirs
from signal_computation.pipeline import process_experiment
from signal_computation.s7_patch import patch_s7_for_experiment

from refusal_analysis.keyword_regex import DEFAULT_CONFIG_PATH

_DEFAULT_RESULT_DIR = script_dir() / "result"
_DEFAULT_REFUSAL_CONFIG = DEFAULT_CONFIG_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute sycophancy signals (S1-S7) from RefDiff JSONL."
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=_DEFAULT_RESULT_DIR,
        help="Path to result/ directory (default: repo result/).",
    )
    parser.add_argument(
        "--exp",
        help="Only process this experiment folder name under result/.",
    )
    parser.add_argument(
        "--skip-s5-refdiff",
        action="store_true",
        help="Skip S5 layer-2 cross-turn RefDiff compares (exact lineage P-A-P only).",
    )
    parser.add_argument(
        "--refusal-config",
        type=Path,
        default=_DEFAULT_REFUSAL_CONFIG,
        help="Path to keyword_regex_config.json for S7 verbal-refusal detection.",
    )
    parser.add_argument(
        "--s7-only",
        action="store_true",
        help="Patch S7 into existing signals JSON/CSV only (skip S1-S6 recomputation).",
    )
    args = parser.parse_args(argv)

    result_dir = args.result_dir.resolve()
    if not result_dir.is_dir():
        eprint(f"error: result dir not found: {result_dir}")
        return 2

    if args.exp:
        exp_dir = result_dir / args.exp
        if not exp_dir.is_dir():
            eprint(f"error: experiment not found: {exp_dir}")
            return 2
        exp_dirs = [exp_dir]
    else:
        exp_dirs = experiment_dirs(result_dir)

    refusal_config = args.refusal_config.resolve()

    if args.s7_only:
        total = 0
        for exp_dir in exp_dirs:
            total += patch_s7_for_experiment(exp_dir, refusal_config=refusal_config)
        if total == 0:
            eprint("No S7 patches applied (no refdiff/*-refdiff.jsonl or missing signals JSON).")
            return 1
        eprint(f"[summary] patched S7 for {total} model run-sequences.")
        return 0

    eps1, eps3, eps6 = load_thresholds()
    eprint(f"[info] thresholds: {ENV_EPS1}={eps1}, {ENV_EPS3}={eps3}, {ENV_EPS6}={eps6}")

    loc_cache: dict[tuple[str, str], int] = {}
    compare_cache: dict[tuple[str, str, str, str], dict] = {}
    total = 0
    for exp_dir in exp_dirs:
        results = process_experiment(
            exp_dir,
            eps1=eps1,
            eps3=eps3,
            eps6=eps6,
            loc_cache=loc_cache,
            skip_s5_refdiff=args.skip_s5_refdiff,
            compare_cache=compare_cache,
            refusal_config=refusal_config,
        )
        total += len(results)

    if total == 0:
        eprint("No signals computed (no refdiff/*-refdiff.jsonl found).")
        return 1
    eprint(f"[summary] computed signals for {total} model run-sequences.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
