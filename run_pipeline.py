#!/usr/bin/env python3
"""Robust long-running pipeline orchestrator.

Reads an editable JSON planner (``pipeline_plan.json``) describing a batch of
codebases, models, iterations, and phases, then drives the existing pipeline
components to completion. Outputs land under a separate ``output/`` tree split
into ``Algorithms/`` and ``RealWorld/`` (one folder per group in the planner).

Phase-first execution is the core model: run one phase across the whole plan
(e.g. all ``run_exp``, later all ``refdiff``), or omit ``--phase`` to run the
full canonical chain per experiment. Every invocation is independent and
resumable -- a shared state file (``output/.pipeline_state.json``) records which
steps are ``done``/``failed`` so restarts skip finished work.

The orchestrator is pure glue: it shells out to the existing entry points
(run_experiment.py, run_refdiff.py, compute_signals.py, plot_*.py,
dashboard/build.py), each with the right ``--output-base`` / ``--result-dir``.

Usage:
    python run_pipeline.py [--plan FILE] [--phase run_exp,refdiff,...]
        [--only-category algorithms|realworld] [--task NAME]
        [--force] [--retry-failed] [--no-dep-check] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_PLAN = _SCRIPT_DIR / "pipeline_plan.json"
_DEFAULT_OUTPUT = _SCRIPT_DIR / "output"
_STATE_FILENAME = ".pipeline_state.json"
_PYTHON = sys.executable

# Canonical phase order. The orchestrator always runs phases in this order,
# regardless of how they are written in the planner or passed via --phase.
CANONICAL_PHASES = ["run_exp", "plot_lines", "refdiff", "plot_refdiff", "signals", "plot_signals", "dashboard"]

# Upstream dependency for the soft dep-check: a phase should only run once the
# named upstream phase is `done` for the same experiment. run_exp has no upstream.
PHASE_UPSTREAM = {
    "run_exp": None,
    "plot_lines": "run_exp",
    "refdiff": "run_exp",
    "plot_refdiff": "refdiff",
    "signals": "refdiff",
    "plot_signals": "signals",
    "dashboard": "run_exp",
}

# Map planner group key -> output subdirectory name.
CATEGORY_DIRS = {"algorithms": "Algorithms", "realworld": "RealWorld"}


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Experiment-folder naming (mirrors experiment_runner/config.py:163-167)
# ---------------------------------------------------------------------------

import re  # noqa: E402


def _sanitize_slug(s: str, max_len: int = 64) -> str:
    """Replicates experiment_runner.util.sanitize_slug for label/folder names."""
    t = (s or "").strip().replace("\\", "-").replace("/", "-").replace(" ", "_")
    t = re.sub(r"[^a-zA-Z0-9._-]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-_.")
    return (t or "default")[:max_len]


def git_root_name(target: Path) -> str:
    """Repo-root folder name for `target` (the experiment folder is named after it).

    Matches TargetScope.repo_name, which uses the git toplevel, not the target path.
    Falls back to the target's own name if `target` is not inside a git repo.
    """
    cwd = target if target.is_dir() else target.parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).name or "target"
    except OSError:
        pass
    return (target.name or "target")


def experiment_folder_name(target: Path, label: str | None, prompter: bool) -> str:
    """Compute result/<exp> folder name exactly as build_experiment_config does."""
    name = git_root_name(target)
    label_slug = _sanitize_slug(label) if label else None
    if label_slug:
        name = f"{name}-{label_slug}"
    if prompter:
        name = f"{name}-Agent"  # PROMPTER_SUFFIX
    return name


# ---------------------------------------------------------------------------
# Planner parsing
# ---------------------------------------------------------------------------

@dataclass
class Task:
    category: str            # "algorithms" | "realworld"
    output_base: Path        # output/Algorithms | output/RealWorld
    target: Path
    commit: str
    models: list[str]
    iterations: int
    phases: list[str]
    prompter: bool
    label: str | None
    effort_codex: str | None = None
    effort_claude: str | None = None
    exp_folder: str = field(default="")

    def __post_init__(self) -> None:
        if not self.exp_folder:
            self.exp_folder = experiment_folder_name(self.target, self.label, self.prompter)


def _merge_defaults(defaults: dict, task: dict) -> dict:
    merged = dict(defaults)
    merged.update(task)
    return merged


def load_plan(plan_path: Path, output_root: Path) -> list[Task]:
    if not plan_path.is_file():
        raise FileNotFoundError(f"planner file not found: {plan_path}")
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    tasks: list[Task] = []
    for category in ("algorithms", "realworld"):
        for raw in data.get(category, []):
            merged = _merge_defaults(defaults, raw)
            if "target" not in merged or "commit" not in merged:
                raise ValueError(f"task in '{category}' missing target/commit: {raw}")
            phases = merged.get("phases", CANONICAL_PHASES)
            unknown = [p for p in phases if p not in CANONICAL_PHASES]
            if unknown:
                raise ValueError(f"unknown phase(s) {unknown} in task {merged['target']}")
            tasks.append(
                Task(
                    category=category,
                    output_base=(output_root / CATEGORY_DIRS[category]).resolve(),
                    target=Path(merged["target"]),
                    commit=str(merged["commit"]),
                    models=list(merged.get("models", [])),
                    iterations=int(merged.get("iterations", 10)),
                    phases=[p for p in CANONICAL_PHASES if p in phases],  # canonical order
                    prompter=bool(merged.get("prompter", False)),
                    label=merged.get("label"),
                    effort_codex=merged.get("effort_codex"),
                    effort_claude=merged.get("effort_claude"),
                )
            )
    return tasks


# ---------------------------------------------------------------------------
# State (resume)
# ---------------------------------------------------------------------------

class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, dict] = {}
        if path.is_file():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def status(self, key: str) -> str | None:
        entry = self.data.get(key)
        return entry.get("status") if entry else None

    def is_done(self, key: str) -> bool:
        return self.status(key) == "done"

    def set(self, key: str, status: str, detail: str = "") -> None:
        self.data[key] = {"status": status, "ts": utc_now(), "detail": detail}
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Step model + command building
# ---------------------------------------------------------------------------

@dataclass
class Step:
    key: str
    task: Task
    phase: str
    model: str | None  # only run_exp is per-model


def step_key(task: Task, phase: str, model: str | None) -> str:
    base = f"{CATEGORY_DIRS[task.category]}/{task.exp_folder}::{phase}"
    return f"{base}::{model}" if model else base


def build_steps(task: Task, phases_filter: set[str] | None) -> list[Step]:
    steps: list[Step] = []
    for phase in task.phases:
        if phases_filter is not None and phase not in phases_filter:
            continue
        if phase == "run_exp":
            for model in task.models:
                steps.append(Step(step_key(task, phase, model), task, phase, model))
        else:
            steps.append(Step(step_key(task, phase, None), task, phase, None))
    return steps


def _agent_for_model(model: str) -> str:
    """Mirror of run_experiment's CLI inference (claude-* → Claude, else Codex)."""
    return "claude" if model.strip().lower().startswith("claude") else "codex"


