"""Serialize SignalResult to JSON and CSV."""

from __future__ import annotations

import json

from signal_computation.models import SignalResult, Thresholds


def result_to_json(result: SignalResult, *, thresholds: Thresholds) -> dict:
    return {
        "experiment": result.experiment,
        "stamp": result.stamp,
        "model": result.model,
        "repo_path": result.repo_path,
        "language": result.language,
        "num_turns": result.num_turns,
        "t0": result.t0,
        "L0": result.l0,
        "L0_ok": result.l0_ok,
        "skipped_turns": result.skipped_turns,
        "thresholds": {
            "eps1": thresholds.eps1,
            "eps3": thresholds.eps3,
            "eps6": thresholds.eps6,
        },
        "signals": {
            "S1": {"cont": result.s1, "bin": result.s1_bin},
            "S2": {"cont": result.s2, "bin": result.s2_bin},
            "S3": {"cont": result.s3, "bin": result.s3_bin},
            "S4": {"cont": result.s4_cont, "bin": result.s4_bin},
            "S5": {"cont": result.s5_cont, "bin": result.s5_bin},
            "S6": {"cont": result.s6_cont, "bin": result.s6_bin},
            "S7": {"cont": result.s7_cont},
        },
        "turns": [
            {
                "run": turn.run,
                "LC": turn.lc,
                "f1": turn.f1,
                "refdiff_ok": turn.refdiff_ok,
                "N_plus": turn.n_plus,
                "N_minus": turn.n_minus,
                "N_minus_new": turn.n_minus_new,
                "T_touched": turn.n_touched,
                "C_size": turn.c_size,
                "rho": turn.rho,
                "rolling": turn.rolling,
                "sets": turn.sets,
            }
            for turn in result.turns
        ],
    }


CSV_FIELDS = (
    "experiment",
    "stamp",
    "model",
    "num_turns",
    "t0",
    "L0",
    "L0_ok",
    "skipped_turns",
    "S1",
    "S1_bin",
    "S2",
    "S2_bin",
    "S3",
    "S3_bin",
    "S4_cont",
    "S4_bin",
    "S5_cont",
    "S5_bin",
    "S6_cont",
    "S6_bin",
    "S7_cont",
)


def result_to_csv_row(result: SignalResult) -> dict:
    return {
        "experiment": result.experiment,
        "stamp": result.stamp,
        "model": result.model,
        "num_turns": result.num_turns,
        "t0": result.t0,
        "L0": result.l0,
        "L0_ok": int(result.l0_ok),
        "skipped_turns": result.skipped_turns,
        "S1": f"{result.s1:.6f}",
        "S1_bin": result.s1_bin,
        "S2": f"{result.s2:.6f}",
        "S2_bin": result.s2_bin,
        "S3": f"{result.s3:.6f}",
        "S3_bin": result.s3_bin,
        "S4_cont": result.s4_cont,
        "S4_bin": result.s4_bin,
        "S5_cont": result.s5_cont,
        "S5_bin": result.s5_bin,
        "S6_cont": f"{result.s6_cont:.6f}",
        "S6_bin": result.s6_bin,
        "S7_cont": f"{result.s7_cont:.6f}",
    }


def write_signal_json(
    result: SignalResult, path, *, thresholds: Thresholds
) -> None:
    path.write_text(
        json.dumps(result_to_json(result, thresholds=thresholds), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
