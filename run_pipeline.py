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
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
    no_snapshot: bool = False
    refdiff_lang: str | None = None
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
                    no_snapshot=bool(merged.get("no_snapshot", False)),
                    refdiff_lang=merged.get("refdiff_lang"),
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
        if t.no_snapshot:
            cmd += ["--no-snapshot"]
        return cmd
    if step.phase == "refdiff":
        cmd = [
            _PYTHON, str(_SCRIPT_DIR / "run_refdiff.py"),
            "--repo", str(t.target),
            "--output-base", base,
            "--exp", t.exp_folder,
        ]
        if t.refdiff_lang:
            cmd += ["--lang", t.refdiff_lang]
        return cmd
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
    # run_experiment.py: 0 ok, 1 partial (CSV still written), 2 setup error,
    # 3 provider-limit-blocked (a usage/session limit was hit; a .limit_block.json marker
    # was written). Treat 0/1 as done; 3 as "blocked" (not done → re-attempted, never
    # silently skipped); 2 and other nonzero as failed.
    if step.phase == "run_exp":
        if rc == 3:
            status = "blocked"
        elif rc in (0, 1):
            status = "done"
        else:
            status = "failed"
    else:
        status = "done" if rc == 0 else "failed"
    return (status, detail)


# ---------------------------------------------------------------------------
# Provider-limit auto-pause (run_exp scheduling)
# ---------------------------------------------------------------------------

_MARKER_FILENAME = ".limit_block.json"


@dataclass
class PauseConfig:
    """Orchestrator-side auto-pause settings (env/prompt.env defaults, CLI overrides)."""

    auto_pause: bool = True
    max_wait_min: int = 480
    poll_s: int = 60
    buffer_min: int = 2
    fixed_wait_min: int = 60
    cleanup: bool = True
    max_attempts: int = 5

    @property
    def max_wait_s(self) -> int:
        return self.max_wait_min * 60


def _read_prompt_env() -> dict[str, str]:
    """Minimal prompt.env reader (stdlib only) so the orchestrator avoids importing the
    heavy experiment_runner chain. Live env vars take precedence per key."""
    values: dict[str, str] = {}
    candidates = (
        Path.cwd() / "prompt.env",
        _SCRIPT_DIR / "config" / "prompt.env",
        _SCRIPT_DIR / "prompt.env",
    )
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'").strip()
            if key and val and key not in values:
                values[key] = val
        break
    return values


def _env_value(key: str, prompt_env: dict[str, str]) -> str | None:
    live = os.environ.get(key)
    if live and live.strip():
        return live.strip()
    return prompt_env.get(key)


def _env_bool(key: str, prompt_env: dict[str, str], *, default: bool) -> bool:
    raw = _env_value(key, prompt_env)
    if raw is None:
        return default
    norm = raw.strip().lower()
    if norm in {"1", "true", "yes", "on"}:
        return True
    if norm in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(key: str, prompt_env: dict[str, str], *, default: int) -> int:
    raw = _env_value(key, prompt_env)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def build_pause_config(args: argparse.Namespace) -> PauseConfig:
    pe = _read_prompt_env()
    auto_pause = _env_bool("LIMIT_AUTO_PAUSE", pe, default=True)
    if getattr(args, "no_auto_pause", False):
        auto_pause = False
    return PauseConfig(
        auto_pause=auto_pause,
        max_wait_min=args.max_wait_minutes
        if args.max_wait_minutes is not None
        else _env_int("LIMIT_MAX_WAIT_MINUTES", pe, default=480),
        poll_s=args.poll_interval_seconds
        if args.poll_interval_seconds is not None
        else _env_int("LIMIT_POLL_INTERVAL_SECONDS", pe, default=60),
        buffer_min=args.buffer_minutes
        if args.buffer_minutes is not None
        else _env_int("LIMIT_BUFFER_MINUTES", pe, default=2),
        fixed_wait_min=args.fixed_wait_minutes
        if args.fixed_wait_minutes is not None
        else _env_int("LIMIT_FIXED_WAIT_MINUTES", pe, default=60),
        cleanup=_env_bool("LIMIT_CLEANUP_DEAD_RUNS", pe, default=True),
    )