def build_command(step: Step) -> list[str]:
    t = step.task
    base = str(t.output_base)
    if step.phase == "run_exp":
        cmd = [
            _PYTHON, str(_SCRIPT_DIR / "run_experiment.py"),
            str(t.target), t.commit, str(t.iterations),
            "--model", step.model,
            "--output-base", base,
        ]
        effort = t.effort_claude if _agent_for_model(step.model) == "claude" else t.effort_codex
        if effort:
            cmd += ["--effort", effort]
        if t.label:
            cmd += ["--label", t.label]
        if t.prompter:
            cmd += ["--prompter"]
        return cmd
    if step.phase == "refdiff":
        return [
            _PYTHON, str(_SCRIPT_DIR / "run_refdiff.py"),
            "--repo", str(t.target),
            "--output-base", base,
        ]
    if step.phase == "plot_lines":
        return [_PYTHON, str(_SCRIPT_DIR / "plot_lines.py"), "--output-base", base]
    if step.phase == "plot_refdiff":
        return [_PYTHON, str(_SCRIPT_DIR / "plot_refdiff.py"), "--output-base", base]
    if step.phase == "signals":
        return [
            _PYTHON, str(_SCRIPT_DIR / "compute_signals.py"),
            "--result-dir", base,
            "--exp", t.exp_folder,
        ]
    if step.phase == "plot_signals":
        return [_PYTHON, str(_SCRIPT_DIR / "plot_signals.py"), "--output-base", base]
    if step.phase == "dashboard":
        return [
            _PYTHON, str(_SCRIPT_DIR / "dashboard" / "build.py"),
            "--exp", t.exp_folder,
            "--result-dir", base,
        ]
    raise ValueError(f"unknown phase: {step.phase}")


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

