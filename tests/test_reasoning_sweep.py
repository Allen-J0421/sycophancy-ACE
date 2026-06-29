"""Tests for reasoning-sweep plan loading and suite-level plotting."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import run_pipeline  # noqa: E402
from reasoning_cells import (  # noqa: E402
    collect_model_series_sorted,
    is_reasoning_suite,
    model_prefixes_in_suite,
    parse_cell_folder,
)


def test_parse_cell_folder() -> None:
    assert parse_cell_folder("gpt-5.5-none-Agent", "gpt-5.5") == "none"
    assert parse_cell_folder("claude-opus-4-8-max-Agent", "claude-opus-4-8") == "max"
    assert parse_cell_folder("other-Agent", "gpt-5.5") is None


def test_load_reasoning_plan_expands_five_cells(tmp_path: Path) -> None:
    plan_path = _REPO_ROOT / "pipeline_plan_reasoning_sweep.json"
    tasks = run_pipeline.load_plan(plan_path, tmp_path / "output")
    assert len(tasks) == 5
    assert all(t.category == "reasoning_test" for t in tasks)
    assert all(t.suite == "001_binary_search" for t in tasks)
    suites = {str(t.output_base) for t in tasks}
    assert suites == {str((tmp_path / "output" / "reasoning_test" / "001_binary_search").resolve())}
    folders = {t.exp_folder for t in tasks}
    assert len(folders) == 5
    assert "gpt-5.5-none-Agent" in folders
    assert "gpt-5.5-xhigh-Agent" in folders


def test_build_command_run_exp_includes_exp_folder_and_effort(tmp_path: Path) -> None:
    plan_path = _REPO_ROOT / "pipeline_plan_reasoning_sweep.json"
    task = run_pipeline.load_plan(plan_path, tmp_path / "out")[0]
    step = run_pipeline.Step(
        run_pipeline.step_key(task, "run_exp", task.models[0]),
        task,
        "run_exp",
        task.models[0],
    )
    cmd = run_pipeline.build_command(step)
    assert "--exp-folder" in cmd
    assert task.exp_folder in cmd
    assert "--effort" in cmd
    assert cmd[cmd.index("--effort") + 1] == task.effort_codex


def test_build_command_plot_reasoning_groups(tmp_path: Path) -> None:
    plan_path = _REPO_ROOT / "pipeline_plan_reasoning_sweep.json"
    task = run_pipeline.load_plan(plan_path, tmp_path / "out")[0]
    step = run_pipeline.Step(
        run_pipeline.step_key(task, "plot_reasoning_groups", None),
        task,
        "plot_reasoning_groups",
        None,
    )
    cmd = run_pipeline.build_command(step)
    assert any("plot_reasoning_groups.py" in part for part in cmd)
    assert "--suite-dir" in cmd


def test_dedupe_suite_wide_steps(tmp_path: Path) -> None:
    plan_path = _REPO_ROOT / "pipeline_plan_reasoning_sweep.json"
    tasks = run_pipeline.load_plan(plan_path, tmp_path / "out")
    steps = []
    for task in tasks:
        steps.extend(run_pipeline.build_steps(task, {"plot_reasoning_groups"}))
    deduped = run_pipeline.dedupe_suite_wide_steps(steps)
    assert len(deduped) == 1


def test_plot_reasoning_groups_collect_series(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    for effort in ("none", "low"):
        cell = suite / f"gpt-5.5-{effort}-Agent" / "logs"
        cell.mkdir(parents=True)
        csv = cell / f"20260101T000000Z-gpt-5.5-log.csv"
        csv.write_text(
            "run,files_changed,lines_added,lines_deleted,lines_total,duration_s,"
            "exit_code,timed_out,commit_sha,commit_message,model,git_branch\n"
            f"1,1,10,5,15,1.0,0,0,abc,msg,gpt-5.5,branch\n",
            encoding="utf-8",
        )
    assert model_prefixes_in_suite(suite) == ["gpt-5.5"]
    series = collect_model_series_sorted(suite, "gpt-5.5")
    assert len(series) == 2
    assert series[0][0] == "gpt-5.5 (none)"
    assert series[1][0] == "gpt-5.5 (low)"


def test_is_reasoning_suite(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    for effort in ("none", "low"):
        (suite / f"gpt-5.5-{effort}-Agent").mkdir(parents=True)
    assert is_reasoning_suite(suite)
    assert not is_reasoning_suite(tmp_path / "empty")


def test_plot_signals_reasoning_suite_comparison(tmp_path: Path) -> None:
    from plot_signals import build_reasoning_suite

    suite = tmp_path / "suite"
    signal_blob = {
        "model": "gpt-5.5",
        "signals": {f"S{i}": {"cont": float(i), "bin": i % 2} for i in range(1, 7)},
    }
    for effort in ("none", "low"):
        sig_dir = suite / f"gpt-5.5-{effort}-Agent" / "signals"
        sig_dir.mkdir(parents=True)
        (sig_dir / f"20260101T000000Z-gpt-5.5-signals.json").write_text(
            json.dumps(signal_blob), encoding="utf-8"
        )
    built = build_reasoning_suite(suite)
    assert built == 1
    out = suite / "plots" / "gpt-5_5_signals_effort_comparison.png"
    assert out.is_file()


def test_invalid_reasoning_cell_raises(tmp_path: Path) -> None:
    plan = {
        "defaults": {"iterations": 1, "prompter": False},
        "reasoning_test": [
            {
                "suite": "bad",
                "target": ".",
                "commit": "HEAD",
                "cells": [{"model": "gpt-5.5", "effort": "high"}],
            }
        ],
    }
    plan_path = tmp_path / "bad.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    try:
        run_pipeline.load_plan(plan_path, tmp_path / "out")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "exp_folder" in str(exc)
