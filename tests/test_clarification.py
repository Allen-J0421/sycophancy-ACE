"""Tests for clarification detection."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "dashboard"))

from codex_parse import extract_final_agent_message  # noqa: E402
from experiment_runner.clarification import needs_clarification_followup  # noqa: E402
from experiment_runner.env import load_clarification_patterns  # noqa: E402
from experiment_runner.models import AgentRunResult, LineStats  # noqa: E402

RESULT_ROOT = _REPO_ROOT / "result"

POSITIVE_PATHS = {
    "bubble_sort_Java/20260616T002006Z-claude-haiku-4-5/run_002/claude.jsonl",
    "bubble_sort_Java/20260616T002006Z-claude-haiku-4-5/run_003/claude.jsonl",
    "bubble_sort_Java/20260616T002006Z-claude-haiku-4-5/run_004/claude.jsonl",
    "bubble_sort_Java-claude-Agent/20260616T015047Z-claude-haiku-4-5/run_001/claude.jsonl",
}


def _agent_jsonl_paths() -> list[Path]:
    paths = sorted(RESULT_ROOT.rglob("claude.jsonl")) + sorted(RESULT_ROOT.rglob("codex.jsonl"))
    return [p for p in paths if "prompter" not in p.name and "refdiff" not in str(p)]


def _zero_diff_paths() -> list[Path]:
    zero: list[Path] = []
    for jsonl_path in _agent_jsonl_paths():
        diff_path = jsonl_path.parent / "diff.patch"
        if not diff_path.exists() or not diff_path.read_text(encoding="utf-8", errors="replace").strip():
            zero.append(jsonl_path)
    return zero


@pytest.fixture(scope="module")
def patterns():
    return load_clarification_patterns()


def test_patterns_load_from_files(patterns):
    assert patterns.refusal_blockers
    assert patterns.clarification_signals
    assert patterns.require_question_mark is True


@pytest.mark.parametrize("rel_path", sorted(POSITIVE_PATHS))
def test_positive_zero_diff_clarification(rel_path: str, patterns):
    jsonl_path = RESULT_ROOT / rel_path
    text = jsonl_path.read_text(encoding="utf-8")
    msg = extract_final_agent_message(text)
    agent = AgentRunResult(exit_code=0, duration_s=1.0, timed_out=False, session_id="s")
    assert needs_clarification_followup(
        agent=agent,
        diff_patch="",
        stats=LineStats.empty(),
        final_message=msg,
        patterns=patterns,
    )


@pytest.mark.parametrize("jsonl_path", _zero_diff_paths())
def test_zero_diff_negatives_except_known_positives(jsonl_path: Path, patterns):
    rel = str(jsonl_path.relative_to(RESULT_ROOT))
    if rel in POSITIVE_PATHS:
        pytest.skip("known positive")
    text = jsonl_path.read_text(encoding="utf-8", errors="replace")
    msg = extract_final_agent_message(text)
    agent = AgentRunResult(exit_code=0, duration_s=1.0, timed_out=False, session_id="s")
    assert not needs_clarification_followup(
        agent=agent,
        diff_patch="",
        stats=LineStats.empty(),
        final_message=msg,
        patterns=patterns,
    )


def test_nonzero_diff_never_triggers(patterns):
    jsonl_path = next(RESULT_ROOT.rglob("claude.jsonl"))
    text = jsonl_path.read_text(encoding="utf-8")
    msg = extract_final_agent_message(text)
    agent = AgentRunResult(exit_code=0, duration_s=1.0, timed_out=False, session_id="s")
    assert not needs_clarification_followup(
        agent=agent,
        diff_patch="diff",
        stats=LineStats(files_changed=1, lines_added=3, lines_deleted=1),
        final_message=msg,
        patterns=patterns,
    )


def test_failed_agent_never_triggers(patterns):
    agent = AgentRunResult(exit_code=1, duration_s=1.0, timed_out=False, session_id="s")
    assert not needs_clarification_followup(
        agent=agent,
        diff_patch="",
        stats=LineStats.empty(),
        final_message="Could you clarify what to refactor?",
        patterns=patterns,
    )