def upstream_satisfied(step: Step, state: State) -> bool:
    """True if the step's upstream phase is `done` for this experiment.

    For run_exp gating (upstream of refdiff/dashboard), require that at least one
    run_exp model step for the experiment is done.
    """
    upstream = PHASE_UPSTREAM.get(step.phase)
    if upstream is None:
        return True
    if upstream == "run_exp":
        prefix = f"{CATEGORY_DIRS[step.task.category]}/{step.task.exp_folder}::run_exp::"
        return any(k.startswith(prefix) and v.get("status") == "done" for k, v in state.data.items())
    return state.is_done(step_key(step.task, upstream, None))


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_step(step: Step, *, dry_run: bool) -> tuple[str, str]:
    """Returns (status, detail). status in {done, failed, skipped}."""
    t = step.task
    cmd = build_command(step)
    if dry_run:
        eprint("  [dry-run] " + " ".join(cmd))
        return ("skipped", "dry-run")

    log_dir = t.output_base / t.exp_folder / "pipeline-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{utc_now()}-{step.phase}{('-' + step.model) if step.model else ''}.log"

    eprint(f"  -> {step.key}")
    try:
        with log_path.open("w", encoding="utf-8") as fh:
            fh.write("$ " + " ".join(cmd) + "\n\n")
            fh.flush()
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    except OSError as exc:
        return ("failed", f"spawn error: {exc}")

    rc = proc.returncode
    detail = f"exit={rc} log={log_path.name}"
    # run_experiment.py: 0 ok, 1 partial (CSV still written), 2 setup error.
    # Treat 0 and 1 as "done enough to proceed"; 2 (and other nonzero) as failed.
    if step.phase == "run_exp":
        status = "done" if rc in (0, 1) else "failed"
    else:
        status = "done" if rc == 0 else "failed"
    return (status, detail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, default=_DEFAULT_PLAN, help="Planner JSON file.")
    parser.add_argument("--output-root", type=Path, default=_DEFAULT_OUTPUT, help="Root for output/ tree.")
    parser.add_argument(
        "--phase", default=None,
        help="Run only these phases across the whole plan (comma list). "
             "Omit to run the full canonical chain per experiment.",
    )
    parser.add_argument("--only-category", choices=["algorithms", "realworld"], default=None)
    parser.add_argument("--task", default=None, help="Run only tasks whose target path or exp folder matches this substring.")
    parser.add_argument("--force", action="store_true", help="Re-run steps even if already done.")
    parser.add_argument("--retry-failed", action="store_true", help="Re-run only steps marked failed.")
    parser.add_argument("--no-dep-check", action="store_true", help="Skip the upstream dependency guard.")
    parser.add_argument(
        "--check", dest="check", action="store_true", default=None,
        help="Run the plan sanity checker before executing (this is the default for live runs).",
    )
    parser.add_argument(
        "--no-check", dest="check", action="store_false",
        help="Skip the pre-flight sanity check.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the ordered command plan; do not execute.")
    args = parser.parse_args(argv)

    output_root = args.output_root.resolve()
    try:
        tasks = load_plan(args.plan.resolve(), output_root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        eprint(f"error: {exc}")
        return 2

    if args.only_category:
        tasks = [t for t in tasks if t.category == args.only_category]
    if args.task:
        needle = args.task
        tasks = [t for t in tasks if needle in str(t.target) or needle in t.exp_folder]
    if not tasks:
        eprint("error: no tasks matched the selection.")
        return 2

    # Pre-flight sanity check. Default: run it for live runs; skip on dry-run
    # (executes nothing) or when explicitly disabled with --no-check. A hard
    # error aborts unless --force is given.
    run_check = args.check if args.check is not None else (not args.dry_run)
    if run_check and not args.dry_run:
        try:
            import check_plan
        except ImportError as exc:
            eprint(f"[check] could not import check_plan ({exc}); use --no-check to skip.")
            return 2
        n_err, n_warn, findings = check_plan.run_checks(tasks, strict=False)
        check_plan.print_report(findings, n_err, n_warn)
        if n_err:
            if args.force:
                eprint(f"[check] {n_err} error(s) — proceeding anyway because --force was given.")
            else:
                eprint(f"[check] {n_err} error(s) — aborting. Fix the plan, or pass --no-check / --force.")
                return 2

    phases_filter: set[str] | None = None
    if args.phase:
        requested = [p.strip() for p in args.phase.split(",") if p.strip()]
        unknown = [p for p in requested if p not in CANONICAL_PHASES]
        if unknown:
            eprint(f"error: unknown --phase value(s): {unknown}")
            return 2
        phases_filter = set(requested)

    state = State(output_root / _STATE_FILENAME)

    # Build the full ordered step list (canonical phase order, tasks in plan order).
    ordered_steps: list[Step] = []
    for phase in CANONICAL_PHASES:
        if phases_filter is not None and phase not in phases_filter:
            continue
        for task in tasks:
            for step in build_steps(task, {phase}):
                ordered_steps.append(step)

    eprint(f"[plan] {len(tasks)} task(s), {len(ordered_steps)} step(s); output root: {output_root}")
    if phases_filter:
        eprint(f"[plan] phase filter: {sorted(phases_filter)}")

    counts = {"done": 0, "failed": 0, "skipped": 0}
    for step in ordered_steps:
        prior = state.status(step.key)

        # Selection of which steps to (re-)run:
        #   --retry-failed : only previously-failed steps.
        #   --force        : everything, regardless of prior state.
        #   default        : skip steps already done; (re)attempt pending/failed.
        if not args.dry_run:
            if args.retry_failed:
                if prior != "failed":
                    counts["skipped"] += 1
                    continue
            elif not args.force and prior == "done":
                counts["skipped"] += 1
                continue

        # In dry-run we show the full command plan, so skip the dep guard
        # (no steps are ever marked done during a dry-run).
        if not args.dry_run and not args.no_dep_check and not upstream_satisfied(step, state):
            up = PHASE_UPSTREAM.get(step.phase)
            eprint(f"  [skip] {step.key} — upstream '{up}' not done (use --no-dep-check to override)")
            counts["skipped"] += 1
            continue

        status, detail = run_step(step, dry_run=args.dry_run)
        if not args.dry_run:
            state.set(step.key, status, detail)
        counts[status if status in counts else "skipped"] += 1
        if status == "failed":
            eprint(f"  [FAILED] {step.key} ({detail}) — continuing")

    eprint(
        f"[done] done={counts['done']} failed={counts['failed']} skipped={counts['skipped']} "
        f"| state: {state.path}"
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
