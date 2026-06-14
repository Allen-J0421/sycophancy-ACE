"""Batch processing of experiment result directories."""

from __future__ import annotations

import csv
from pathlib import Path

from experiment_runner.result_paths import signals_csv_path, signals_dir
from experiment_runner.util import eprint

from signal_computation.calculator import SignalCalculator
from signal_computation.discovery import refdiff_jsonl_files
from signal_computation.jsonl_io import load_refdiff_records
from signal_computation.models import SignalResult, Thresholds
from signal_computation.s5_refdiff_links import (
    S5LinkBuilder,
    s5_links_cache_path,
    write_s5_links_cache,
)
from signal_computation.serialization import (
    CSV_FIELDS,
    result_to_csv_row,
    write_signal_json,
)


class ExperimentSignalPipeline:
    """Processes all RefDiff JSONL files for one experiment (SRP: I/O orchestration)."""

    def __init__(
        self,
        calculator: SignalCalculator,
        *,
        skip_s5_refdiff: bool = False,
        compare_cache: dict | None = None,
    ) -> None:
        self._calculator = calculator
        self._skip_s5_refdiff = skip_s5_refdiff
        self._link_builder = S5LinkBuilder(
            compare_cache=compare_cache if compare_cache is not None else {}
        )

    def process(self, exp_dir: Path) -> list[SignalResult]:
        jsonl_files = refdiff_jsonl_files(exp_dir)
        if not jsonl_files:
            return []

        results: list[SignalResult] = []
        signals_out_dir = signals_dir(exp_dir)
        thresholds = self._calculator.thresholds

        for jsonl_path in jsonl_files:
            records = load_refdiff_records(jsonl_path)
            if not records:
                eprint(f"[skip] {jsonl_path.name}: no records")
                continue

            first = records[0]
            s5_links = self._link_builder.build(
                records,
                repo_path=str(first.get("repo_path") or ""),
                language=str(first.get("language") or ""),
                enabled=not self._skip_s5_refdiff,
            )
            cache_path = s5_links_cache_path(jsonl_path)
            write_s5_links_cache(s5_links, cache_path)
            if s5_links:
                eprint(f"[s5] {cache_path.name}: {len(s5_links)} cross-turn link(s)")

            result = self._calculator.compute_for_jsonl(
                jsonl_path,
                exp_dir.name,
                s5_links=s5_links,
            )
            if result is None:
                eprint(f"[skip] {jsonl_path.name}: no records")
                continue
            results.append(result)

            signals_out_dir.mkdir(parents=True, exist_ok=True)
            out_json = signals_out_dir / f"{result.stamp}-signals.json"
            write_signal_json(result, out_json, thresholds=thresholds)
            eprint(f"[done] {out_json}")

        if results:
            signals_out_dir.mkdir(parents=True, exist_ok=True)
            csv_path = signals_csv_path(exp_dir)
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()
                for result in results:
                    writer.writerow(result_to_csv_row(result))
            eprint(f"[done] {csv_path}")

        return results


def process_experiment(
    exp_dir: Path,
    *,
    eps1: float,
    eps3: float,
    eps6: float,
    loc_cache: dict[tuple[str, str], int],
    skip_s5_refdiff: bool = False,
    compare_cache: dict | None = None,
) -> list[SignalResult]:
    """Backward-compatible entry point for batch experiment processing."""
    from signal_computation.loc import GitLocCounter

    calculator = SignalCalculator(
        GitLocCounter(cache=loc_cache),
        Thresholds(eps1=eps1, eps3=eps3, eps6=eps6),
    )
    return ExperimentSignalPipeline(
        calculator,
        skip_s5_refdiff=skip_s5_refdiff,
        compare_cache=compare_cache,
    ).process(exp_dir)