def step_providers(step: Step) -> set[str]:
    """Providers a run_exp step depends on: its coding-agent CLI plus Gemini in prompter mode."""
    provs = {_agent_for_model(step.model)} if step.model else set()
    if step.task.prompter:
        provs.add("gemini")
    return provs


def marker_path_for(task: Task) -> Path:
    return task.output_base / task.exp_folder / _MARKER_FILENAME


def read_limit_marker(task: Task) -> dict | None:
    path = marker_path_for(task)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def clear_limit_marker(task: Task) -> None:
    path = marker_path_for(task)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def clean_dead_run(marker: dict, *, cleanup: bool) -> None:
    """Delete the blocked run's partial CSV + artifacts dir so a fresh re-run starts clean
    and no zombie experiment is picked up by downstream globs."""
    if not cleanup:
        return
    for key in ("partial_csv", "artifacts_dir"):
        raw = marker.get(key)
        if not raw:
            continue
        path = Path(raw)
        try:
            if path.is_dir():
                shutil.rmtree(path)
                eprint(f"  [cleanup] removed {path}")
            elif path.is_file():
                path.unlink()
                eprint(f"  [cleanup] removed {path}")
        except OSError as exc:
            eprint(f"  [cleanup] could not remove {path}: {exc}")


def _block_until(marker: dict | None, cfg: PauseConfig) -> datetime:
    """When to retry: parsed reset + buffer, else now + fixed fallback wait."""
    reset_iso = (marker or {}).get("reset_dt_iso")
    if reset_iso:
        try:
            dt = datetime.fromisoformat(reset_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt + timedelta(minutes=cfg.buffer_min)
        except ValueError:
            pass
    return datetime.now(timezone.utc) + timedelta(minutes=cfg.fixed_wait_min)


def _sleep_until(target: datetime, *, poll_s: int) -> None:
    while True:
        now = datetime.now(timezone.utc)
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return
        chunk = min(poll_s, remaining)
        eprint(f"  [pause] sleeping {int(remaining // 60)}m{int(remaining % 60):02d}s "
               f"until {target.isoformat()} …")
        time.sleep(chunk)


def schedule_run_exp(
    run_exp_steps: list[Step],
    state: State,
    args: argparse.Namespace,
    counts: dict[str, int],
    cfg: PauseConfig,
) -> None:
    """Run all run_exp steps with provider-aware scheduling: while one provider is blocked,
    keep running steps for other providers; when only blocked work remains, sleep until the
    earliest reset (capped), then retry. Blocked runs are cleaned up and re-run fresh."""
    # Initial selection mirrors the simple loop (run_exp has no upstream dep).
    pending: list[Step] = []
    for step in run_exp_steps:
        prior = state.status(step.key)
        if args.retry_failed:
            if prior not in ("failed", "blocked"):
                counts["skipped"] += 1
                continue
        elif not args.force and prior == "done":
            counts["skipped"] += 1
            continue
        pending.append(step)

    blocked_until: dict[str, datetime] = {}
    attempts: dict[str, int] = {}

    while pending:
        now = datetime.now(timezone.utc)
        for prov in [p for p, until in blocked_until.items() if until <= now]:
            del blocked_until[prov]

        runnable = next(
            (s for s in pending if not (step_providers(s) & blocked_until.keys())),
            None,
        )
        if runnable is None:
            relevant = set().union(*(step_providers(s) for s in pending))
            blocks = [blocked_until[p] for p in relevant if p in blocked_until]
            if not blocks:
                break  # safety: nothing runnable and nothing blocked — avoid spin
            earliest = min(blocks)
            wait_s = (earliest - now).total_seconds()
            if wait_s > cfg.max_wait_s:
                eprint(f"  [pause] earliest reset {earliest.isoformat()} exceeds max wait "
                       f"{cfg.max_wait_min}min — leaving {len(pending)} run_exp step(s) blocked.")
                counts["blocked"] += len(pending)
                pending.clear()
                break
            eprint(f"  [pause] all remaining run_exp providers cooling down "
                   f"({sorted(relevant & blocked_until.keys())}); waiting for {earliest.isoformat()}.")
            _sleep_until(earliest, poll_s=cfg.poll_s)
            continue

        pending.remove(runnable)
        status, detail = run_step(runnable, dry_run=False)
        if status == "blocked":
            marker = read_limit_marker(runnable.task)
            provider = (marker or {}).get("provider") or (_agent_for_model(runnable.model) if runnable.model else "?")
            until = _block_until(marker, cfg)
            blocked_until[provider] = max(blocked_until.get(provider, until), until)
            attempts[runnable.key] = attempts.get(runnable.key, 0) + 1
            if marker is not None:
                clean_dead_run(marker, cleanup=cfg.cleanup)
                clear_limit_marker(runnable.task)
            state.set(runnable.key, "blocked", detail)
            if attempts[runnable.key] >= cfg.max_attempts:
                eprint(f"  [give-up] {runnable.key} hit a limit {attempts[runnable.key]}x — leaving blocked.")
                counts["blocked"] += 1
            else:
                eprint(f"  [blocked] {runnable.key} — {provider} limit; retry after "
                       f"{blocked_until[provider].isoformat()} (attempt {attempts[runnable.key]}).")
                pending.append(runnable)
        else:
            state.set(runnable.key, status, detail)
            counts[status if status in counts else "skipped"] += 1
            if status == "failed":
                eprint(f"  [FAILED] {runnable.key} ({detail}) — continuing")


def attempt_step(
    step: Step,
    state: State,
    args: argparse.Namespace,
    counts: dict[str, int],
) -> None:
    """Single-step selection + dep-guard + run (used for dry-run, downstream phases, and the
    no-auto-pause path). Mirrors the original main-loop body."""
    prior = state.status(step.key)
    if not args.dry_run:
        if args.retry_failed:
            if prior not in ("failed", "blocked"):
                counts["skipped"] += 1
                return
        elif not args.force and prior == "done":
            counts["skipped"] += 1
            return

    if not args.dry_run and not args.no_dep_check and not upstream_satisfied(step, state):
        up = PHASE_UPSTREAM.get(step.phase)
        eprint(f"  [skip] {step.key} — upstream '{up}' not done (use --no-dep-check to override)")
        counts["skipped"] += 1
        return

    status, detail = run_step(step, dry_run=args.dry_run)
    if not args.dry_run:
        state.set(step.key, status, detail)
    counts[status if status in counts else "skipped"] += 1
    if status == "failed":
        eprint(f"  [FAILED] {step.key} ({detail}) — continuing")


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
    parser.add_argument(
        "--no-auto-pause", action="store_true",
        help="Disable provider-limit auto-pause (run_exp scheduling). Blocked steps are still "
             "recorded as 'blocked' (not 'done'), but the pipeline does not wait/retry them.",
    )
    parser.add_argument("--max-wait-minutes", type=int, default=None,
                        help="Cap on how long to wait for a provider reset (default 480 / 8h).")
    parser.add_argument("--poll-interval-seconds", type=int, default=None,
                        help="Sleep granularity while waiting for a reset (default 60).")
    parser.add_argument("--buffer-minutes", type=int, default=None,
                        help="Extra minutes added after a parsed reset time (default 2).")
    parser.add_argument("--fixed-wait-minutes", type=int, default=None,
                        help="Wait used when a reset time can't be parsed (default 60).")
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

    pause_cfg = build_pause_config(args)
    counts = {"done": 0, "failed": 0, "skipped": 0, "blocked": 0}

    run_exp_steps = [s for s in ordered_steps if s.phase == "run_exp"]
    other_steps = [s for s in ordered_steps if s.phase != "run_exp"]
    use_scheduler = pause_cfg.auto_pause and not args.dry_run and bool(run_exp_steps)

    if use_scheduler:
        eprint("[plan] provider-limit auto-pause: ON "
               f"(max wait {pause_cfg.max_wait_min}min, buffer {pause_cfg.buffer_min}min)")
        schedule_run_exp(run_exp_steps, state, args, counts, pause_cfg)
        for step in other_steps:
            attempt_step(step, state, args, counts)
    else:
        if not pause_cfg.auto_pause and run_exp_steps and not args.dry_run:
            eprint("[plan] provider-limit auto-pause: OFF (--no-auto-pause)")
        for step in ordered_steps:
            attempt_step(step, state, args, counts)

    eprint(
        f"[done] done={counts['done']} failed={counts['failed']} "
        f"blocked={counts['blocked']} skipped={counts['skipped']} | state: {state.path}"
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
