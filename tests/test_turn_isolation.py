"""Tests for per-turn isolation: one commit per turn (agent commits folded), dirty-tree guard,
self-continuation detection, and the Claude environment that disables memory/background."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from experiment_runner import claude_agent, util  # noqa: E402
from experiment_runner.constants import CLAUDE_ENV  # noqa: E402
from experiment_runner.git_repo import GitRepository  # noqa: E402
from experiment_runner.iteration import count_result_events  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "baseline")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "A.java").write_text("class A {}\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "baseline")
    return tmp_path


def _start(repo: Path) -> tuple[GitRepository, str]:
    git = GitRepository(repo)
    base = _git(repo, "rev-parse", "HEAD")
    return git, git.setup_branch(base, "claude-exp/test")


def test_agent_commits_fold_into_one_iteration_commit(repo):
    git, base = _start(repo)
    for i in range(3):  # the agent commits three times during the turn
        (repo / f"B{i}.java").write_text(f"class B{i} {{}}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"agent commit {i}")
    (repo / "C.java").write_text("class C {}\n")  # plus uncommitted work

    git.stage_all_and_diff_stats(base, None)
    assert git.fold_agent_commits(base) == 3
    sha = git.commit("claude-exp: iteration 1")

    assert _git(repo, "rev-parse", f"{sha}^") == base
    changed = _git(repo, "diff", "--name-only", f"{sha}^", sha).split()
    assert sorted(changed) == ["B0.java", "B1.java", "B2.java", "C.java"]
    assert _git(repo, "branch", "--show-current") == "claude-exp/test"


def test_agent_branch_switch_is_folded_back_onto_experiment_branch(repo):
    git, base = _start(repo)
    _git(repo, "checkout", "-q", "-b", "agent-feature")
    (repo / "D.java").write_text("class D {}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "agent work on its own branch")

    git.stage_all_and_diff_stats(base, None)
    assert git.fold_agent_commits(base) == 1
    sha = git.commit("claude-exp: iteration 1")
    assert _git(repo, "branch", "--show-current") == "claude-exp/test"
    assert _git(repo, "rev-parse", "claude-exp/test") == sha
    assert _git(repo, "rev-parse", f"{sha}^") == base
    assert (repo / "D.java").exists()


def test_no_agent_commits_is_a_no_op(repo):
    git, base = _start(repo)
    (repo / "E.java").write_text("class E {}\n")
    git.stage_all_and_diff_stats(base, None)
    assert git.fold_agent_commits(base) == 0
    sha = git.commit("claude-exp: iteration 1")
    assert _git(repo, "rev-parse", f"{sha}^") == base


def test_setup_branch_refuses_dirty_tree(repo):
    (repo / "leftover.java").write_text("class Leftover {}\n")
    git = GitRepository(repo)
    with pytest.raises(RuntimeError, match="uncommitted changes"):
        git.setup_branch(_git(repo, "rev-parse", "HEAD"), "claude-exp/test")


def test_count_result_events():
    one = json.dumps({"type": "result", "result": "done"})
    other = json.dumps({"type": "assistant", "message": {}})
    assert count_result_events("\n".join([other, one])) == 1
    assert count_result_events("\n".join([one, other, one, one])) == 3
    assert count_result_events("not json\n" + json.dumps({"type": "result"})) == 1
    assert count_result_events("") == 0


def test_claude_env_disables_memory_background_and_autoupdate():
    assert CLAUDE_ENV == {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
        "DISABLE_AUTOUPDATER": "1",
    }


def test_claude_agent_passes_env(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, *, cwd=None, timeout=None, env=None):
        seen["env"] = env
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(
            {"type": "result", "session_id": "s1"}), stderr="")

    monkeypatch.setattr(claude_agent, "run_text_command", fake_run)
    claude_agent.ClaudeAgent(tmp_path, "claude-sonnet-4-6").run("hi", is_first=True)
    assert seen["env"] == CLAUDE_ENV


def test_run_text_command_layers_env_on_inherited(monkeypatch):
    monkeypatch.setenv("KEEP_ME", "yes")
    out = util.run_text_command(
        [sys.executable, "-c",
         "import os; print(os.environ.get('KEEP_ME'), os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY'))"],
        env=CLAUDE_ENV,
    ).stdout.split()
    assert out == ["yes", "1"]
