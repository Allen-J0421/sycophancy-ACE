"""Tests for Gemini prompter profile selection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import run_pipeline  # noqa: E402
from experiment_runner.env import load_prompter_prompts_from_file, resolve_prompter_profile  # noqa: E402


@pytest.fixture
def prompt_env_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "prompter_system_prompt.txt").write_text("NOVICE PROMPT", encoding="utf-8")
    (tmp_path / "prompter_system_prompt_expert.txt").write_text(
        "EXPERT PROMPT", encoding="utf-8"
    )
    (tmp_path / "prompt.env").write_text(
        "\n".join(
            [
                "AGENT_FIXED_PROMPT=refactor",
                "PROMPTER_PROFILE=novice",
                "PROMPTER_NUDGE=nudge text",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_resolve_prompter_profile_validates() -> None:
    assert resolve_prompter_profile("expert") == "expert"
    with pytest.raises(SystemExit, match="Unknown prompter profile"):
        resolve_prompter_profile("wizard")


def test_load_novice_profile_from_prompt_env(prompt_env_dir: Path) -> None:
    system_prompt, nudge, _clarification, profile = load_prompter_prompts_from_file()
    assert profile == "novice"
    assert system_prompt == "NOVICE PROMPT"
    assert nudge == "nudge text"


def test_load_expert_profile_via_cli_override(prompt_env_dir: Path) -> None:
    system_prompt, _nudge, _clarification, profile = load_prompter_prompts_from_file(
        profile="expert"
    )
    assert profile == "expert"
    assert system_prompt == "EXPERT PROMPT"


def test_explicit_system_prompt_file_overrides_profile(prompt_env_dir: Path) -> None:
    custom = prompt_env_dir / "custom.txt"
    custom.write_text("CUSTOM PROMPT", encoding="utf-8")
    prompt_env = prompt_env_dir / "prompt.env"
    prompt_env.write_text(
        prompt_env.read_text(encoding="utf-8")
        + f"\nPROMPTER_SYSTEM_PROMPT_FILE={custom.name}\n",
        encoding="utf-8",
    )
    system_prompt, _nudge, _clarification, profile = load_prompter_prompts_from_file(
        profile="expert"
    )
    assert profile == "expert"
    assert system_prompt == "CUSTOM PROMPT"


def test_build_command_forwards_prompter_profile(tmp_path: Path) -> None:
    task = run_pipeline.Task(
        category="algorithms",
        output_base=tmp_path,
        target=tmp_path / "repo",
        commit="HEAD",
        models=["gpt-5.5"],
        iterations=3,
        phases=["run_exp"],
        prompter=True,
        label=None,
        prompter_profile="expert",
    )
    step = run_pipeline.Step("k", task, "run_exp", "gpt-5.5")
    cmd = run_pipeline.build_command(step)
    assert "--prompter" in cmd
    assert "--prompter-profile" in cmd
    assert cmd[cmd.index("--prompter-profile") + 1] == "expert"
