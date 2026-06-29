"""Tests for per-CLI thinking/effort level threading through run_exp."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import run_pipeline  # noqa: E402
from experiment_runner.claude_agent import build_claude_command  # noqa: E402
from experiment_runner.codex_agent import build_codex_command  # noqa: E402
from experiment_runner.config import parse_args  # noqa: E402


# --- command builders ------------------------------------------------------

def test_claude_command_includes_effort() -> None:
    cmd = build_claude_command("do it", "claude-opus-4-6", is_first=True, effort="xhigh")
    assert "--effort" in cmd
    assert cmd[cmd.index("--effort") + 1] == "xhigh"


def test_claude_command_omits_effort_when_none() -> None:
    cmd = build_claude_command("do it", "claude-opus-4-6", is_first=True)
    assert "--effort" not in cmd


def test_codex_command_includes_effort(tmp_path: Path) -> None:
    cmd = build_codex_command(tmp_path, "do it", "gpt-5.5", is_first=True, effort="low")
    assert "-c" in cmd
    assert "model_reasoning_effort=low" in cmd


def test_codex_command_omits_effort_when_none(tmp_path: Path) -> None:
    cmd = build_codex_command(tmp_path, "do it", "gpt-5.5", is_first=True)
    assert "-c" not in cmd
    assert not any("model_reasoning_effort" in part for part in cmd)


def test_codex_command_keeps_full_auto(tmp_path: Path) -> None:
    cmd = build_codex_command(tmp_path, "do it", "gpt-5.5", is_first=True, effort="high")
    assert "--full-auto" in cmd


def test_codex_command_none_effort_uses_full_auto(tmp_path: Path) -> None:
    cmd = build_codex_command(tmp_path, "do it", "gpt-5.5", is_first=True, effort="none")
    assert "--full-auto" in cmd
    assert "model_reasoning_effort=none" in cmd


# --- parse_args validation -------------------------------------------------

def _base_argv(model: str, effort: str) -> list[str]:
    return [".", "HEAD", "1", "--model", model, "--effort", effort]


def test_parse_args_accepts_valid_claude_effort() -> None:
    args = parse_args(_base_argv("claude-opus-4-6", "xhigh"))
    assert args.effort == "xhigh"
    assert args.agent == "claude"


def test_parse_args_accepts_valid_codex_effort() -> None:
    args = parse_args(_base_argv("gpt-5.5", "none"))
    assert args.effort == "none"
    assert args.agent == "codex"


def test_parse_args_accepts_exp_folder() -> None:
    args = parse_args([".", "HEAD", "1", "--model", "gpt-5.5", "--exp-folder", "gpt-5.5-none-Agent"])
    assert args.exp_folder == "gpt-5.5-none-Agent"


def test_parse_args_accepts_xhigh_for_codex() -> None:
    args = parse_args(_base_argv("gpt-5.5", "xhigh"))
    assert args.effort == "xhigh"
    assert args.agent == "codex"


def test_parse_args_rejects_max_for_codex() -> None:
    with pytest.raises(SystemExit):
        parse_args(_base_argv("gpt-5.5", "max"))


def test_parse_args_rejects_none_for_claude() -> None:
    with pytest.raises(SystemExit):
        parse_args(_base_argv("claude-opus-4-6", "none"))


# --- plan parsing + build_command ------------------------------------------

def _write_plan(tmp_path: Path, task_extra: dict) -> Path:
    plan = {
        "defaults": {"effort_codex": "high", "effort_claude": "medium"},
        "algorithms": [{"target": ".", "commit": "HEAD", **task_extra}],
        "realworld": [],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan_path


def test_load_plan_parses_effort_defaults(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, {"models": ["gpt-5.5"]})
    tasks = run_pipeline.load_plan(plan_path, tmp_path / "out")
    assert tasks[0].effort_codex == "high"
    assert tasks[0].effort_claude == "medium"


def test_load_plan_per_task_override(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, {"models": ["gpt-5.5"], "effort_codex": "low"})
    tasks = run_pipeline.load_plan(plan_path, tmp_path / "out")
    assert tasks[0].effort_codex == "low"
    assert tasks[0].effort_claude == "medium"  # default retained


def _effort_in_command(tmp_path: Path, model: str) -> str | None:
    plan_path = _write_plan(tmp_path, {"models": [model]})
    task = run_pipeline.load_plan(plan_path, tmp_path / "out")[0]
    step = run_pipeline.Step(
        run_pipeline.step_key(task, "run_exp", model), task, "run_exp", model
    )
    cmd = run_pipeline.build_command(step)
    if "--effort" not in cmd:
        return None
    return cmd[cmd.index("--effort") + 1]


def test_build_command_forwards_codex_effort(tmp_path: Path) -> None:
    assert _effort_in_command(tmp_path, "gpt-5.5") == "high"


def test_build_command_forwards_claude_effort(tmp_path: Path) -> None:
    assert _effort_in_command(tmp_path, "claude-opus-4-6") == "medium"
