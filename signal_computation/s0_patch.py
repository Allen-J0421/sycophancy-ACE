"""Patch S0 into existing signal outputs without recomputing S1-S7."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from experiment_runner.result_paths import signals_csv_path, signals_dir
from experiment_runner.util import eprint

from signal_computation.discovery import refdiff_jsonl_files
from signal_computation.jsonl_io import load_refdiff_records
from signal_computation.line_signals import compute_s0, compute_s0_prefix, lc_of


def signals_json_path(exp_dir: Path, stamp: str) -> Path:
    return signals_dir(exp_dir) / f"{stamp}-signals.json"


def compute_s0_for_jsonl(jsonl_path: Path) -> tuple[int, bool, list[dict]] | None:
    """Return (s0_cont, never_stopped, per-turn patch dicts) for one refdiff JSONL."""
    records = load_refdiff_records(jsonl_path)
    if not records:
        return None

    by_run = {int(r["run"]): r for r in records}
    runs = sorted(by_run)
    num_turns = runs[-1]
    lc_by_run = {t: lc_of(by_run[t]) for t in runs}
    s0_cont, never_stopped = compute_s0(runs, lc_by_run)

    turn_patches: list[dict] = []
    for idx, t in enumerate(runs):
        prefix_runs = runs[: idx + 1]
        r_s0, r_never = compute_s0_prefix(prefix_runs, lc_by_run, t, num_turns)
        turn_patches.append(
            {
                "run": t,
                "rolling_s0": r_s0,
                "rolling_never_stopped": r_never,
            }
        )
    return s0_cont, never_stopped, turn_patches


def patch_signals_json(
    path: Path,
    s0_cont: int,
    never_stopped: bool,
    turn_patches: list[dict],
) -> bool:
    if not path.is_file():
        return False

    data = json.loads(path.read_text(encoding="utf-8"))
    signals = data.setdefault("signals", {})
    signals["S0"] = {"cont": s0_cont, "never_stopped": never_stopped}

    patches_by_run = {p["run"]: p for p in turn_patches}
    for turn in data.get("turns") or []:
        run = int(turn.get("run", 0))
        patch = patches_by_run.get(run)
        if patch is None:
            continue
        rolling = turn.setdefault("rolling", {})
        rolling["S0"] = {
            "cont": patch["rolling_s0"],
            "never_stopped": patch["rolling_never_stopped"],
        }

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def patch_signals_csv_row(
    csv_path: Path,
    stamp: str,
    s0_cont: int,
    never_stopped: bool,
) -> bool:
    if not csv_path.is_file():
        return False

    rows: list[dict[str, str]] = []
    fieldnames: list[str] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for col in ("S0", "S0_never_stopped"):
        if col not in fieldnames:
            fieldnames.append(col)

    updated = False
    for row in rows:
        if row.get("stamp") == stamp:
            row["S0"] = str(s0_cont)
            row["S0_never_stopped"] = str(int(never_stopped))
            updated = True

    if not updated:
        return False

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return True


def patch_s0_for_experiment(exp_dir: Path) -> int:
    """Patch S0 into existing signals JSON/CSV for one experiment. Returns count patched."""
    jsonl_files = refdiff_jsonl_files(exp_dir)
    if not jsonl_files:
        return 0

    patched = 0
    s0_by_stamp: dict[str, tuple[int, bool]] = {}

    for jsonl_path in jsonl_files:
        result = compute_s0_for_jsonl(jsonl_path)
        if result is None:
            eprint(f"[skip] {jsonl_path.name}: no records")
            continue

        s0_cont, never_stopped, turn_patches = result
        stamp = jsonl_path.name.removesuffix("-refdiff.jsonl")
        s0_by_stamp[stamp] = (s0_cont, never_stopped)
        out_json = signals_json_path(exp_dir, stamp)

        if not patch_signals_json(out_json, s0_cont, never_stopped, turn_patches):
            eprint(
                f"[skip] {out_json.name}: signals JSON not found (run compute_signals.py first)"
            )
            continue

        patched += 1
        cens = " (never stopped)" if never_stopped else ""
        eprint(f"[s0] {out_json.name}: S0={s0_cont}{cens}")

    csv_path = signals_csv_path(exp_dir)
    if csv_path.is_file():
        for stamp, (s0_cont, never_stopped) in s0_by_stamp.items():
            patch_signals_csv_row(csv_path, stamp, s0_cont, never_stopped)
        if s0_by_stamp:
            eprint(f"[s0] updated {csv_path.name}")

    return patched
