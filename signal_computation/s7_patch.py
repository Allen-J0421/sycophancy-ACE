"""Patch S7 into existing signal outputs without recomputing S1-S6."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from experiment_runner.result_paths import signals_csv_path, signals_dir
from experiment_runner.util import eprint

from signal_computation.discovery import refdiff_jsonl_files
from signal_computation.jsonl_io import load_refdiff_records
from signal_computation.line_signals import lc_of
from signal_computation.s7_signals import S7Calculator, compute_s7, prefix_s7


def signals_json_path(exp_dir: Path, stamp: str) -> Path:
    return signals_dir(exp_dir) / f"{stamp}-signals.json"


def compute_s7_for_jsonl(
    jsonl_path: Path,
    exp_dir: Path,
    calculator: S7Calculator,
) -> tuple[float, list[dict]] | None:
    """Return (s7_cont, per-turn patch dicts) for one refdiff JSONL."""
    records = load_refdiff_records(jsonl_path)
    if not records:
        return None

    by_run = {int(r["run"]): r for r in records}
    runs = sorted(by_run)
    first = by_run[runs[0]]
    stamp = str(first.get("stamp") or jsonl_path.name.removesuffix("-refdiff.jsonl"))
    model = str(first.get("model") or "")
    lc_by_run = {t: lc_of(by_run[t]) for t in runs}

    flags = calculator.turn_flags(
        exp_dir=exp_dir,
        stamp=stamp,
        model=model,
        runs=runs,
        lc_by_run=lc_by_run,
        warn=eprint,
    )
    s7_cont = compute_s7(flags)

    turn_patches: list[dict] = []
    for idx, t in enumerate(runs):
        flag = flags[idx]
        turn_patches.append(
            {
                "run": t,
                "verbal_decline": flag.verbal_decline,
                "hypocritical_refusal": flag.hypocritical,
                "rolling_s7": prefix_s7(flags, idx),
            }
        )
    return s7_cont, turn_patches


def patch_signals_json(path: Path, s7_cont: float, turn_patches: list[dict]) -> bool:
    if not path.is_file():
        return False

    data = json.loads(path.read_text(encoding="utf-8"))
    signals = data.setdefault("signals", {})
    signals["S7"] = {"cont": s7_cont}

    patches_by_run = {p["run"]: p for p in turn_patches}
    for turn in data.get("turns") or []:
        run = int(turn.get("run", 0))
        patch = patches_by_run.get(run)
        if patch is None:
            continue
        sets = turn.setdefault("sets", {})
        sets["verbal_decline"] = [str(int(patch["verbal_decline"]))]
        sets["hypocritical_refusal"] = [str(int(patch["hypocritical_refusal"]))]
        rolling = turn.setdefault("rolling", {})
        rolling["S7"] = {"cont": patch["rolling_s7"]}

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def patch_signals_csv_row(csv_path: Path, stamp: str, s7_cont: float) -> bool:
    if not csv_path.is_file():
        return False

    rows: list[dict[str, str]] = []
    fieldnames: list[str] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "S7_cont" not in fieldnames:
        fieldnames.append("S7_cont")

    updated = False
    for row in rows:
        if row.get("stamp") == stamp:
            row["S7_cont"] = f"{s7_cont:.6f}"
            updated = True

    if not updated:
        return False

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return True


def patch_s7_for_experiment(exp_dir: Path, *, refusal_config: Path | None = None) -> int:
    """Patch S7 into existing signals JSON/CSV for one experiment. Returns count patched."""
    calculator = S7Calculator(refusal_config)
    jsonl_files = refdiff_jsonl_files(exp_dir)
    if not jsonl_files:
        return 0

    patched = 0
    s7_by_stamp: dict[str, float] = {}

    for jsonl_path in jsonl_files:
        result = compute_s7_for_jsonl(jsonl_path, exp_dir, calculator)
        if result is None:
            eprint(f"[skip] {jsonl_path.name}: no records")
            continue

        s7_cont, turn_patches = result
        stamp = jsonl_path.name.removesuffix("-refdiff.jsonl")
        s7_by_stamp[stamp] = s7_cont
        out_json = signals_json_path(exp_dir, stamp)

        if not patch_signals_json(out_json, s7_cont, turn_patches):
            eprint(f"[skip] {out_json.name}: signals JSON not found (run compute_signals.py first)")
            continue

        patched += 1
        eprint(f"[s7] {out_json.name}: S7={s7_cont:.6f}")

    csv_path = signals_csv_path(exp_dir)
    if csv_path.is_file():
        for stamp, s7_cont in s7_by_stamp.items():
            patch_signals_csv_row(csv_path, stamp, s7_cont)
        if s7_by_stamp:
            eprint(f"[s7] updated {csv_path.name}")

    return patched
