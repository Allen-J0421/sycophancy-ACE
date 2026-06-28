"""Tests for refdiff --lang/--exp wiring through the pipeline planner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import run_pipeline  # noqa: E402


def _write_plan(tmp_path: Path, task_extra: dict | None = None) -> Path:
    plan = {
        "defaults": {"models": ["gpt-5.5"], "phases": ["refdiff"]},
        "algorithms": [],
        "realworld": [
            {
                "target": ".",
                "commit": "HEAD",
                **(task_extra or {}),
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan_path


def test_load_plan_parses_refdiff_lang(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, {"refdiff_lang": "java"})
    task = run_pipeline.load_plan(plan_path, tmp_path / "out")[0]
    assert task.refdiff_lang == "java"


def test_build_command_refdiff_passes_exp_and_lang(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, {"refdiff_lang": "java", "label": "high", "prompter": True})
    task = run_pipeline.load_plan(plan_path, tmp_path / "out")[0]
    step = run_pipeline.Step(
        run_pipeline.step_key(task, "refdiff", None), task, "refdiff", None
    )
    cmd = run_pipeline.build_command(step)
    assert "--exp" in cmd
    assert cmd[cmd.index("--exp") + 1] == task.exp_folder
    assert "--lang" in cmd
    assert cmd[cmd.index("--lang") + 1] == "java"


def test_build_command_refdiff_omits_lang_when_unset(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path)
    task = run_pipeline.load_plan(plan_path, tmp_path / "out")[0]
    step = run_pipeline.Step(
        run_pipeline.step_key(task, "refdiff", None), task, "refdiff", None
    )
    cmd = run_pipeline.build_command(step)
    assert "--exp" in cmd
    assert "--lang" not in cmd
