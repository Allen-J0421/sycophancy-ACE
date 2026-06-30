#!/usr/bin/env python3
"""Driver for the 8-cell B+A prompt ablation on a single codebase.

Reads ``config/ablation_B_plus_A_core8.json`` (8 prompter system-prompt variants),
writes each cell's ``full_text`` to ``config/prompt_cells/<cellid>.txt``, then runs
each cell as an independent experiment -- coding agent ``gpt-5.5`` at effort ``high``,
10 iterations, Gemini prompter mode -- landing results in a per-codebase suite dir:

    output/prompt-expert/Algorithms/<codebase>/<cellid>-Agent/

Each cell only differs in the prompter's system prompt (passed via
``run_experiment.py --prompter-system-prompt-file``). Downstream ``refdiff`` and
``signals`` phases run per cell. Finally ``plot_prompt_groups.py`` renders the
8-way comparison charts (lines / signals / refdiff) into ``<suite>/plots/``.

Resumable: a cell's ``run_exp`` is skipped when its ``logs/*-log.csv`` already
exists (unless ``--force``); refdiff/signals are skipped when their outputs exist.

Usage:
    python run_prompt_expert.py [--only CELLID] [--phase run_exp,refdiff,signals,plot]
        [--codebase 001_binary_search] [--force] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PYTHON = sys.executable

_ABLATION_CONFIG = _SCRIPT_DIR / "config" / "ablation_B_plus_A_core8.json"
_PROMPT_CELLS_DIR = _SCRIPT_DIR / "config" / "prompt_cells"
_PLAN = _SCRIPT_DIR / "pipeline_plan.json"

DEFAULT_CODEBASE = "001_binary_search"
MODEL = "gpt-5.5"
EFFORT = "high"
ITERATIONS = 10
SUITE_ROOT = _SCRIPT_DIR / "output" / "prompt-expert" / "Algorithms"

PHASES = ("run_exp", "refdiff", "signals", "plot")


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_cells() -> list[dict]:
    data = json.loads(_ABLATION_CONFIG.read_text(encoding="utf-8"))
    cells = data.get("cells", [])
    if not cells:
        raise SystemExit(f"no cells found in {_ABLATION_CONFIG}")
    for cell in cells:
        if "id" not in cell or "full_text" not in cell:
            raise SystemExit(f"cell missing id/full_text: {cell}")
    return cells


def resolve_codebase(codebase: str) -> tuple[Path, str]:
    """Find target path + commit for ``codebase`` from pipeline_plan.json's algorithms list."""
    plan = json.loads(_PLAN.read_text(encoding="utf-8"))
    for entry in plan.get("algorithms", []):
        target = Path(entry["target"])
        if target.name == codebase:
            abs_target = (_SCRIPT_DIR / target).resolve() if not target.is_absolute() else target
            return abs_target, str(entry["commit"])
    raise SystemExit(f"codebase {codebase!r} not found in {_PLAN} algorithms list")


def write_prompt_cell_files(cells: list[dict]) -> dict[str, Path]:
    """Write each cell's full_text to config/prompt_cells/<id>.txt; return id -> path."""
    _PROMPT_CELLS_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for cell in cells:
        path = _PROMPT_CELLS_DIR / f"{cell['id']}.txt"
        path.write_text(cell["full_text"].rstrip() + "\n", encoding="utf-8")
        paths[cell["id"]] = path
    return paths


# ---------------------------------------------------------------------------
# Command building (mirrors run_pipeline.build_command shapes)
# ---------------------------------------------------------------------------

def exp_folder_for(cell_id: str) -> str:
    return f"{cell_id}-Agent"


def run_exp_cmd(target: Path, commit: str, suite_dir: Path, cell_id: str, prompt_file: Path) -> list[str]:
    return [
        _PYTHON, str(_SCRIPT_DIR / "run_experiment.py"),
        str(target), commit, str(ITERATIONS),
        "--model", MODEL,
        "--effort", EFFORT,
        "--prompter",
        "--prompter-system-prompt-file", str(prompt_file),
        "--output-base", str(suite_dir),
        "--exp-folder", exp_folder_for(cell_id),
    ]


def refdiff_cmd(target: Path, suite_dir: Path, cell_id: str) -> list[str]:
    return [
        _PYTHON, str(_SCRIPT_DIR / "run_refdiff.py"),
        "--repo", str(target),
        "--output-base", str(suite_dir),
        "--exp", exp_folder_for(cell_id),
    ]


def signals_cmd(suite_dir: Path, cell_id: str) -> list[str]:
    return [
        _PYTHON, str(_SCRIPT_DIR / "compute_signals.py"),
        "--result-dir", str(suite_dir),
        "--exp", exp_folder_for(cell_id),
    ]


