#!/usr/bin/env python3
"""Pre-flight sanity checker for pipeline_plan.json.

Run this right after editing the planner, before kicking off a long batch.
It validates everything required for the run to succeed and reports *all*
problems at once (per task), so you don't discover a bad path or missing tool
hours into a run.

Checks mirror the real setup-time failure points of each component:
  * run_exp   : git + agent CLI (claude/codex) on PATH; target inside a git
                repo; commit resolvable; AGENT_FIXED_PROMPT in prompt.env
                (unless --prompter, which needs GEMINI_API_KEY + PROMPTER_MODEL
                + an importable google-genai).
  * refdiff   : single-language Java or JS/JSX target (or refdiff_lang override for
                polyglot repos); a usable JDK (<= 23) for Gradle; the Gradle wrapper
                at refdiff-runner/gradlew.
  * plot_*    : matplotlib importable.

The planner is parsed with run_pipeline.load_plan so the checker and the
orchestrator interpret the plan identically (no duplicated parsing).

Usage:
    python check_plan.py [--plan FILE] [--only-category algorithms|realworld]
        [--task SUBSTR] [--strict]

Exit codes: 0 = no hard errors (warnings allowed), 1 = hard errors found,
2 = plan unreadable / invalid.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

# Import the plan model from the orchestrator (import-safe: stdlib only), so the
# checker and run_pipeline interpret the plan identically — no duplicated parsing.
import run_pipeline  # noqa: E402
from run_pipeline import CATEGORY_DIRS  # noqa: E402

# Refdiff requirements (replicated from run_refdiff.py — importing it would pull
# in the heavy experiment_runner package chain, which we deliberately avoid here).
_RUNNER_DIR = _SCRIPT_DIR / "refdiff-runner"
_GRADLEW = _RUNNER_DIR / "gradlew"
_DEFAULT_JAVA_HOME = Path("/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home")
_MAX_GRADLE_JAVA = 23

# Thinking/reasoning effort levels per agent CLI (replicated from
# experiment_runner.constants to keep this checker stdlib-only).
_CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
_CODEX_EFFORT_LEVELS = ("none", "low", "medium", "high", "xhigh")


# ---------------------------------------------------------------------------
# Finding model
# ---------------------------------------------------------------------------

@dataclass
class Findings:
    """Accumulated check results for one task (one experiment folder)."""
    label: str
    oks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        self.oks.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)


# ---------------------------------------------------------------------------
# Low-level probes
# ---------------------------------------------------------------------------

def agent_for_model(model: str) -> str:
    return "claude" if model.strip().lower().startswith("claude") else "codex"


def git_toplevel(target: Path) -> Path | None:
    cwd = target if target.is_dir() else target.parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd), capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return None


def commit_resolvable(repo_root: Path, commit: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"],
            cwd=str(repo_root), capture_output=True, text=True, check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0


def detect_repo_language(repo: Path) -> str | None:
    """Replicates run_refdiff.detect_repo_language: single language or None."""
    has_java = bool(next(repo.rglob("*.java"), None))
    has_js = bool(next(repo.rglob("*.js"), None)) or bool(next(repo.rglob("*.jsx"), None))
    if has_java and has_js:
        return None  # mixed
    if has_java:
        return "java"
    if has_js:
        return "js"
    return None  # none


def jdk_major_version(home: Path) -> int | None:
    """Best-effort JDK major version from <home>/release (mirrors run_refdiff)."""
    release = home / "release"
    if release.is_file():
        try:
            text = release.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        m = re.search(r'JAVA_VERSION="?(\d+)(?:\.(\d+))?', text)
        if m:
            major = int(m.group(1))
            if major == 1 and m.group(2):
                return int(m.group(2))
            return major
    return None


def resolve_java_home() -> tuple[Path | None, int | None, str]:
    """Return (chosen_home, major, note). Mirrors run_refdiff.java_home selection:
    prefer $JAVA_HOME, fall back to the bundled default, accept first with major<=23.
    """
    env_home = os.environ.get("JAVA_HOME", "").strip()
    candidates: list[Path] = []
    if env_home:
        candidates.append(Path(env_home))
    if _DEFAULT_JAVA_HOME not in candidates:
        candidates.append(_DEFAULT_JAVA_HOME)
    for home in candidates:
        if not home.is_dir():
            continue
        major = jdk_major_version(home)
        if major is None:
            continue
        if major > _MAX_GRADLE_JAVA:
            continue
        if env_home and Path(env_home) == home:
            note = ""  # using JAVA_HOME as-is
        elif env_home:
            note = " (JAVA_HOME unusable — falling back to bundled openjdk@21)"
        else:
            note = " (JAVA_HOME unset — using bundled openjdk@21)"
        return home, major, note
    return None, None, ""


def module_available(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# prompt.env / .env loading (read-only, no os.environ mutation)
# ---------------------------------------------------------------------------

def _parse_env_line(raw: str) -> tuple[str, str] | None:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip().strip('"').strip("'").strip()


def _read_env_file_values(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(raw)
            if parsed and parsed[1]:
                out.setdefault(parsed[0], parsed[1])
    except OSError:
        pass
    return out


def prompt_env_value(key: str) -> str | None:
    """Resolve KEY the way env.py does: live env var, else prompt.env (cwd/script)."""
    val = os.environ.get(key)
    if val and val.strip():
        return val.strip()
    for path in (Path.cwd() / "prompt.env", _SCRIPT_DIR / "config" / "prompt.env", _SCRIPT_DIR / "prompt.env"):
        vals = _read_env_file_values(path)
        if key in vals:
            return vals[key]
    return None


def dotenv_value(key: str) -> str | None:
    """Resolve KEY from live env, else .env (cwd/script) — for GEMINI_API_KEY etc."""
    val = os.environ.get(key)
    if val and val.strip():
        return val.strip()
    for path in (Path.cwd() / ".env", _SCRIPT_DIR / "config" / ".env", _SCRIPT_DIR / ".env"):
        vals = _read_env_file_values(path)
        if key in vals:
            return vals[key]
    return None


# ---------------------------------------------------------------------------
# Per-task checks
# ---------------------------------------------------------------------------

def check_task(task: "run_pipeline.Task") -> Findings:
    f = Findings(label=run_pipeline._task_state_prefix(task))
    phases = set(task.phases)

    # --- target + git repo + commit ---------------------------------------
    target = task.target
    if not target.exists():
        f.error(f"target not found: {target}")
        repo_root = None
    else:
        f.ok(f"target exists: {target}")
        repo_root = git_toplevel(target)
        if repo_root is None:
            f.error(f"target is not inside a git repository: {target}")
        else:
            f.ok(f"git repo: {repo_root}")
            if commit_resolvable(repo_root, task.commit):
                f.ok(f"commit resolvable: {task.commit}")
            else:
                f.error(f"commit not resolvable in {repo_root.name}: {task.commit}")

    # --- run_exp deps ------------------------------------------------------
    if "run_exp" in phases:
        if not task.models:
            f.error("run_exp requested but 'models' is empty")
        if shutil.which("git") is None:
            f.error("`git` not found on PATH (required by run_exp)")
        # Agent CLIs needed, deduped across the task's models.
        agents = sorted({agent_for_model(m) for m in task.models})
        for agent in agents:
            users = [m for m in task.models if agent_for_model(m) == agent]
            if shutil.which(agent) is None:
                f.error(f"`{agent}` CLI not on PATH — needed by model(s): {', '.join(users)}")
            else:
                f.ok(f"`{agent}` CLI available (for {', '.join(users)})")

        # Effort levels must be valid for their CLI; warn if set with no matching model.
        for label, value, levels in (
            ("effort_claude", task.effort_claude, _CLAUDE_EFFORT_LEVELS),
            ("effort_codex", task.effort_codex, _CODEX_EFFORT_LEVELS),
        ):
            if value is None:
                continue
            agent = "claude" if label == "effort_claude" else "codex"
            if value not in levels:
                f.error(f"{label} {value!r} invalid; choose one of: {', '.join(levels)}")
            elif agent not in agents:
                f.warn(f"{label}={value} set but no {agent} model in this task")
            else:
                f.ok(f"{label}={value}")

        if task.prompter:
            if dotenv_value("GEMINI_API_KEY"):
                f.ok("GEMINI_API_KEY present (prompter)")
            else:
                f.error("--prompter set but GEMINI_API_KEY missing (.env / env)")
            if prompt_env_value("PROMPTER_MODEL") or dotenv_value("PROMPTER_MODEL"):
                f.ok("PROMPTER_MODEL present (prompter)")
            else:
                f.error("--prompter set but PROMPTER_MODEL missing (prompt.env / .env / env)")
            if module_available("google.genai"):
                f.ok("google-genai importable (prompter)")
            else:
                f.error("--prompter set but `google-genai` not importable (pip install -r requirements-prompter.txt)")
        else:
            if prompt_env_value("AGENT_FIXED_PROMPT"):
                f.ok("AGENT_FIXED_PROMPT present (prompt.env)")
            else:
                f.error("AGENT_FIXED_PROMPT missing — set it in prompt.env (or use prompter: true)")

    # --- refdiff deps ------------------------------------------------------
    if "refdiff" in phases:
        if target.exists():
            if task.refdiff_lang:
                if task.refdiff_lang not in ("java", "js"):
                    f.error(f"refdiff_lang {task.refdiff_lang!r} invalid; must be java or js")
                else:
                    f.ok(f"refdiff language: {task.refdiff_lang} (refdiff_lang override)")
            else:
                lang = detect_repo_language(target)
                if lang is None:
                    has_java = bool(next(target.rglob("*.java"), None))
                    has_js = bool(next(target.rglob("*.js"), None)) or bool(next(target.rglob("*.jsx"), None))
                    if has_java and has_js:
                        f.error(
                            "refdiff: target has both .java and .js/.jsx — "
                            "set refdiff_lang to java or js in pipeline_plan.json"
                        )
                    else:
                        f.error("refdiff: target has no .java/.js/.jsx source files")
                else:
                    f.ok(f"refdiff language: {lang}")
        home, major, note = resolve_java_home()
        if home is None:
            f.error(f"refdiff: no usable JDK (<= {_MAX_GRADLE_JAVA}) found; set JAVA_HOME to e.g. {_DEFAULT_JAVA_HOME}")
        else:
            f.ok(f"refdiff JDK: {home} (Java {major}){note}")
        if _GRADLEW.is_file():
            f.ok(f"refdiff Gradle wrapper present: {_GRADLEW.name}")
        else:
            f.error(f"refdiff: Gradle wrapper not found at {_GRADLEW}")

    # --- plot deps ---------------------------------------------------------
    if {"plot_lines", "plot_refdiff", "plot_signals", "plot_reasoning_groups"} & set(phases):
        if module_available("matplotlib"):
            f.ok("matplotlib importable (plots)")
        else:
            f.error("plot phase requested but `matplotlib` not importable")
    if {"plot_lines", "plot_reasoning_groups"} & set(phases):
        if module_available("pandas"):
            f.ok("pandas importable (plot_lines / plot_reasoning_groups)")
        else:
            f.error("plot phase requested but `pandas` not importable")

    return f


def run_checks(tasks: list["run_pipeline.Task"], *, strict: bool = False) -> tuple[int, int, list[Findings]]:
    """Check all tasks. Returns (n_errors, n_warnings, findings).

    With strict=True, warnings are counted as errors for the exit decision.
    Also flags duplicate experiment-folder collisions across tasks (warning).
    """
    findings = [check_task(t) for t in tasks]

    # Suite summary for reasoning_test plans.
    suites: dict[tuple[str, str], list[str]] = {}
    for task in tasks:
        if task.category == "reasoning_test" and task.suite:
            key = (task.suite, str(task.output_base))
            suites.setdefault(key, []).append(task.exp_folder)
    for (suite, _base), folders in sorted(suites.items()):
        codex = sum(1 for t in tasks if t.suite == suite and t.effort_codex)
        claude = sum(1 for t in tasks if t.suite == suite and t.effort_claude)
        print(
            f"[reasoning_test] {suite}: {len(folders)} cells "
            f"({codex} codex + {claude} claude)",
            file=sys.stderr,
        )

    # Duplicate experiment-folder collision detection (would overwrite outputs).
    seen: dict[str, int] = {}
    for fnd in findings:
        seen[fnd.label] = seen.get(fnd.label, 0) + 1
    for fnd in findings:
        if seen[fnd.label] > 1:
            fnd.warn("duplicate experiment folder — multiple tasks resolve to this path and will overwrite each other")

    n_err = sum(len(f.errors) for f in findings)
    n_warn = sum(len(f.warnings) for f in findings)
    effective_err = n_err + (n_warn if strict else 0)
    return effective_err, n_warn, findings


def print_report(findings: list[Findings], n_err: int, n_warn: int) -> None:
    for f in findings:
        print(f"\n=== {f.label} ===")
        for msg in f.oks:
            print(f"  ✓ {msg}")
        for msg in f.warnings:
            print(f"  ⚠ {msg}")
        for msg in f.errors:
            print(f"  ✗ {msg}")
    print(
        f"\n{'-' * 60}\n"
        f"{len(findings)} task(s) | {n_err} error(s) | {n_warn} warning(s)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, default=_SCRIPT_DIR / "pipeline_plan.json", help="Planner JSON file.")
    parser.add_argument("--output-root", type=Path, default=_SCRIPT_DIR / "output", help="Root for output/ tree.")
    parser.add_argument("--only-category", choices=["algorithms", "realworld", "reasoning_test"], default=None)
    parser.add_argument("--task", default=None, help="Only tasks whose target path / exp folder contains this substring.")
    parser.add_argument("--strict", action="store_true", help="Promote warnings to errors for the exit code.")
    args = parser.parse_args(argv)

    try:
        # FileNotFoundError/OSError (unreadable), ValueError (bad fields / JSON;
        # json.JSONDecodeError subclasses ValueError) all surface as exit 2.
        tasks = run_pipeline.load_plan(args.plan.resolve(), args.output_root.resolve())
    except (OSError, ValueError) as exc:
        print(f"error: cannot read plan: {exc}", file=sys.stderr)
        return 2

    if args.only_category:
        tasks = [t for t in tasks if t.category == args.only_category]
    if args.task:
        tasks = [t for t in tasks if args.task in str(t.target) or args.task in t.exp_folder]
    if not tasks:
        print("error: no tasks matched the selection.", file=sys.stderr)
        return 2

    n_err, n_warn, findings = run_checks(tasks, strict=args.strict)
    print_report(findings, n_err, n_warn)
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
