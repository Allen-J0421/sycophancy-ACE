"""CLI parsing and experiment configuration."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from experiment_runner.claude_agent import ClaudeAgent
from experiment_runner.codex_agent import CodexAgent
from experiment_runner.coding_agent import CodingAgent
from experiment_runner.constants import (
    DEFAULT_TIMEOUT,
    PROMPTER_SUFFIX,
    effort_levels_for_agent,
)
from experiment_runner.env import load_clarification_patterns, load_prompter_config, load_prompt
from experiment_runner.git_repo import find_git_root
from experiment_runner.models import AgentKind, CliArgs, ExperimentConfig, TargetScope
from experiment_runner.result_paths import artifacts_dir, log_csv_path
from experiment_runner.prompt_source import FixedPromptSource, GeminiPromptSource, PromptSource
from experiment_runner.util import (
    eprint,
    non_empty_string,
    resolve_label_slug,
    resolve_model_info,
    sanitize_slug,
    script_dir,
    utc_stamp,
)


def infer_agent_from_model(model: str) -> AgentKind:
    """Choose Codex vs Claude CLI from ``--model`` (e.g. ``claude-*`` → Claude)."""
    if model.strip().lower().startswith("claude"):
        return "claude"
    return "codex"


def resolve_existing_path(target: Path) -> Path:
    target_path = target.expanduser().resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"target does not exist: {target_path}")
    return target_path


def target_pathspec(repo_root: Path, target_path: Path) -> tuple[str, list[str] | None]:
    if target_path.is_dir() and target_path == repo_root:
        return "", None

    rel_path = str(target_path.relative_to(repo_root))
    return rel_path, [rel_path]


def work_dir_for_target(target_path: Path) -> Path:
    if target_path.is_dir():
        return target_path
    return target_path.parent


def resolve_target_scope(target: Path) -> TargetScope:
    target_path = resolve_existing_path(target)
    repo_root = find_git_root(target_path)
    rel_path, pathspec = target_pathspec(repo_root, target_path)
    return TargetScope(
        root=repo_root,
        rel_path=rel_path,
        pathspec=pathspec,
        work_dir=work_dir_for_target(target_path),
    )


def default_branch_name(
    stamp: str,
    model_slug: str,
    target_rel: str,
    *,
    agent: AgentKind = "codex",
    label_slug: str | None = None,
    prompter: bool = False,
) -> str:
    branch = f"{agent}-exp/{stamp}-{model_slug}"
    if label_slug:
        branch += f"-{label_slug}"
    if target_rel:
        branch += f"-{sanitize_slug(target_rel)}"
    if prompter:
        branch += PROMPTER_SUFFIX
    return branch


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run a coding agent repeatedly and record line-change totals per iteration."
    )
    p.add_argument("target", type=Path, help="Target codebase directory OR a single file path.")
    p.add_argument("commit", type=str, help="Commit hash to branch from.")
    p.add_argument("iterations", type=int, help="Number of cumulative iterations.")
    p.add_argument(
        "--model",
        type=str,
        required=True,
        help=(
            "Model for the coding agent CLI and log naming "
            "(e.g. gpt-5.5, claude-sonnet-4-6). "
            "Models starting with 'claude' use the Claude CLI; others use Codex."
        ),
    )
    p.add_argument(
        "--label",
        type=str,
        default=None,
        help="Optional tag appended to experiment branch and result/<repo>-<label>/ folder.",
    )
    p.add_argument(
        "--prompter",
        action="store_true",
        help="Use a Gemini user agent to generate vague refactoring prompts each turn.",
    )
    p.add_argument(
        "--effort",
        type=str,
        default=None,
        help=(
            "Thinking / reasoning effort for the coding agent. Must be valid for the "
            "selected --model's CLI: Claude accepts low|medium|high|xhigh|max; "
            "Codex accepts minimal|low|medium|high. Default: CLI default."
        ),
    )
    p.add_argument(
        "--output-base",
        type=Path,
        default=None,
        help=(
            "Base directory holding one folder per experiment "
            "(default: <repo>/result). Used by the pipeline orchestrator to "
            "route outputs into output/Algorithms or output/RealWorld."
        ),
    )
    return p


def parse_args(argv: list[str] | None = None) -> CliArgs:
    p = build_arg_parser()
    namespace = p.parse_args(argv)
    if namespace.iterations < 1:
        p.error("iterations must be >= 1")
    model = non_empty_string(namespace.model)
    if not model:
        p.error("--model must be non-empty")
    if namespace.label is not None and not non_empty_string(namespace.label):
        p.error("--label must be non-empty")
    agent = infer_agent_from_model(model)
    effort = non_empty_string(namespace.effort)
    if effort is not None:
        valid = effort_levels_for_agent(agent)
        if effort not in valid:
            p.error(
                f"--effort {effort!r} is not valid for {agent} models; "
                f"choose one of: {', '.join(valid)}"
            )
    return CliArgs(
        target=namespace.target,
        iterations=namespace.iterations,
        commit=namespace.commit,
        model=model,
        label=namespace.label,
        agent=agent,
        prompter=bool(namespace.prompter),
        output_base=namespace.output_base,
        effort=effort,
    )


def require_tools(*tools: str) -> bool:
    missing_tools = [tool for tool in tools if shutil.which(tool) is None]
    if missing_tools:
        for tool in missing_tools:
            eprint(f"error: `{tool}` not found on PATH.")
        return False
    return True


def build_experiment_config(args: CliArgs) -> ExperimentConfig:
    target = resolve_target_scope(args.target)
    stamp = utc_stamp()
    model = resolve_model_info(args.model)
    label_slug = resolve_label_slug(args.label)
    branch = default_branch_name(
        stamp,
        model.slug,
        target.rel_path,
        agent=args.agent,
        label_slug=label_slug,
        prompter=args.prompter,
    )
    result_dir = target.repo_name
    if label_slug:
        result_dir = f"{target.repo_name}-{label_slug}"
    if args.prompter:
        result_dir = f"{result_dir}{PROMPTER_SUFFIX}"
    base_dir = args.output_base if args.output_base is not None else (script_dir() / "result")
    exp_path = (base_dir / result_dir).resolve()
    results_csv = log_csv_path(exp_path, stamp, model.slug)
    artifacts_dir_path = artifacts_dir(exp_path, stamp, model.slug)
    prompt = load_prompt()
    prompter_config = load_prompter_config(fallback_prompt=prompt) if args.prompter else None
    clarification_patterns = load_clarification_patterns()
    return ExperimentConfig(
        target=target,
        prompt=prompt,
        requested_model=args.model,
        effective_model=model.effective,
        branch=branch,
        results_csv=results_csv,
        artifacts_dir=artifacts_dir_path,
        start_commit=args.commit,
        iterations=args.iterations,
        agent=args.agent,
        prompter=args.prompter,
        prompter_config=prompter_config,
        clarification_patterns=clarification_patterns,
        effort=args.effort,
    )


def eprint_setup(config: ExperimentConfig) -> None:
    eprint(f"[setup] Coding agent:       {config.agent}")
    eprint(f"[setup] Model (effective): {config.effective_model}")
    eprint(f"[setup] Experiment branch:  {config.branch}")
    eprint(f"[setup] CSV log:            {config.results_csv}")
    eprint(f"[setup] Artifacts:          {config.artifacts_dir}/")
    if config.effort:
        eprint(f"[setup] Effort:             {config.effort}")
    if config.prompter and config.prompter_config:
        eprint(f"[setup] Prompter mode:      Gemini ({config.prompter_config.model})")


def build_coding_agent(config: ExperimentConfig) -> CodingAgent:
    if config.agent == "claude":
        return ClaudeAgent(
            config.target.work_dir,
            config.requested_model,
            timeout=DEFAULT_TIMEOUT,
            effort=config.effort,
        )
    return CodexAgent(
        config.target.work_dir,
        config.requested_model,
        timeout=DEFAULT_TIMEOUT,
        effort=config.effort,
    )


def build_prompt_source(config: ExperimentConfig) -> PromptSource:
    if config.prompter and config.prompter_config:
        return GeminiPromptSource.from_config(config.prompter_config)
    return FixedPromptSource(config.prompt)