def plot_cmd(suite_dir: Path) -> list[str]:
    return [
        _PYTHON, str(_SCRIPT_DIR / "plot_prompt_groups.py"),
        "--suite-dir", str(suite_dir),
    ]


# ---------------------------------------------------------------------------
# Resume guards
# ---------------------------------------------------------------------------

def has_log_csv(cell_dir: Path) -> bool:
    logs = cell_dir / "logs"
    return logs.is_dir() and any(logs.glob("*-log.csv"))


def has_refdiff(cell_dir: Path) -> bool:
    refdiff = cell_dir / "refdiff"
    return refdiff.is_dir() and any(refdiff.glob("*-refdiff.jsonl"))


def has_signals(cell_dir: Path) -> bool:
    signals = cell_dir / "signals"
    return signals.is_dir() and any(signals.glob("*-signals.json"))


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run(cmd: list[str], *, dry_run: bool) -> int:
    if dry_run:
        eprint("  [dry-run] " + " ".join(cmd))
        return 0
    eprint("  $ " + " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--codebase", default=DEFAULT_CODEBASE, help="Algorithm codebase name (default: 001_binary_search).")
    parser.add_argument("--only", default=None, help="Run only this cell id.")
    parser.add_argument("--phase", default=None, help="Comma list of phases to run (run_exp,refdiff,signals,plot). Default: all.")
    parser.add_argument("--force", action="store_true", help="Re-run steps even if outputs already exist.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing.")
    args = parser.parse_args(argv)

    phases = PHASES
    if args.phase:
        requested = [p.strip() for p in args.phase.split(",") if p.strip()]
        unknown = [p for p in requested if p not in PHASES]
        if unknown:
            eprint(f"error: unknown phase(s): {unknown}")
            return 2
        phases = tuple(p for p in PHASES if p in requested)

    cells = load_cells()
    if args.only:
        cells = [c for c in cells if c["id"] == args.only]
        if not cells:
            eprint(f"error: cell id {args.only!r} not found")
            return 2

    target, commit = resolve_codebase(args.codebase)
    if not args.dry_run and not target.exists():
        eprint(f"error: target codebase not found: {target}")
        return 2

    suite_dir = (SUITE_ROOT / args.codebase).resolve()
    prompt_files = write_prompt_cell_files(load_cells())  # always write all cell files

    eprint(f"[plan] codebase={args.codebase} target={target}")
    eprint(f"[plan] suite-dir={suite_dir}")
    eprint(f"[plan] {len(cells)} cell(s), phases={list(phases)}, model={MODEL} effort={EFFORT} iters={ITERATIONS}")

    failures = 0

    # Per-cell phases, cells sequential (provider-limit safe), config order preserved.
    for cell in cells:
        cell_id = cell["id"]
        cell_dir = suite_dir / exp_folder_for(cell_id)
        eprint(f"\n[cell] {cell_id}")

        if "run_exp" in phases:
            if not args.force and has_log_csv(cell_dir):
                eprint(f"  [skip] run_exp — {cell_dir.name}/logs/*-log.csv exists")
            else:
                rc = run(run_exp_cmd(target, commit, suite_dir, cell_id, prompt_files[cell_id]), dry_run=args.dry_run)
                if rc not in (0, 1):  # 1 = partial (CSV still written)
                    eprint(f"  [FAILED] run_exp {cell_id} (exit {rc})")
                    failures += 1
                    continue

        if "refdiff" in phases:
            if not args.force and has_refdiff(cell_dir):
                eprint(f"  [skip] refdiff — exists")
            else:
                rc = run(refdiff_cmd(target, suite_dir, cell_id), dry_run=args.dry_run)
                if rc != 0:
                    eprint(f"  [FAILED] refdiff {cell_id} (exit {rc})")
                    failures += 1

        if "signals" in phases:
            if not args.force and has_signals(cell_dir):
                eprint(f"  [skip] signals — exists")
            else:
                rc = run(signals_cmd(suite_dir, cell_id), dry_run=args.dry_run)
                if rc != 0:
                    eprint(f"  [FAILED] signals {cell_id} (exit {rc})")
                    failures += 1

    # Suite-wide comparison plots.
    if "plot" in phases:
        eprint("\n[plot] comparison charts")
        rc = run(plot_cmd(suite_dir), dry_run=args.dry_run)
        if rc != 0:
            eprint(f"  [FAILED] plot (exit {rc})")
            failures += 1

    eprint(f"\n[done] failures={failures} | suite-dir: {suite_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
